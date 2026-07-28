"""Estrazione del contenuto di un articolo a partire dall'URL (RF-03).

Strategia: trafilatura come estrattore principale del testo (robusto su
pagine giornalistiche, gratuito), con fallback a BeautifulSoup per i casi
in cui trafilatura non produce risultato. Selenium NON è incluso in questo
scaffold: va aggiunto solo se in pratica si incontrano pagine che
richiedono rendering JavaScript (RF-03 lo prevede come possibilità, non
come requisito sempre attivo).
"""
import requests
import trafilatura
from bs4 import BeautifulSoup

from src.config import HTTP_USER_AGENT, REQUEST_TIMEOUT_SECONDS


def fetch_html(url: str) -> str | None:
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": HTTP_USER_AGENT},
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
