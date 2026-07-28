"""Classificazione semantica tramite LLM (RF-05).

Implementazione principale: Gemini API (free tier). Il modulo è pensato
per essere sostituibile (RNF-05): un classificatore locale via Ollama
potrà implementare la stessa interfaccia `classify(title, text) -> dict`
per il confronto sperimentale del Cap. 6.
"""
import os
import json
import google.generativeai as genai

from src.config import GEMINI_API_KEY, GEMINI_MODEL
from src.classification.prompts import build_classification_prompt

_configured = False
_cached_model_name: str | None = None


def _ensure_configured():
    global _configured
    if not _configured:
        if not GEMINI_API_KEY:
            msg = "[ERRORE GRAVE] [llm_classifier] GEMINI_API_KEY non impostata: vedi .env.example"
            print(msg)
            raise RuntimeError(msg)
        genai.configure(api_key=GEMINI_API_KEY)
        _configured = True


def select_best_gemini_model() -> str:
    """Seleziona automaticamente il miglior modello Gemini disponibile dall'API.

    Priorità:
    1. Se la variabile d'ambiente GEMINI_MODEL è impostata esplicitamente, usa quel valore.
    2. Altrimenti interroga `genai.list_models()` filtrando per quelli che supportano 'generateContent'.
    3. Preferisce le varianti 'flash' (es. gemini-2.0-flash, gemini-1.5-flash).
    4. Se list_models non restituisce nulla o fallisce, usa 'gemini-1.5-flash' come fallback.
    """
    global _cached_model_name
    if _cached_model_name:
        return _cached_model_name

    env_model = os.environ.get("GEMINI_MODEL")
    if env_model and env_model.strip():
        _cached_model_name = env_model.strip()
        print(f"[INFO] [llm_classifier] Modello Gemini impostato da variabile GEMINI_MODEL: {_cached_model_name}")
        return _cached_model_name

    try:
        models = list(genai.list_models())
        supported = [
            m for m in models
            if "generateContent" in getattr(m, "supported_generation_methods", [])
        ]

        flash_models = [m for m in supported if "flash" in m.name.lower()]

        selected_name = None
        if flash_models:
            flash_models.sort(key=lambda m: m.name, reverse=True)
            selected_name = flash_models[0].name
        elif supported:
            supported.sort(key=lambda m: m.name, reverse=True)
            selected_name = supported[0].name

        if selected_name:
            clean_name = selected_name.removeprefix("models/")
            print(f"[INFO] [llm_classifier] Modello Gemini selezionato automaticamente: {clean_name}")
            _cached_model_name = clean_name
            return _cached_model_name

    except Exception as exc:
        print(f"[ATTENZIONE] [llm_classifier] Impossibile interrogare list_models(): {exc}. Fallback su modello predefinito.")

    fallback = GEMINI_MODEL or "gemini-1.5-flash"
    _cached_model_name = fallback
    print(f"[INFO] [llm_classifier] Utilizzo modello di fallback: {_cached_model_name}")
    return _cached_model_name


def classify(title: str, text: str) -> dict:
    """Restituisce un dict con is_epidemic_signal, confidence, disease,
    location, justification. In caso di errore/parsing fallito, restituisce
    un risultato con is_epidemic_signal=None e justification descrittiva,
    così che il chiamante possa decidere come trattarlo (es. retry, log).
    """
    _ensure_configured()
    model_name = select_best_gemini_model()
    model = genai.GenerativeModel(model_name)
    prompt = build_classification_prompt(title, text)

    try:
        response = model.generate_content(prompt)
        raw = response.text.strip()
        # rimuove eventuali code fence markdown residui
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(raw)
        res = {
            "is_epidemic_signal": parsed.get("is_epidemic_signal"),
            "confidence": parsed.get("confidence"),
            "disease": parsed.get("disease"),
            "location": parsed.get("location"),
            "justification": parsed.get("justification"),
            "llm_model": model_name,
        }
        print(f"[INFO] [llm_classifier] Articolo '{title}' classificato con {model_name} (segnale epidemico: {res['is_epidemic_signal']}, confidenza: {res['confidence']})")
        return res
    except Exception as exc:  # noqa: BLE001 - vogliamo loggare qualunque errore LLM/parsing
        print(f"[ATTENZIONE] [llm_classifier] Errore di classificazione con {model_name} per '{title}': {exc}")
        return {
            "is_epidemic_signal": None,
            "confidence": None,
            "disease": None,
            "location": None,
            "justification": f"errore di classificazione: {exc}",
            "llm_model": model_name,
        }
