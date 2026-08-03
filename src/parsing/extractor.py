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


def clean_rss_summary(raw_html: str | None, title: str | None = None) -> str | None:
    """Rimuove tag HTML e firme automatiche di WordPress da un riassunto RSS.

    Se il riassunto pulito è solo una ripetizione del titolo (comune in Google News RSS), restituisce None.
    """
    if not raw_html or not raw_html.strip():
        return None

    soup = BeautifulSoup(raw_html, "html.parser")
    text = soup.get_text(separator=" ", strip=True)

    # Rimuove la firma standard di WordPress "L'articolo [Titolo] proviene da [Nome sito]."
    pattern = r"L['’]articolo\s+.*?\s+proviene\s+da\s+.*$"
    text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.DOTALL).strip()

    # Normalizza gli spazi intermedi
    text = re.sub(r"\s+", " ", text).strip()

    if not text:
        return None

    if title and not is_meaningful_rss_summary(text, title):
        return None

    return text


def is_meaningful_rss_summary(summary: str | None, title: str | None) -> bool:
    """Verifica se il riassunto RSS contiene un testo informativo effettivo oltre al titolo ed al nome della fonte.

    Scarta i riassunti dei feed che contengono solo la rietichettatura/ripetizione del titolo (es. Google News RSS).
    """
    if not summary or not summary.strip():
        return False

    summary_clean = summary.strip().lower()
    title_clean = (title or "").strip().lower()

    summary_words = set(re.findall(r"\w+", summary_clean))
    title_words = set(re.findall(r"\w+", title_clean))

    if not title_words:
        return True

    # Calcola le parole presenti nel summary che NON fanno parte del titolo
    extra_words = [w for w in summary_words - title_words if len(w) > 2]

    # Se le parole del summary che non figurano nel titolo sono meno di 4,
    # il summary è solo una ripetizione del titolo + nome fonte (es. Il Giorno, Repubblica)
    if len(extra_words) < 4:
        return False

    return True


def clean_jina_output(raw_text: str | None) -> str | None:
    """Pulisce l'output di Jina AI Reader rimuovendo l'header dei metadati, le immagini markdown
    ed applicando un'euristica sui confini dell'articolo (dal primo '# Titolo' fino a 'Condividi:').
    """
    if not raw_text or not raw_text.strip():
        return None

    text = raw_text.strip()

    # 1. Rimuove l'intestazione dei metadati Jina fino a "Markdown Content:"
    pattern_header = r"^Title:.*?\bMarkdown Content:\s*"
    text = re.sub(pattern_header, "", text, flags=re.DOTALL | re.IGNORECASE).strip()

    # 2. Euristica Inizio: individua il primo titolo principale Markdown (# Titolo)
    # e scarta tutto il menu di navigazione o il chrome antecedente.
    match_title = re.search(r"(?m)^#\s+.*$", text)
    if match_title:
        text = text[match_title.start():]

    # 3. Euristica Fine: individua la prima occorrenza di "Condividi:" / "Share:" / "Fai clic per condividere"
    # dopo il titolo e scarta tutto ciò che segue (articoli correlati, più letti, footer, banner cookie).
    match_share = re.search(
        r"(?i)(?:^#{1,6}\s*Condividi\b|\bCondividi\s*:|\bShare\s*:|\bFai clic per condividere\b|\bCondividi questo articolo\b)",
        text,
    )
    if match_share:
        text = text[:match_share.start()].rstrip()
        # Rimuove eventuali cancelletti di intestazione rimasti sospesi in fondo prima di "Condividi"
        text = re.sub(r"\n+#{1,6}\s*$", "", text).strip()

    # 4. Rimuove link markdown senza testo visibile con parentesi quadre vuote: [](url)
    text = re.sub(r"\[\]\(.*?\)", "", text)

    # 5. Rimuove immagini markdown nidificate con link: [![alt](img_url)](link_url)
    text = re.sub(r"\[!\[.*?\]\(.*?\)]\(.*?\)", "", text)

    # 6. Rimuove immagini markdown semplici: ![alt](img_url)
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)

    # 7. Rimuove righe di sola firma d'autore o crediti fotografici brevi prima del corpo dell'articolo
    lines = [line.strip() for line in text.splitlines()]
    filtered_lines = []
    for line in lines:
        if not line:
            filtered_lines.append("")
            continue

        # Rimuove link solitari ad autore tipo [Linkiesta](url) o crediti fotografici brevi tipo AP/Lapresse
        if (re.match(r"^\[.*?\]\(.*?\)$", line) and len(line) < 60) or line in ("AP/Lapresse", "Foto AP/Lapresse", "Ansa", "Lapresse"):
            continue

        filtered_lines.append(line)

    text = "\n".join(filtered_lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

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
    Nota: non passare headers HTTP personalizzati a Jina per non interferire con il suo gateway di estrazione.
    """
    jina_url = f"https://r.jina.ai/{url}"
    try:
        resp = requests.get(
            jina_url,
            timeout=20,
        )
        if resp.status_code == 200 and resp.text:
            cleaned = clean_jina_output(resp.text)
            if cleaned and len(cleaned) > 200:
                print(f"[INFO] [extractor] Contenuto recuperato e pulito con successo tramite Jina AI Reader per {url} ({len(cleaned)} caratteri)")
                return cleaned
            else:
                print(f"[ATTENZIONE] [extractor] Testo pulito da Jina AI Reader insufficiente o vuoto per {url}")
        else:
            print(f"[ATTENZIONE] [extractor] Jina AI Reader ha risposto con status {resp.status_code} per {url}")
    except requests.RequestException as exc:
        print(f"[ATTENZIONE] [extractor] Errore durante il recupero via Jina AI Reader per {url}: {exc}")

    return None


SOCIAL_PATTERNS = [
    r"facebook\.com/share",
    r"x\.com/intent",
    r"twitter\.com/(?:intent|share)",
    r"linkedin\.com/share",
    r"(?:api\.)?whatsapp\.com/send",
    r"whatsapp://send",
    r"(?:telegram\.me|t\.me)/share",
    r"fb-messenger://",
    r"mailto:\?subject=",
    r"mailto:\?body=",
]


def is_pure_ui_metadata_line(line: str) -> bool:
    """Restituisce True solo se la riga è una concatenazione isolata di badge/metadati UI
    (es. 'di Redazione Salute ai preferiti su Google 3' di lettura I punti chiave 3' di lettura')
    e NON una frase sintattica di testo reale.
    """
    l_str = line.strip()
    if not l_str:
        return False

    has_preferiti = bool(re.search(r"(?i)\bai\s+preferiti\s+su\s+google\b", l_str))
    has_tempo_lettura = bool(re.search(r"(?i)\b\d+['’]\s*di\s+lettura\b", l_str))
    has_punti_chiave = bool(re.search(r"(?i)^(?:#{1,6}\s*)?I\s+punti\s+chiave$", l_str))

    if has_preferiti or has_tempo_lettura or has_punti_chiave:
        if len(l_str) < 130 and not l_str.endswith((".", "!", "?")):
            return True

    return False


def clean_extracted_text(text: str | None) -> str | None:
    """Pulisce il testo estratto (da trafilatura, BeautifulSoup o Jina AI Reader):
    1. Rimuove righe di condivisione social (>= 3 link) e righe di metadati UI isolati (es. preferiti su Google, 3' di lettura).
    2. Tronca il testo se è presente la dicitura '© Riproduzione riservata'.
    """
    if not text or not text.strip():
        return None

    cleaned = text.strip()

    # 1. Rimuove righe di pulsanti social e metadati UI isolati
    lines = [line.strip() for line in cleaned.splitlines()]
    filtered_lines = [
        line for line in lines
        if not is_social_sharing_line(line) and not is_pure_ui_metadata_line(line)
    ]
    cleaned = "\n".join(filtered_lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    # 2. Tronca dopo '© Riproduzione riservata'
    pattern = r"(?i)(?:©\s*)?Riproduzione\s+riservata"
    match = re.search(pattern, cleaned)
    if match:
        cleaned = cleaned[:match.start()].strip()

    return cleaned if cleaned else None


def extract_article_text(url: str, html: str | None = None) -> str | None:
    """Restituisce il testo principale dell'articolo.

    Livelli di estrazione (RF-03):
    1. Download diretto HTML + trafilatura (con fallback a BeautifulSoup).
    2. Se il download diretto fallisce (es. 403 Forbidden o testo < 200 car), tenta Jina AI Reader (https://r.jina.ai/).
    3. Se anche Jina AI Reader fallisce, restituisce None (permettendo il fallback a rss_summary).
    """
    html_content = html or fetch_html(url)
    if html_content:
        text = trafilatura.extract(html_content, favor_precision=True)
        if text:
            cleaned_text = clean_extracted_text(text)
            if cleaned_text and len(cleaned_text.strip()) > 200:
                return cleaned_text.strip()

        # fallback grezzo con BeautifulSoup: concatena i paragrafi <p>
        soup = BeautifulSoup(html_content, "lxml")
        paragraphs = [p.get_text(strip=True) for p in soup.find_all("p")]
        fallback_text = "\n".join(p for p in paragraphs if p)
        if fallback_text:
            cleaned_fallback = clean_extracted_text(fallback_text)
            if cleaned_fallback and len(cleaned_fallback.strip()) > 200:
                print(f"[INFO] [extractor] Utilizzato fallback BeautifulSoup per {url}")
                return cleaned_fallback.strip()

    # Livello intermedio: Jina AI Reader (se il download diretto è fallito 403 o ha prodotto testo troppo corto)
    print(f"[INFO] [extractor] Download diretto fallito o testo insufficiente per {url}. Tentativo via Jina AI Reader...")
    jina_text = fetch_via_jina_reader(url)
    if jina_text:
        return clean_extracted_text(jina_text)

    print(f"[ATTENZIONE] [extractor] Impossibile estrarre testo dall'articolo (diretto e Jina falliti) per {url}")
    return None
