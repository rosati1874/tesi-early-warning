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


def extract_article_text(url: str, html: str | None = None) -> str | None:
    """Restituisce il testo principale dell'articolo, o None se non estraibile."""
    html = html or fetch_html(url)
    if not html:
        return None

    text = trafilatura.extract(html, favor_recall=True)
    if text:
        return text.strip()

    # fallback grezzo con BeautifulSoup: concatena i paragrafi <p>
    soup = BeautifulSoup(html, "lxml")
    paragraphs = [p.get_text(strip=True) for p in soup.find_all("p")]
    fallback_text = "\n".join(p for p in paragraphs if p)
    if fallback_text:
        print(f"[INFO] [extractor] Utilizzato fallback BeautifulSoup per {url}")
        return fallback_text

    print(f"[ATTENZIONE] [extractor] Impossibile estrarre testo dall'articolo {url}")
    return None
