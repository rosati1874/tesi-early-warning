"""Acquisizione generalista (RF-02) via Google News RSS.

Scelta motivata (vedi Cap. 4.1): le API ufficiali di Google Search sono a
pagamento oltre una soglia minima; le librerie di scraping non ufficiale
(es. googlesearch-python) sono fragili e a rischio di violazione ToS.
Google News RSS è un canale gratuito, senza chiave API, pensato per query
testuali e filtrabile per lingua/regione, ed è quindi la scelta principale
per l'acquisizione generalista in questo scaffold.
"""
import time
from datetime import datetime, timezone
import re
from urllib.parse import quote_plus, urlparse
import feedparser
import requests
from googlenewsdecoder import new_decoderv1

from src.config import GENERALIST_QUERIES, HTTP_USER_AGENT, REQUEST_TIMEOUT_SECONDS
from src.parsing.extractor import clean_rss_summary

GOOGLE_NEWS_RSS_TEMPLATE = (
    "https://news.google.com/rss/search?q={query}&hl=it-IT&gl=IT&ceid=IT:it"
)

_BARE_AMPERSAND = re.compile(r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)")


def _parse_generalist_feed(feed_url: str):
    """Legge un feed Google News RSS, con riparazione XML automatica in caso di ampersand non scappati (&)."""
    try:
        resp = requests.get(
            feed_url,
            headers={"User-Agent": HTTP_USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS
        )
        resp.raise_for_status()
        raw = resp.content
    except Exception as exc:
        print(f"[ATTENZIONE] [generalist] Impossibile scaricare feed Google News {feed_url}: {exc}")
        return feedparser.FeedParserDict(entries=[])

    parsed = feedparser.parse(raw)
    if parsed.entries:
        return parsed

    try:
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

    Strategia multistadio:
    1. Tenta la decodifica offline con googlenewsdecoder (new_decoderv1).
    2. Se fallisce o restituisce ancora un URL Google News, tenta l'inseguimento dei redirect HTTP
       con retry e backoff in caso di errori transitori di rete.
    3. Come riserva finale, logga un avviso [ATTENZIONE] e restituisce l'URL originale invariato.
    """
    if not raw_url:
        return None

    if "news.google.com" in raw_url:
        # Livello 1: Tentativo di decodifica offline con googlenewsdecoder
        decoded_url = None
        try:
            res = new_decoderv1(raw_url)
            if isinstance(res, dict) and res.get("status") and res.get("decoded_url"):
                decoded_url = res["decoded_url"]
            elif isinstance(res, str) and res.startswith("http"):
                decoded_url = res
        except Exception:
            pass

        if decoded_url and "news.google.com" not in decoded_url:
            return decoded_url

        # Livello 2: Fallback tramite inseguimento dei redirect HTTP (con retry e backoff)
        max_retries = 2
        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.get(
                    raw_url,
                    allow_redirects=True,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                    headers={"User-Agent": HTTP_USER_AGENT},
                )
                if resp.status_code == 200 and resp.url and "news.google.com" not in resp.url:
                    print(f"[INFO] [generalist] URL Google News decodificato tramite fallback HTTP redirect: {resp.url}")
                    return resp.url
                break
            except requests.exceptions.RequestException as exc:
                if attempt < max_retries:
                    print(f"[ATTENZIONE] [generalist] Tentativo {attempt}/{max_retries} per HTTP redirect su '{raw_url}' fallito ({exc}). Retry in 1s...")
                    time.sleep(1)
                else:
                    print(f"[ATTENZIONE] [generalist] Impossibile decodificare URL Google News '{raw_url}' via HTTP redirect dopo {max_retries} tentativi: {exc}")
                    return raw_url

        print(f"[ATTENZIONE] [generalist] Impossibile decodificare URL Google News '{raw_url}': sia decoder sia HTTP redirect hanno restituito link Google News")

    return raw_url


def _extract_source_name(
    entry: dict,
    resolved_url: str | None = None,
    targeted_sources_map: dict[str, str] | None = None
) -> str:
    """Estrae il nome reale della testata dall'elemento RSS di Google News o dall'URL decodificato.

    Gerarchia di fallback:
    1. Tag dedicato <source> di Google News RSS (es. entry.source.title = "La Repubblica").
    2. Cross-referenziazione con il canale mirato (tramite URL decodificato o titolo identico).
    3. Dominio dell'URL reale decodificato (es. "repubblica.it", "linkiesta.it").
    4. Parsing del titolo dell'item RSS (formato "Titolo articolo - Nome testata").
    5. Riserva generica finale "google_news".
    """
    # 1. Tentativo da tag <source> di Google News RSS
    source_obj = entry.get("source") if isinstance(entry, dict) else getattr(entry, "source", None)
    if isinstance(source_obj, dict) and source_obj.get("title"):
        s_name = source_obj["title"].strip()
        if s_name:
            return s_name
    elif hasattr(source_obj, "title") and getattr(source_obj, "title"):
        s_name = getattr(source_obj, "title").strip()
        if s_name:
            return s_name

    # 2. Cross-referenziazione con il canale mirato (se fornita mappa URL/Titolo -> Fonte)
    if targeted_sources_map:
        if resolved_url and resolved_url in targeted_sources_map:
            return targeted_sources_map[resolved_url]
        raw_title = entry.get("title") if isinstance(entry, dict) else getattr(entry, "title", None)
        if raw_title and isinstance(raw_title, str) and raw_title.strip().lower() in targeted_sources_map:
            return targeted_sources_map[raw_title.strip().lower()]

    # 3. Riserva da dominio dell'URL decodificato
    if resolved_url:
        try:
            domain = urlparse(resolved_url).netloc.lower()
            if domain:
                domain = domain.removeprefix("www.").strip()
                if domain and domain != "news.google.com":
                    return domain
        except Exception as exc:
            print(f"[ATTENZIONE] [generalist] Impossibile estrarre il dominio dall'URL '{resolved_url}': {exc}")

    # 4. Parsing del titolo dell'item RSS (formato "Titolo articolo - Nome testata")
    title = entry.get("title") if isinstance(entry, dict) else getattr(entry, "title", None)
    if title and isinstance(title, str):
        parts = re.split(r"\s+[\-\–\—]\s+", title)
        if len(parts) > 1:
            candidate = parts[-1].strip()
            # Validazione: lunghezza compresa tra 2 e 60 car, non coincide col titolo intero, non solo cifre
            if candidate and 2 <= len(candidate) <= 60 and candidate.lower() != title.lower() and not candidate.isdigit():
                return candidate

    # 5. Riserva generica finale
    return "google_news"


def fetch_generalist_articles(
    queries: list[str] | None = None,
    targeted_sources_map: dict[str, str] | None = None
) -> list[dict]:
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
            source_name = _extract_source_name(entry, resolved_url, targeted_sources_map)

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

