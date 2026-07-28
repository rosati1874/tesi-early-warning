"""Acquisizione mirata (RF-01): feed RSS delle testate monitorate.

ATTENZIONE: gli URL dei feed sotto sono placeholder plausibili.
Vanno verificati manualmente (spesso <sito>/feed o <sito>/rss) prima
del primo run reale, ed eventualmente corretti.
"""
from datetime import datetime, timezone
import feedparser

TARGETED_FEEDS = [
    {"source": "openonline", "url": "https://www.open.online/feed/"},
    {"source": "ilpost", "url": "https://www.ilpost.it/feed/"},
    {"source": "linkiesta", "url": "https://www.linkiesta.it/feed/"},
]


def fetch_targeted_articles() -> list[dict]:
    """Interroga i feed RSS mirati e restituisce una lista di articoli grezzi.

    Ogni elemento: {url, source, title, published_at, acquisition_mode}.
    Il testo completo NON è incluso qui: viene recuperato dal modulo di
    parsing (src.parsing.extractor) a partire dall'URL.
    """
    articles = []
    for feed_cfg in TARGETED_FEEDS:
        parsed = feedparser.parse(feed_cfg["url"])
        if parsed.bozo and not parsed.entries:
            print(f"[targeted] impossibile leggere il feed {feed_cfg['url']}: "
                  f"{parsed.get('bozo_exception')}")
            continue

        for entry in parsed.entries:
            published_at = None
            if getattr(entry, "published_parsed", None):
                published_at = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)

            articles.append({
                "url": entry.get("link"),
                "source": feed_cfg["source"],
                "title": entry.get("title"),
                "published_at": published_at,
                "acquisition_mode": "mirato",
            })
    return articles
