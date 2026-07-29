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
from googlenewsdecoder import new_decoderv1

from src.config import GENERALIST_QUERIES

GOOGLE_NEWS_RSS_TEMPLATE = (
    "https://news.google.com/rss/search?q={query}&hl=it-IT&gl=IT&ceid=IT:it"
)


def _resolve_article_url(raw_url: str | None) -> str | None:
    """Decodifica un link cifrato di Google News nell'URL reale di destinazione dell'articolo.
    In caso di errore, logga un avviso [ATTENZIONE] e restituisce l'URL originale come riserva.
    """
    if not raw_url:
        return None

    if "news.google.com" in raw_url:
        try:
            res = new_decoderv1(raw_url)
            if isinstance(res, dict) and res.get("status") and res.get("decoded_url"):
                return res["decoded_url"]
            elif isinstance(res, str) and res.startswith("http"):
                return res
        except Exception as exc:
            print(f"[ATTENZIONE] [generalist] Impossibile decodificare URL Google News '{raw_url}': {exc}")

    return raw_url


def fetch_generalist_articles(queries: list[str] | None = None) -> list[dict]:
    """Interroga Google News RSS per ciascuna query e restituisce articoli grezzi con URL decodificati."""
    queries = queries or GENERALIST_QUERIES
    articles = []

    for query in queries:
        feed_url = GOOGLE_NEWS_RSS_TEMPLATE.format(query=quote_plus(query))
        parsed = feedparser.parse(feed_url)
        if parsed.bozo and not parsed.entries:
            print(f"[ATTENZIONE] [generalist] Impossibile leggere risultati per la query '{query}': "
                  f"{parsed.get('bozo_exception')}")
            continue

        for entry in parsed.entries:
            published_at = None
            if getattr(entry, "published_parsed", None):
                published_at = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)

            raw_link = entry.get("link")
            resolved_url = _resolve_article_url(raw_link)

            articles.append({
                "url": resolved_url,
                "source": "google_news",
                "title": entry.get("title"),
                "published_at": published_at,
                "acquisition_mode": "generalista",
                "rss_summary": entry.get("summary"),
            })

    if not articles:
        print("[ATTENZIONE] [generalist] Nessun articolo recuperato da Google News RSS")
    else:
        print(f"[INFO] [generalist] Acquisizione generalista completata: {len(articles)} articoli estratti")

    return articles
