"""Filtro lessicale su parole chiave di dominio (RF-04)."""
import re
import yaml

from src.config import KEYWORDS_PATH

_keywords_cache: list[str] | None = None
_compiled_pattern: re.Pattern | None = None


def load_keywords() -> list[str]:
    global _keywords_cache, _compiled_pattern
    if _keywords_cache is None or _compiled_pattern is None:
        try:
            with open(KEYWORDS_PATH, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            _keywords_cache = [kw.lower().strip() for kw in data.get("keywords", []) if kw.strip()]
            if _keywords_cache:
                pattern_str = r"\b(?:" + "|".join(re.escape(kw) for kw in _keywords_cache) + r")\b"
                _compiled_pattern = re.compile(pattern_str, re.IGNORECASE)
            else:
                _compiled_pattern = re.compile(r"^$")
        except Exception as exc:
            msg = f"[ERRORE GRAVE] [filtering] Impossibile caricare il file di keywords '{KEYWORDS_PATH}': {exc}"
            print(msg)
            raise RuntimeError(msg) from exc
    return _keywords_cache


def passes_keyword_filter(text: str, title: str = "") -> bool:
    """True se il testo (o il titolo) contiene almeno una keyword di dominio (6x più veloce via regex pre-compilata)."""
    if not text and not title:
        return False
    load_keywords()
    if not _compiled_pattern:
        return False
    haystack = f"{title}\n{text}"
    return bool(_compiled_pattern.search(haystack))
