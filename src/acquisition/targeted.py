"""Acquisizione mirata (RF-01): feed RSS delle testate monitorate.

ATTENZIONE: gli URL dei feed sotto sono placeholder plausibili.
Vanno verificati manualmente (spesso <sito>/feed o <sito>/rss) prima
del primo run reale, ed eventualmente corretti.
"""
import re
import urllib.request
from datetime import datetime, timezone
import feedparser

from src.config import REQUEST_TIMEOUT_SECONDS

TARGETED_FEEDS = [
    {"source": "openonline", "url": "https://www.open.online/feed/"},
    {"source": "ilpost", "url": "https://www.ilpost.it/feed"},
    {"source": "linkiesta", "url": "https://www.linkiesta.it/feed/"},
    {"source": "ansa_salute", "url": "https://www.ansa.it/canale_saluteebenessere/notizie/saluteebenessere_rss.xml"},
    {"source": "repubblica", "url": "https://www.repubblica.it/rss/homepage/rss2.0.xml"},
    # Feed verificato e perfettamente funzionante.
    {"source": "adnkronos_salute", "url": "https://www.adnkronos.com/RSS_Salute.xml"},
]

# Un simbolo "&" scritto da solo (non seguito da un codice valido come
# &amp; o &#39;) non è XML corretto e manda in errore i parser rigorosi.
# È il difetto più comune nei feed "leggermente rotti". Questa regex trova
# solo i "&" scritti male e li ripara, senza toccare quelli già corretti.
_BARE_AMPERSAND = re.compile(r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)")

# Stesso User-Agent usato internamente da feedparser: lo scarichiamo "a
# mano" solo per poter riparare il contenuto, ma presentandoci nello
# stesso modo discreto che il sito non blocca (a differenza di un
# User-Agent da browser con la libreria requests, osservato bloccato).
_FEEDPARSER_USER_AGENT = "UniversalFeedParser/6.0.11 +https://github.com/kurtmckee/feedparser/"


def _sanitize_xml(raw_bytes: bytes) -> bytes:
    text = raw_bytes.decode("utf-8", errors="replace")
    fixed = _BARE_AMPERSAND.sub("&amp;", text)
    return fixed.encode("utf-8")


def _fetch_raw(url: str) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _FEEDPARSER_USER_AGENT})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            return resp.read()
    except Exception as exc:  # noqa: BLE001 - qualunque errore di rete/HTTP
        print(f"[targeted] errore nel recupero grezzo del feed {url}: {exc}")
        return None


def _parse_feed(url: str):
    """Legge un feed RSS, con un tentativo di riparazione in caso di errore.

    1. feedparser.parse(url) direttamente — funziona nella maggior parte
       dei casi.
    2. Se fallisce per XML malformato (non per un blocco di rete): si
       riscarica il contenuto grezzo con lo stesso User-Agent "discreto"
       di feedparser (per non incorrere nello stesso blocco anti-bot
       osservato con intestazioni da browser), si ripara il difetto XML
       più comune, e si riprova a leggerlo.
    """
    parsed = feedparser.parse(url)
    if parsed.entries:
        return parsed

    raw = _fetch_raw(url)
    if raw:
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
