"""Monitoraggio periodico di disponibilità e contenuto (RF-06, Cap. 4.6).

Applicato solo agli articoli con is_epidemic_signal=True entro la finestra temporale
configurata, per contenere il carico ed essere coerenti col vincolo di gratuità (RNF-03/RNF-04).
Riusa requests + trafilatura ad alta precisione.
"""
from datetime import datetime, timezone, timedelta
import hashlib
import re
from urllib.parse import urlparse

import requests

from src.config import HTTP_USER_AGENT, REQUEST_TIMEOUT_SECONDS, MONITORING_WINDOW_DAYS
from src.parsing.extractor import extract_main_text_for_monitoring
from src.db.models import Article, ArticleVersion, AvailabilityCheck
from src.notifications.webhook import notify_monitoring_update


def _normalize_text(text: str) -> str:
    """Normalizza il testo riducendo spazi multipli e ritorni a capo a un singolo spazio e convertendo in minuscolo."""
    return re.sub(r"\s+", " ", text).strip().lower()


def _hash_text(text: str) -> str:
    """Calcola l'hash SHA-256 del testo normalizzato."""
    normalized = _normalize_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def check_article(session, article: Article) -> dict:
    """Esegue un controllo di disponibilità e contenuto su un singolo articolo.

    Registra l'esito della disponibilità (availability_checks), rileva eventuali rimozioni
    (404, 410 o redirect alla home) e, se disponibile, confronta l'impronta del corpo principale
    rispetto alla versione di partenza (baseline) o all'ultimo aggiornamento calcolato con 'main_text_v2'.
    """
    original_status = article.status
    has_updated = False
    is_new_baseline = False
    new_version = None

    try:
        resp = requests.get(
            article.url,
            headers={"User-Agent": HTTP_USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        http_status = resp.status_code

        # Riconoscimento reindirizzamento alla home del sito (percorso vuoto o "/")
        is_redirect_to_home = False
        if resp.history:
            parsed_final = urlparse(resp.url)
            if parsed_final.path in ("", "/"):
                is_redirect_to_home = True

        if resp.status_code in (404, 410):
            result = "removed"
            article.status = "removed"
            print(f"[ATTENZIONE] [monitoring] Articolo ID {article.id} ({article.url}) rimosso (HTTP {resp.status_code})")
        elif is_redirect_to_home:
            result = "removed"
            article.status = "removed"
            print(f"[ATTENZIONE] [monitoring] Articolo ID {article.id} ({article.url}) rimosso tramite reindirizzamento alla home ({resp.url})")
        elif resp.ok:
            result = "available"
            article.status = "active"
        else:
            result = "access_error"
            print(f"[ATTENZIONE] [monitoring] Errore accesso all'articolo ID {article.id} ({article.url}): HTTP {http_status}")

    except requests.RequestException as exc:
        print(f"[ATTENZIONE] [monitoring] Errore accesso all'articolo ID {article.id} ({article.url}): {exc}")
        http_status = None
        result = "access_error"

    session.add(AvailabilityCheck(
        article_id=article.id,
        http_status=http_status,
        result=result,
    ))

    if result == "available":
        # Estrazione del solo testo principale ad alta precisione
        current_text = extract_main_text_for_monitoring(resp.text)
        if current_text:
            new_hash = _hash_text(current_text)

            # Ricerca dell'ultima versione memorizzata con il metodo 'main_text_v2'
            last_version = (
                session.query(ArticleVersion)
                .filter_by(article_id=article.id, hash_method="main_text_v2")
                .order_by(ArticleVersion.captured_at.desc(), ArticleVersion.id.desc())
                .first()
            )

            # Se non esiste ancora alcuna versione 'main_text_v2', salva come versione di partenza (baseline)
            if not last_version:
                new_version = ArticleVersion(
                    article_id=article.id,
                    content_hash=new_hash,
                    text_snapshot=current_text,
                    is_baseline=True,
                    hash_method="main_text_v2",
                )
                session.add(new_version)
                is_new_baseline = True
                print(f"[INFO] [monitoring] Registrata versione di partenza (baseline) per articolo ID {article.id}")
            elif last_version.content_hash != new_hash:
                # Se l'hash differisce dalla versione precedente, registra una nuova versione aggiornata
                new_version = ArticleVersion(
                    article_id=article.id,
                    content_hash=new_hash,
                    text_snapshot=current_text,
                    is_baseline=False,
                    hash_method="main_text_v2",
                )
                session.add(new_version)
                has_updated = True
                print(f"[INFO] [monitoring] Rilevata nuova versione del contenuto per articolo ID {article.id}")
        else:
            print(f"[INFO] [monitoring] Articolo ID {article.id}: corpo principale non estratto o inferiore a 200 caratteri, confronto contenuto saltato")

    article.last_checked_at = datetime.now(timezone.utc)
    session.commit()

    # Invio notifiche webhook solo per rimozione o aggiornamento reale (escludendo le versioni di partenza)
    if original_status != "removed" and article.status == "removed" and article.is_epidemic_signal:
        print(f"[INFO] [monitoring] Invio notifica webhook per rimozione articolo ID {article.id}")
        notify_monitoring_update(session, article, "epidemic_signal_removed", http_status=http_status)
    elif has_updated and article.is_epidemic_signal:
        print(f"[INFO] [monitoring] Invio notifica webhook per aggiornamento articolo ID {article.id}")
        notify_monitoring_update(session, article, "epidemic_signal_updated", version=new_version)

    return {
        "result": result,
        "is_baseline": is_new_baseline,
        "has_updated": has_updated,
    }


def run_monitoring_cycle(session) -> None:
    """Esegue un ciclo di monitoraggio sugli articoli rilevanti entro la finestra temporale configurata."""
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=MONITORING_WINDOW_DAYS)
    relevant_articles = (
        session.query(Article)
        .filter(
            Article.is_epidemic_signal.is_(True),
            Article.status == "active",
            Article.first_seen_at >= cutoff_date,
        )
        .all()
    )

    total_candidates = len(relevant_articles)
    print(f"[INFO] [monitoring] Avvio ciclo di monitoraggio: {total_candidates} articoli da controllare (finestra: {MONITORING_WINDOW_DAYS} giorni)")

    if total_candidates == 0:
        print("[INFO] [monitoring] Nessun articolo attivo da controllare nella finestra temporale")
        return

    checked_count = 0
    available_count = 0
    access_error_count = 0
    removed_count = 0
    baseline_count = 0
    updated_count = 0
    unexpected_error_count = 0

    for article in relevant_articles:
        try:
            outcome = check_article(session, article)
            checked_count += 1
            res = outcome.get("result")
            if res == "available":
                available_count += 1
            elif res == "removed":
                removed_count += 1
            elif res == "access_error":
                access_error_count += 1

            if outcome.get("is_baseline"):
                baseline_count += 1
            elif outcome.get("has_updated"):
                updated_count += 1
        except Exception as exc:
            session.rollback()
            unexpected_error_count += 1
            print(f"[ATTENZIONE] [monitoring] Errore imprevisto durante il controllo dell'articolo ID {article.id}: {exc}")

    print(
        f"[INFO] [monitoring] Riepilogo ciclo completato: {checked_count} articoli controllati "
        f"({available_count} disponibili, {access_error_count} errori di accesso, {removed_count} rimossi), "
        f"{baseline_count} nuove versioni di partenza, {updated_count} aggiornamenti rilevati, "
        f"{unexpected_error_count} errori imprevisti"
    )

    # Se c'erano articoli da controllare ma nessuno è andato a buon fine, solleva un errore grave
    if total_candidates > 0 and checked_count == 0:
        msg = f"[ERRORE GRAVE] [monitoring] Nessun articolo controllato con successo nel ciclo di monitoraggio ({total_candidates} articoli in coda)"
        print(msg)
        raise RuntimeError(msg)
