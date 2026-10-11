"""Prefiltraggio e deduplicazione degli articoli (RF-08, RF-09).

Fornisce le funzioni per:
1. Filtrare gli articoli in base alla data di pubblicazione (freschezza).
2. Deduplicare gli articoli all'interno del batch di acquisizione corrente.
3. Verificare la presenza di duplicati già salvati nel database (per URL esatto
   o per titolo normalizzato e dominio con date compatibili).
"""
from urllib.parse import urlparse
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import or_, and_
from sqlalchemy.orm import Session

from src.db.models import Article
from src.config import (
    DEDUP_PUBLICATION_TOLERANCE_HOURS,
    DEDUP_ACQUISITION_WINDOW_HOURS,
)

ROME_TZ = ZoneInfo("Europe/Rome")


def _extract_domain(url: str | None) -> str | None:
    """Estrae il dominio (netloc) dall'URL, lo normalizza in minuscolo e rimuove il prefisso www."""
    if not url:
        return None
    try:
        domain = urlparse(url).netloc.lower()
        return domain.removeprefix("www.").strip() if domain else None
    except Exception:
        return None


def _to_utc(dt: datetime | None) -> datetime | None:
    """Converte un oggetto datetime in UTC consapevole (timezone-aware)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalize_title(
    title: str | None,
    acquisition_mode: str | None = None,
    source: str | None = None,
) -> str:
    """Normalizza il titolo rimuovendo spazi multipli e convertendo in minuscolo.

    Se acquisition_mode è 'generalista' e il titolo termina con un trattino
    (' - ', ' – ' o ' — ') seguito esattamente dalla testata (source), tale
    suffisso viene rimosso per consentire il confronto con il canale mirato.
    """
    _, stripped = get_normalized_title_forms(title, acquisition_mode, source)
    return stripped


def get_normalized_title_forms(
    title: str | None,
    acquisition_mode: str | None = None,
    source: str | None = None,
) -> tuple[str, str]:
    """Restituisce la forma intera e la forma senza suffisso del titolo normalizzato.

    La prima forma è il titolo con spazi multipli ridotti a uno e in minuscolo.
    La seconda forma rimuove il suffisso della testata (' - source', ' – source', ' — source')
    se l'articolo è generalista e il suffisso coincide esattamente con il campo source.
    Se il suffisso non è presente o non coincide, la seconda forma è identica alla prima.
    """
    if not title:
        return "", ""

    full = " ".join(title.strip().split()).lower()
    stripped = full

    if acquisition_mode == "generalista" and source:
        norm_source = " ".join(source.strip().split()).lower()
        if norm_source:
            for dash in (" - ", " – ", " — "):
                suffix = f"{dash}{norm_source}"
                if full.endswith(suffix):
                    stripped = full[:-len(suffix)].rstrip()
                    break

    return full, stripped


def _titles_match(forms_a: tuple[str, str], forms_b: tuple[str, str]) -> bool:
    """Verifica se due titoli coincidono nella forma intera oppure nella forma senza suffisso."""
    full_a, stripped_a = forms_a
    full_b, stripped_b = forms_b
    if not full_a or not full_b:
        return False
    return (full_a == full_b) or (bool(stripped_a) and bool(stripped_b) and stripped_a == stripped_b)


def filter_by_freshness(raw_articles: list[dict], max_age_days: int) -> list[dict]:
    """Scarta gli articoli con data di pubblicazione (published_at) nota e antecedente a max_age_days giorni.

    Gli articoli privi di data (published_at è None) vengono mantenuti per evitare falsi scarti per mancanza di metadati.
    """
    now = datetime.now(timezone.utc)
    cutoff_date = now - timedelta(days=max_age_days)

    fresh_articles = []
    discarded_by_age = 0
    for raw in raw_articles:
        pub_at = raw.get("published_at")
        if pub_at and pub_at < cutoff_date:
            discarded_by_age += 1
            continue
        fresh_articles.append(raw)

    if discarded_by_age > 0:
        print(f"[INFO] [prefilter] {discarded_by_age} articoli scartati perché pubblicati da oltre {max_age_days} giorni")

    return fresh_articles


def deduplicate_in_batch(raw_articles: list[dict]) -> list[dict]:
    """Deduplica gli articoli all'interno del batch corrente per URL esatto, mantenendo il primo occorso."""
    seen_in_batch = set()
    deduped_raw_articles = []
    for raw in raw_articles:
        url = raw.get("url")
        if url and url not in seen_in_batch:
            seen_in_batch.add(url)
            deduped_raw_articles.append(raw)
    return deduped_raw_articles


def is_duplicate_in_db(
    session: Session,
    raw: dict,
    publication_tolerance_hours: int = DEDUP_PUBLICATION_TOLERANCE_HOURS,
    acquisition_window_hours: int = DEDUP_ACQUISITION_WINDOW_HOURS,
    title_dedup_window_hours: int | None = None,
) -> bool:
    """Verifica se l'articolo è un duplicato di uno già salvato nel database.

    Criteri di deduplicazione:
    (a) Primo livello: esistenza di un articolo con lo stesso URL esatto.
    (b) Secondo livello: esistenza di un articolo con titolo compatibile, stesso dominio
        e date compatibili.

    Confronto dei titoli:
    Per ciascun articolo vengono calcolate due forme: il titolo normalizzato intero (spazi
    ridotti a uno e minuscole) e il titolo normalizzato senza suffisso della testata
    (' - source', ' – source', ' — source'), quest'ultima solo per articoli generalisti con
    suffisso corrispondente a source. Due articoli hanno titolo compatibile se le forme
    intere coincidono oppure se le forme senza suffisso coincidono.

    Compatibilità delle date:
    - Se entrambi gli articoli hanno published_at ed entrambi provengono da canale mirato,
      la differenza tra le date di pubblicazione deve essere minore o uguale a
      publication_tolerance_hours (default 6 ore).
    - Se entrambi gli articoli hanno published_at e almeno uno proviene da canale generalista,
      le date sono compatibili se cadono nello stesso giorno di calendario nel fuso Europe/Rome
      (per compensare la granularità a livello di solo giorno di Google News).
    - Se almeno uno dei due non ha published_at, si verifica che il candidato nel database
      sia stato acquisito (first_seen_at) nelle ultime acquisition_window_hours (default 48 ore).
    """
    if title_dedup_window_hours is not None:
        acquisition_window_hours = title_dedup_window_hours

    raw_url = raw.get("url")
    if not raw_url:
        return False

    # (a) Controllo URL esatto
    existing_url = session.query(Article).filter_by(url=raw_url).first()
    if existing_url:
        print(f"[INFO] [prefilter] Articolo duplicato (stesso URL) scartato: {raw_url}")
        return True

    # (b) Controllo titolo normalizzato + dominio con date compatibili
    raw_title = raw.get("title")
    if not raw_title:
        return False

    raw_domain = _extract_domain(raw_url)
    if not raw_domain:
        return False

    raw_forms = get_normalized_title_forms(
        raw_title,
        acquisition_mode=raw.get("acquisition_mode"),
        source=raw.get("source"),
    )
    if not raw_forms[0]:
        return False

    now = datetime.now(timezone.utc)
    raw_pub = raw.get("published_at")
    raw_pub_utc = _to_utc(raw_pub)
    acq_cutoff = now - timedelta(hours=acquisition_window_hours)

    query = session.query(Article)
    if raw_pub_utc is not None:
        pub_margin = timedelta(hours=max(publication_tolerance_hours, 26))
        pub_min = raw_pub_utc - pub_margin
        pub_max = raw_pub_utc + pub_margin
        query = query.filter(
            or_(
                Article.published_at.between(pub_min, pub_max),
                and_(Article.published_at.is_(None), Article.first_seen_at >= acq_cutoff),
            )
        )
    else:
        query = query.filter(Article.first_seen_at >= acq_cutoff)

    candidates = query.all()

    for candidate in candidates:
        cand_domain = _extract_domain(candidate.url)
        if cand_domain != raw_domain:
            continue

        cand_forms = get_normalized_title_forms(
            candidate.title,
            acquisition_mode=candidate.acquisition_mode,
            source=candidate.source,
        )
        if not _titles_match(raw_forms, cand_forms):
            continue

        cand_pub_utc = _to_utc(candidate.published_at)
        cand_first_seen_utc = _to_utc(candidate.first_seen_at)

        # Se entrambi hanno published_at: verifica compatibilità date di pubblicazione
        if raw_pub_utc is not None and cand_pub_utc is not None:
            is_generalist = (raw.get("acquisition_mode") == "generalista") or (
                candidate.acquisition_mode == "generalista"
            )
            if is_generalist:
                raw_date = raw_pub_utc.astimezone(ROME_TZ).date()
                cand_date = cand_pub_utc.astimezone(ROME_TZ).date()
                if raw_date == cand_date:
                    print(
                        f"[INFO] [prefilter] Articolo duplicato (stesso titolo/dominio, date di pubblicazione vicine) scartato: {raw_url}"
                    )
                    return True
            else:
                diff_sec = abs((raw_pub_utc - cand_pub_utc).total_seconds())
                if diff_sec <= publication_tolerance_hours * 3600:
                    print(
                        f"[INFO] [prefilter] Articolo duplicato (stesso titolo/dominio, date di pubblicazione vicine) scartato: {raw_url}"
                    )
                    return True
        else:
            # Se almeno uno dei due non ha published_at: finestra di acquisizione su first_seen_at
            if cand_first_seen_utc and cand_first_seen_utc >= acq_cutoff:
                print(
                    f"[INFO] [prefilter] Articolo duplicato (stesso titolo/dominio, finestra di acquisizione) scartato: {raw_url}"
                )
                return True

    return False


