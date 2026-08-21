"""Configurazione centrale del sistema, letta da variabili d'ambiente."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "")

# Interruttore per la classificazione LLM: quando è "false" (default),
# la pipeline raccoglie e salva comunque gli articoli, ma salta la
# chiamata a Gemini. Utile per continuare a lavorare sull'acquisizione
# quando si esaurisce la quota gratuita, senza modificare il codice:
# basta creare/aggiornare la variabile ENABLE_LLM_CLASSIFICATION nei
# secrets/variables di GitHub (valore "true" per riattivarla).
ENABLE_LLM_CLASSIFICATION = os.environ.get(
    "ENABLE_LLM_CLASSIFICATION", "false"
).lower() == "true"

# Interruttore per le notifiche webhook pub-sub: quando è "false" (default),
# la pipeline non effettua query alla tabella subscribers né invia chiamate HTTP POST.
ENABLE_WEBHOOK_NOTIFICATIONS = os.environ.get(
    "ENABLE_WEBHOOK_NOTIFICATIONS", "false"
).lower() == "true"

# Numero massimo di articoli da inviare al modello LLM ad ogni esecuzione (default 60)
MAX_LLM_CLASSIFICATIONS_PER_RUN = int(
    os.environ.get("MAX_LLM_CLASSIFICATIONS_PER_RUN", "60")
)

# Filtro di freschezza: scarta gli articoli pubblicati da più di N giorni (default 30)
MAX_ARTICLE_AGE_DAYS = int(os.environ.get("MAX_ARTICLE_AGE_DAYS", "30"))

BASE_DIR = Path(__file__).resolve().parent
KEYWORDS_PATH = BASE_DIR / "filtering" / "keywords.yaml"

# Query usate per l'acquisizione generalista via Google News RSS
GENERALIST_QUERIES = [
    "epidemia Italia",
    "focolaio virus",
    "contagio nuovi casi",
    "allerta sanitaria OMS",
]

# User-Agent per le richieste HTTP. Un User-Agent che si dichiara "bot" viene
# bloccato (403) da alcune testate (osservato con Linkiesta): usiamo quindi
# uno User-Agent standard da browser desktop. Il rispetto delle fonti resta
# garantito dal fatto che il sistema fa una sola richiesta per articolo,
# a bassa frequenza (RNF-04), non da come ci si presenta nell'header.
HTTP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT_SECONDS = 15

if not DATABASE_URL:
    print("[ATTENZIONE] [config] DATABASE_URL non impostata (vedi .env.example)")
if not GEMINI_API_KEY:
    print("[ATTENZIONE] [config] GEMINI_API_KEY non impostata (vedi .env.example)")
