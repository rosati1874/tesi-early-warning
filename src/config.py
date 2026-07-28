"""Configurazione centrale del sistema, letta da variabili d'ambiente."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")

BASE_DIR = Path(__file__).resolve().parent
KEYWORDS_PATH = BASE_DIR / "filtering" / "keywords.yaml"

# Query usate per l'acquisizione generalista via Google News RSS
GENERALIST_QUERIES = [
    "epidemia Italia",
    "focolaio virus",
    "contagio nuovi casi",
    "allerta sanitaria OMS",
]

# User-Agent onesto per le richieste HTTP (buona pratica, RNF-05/robots.txt)
HTTP_USER_AGENT = (
    "TesiEarlyWarningBot/0.1 (+progetto di tesi magistrale, uso non commerciale)"
)
REQUEST_TIMEOUT_SECONDS = 15

if not DATABASE_URL:
    print("[config] ATTENZIONE: DATABASE_URL non impostata (vedi .env.example)")
if not GEMINI_API_KEY:
    print("[config] ATTENZIONE: GEMINI_API_KEY non impostata (vedi .env.example)")
