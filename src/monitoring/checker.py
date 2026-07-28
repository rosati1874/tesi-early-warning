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


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check_article(session, article: Article) -> None:
    """Esegue un controllo di disponibilità/contenuto su un singolo articolo
    e registra i risultati (availability_checks, eventuale nuova
    article_versions), aggiornando lo stato dell'articolo.
    """
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
        elif resp.ok:
            result = "available"
            article.status = "active"
        else:
            result = "access_error"

    except requests.RequestException as exc:
        print(f"[monitoring] errore accesso a {article.url}: {exc}")
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
            if last_version is None or last_version.content_hash != new_hash:
                session.add(ArticleVersion(
                    article_id=article.id,
                    content_hash=new_hash,
                    text_snapshot=current_text,
                ))

    article.last_checked_at = datetime.now(timezone.utc)
    session.commit()


def run_monitoring_cycle(session) -> None:
    """Esegue un ciclo di monitoraggio su tutti gli articoli rilevanti."""
    relevant_articles = (
        session.query(Article)
        .filter(Article.is_epidemic_signal.is_(True))
        .all()
    )
    print(f"[monitoring] {len(relevant_articles)} articoli da controllare")
    for article in relevant_articles:
        check_article(session, article)
