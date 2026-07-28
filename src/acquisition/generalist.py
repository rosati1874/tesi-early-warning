"""Acquisizione generalista (RF-02) via Google News RSS.

Scelta motivata (vedi Cap. 4.1): le API ufficiali di Google Search sono a
pagamento oltre una soglia minima; le librerie di scraping non ufficiale
(es. googlesearch-python) sono fragili e a rischio di violazione ToS.
Google News RSS è un canale gratuito, senza chiave API, pensato per query
testuali e filtrabile per lingua/regione, ed è quindi la scelta principale
per l'acquisizione generalista in questo scaffold.
"""
from datetime import datetime, timezone
from urllib.parse import quote_plus
import feedparser

from src.config import GENERALIST_QUERIES

GOOGLE_NEWS_RSS_TEMPLATE = (
    "https://news.google.com/rss/search?q={query}&hl=it-IT&gl=IT&ceid=IT:it"
)


def fetch_generalist_articles(queries: list[str] | None = None) -> list[dict]:
    """Interroga Google News RSS per ciascuna query e restituisce articoli grezzi."""
    queries = queries or GENERALIST_QUERIES
    articles = []

    for query in queries:
        feed_url = GOOGLE_NEWS_RSS_TEMPLATE.format(query=quote_plus(query))
        parsed = feedparser.parse(feed_url)
        if parsed.bozo and not parsed.entries:
            print(f"[generalist] impossibile leggere risultati per '{query}': "
                  f"{parsed.get('bozo_exception')}")
            continue

        for entry in parsed.entries:
            published_at = None
            if getattr(entry, "published_parsed", None):
                published_at = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)

            articles.append({
                "url": entry.get("link"),
                "source": "google_news",
                "title": entry.get("title"),
                "published_at": published_at,
                "acquisition_mode": "generalista",
            })
    return articles
