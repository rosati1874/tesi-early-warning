"""Estrazione del contenuto di un articolo a partire dall'URL (RF-03).

Strategia: trafilatura come estrattore principale del testo (robusto su
pagine giornalistiche, gratuito), con fallback a BeautifulSoup per i casi
in cui trafilatura non produce risultato. Selenium NON è incluso in questo
scaffold: va aggiunto solo se in pratica si incontrano pagine che
richiedono rendering JavaScript (RF-03 lo prevede come possibilità, non
come requisito sempre attivo).
"""
import re
import requests
import trafilatura
from bs4 import BeautifulSoup

from src.config import HTTP_USER_AGENT, REQUEST_TIMEOUT_SECONDS


def clean_rss_summary(raw_html: str | None) -> str | None:
    """Rimuove tag HTML e firme automatiche di WordPress da un riassunto RSS."""
    if not raw_html or not raw_html.strip():
        return None

    soup = BeautifulSoup(raw_html, "html.parser")
    text = soup.get_text(separator=" ", strip=True)

    # Rimuove la firma standard di WordPress "L'articolo [Titolo] proviene da [Nome sito]."
    pattern = r"L['’]articolo\s+.*?\s+proviene\s+da\s+.*$"
    text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.DOTALL).strip()

    # Normalizza gli spazi intermedi
    text = re.sub(r"\s+", " ", text).strip()

    return text if text else None


DEFAULT_HEADERS = {
    "User-Agent": HTTP_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
}


def fetch_html(url: str) -> str | None:
    try:
        resp = requests.get(
            url,
            headers=DEFAULT_HEADERS,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as exc:
        print(f"[ATTENZIONE] [extractor] Errore nel recupero di {url}: {exc}")
        return None


def fetch_via_jina_reader(url: str) -> str | None:
    """Tenta il recupero del contenuto dell'articolo tramite il servizio gratuito Jina AI Reader (https://r.jina.ai/).

    Supera blocchi 403 Forbidden ed anti-bot su testate come Linkiesta e Repubblica senza richiedere chiave API.
    """
    jina_url = f"https://r.jina.ai/{url}"
    try:
        resp = requests.get(
            jina_url,
            headers=DEFAULT_HEADERS,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if resp.status_code == 200 and resp.text and len(resp.text.strip()) > 200:
            print(f"[INFO] [extractor] Contenuto recuperato con successo tramite Jina AI Reader per {url} ({len(resp.text)} caratteri)")
            return resp.text.strip()
    except requests.RequestException as exc:
        print(f"[ATTENZIONE] [extractor] Errore durante il recupero via Jina AI Reader per {url}: {exc}")

    return None


def extract_article_text(url: str, html: str | None = None) -> str | None:
    """Restituisce il testo principale dell'articolo.

    Livelli di estrazione (RF-03):
    1. Download diretto HTML + trafilatura (con fallback a BeautifulSoup).
    2. Se il download diretto fallisce (es. 403 Forbidden o testo < 200 car), tenta Jina AI Reader (https://r.jina.ai/).
    3. Se anche Jina AI Reader fallisce, restituisce None (permettendo il fallback a rss_summary).
    """
    html_content = html or fetch_html(url)
    if html_content:
        text = trafilatura.extract(html_content, favor_recall=True)
        if text and len(text.strip()) > 200:
            return text.strip()

        # fallback grezzo con BeautifulSoup: concatena i paragrafi <p>
        soup = BeautifulSoup(html_content, "lxml")
        paragraphs = [p.get_text(strip=True) for p in soup.find_all("p")]
        fallback_text = "\n".join(p for p in paragraphs if p)
        if fallback_text and len(fallback_text.strip()) > 200:
            print(f"[INFO] [extractor] Utilizzato fallback BeautifulSoup per {url}")
            return fallback_text.strip()

    # Livello intermedio: Jina AI Reader (se il download diretto è fallito 403 o ha prodotto testo troppo corto)
    print(f"[INFO] [extractor] Download diretto fallito o testo insufficiente per {url}. Tentativo via Jina AI Reader...")
    jina_text = fetch_via_jina_reader(url)
    if jina_text:
        return jina_text

    print(f"[ATTENZIONE] [extractor] Impossibile estrarre testo dall'articolo (diretto e Jina falliti) per {url}")
    return None
