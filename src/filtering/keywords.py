"""Filtro lessicale su parole chiave di dominio (RF-04)."""
import re
import yaml

from src.config import KEYWORDS_PATH

_keywords_cache: list[str] | None = None


def load_keywords() -> list[str]:
    global _keywords_cache
    if _keywords_cache is None:
        try:
            with open(KEYWORDS_PATH, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            _keywords_cache = [kw.lower() for kw in data.get("keywords", [])]
        except Exception as exc:
            msg = f"[ERRORE GRAVE] [filtering] Impossibile caricare il file di keywords '{KEYWORDS_PATH}': {exc}"
            print(msg)
            raise RuntimeError(msg) from exc
    return _keywords_cache


def passes_keyword_filter(text: str, title: str = "") -> bool:
    """True se il testo (o il titolo) contiene almeno una keyword di dominio."""
    if not text and not title:
        return False
    haystack = f"{title}\n{text}".lower()
    return any(re.search(rf"\b{re.escape(kw)}\b", haystack) for kw in load_keywords())
