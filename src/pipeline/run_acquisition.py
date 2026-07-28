"""Entry point della pipeline di acquisizione (RF-01 -> RF-05).

acquisizione (mirata + generalista) -> parsing -> filtro keyword ->
classificazione LLM -> storage.

Richiamato dal workflow .github/workflows/acquisition.yml.
"""
from datetime import datetime, timezone

from src.db.connection import get_session
from src.db.models import Article
from src.acquisition.targeted import fetch_targeted_articles
from src.acquisition.generalist import fetch_generalist_articles
from src.parsing.extractor import extract_article_text
from src.filtering.keywords import passes_keyword_filter
from src.classification.llm_classifier import classify
from src.config import ENABLE_LLM_CLASSIFICATION


def run() -> None:
    session = get_session()

    raw_articles = fetch_targeted_articles() + fetch_generalist_articles()
    print(f"[pipeline] {len(raw_articles)} articoli grezzi acquisiti")

    new_count = 0
    for raw in raw_articles:
        if not raw.get("url"):
            continue

        # RF-03: evita di rielaborare articoli già acquisiti in precedenza
        existing = session.query(Article).filter_by(url=raw["url"]).first()
        if existing:
            continue

        text = extract_article_text(raw["url"])
        if not text:
            # riserva: usa il riassunto già incluso nel feed RSS, quando
            # la pagina completa non è raggiungibile (es. blocco anti-bot,
            # osservato con Linkiesta). Meno ricco del testo completo, ma
            # evita di perdere del tutto l'articolo.
            text = raw.get("rss_summary")
        if not text:
            continue

        passed_filter = passes_keyword_filter(text, raw.get("title", ""))

        classification = {
            "is_epidemic_signal": None,
            "confidence": None,
            "disease": None,
            "location": None,
            "justification": None,
            "llm_model": None,
        }
        if passed_filter and ENABLE_LLM_CLASSIFICATION:
            classification = classify(raw.get("title", ""), text)

        article = Article(
            url=raw["url"],
            source=raw["source"],
            acquisition_mode=raw["acquisition_mode"],
            title=raw.get("title"),
            published_at=raw.get("published_at"),
            first_seen_at=datetime.now(timezone.utc),
            raw_text=text,
            passed_keyword_filter=passed_filter,
            is_epidemic_signal=classification["is_epidemic_signal"],
            llm_confidence=classification["confidence"],
            llm_disease=classification["disease"],
            llm_location=classification["location"],
            llm_justification=classification["justification"],
            llm_model=classification["llm_model"],
        )
        session.add(article)
        session.commit()
        new_count += 1

    print(f"[pipeline] {new_count} nuovi articoli salvati")


if __name__ == "__main__":
    run()
