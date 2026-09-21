"""Monitoraggio periodico di disponibilità e contenuto (RF-06, Cap. 4.6).

Applicato solo agli articoli con is_epidemic_signal=True, per contenere
il carico ed essere coerenti col vincolo di gratuità (RNF-03/RNF-04).
Riusa requests + trafilatura già presenti nella pipeline di parsing.
"""
import hashlib
from datetime import datetime, timezone

import requests

from src.config import HTTP_USER_AGENT, REQUEST_TIMEOUT_SECONDS
from src.parsing.extractor import extract_article_text
from src.db.models import Article, ArticleVersion, AvailabilityCheck
from src.notifications.webhook import notify_monitoring_update


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check_article(session, article: Article) -> None:
    """Esegue un controllo di disponibilità/contenuto su un singolo articolo
    e registra i risultati (availability_checks, eventuale nuova
    article_versions), aggiornando lo stato dell'articolo.
    Se rileva una rimozione (404) o un aggiornamento, invia una notifica webhook.
    """
    original_status = article.status
    has_updated = False
    new_version = None

    try:
        resp = requests.get(
            article.url,
            headers={"User-Agent": HTTP_USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        http_status = resp.status_code

        if resp.status_code == 404:
            result = "removed"
            article.status = "removed"
            print(f"[ATTENZIONE] [monitoring] Articolo ID {article.id} ({article.url}) rimosso (HTTP 404)")
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
        current_text = extract_article_text(article.url, html=resp.text)
        if current_text:
            new_hash = _hash_text(current_text)
            last_version = (
                session.query(ArticleVersion)
                .filter_by(article_id=article.id)
                .order_by(ArticleVersion.captured_at.desc())
                .first()
            )
            
            # Se non c'è una versione salvata, hash di default è quello del testo originale
            hash_to_compare = last_version.content_hash if last_version else _hash_text(article.raw_text or "")
            
            if hash_to_compare != new_hash:
                new_version = ArticleVersion(
                    article_id=article.id,
                    content_hash=new_hash,
                    text_snapshot=current_text,
                )
                session.add(new_version)
                has_updated = True
                print(f"[INFO] [monitoring] Rilevata nuova versione del contenuto per articolo ID {article.id}")

    article.last_checked_at = datetime.now(timezone.utc)
    session.commit()
    
    # Invia notifiche webhook (RF-06/RF-07) se ci sono stati cambiamenti di stato o contenuto
    if original_status != "removed" and article.status == "removed" and article.is_epidemic_signal:
        print(f"[INFO] [monitoring] Invio notifica webhook per rimozione articolo ID {article.id}")
        notify_monitoring_update(session, article, "epidemic_signal_removed", http_status=http_status)
    elif has_updated and article.is_epidemic_signal:
        print(f"[INFO] [monitoring] Invio notifica webhook per aggiornamento articolo ID {article.id}")
        # Ricarico new_version per assicurarmi che captured_at sia valorizzato dopo il commit
        if new_version:
            session.refresh(new_version)
        notify_monitoring_update(session, article, "epidemic_signal_updated", version=new_version)


def run_monitoring_cycle(session) -> None:
    """Esegue un ciclo di monitoraggio su tutti gli articoli rilevanti con stato attivo."""
    relevant_articles = (
        session.query(Article)
        .filter(
            Article.is_epidemic_signal.is_(True),
            Article.status == "active",
        )
        .all()
    )
    print(f"[INFO] [monitoring] Avvio ciclo di monitoraggio: {len(relevant_articles)} articoli da controllare")
    for article in relevant_articles:
        check_article(session, article)
    print("[INFO] [monitoring] Ciclo di monitoraggio completato con successo")
