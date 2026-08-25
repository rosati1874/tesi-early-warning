"""Prefiltraggio e deduplicazione degli articoli (RF-08, RF-09).

Fornisce le funzioni per:
1. Filtrare gli articoli in base alla data di pubblicazione (freschezza).
2. Deduplicare gli articoli all'interno del batch di acquisizione corrente.
3. Verificare la presenza di duplicati già salvati nel database (per URL esatto o titolo+fonte entro 48 ore).
"""
from datetime import datetime, timedelta, timezone
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.db.models import Article


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


def is_duplicate_in_db(session: Session, raw: dict, title_dedup_window_hours: int = 48) -> bool:
    """Verifica se l'articolo è un duplicato di uno già salvato nel database.

    Criteri di deduplicazione:
    (a) Esistenza di un articolo con lo stesso URL esatto.
    (b) Esistenza di un articolo con la stessa fonte e lo stesso titolo normalizzato (strip + lower)
        primo visto (first_seen_at) entro le ultime title_dedup_window_hours ore (default 48).
    """
    raw_url = raw.get("url")
    if not raw_url:
        return False

    # (a) Controllo URL esatto
    existing_url = session.query(Article).filter_by(url=raw_url).first()
    if existing_url:
        return True

    # (b) Controllo titolo normalizzato + fonte entro finestra temporale
    raw_title = raw.get("title")
    raw_source = raw.get("source")
    if raw_title and raw_source:
        normalized_title = raw_title.strip().lower()
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=title_dedup_window_hours)
        existing_title_dup = (
            session.query(Article)
            .filter(
                Article.source == raw_source,
                func.lower(func.trim(Article.title)) == normalized_title,
                Article.first_seen_at >= cutoff_time,
            )
            .first()
        )
        if existing_title_dup:
            print(f"[INFO] [prefilter] Articolo duplicato (stesso titolo/fonte) scartato: {raw_url}")
            return True

    return False
