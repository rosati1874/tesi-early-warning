"""Acquisizione generalista (RF-02) via Google News RSS.

Scelta motivata (vedi Cap. 4.1): le API ufficiali di Google Search sono a
pagamento oltre una soglia minima; le librerie di scraping non ufficiale
(es. googlesearch-python) sono fragili e a rischio di violazione ToS.
Google News RSS è un canale gratuito, senza chiave API, pensato per query
testuali e filtrabile per lingua/regione, ed è quindi la scelta principale
per l'acquisizione generalista in questo scaffold.
"""
from datetime import datetime, timezone
import re
import urllib.request
from urllib.parse import quote_plus, urlparse
import feedparser
from googlenewsdecoder import new_decoderv1

from src.config import GENERALIST_QUERIES, REQUEST_TIMEOUT_SECONDS
from src.parsing.extractor import clean_rss_summary

GOOGLE_NEWS_RSS_TEMPLATE = (
    "https://news.google.com/rss/search?q={query}&hl=it-IT&gl=IT&ceid=IT:it"
)

_BARE_AMPERSAND = re.compile(r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)")
_FEEDPARSER_USER_AGENT = "UniversalFeedParser/6.0.11 +https://github.com/kurtmckee/feedparser/"


def _parse_generalist_feed(feed_url: str):
    """Legge un feed Google News RSS, con riparazione XML automatica in caso di ampersand non scappati (&)."""
    parsed = feedparser.parse(feed_url)
    if parsed.entries:
        return parsed

    try:
        req = urllib.request.Request(feed_url, headers={"User-Agent": _FEEDPARSER_USER_AGENT})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            raw = resp.read()
            if raw:
                text_xml = raw.decode("utf-8", errors="replace")
                fixed_xml = _BARE_AMPERSAND.sub("&amp;", text_xml)
                parsed_sanitized = feedparser.parse(fixed_xml.encode("utf-8"))
                if parsed_sanitized.entries:
                    print(f"[INFO] [generalist] Feed Google News per query letto dopo riparazione XML automatica")
                    return parsed_sanitized
                return parsed_sanitized
    except Exception as exc:
        print(f"[ATTENZIONE] [generalist] Impossibile riparare feed Google News {feed_url}: {exc}")

    return parsed


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


def _extract_source_name(entry: dict, resolved_url: str | None = None) -> str:
    """Estrae il nome reale della testata dall'elemento RSS di Google News o dall'URL decodificato.

    1. Tenta il tag dedicato <source> di Google News (feedparser lo decodifica in entry.source).
    2. Come riserva, estrae il dominio dall'URL reale decodificato (es. "repubblica.it", "linkiesta.it").
    3. Se entrambi falliscono, restituisce "google_news".
    """
    # 1. Tentativo da tag <source> di Google News RSS
    source_obj = entry.get("source")
    if isinstance(source_obj, dict) and source_obj.get("title"):
        return source_obj["title"].strip()
    elif hasattr(source_obj, "title") and getattr(source_obj, "title"):
        return getattr(source_obj, "title").strip()

    # 2. Riserva da dominio dell'URL decodificato
    if resolved_url:
        try:
            domain = urlparse(resolved_url).netloc.lower()
            if domain:
                domain = domain.removeprefix("www.").strip()
                if domain and domain != "news.google.com":
                    return domain
        except Exception as exc:
            print(f"[ATTENZIONE] [generalist] Impossibile estrarre il dominio dall'URL '{resolved_url}': {exc}")

    # 3. Riserva generica
    return "google_news"


def fetch_generalist_articles(queries: list[str] | None = None) -> list[dict]:
    """Interroga Google News RSS per ciascuna query e restituisce articoli grezzi con URL decodificati."""
    queries = queries or GENERALIST_QUERIES
    articles = []

    for query in queries:
        feed_url = GOOGLE_NEWS_RSS_TEMPLATE.format(query=quote_plus(query))
        parsed = _parse_generalist_feed(feed_url)
        if not parsed.entries:
            print(f"[ATTENZIONE] [generalist] Impossibile leggere risultati per la query '{query}': "
                  f"{parsed.get('bozo_exception')}")
            continue

        for entry in parsed.entries:
            published_at = None
            if getattr(entry, "published_parsed", None):
                published_at = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)

            raw_link = entry.get("link")
            resolved_url = _resolve_article_url(raw_link)
            source_name = _extract_source_name(entry, resolved_url)

            articles.append({
                "url": resolved_url,
                "source": source_name,  # Nome reale della testata (es. "FNOMCeO", "La Repubblica", "linkiesta.it")
                "title": entry.get("title"),
                "published_at": published_at,
                "acquisition_mode": "generalista",  # Mantiene l'informazione del canale Google News
                "rss_summary": clean_rss_summary(entry.get("summary"), entry.get("title")),
            })

    if not articles:
        print("[ATTENZIONE] [generalist] Nessun articolo recuperato da Google News RSS")
    else:
        print(f"[INFO] [generalist] Acquisizione generalista completata: {len(articles)} articoli estratti")

    return articles
