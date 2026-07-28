"""Classificazione semantica tramite LLM (RF-05).

Implementazione principale: Gemini API (free tier). Il modulo è pensato
per essere sostituibile (RNF-05): un classificatore locale via Ollama
potrà implementare la stessa interfaccia `classify(title, text) -> dict`
per il confronto sperimentale del Cap. 6.
"""
import json
import google.generativeai as genai

from src.config import GEMINI_API_KEY, GEMINI_MODEL
from src.classification.prompts import build_classification_prompt

_configured = False


def _ensure_configured():
    global _configured
    if not _configured:
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY non impostata: vedi .env.example")
        genai.configure(api_key=GEMINI_API_KEY)
        _configured = True


def classify(title: str, text: str) -> dict:
    """Restituisce un dict con is_epidemic_signal, confidence, disease,
    location, justification. In caso di errore/parsing fallito, restituisce
    un risultato con is_epidemic_signal=None e justification descrittiva,
    così che il chiamante possa decidere come trattarlo (es. retry, log).
    """
    _ensure_configured()
    model = genai.GenerativeModel(GEMINI_MODEL)
    prompt = build_classification_prompt(title, text)

    try:
        response = model.generate_content(prompt)
        raw = response.text.strip()
        # rimuove eventuali code fence markdown residui
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(raw)
        return {
            "is_epidemic_signal": parsed.get("is_epidemic_signal"),
            "confidence": parsed.get("confidence"),
            "disease": parsed.get("disease"),
            "location": parsed.get("location"),
            "justification": parsed.get("justification"),
            "llm_model": GEMINI_MODEL,
        }
    except Exception as exc:  # noqa: BLE001 - vogliamo loggare qualunque errore LLM/parsing
        print(f"[llm_classifier] errore di classificazione: {exc}")
        return {
            "is_epidemic_signal": None,
            "confidence": None,
            "disease": None,
            "location": None,
            "justification": f"errore di classificazione: {exc}",
            "llm_model": GEMINI_MODEL,
        }
