"""Acquisizione mirata (RF-01): feed RSS delle testate monitorate.

ATTENZIONE: gli URL dei feed sotto sono placeholder plausibili.
Vanno verificati manualmente (spesso <sito>/feed o <sito>/rss) prima
del primo run reale, ed eventualmente corretti.
"""
import re
from datetime import datetime, timezone
import feedparser
import requests

from src.config import HTTP_USER_AGENT, REQUEST_TIMEOUT_SECONDS

TARGETED_FEEDS = [
    {"source": "openonline", "url": "https://www.open.online/feed/"},
    {"source": "ilpost", "url": "https://www.ilpost.it/feed/"},
    {"source": "linkiesta", "url": "https://www.linkiesta.it/feed/"},
]

# Un simbolo "&" scritto da solo (non seguito da un codice valido come
# &amp; o &#39;) non è XML corretto e manda in errore i parser rigorosi.
# È il difetto più comune nei feed "leggermente rotti". Questa regex trova
# solo i "&" scritti male e li ripara, senza toccare quelli già corretti.
_BARE_AMPERSAND = re.compile(r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)")


def _sanitize_xml(raw_bytes: bytes) -> bytes:
    text = raw_bytes.decode("utf-8", errors="replace")
    fixed = _BARE_AMPERSAND.sub("&amp;", text)
    return fixed.encode("utf-8")


def _fetch_raw(url: str) -> bytes | None:
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
        return resp.content
    except requests.RequestException as exc:
        print(f"[targeted] errore HTTP nel recupero del feed {url}: {exc}")
        return None


def _parse_feed(url: str):
    """Legge un feed RSS, con due tentativi di recupero in caso di errore.

    1. feedparser.parse(url) direttamente — funziona nella maggior parte
       dei casi ed è il metodo meno soggetto a blocchi anti-bot.
    2. Se fallisce: nuovo download con intestazioni da browser (alcuni
       fallimenti sono dovuti a problemi di rete temporanei).
    3. Se fallisce ANCHE questo: si presume un XML malformato nel feed
       stesso (es. un "&" scritto in modo scorretto, osservato con Il
       Post) e si tenta una riparazione automatica prima di un ultimo
       tentativo di lettura.
    """
    parsed = feedparser.parse(url)
    if parsed.entries:
        return parsed

    raw = _fetch_raw(url)
    if raw:
        parsed_retry = feedparser.parse(raw)
        if parsed_retry.entries:
            return parsed_retry

        # ultimo tentativo: ripara il difetto XML più comune e riprova
        sanitized = _sanitize_xml(raw)
        parsed_sanitized = feedparser.parse(sanitized)
        if parsed_sanitized.entries:
            print(f"[targeted] feed {url} letto dopo riparazione XML automatica")
            return parsed_sanitized
        return parsed_sanitized

    return parsed


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
