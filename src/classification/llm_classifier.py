"""Classificazione semantica tramite LLM (RF-05).

Implementazione principale: Gemini API (free tier). Il modulo è pensato
per essere sostituibile (RNF-05): un classificatore locale via Ollama
potrà implementare la stessa interfaccia `classify(title, text) -> dict`
per il confronto sperimentale del Cap. 6.
"""
import os
import re
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


def _parse_model_sort_key(model_name: str) -> tuple[bool, float, bool]:
    """Criterio di ordinamento numerico e qualitativo per modelli Gemini.

    Restituisce una tupla (è_variante_flash, versione_numerica, è_versione_stabile):
    - è_variante_flash: True se 'flash' è presente nel nome.
    - versione_numerica: estrae la versione numerica (es. "gemini-3.0-flash" -> 3.0, "gemini-2.5-flash" -> 2.5).
    - è_versione_stabile: True se non contiene marchi sperimentali o preview ('-exp', 'experimental', '-preview').

    Ordinando in senso decrescente, questo garantisce che:
    1. Le varianti Flash vengano sempre preferite a quelle Pro o non-Flash.
    2. La versione numerica più recente (es. 3.x > 2.x > 1.x) venga sempre scelta per prima.
    3. A pari versione, i modelli stabili vengano preferiti a quelli sperimentali.
    """
    name = model_name.lower()

    # Estrae la versione numerica (es. "gemini-2.5-flash" -> 2.5, "gemini-3.0-flash" -> 3.0)
    match = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
    version = float(match.group(1)) if match else 0.0

    is_flash = "flash" in name
    is_stable = not any(tag in name for tag in ["-exp", "experimental", "-preview"])

    return (is_flash, version, is_stable)


def select_best_gemini_model() -> str | None:
    """Seleziona automaticamente il miglior modello Gemini disponibile dall'API.

    Priorità:
    1. Se la variabile d'ambiente GEMINI_MODEL è impostata esplicitamente, usa quel valore.
    2. Altrimenti interroga `genai.list_models()` filtrando per i modelli che supportano 'generateContent'.
    3. Ordina i modelli mediante `_parse_model_sort_key` (variante Flash -> versione più recente -> stabilità).
    4. Se list_models() fallisce o non restituisce modelli, restituisce None (evitando fallback su modelli ritirati).
    """
    global _cached_model_name
    if _cached_model_name is not None:
        return _cached_model_name

    env_model = os.environ.get("GEMINI_MODEL") or GEMINI_MODEL
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

        if supported:
            # Ordina in ordine decrescente usando la tupla di ordinamento numerico/qualitativo
            supported.sort(key=lambda m: _parse_model_sort_key(m.name), reverse=True)
            best_model = supported[0].name
            clean_name = best_model.removeprefix("models/")
            print(f"[INFO] [llm_classifier] Modello Gemini selezionato automaticamente tramite list_models(): {clean_name}")
            _cached_model_name = clean_name
            return _cached_model_name
        else:
            print("[ATTENZIONE] [llm_classifier] Nessun modello con supporto 'generateContent' trovato da list_models().")

    except Exception as exc:
        print(f"[ATTENZIONE] [llm_classifier] Impossibile interrogare list_models(): {exc}.")

    # Nessun fallback hardcodato a modelli ritirati: se list_models() fallisce, restituisce None
    return None


def classify(title: str, text: str) -> dict:
    """Restituisce un dict con is_epidemic_signal, confidence, disease,
    location, justification. In caso di errore/parsing fallito/modello non disponibile,
    restituisce un risultato con is_epidemic_signal=None e justification descrittiva.
    """
    _ensure_configured()
    model_name = select_best_gemini_model()
    if not model_name:
        msg = "impossibile determinare un modello Gemini valido tramite list_models()"
        print(f"[ATTENZIONE] [llm_classifier] {msg} per '{title}'")
        return {
            "is_epidemic_signal": None,
            "confidence": None,
            "disease": None,
            "location": None,
            "justification": msg,
            "llm_model": None,
        }

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
