"""Acquisizione mirata (RF-01): feed RSS delle testate monitorate.

ATTENZIONE: gli URL dei feed sotto sono placeholder plausibili.
Vanno verificati manualmente (spesso <sito>/feed o <sito>/rss) prima
del primo run reale, ed eventualmente corretti.
"""
from datetime import datetime, timezone
import feedparser
import requests

from src.config import HTTP_USER_AGENT, REQUEST_TIMEOUT_SECONDS

TARGETED_FEEDS = [
    {"source": "openonline", "url": "https://www.open.online/feed/"},
    {"source": "ilpost", "url": "https://www.ilpost.it/feed/"},
    {"source": "linkiesta", "url": "https://www.linkiesta.it/feed/"},
]


def _parse_feed(url: str):
    """Legge un feed RSS, con un tentativo di recupero in caso di errore.

    Metodo principale: feedparser.parse(url) direttamente — è il metodo che
    in pratica funziona meglio con le testate italiane monitorate (alcuni
    siti bloccano invece le richieste fatte con la libreria "requests" e
    intestazioni da browser, paradossalmente più sospette agli occhi dei
    sistemi anti-bot rispetto al comportamento "onesto" di feedparser).

    Se il primo tentativo fallisce (es. XML malformato, errore di rete),
    si tenta un secondo giro con intestazioni più complete da browser: è
    un tentativo di recupero per problemi occasionali/temporanei, non una
    soluzione garantita contro un sito che blocchi sistematicamente.
    """
    parsed = feedparser.parse(url)
    if parsed.entries:
        return parsed

    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": HTTP_USER_AGENT,
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
                "Accept-Language": "it-IT,it;q=0.9",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return feedparser.parse(resp.content)
    except requests.RequestException as exc:
        print(f"[targeted] errore HTTP nel recupero del feed {url}: {exc}")
        return parsed  # restituisco comunque il primo risultato (probabilmente vuoto)


def fetch_targeted_articles() -> list[dict]:
    """Interroga i feed RSS mirati e restituisce una lista di articoli grezzi.

    Ogni elemento: {url, source, title, published_at, acquisition_mode,
    rss_summary}. rss_summary è il testo/riassunto già incluso nel feed:
    viene usato come riserva dal modulo di parsing se non è possibile
    scaricare la pagina completa dell'articolo (es. sito che blocca lo
    scraping, come osservato con Linkiesta).
    """
    articles = []
    for feed_cfg in TARGETED_FEEDS:
        parsed = _parse_feed(feed_cfg["url"])
        if not parsed.entries:
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
                "rss_summary": entry.get("summary"),
            })
    return articles
