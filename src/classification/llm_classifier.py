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
_blacklisted_models: set[str] = set()


def _ensure_configured():
    global _configured
    if not _configured:
        if not GEMINI_API_KEY:
            msg = "[ERRORE GRAVE] [llm_classifier] GEMINI_API_KEY non impostata: vedi .env.example"
            print(msg)
            raise RuntimeError(msg)
        genai.configure(api_key=GEMINI_API_KEY)
        _configured = True


def _parse_model_sort_key(model_name: str) -> tuple[bool, bool, bool, float]:
    """Criterio di ordinamento per i modelli Gemini.

    Restituisce una tupla (è_variante_lite, è_variante_flash, è_versione_stabile, versione_numerica):
    1. è_variante_lite: True se 'lite' è presente nel nome (priorità massima per quote gratuite più ampie).
    2. è_variante_flash: True se 'flash' è presente nel nome.
    3. è_versione_stabile: True se non contiene marchi sperimentali o preview ('-exp', 'experimental', '-preview').
    4. versione_numerica: estrae la versione numerica (es. "gemini-3.1-flash-lite" -> 3.1, "gemini-2.5-flash" -> 2.5).

    Ordinando in senso decrescente:
    - Le varianti 'lite' (es. gemini-3.1-flash-lite, gemini-2.0-flash-lite) hanno priorità assoluta.
    - Se nessuna variante 'lite' è disponibile, si passa alle varianti 'flash' pienamente supportate.
    - La versione numerica viene valutata all'interno del proprio gruppo (lite/flash/altri), evitando di scegliere forzatamente modelli non-lite appena usciti con quote molto ridotte.
    """
    name = model_name.lower()

    match = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
    version = float(match.group(1)) if match else 0.0

    is_lite = "lite" in name
    is_flash = "flash" in name
    is_stable = not any(tag in name for tag in ["-exp", "experimental", "-preview"])

    return (is_lite, is_flash, is_stable, version)


def get_ranked_gemini_models() -> list[str]:
    """Interroga `genai.list_models()` e restituisce la lista ordinata dei modelli candidati validi,
    escludendo quelli inseriti nella blacklist (es. perché dismessi o non disponibili per la chiave).
    """
    env_model = os.environ.get("GEMINI_MODEL") or GEMINI_MODEL
    if env_model and env_model.strip():
        m_name = env_model.strip().removeprefix("models/")
        if m_name not in _blacklisted_models:
            return [m_name]

    try:
        models = list(genai.list_models())
        supported = [
            m for m in models
            if "generateContent" in getattr(m, "supported_generation_methods", [])
        ]

        if supported:
            supported.sort(key=lambda m: _parse_model_sort_key(m.name), reverse=True)
            candidates = [m.name.removeprefix("models/") for m in supported]
            valid_candidates = [c for c in candidates if c not in _blacklisted_models]
            return valid_candidates
        else:
            print("[ATTENZIONE] [llm_classifier] Nessun modello con supporto 'generateContent' trovato da list_models().")

    except Exception as exc:
        print(f"[ATTENZIONE] [llm_classifier] Impossibile interrogare list_models(): {exc}.")

    return []


def _is_unavailability_error(exc: Exception) -> bool:
    """Verifica se l'eccezione indica che il modello è stato dismesso, ritirato o non è disponibile (HTTP 404)."""
    msg = str(exc).lower()
    phrases = [
        "no longer available",
        "not available to new users",
        "404",
        "not_found",
        "is not supported",
        "not found",
    ]
    return any(p in msg for p in phrases)


def classify(title: str, text: str) -> dict:
    """Restituisce un dict con is_epidemic_signal, confidence, disease,
    location, justification. In caso di modello non disponibile o dismesso (404 / no longer available),
    inserisce il modello in blacklist e ritenta immediatamente con il successivo modello candidato.
    """
    _ensure_configured()
    candidates = get_ranked_gemini_models()
    if not candidates:
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

    prompt = build_classification_prompt(title, text)

    for model_name in list(candidates):
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            raw = response.text.strip()
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

        except Exception as exc:  # noqa: BLE001
            if _is_unavailability_error(exc):
                print(f"[ATTENZIONE] [llm_classifier] Il modello '{model_name}' non è disponibile ({exc}). Aggiunto alla blacklist, proviamo il successivo candidato...")
                _blacklisted_models.add(model_name)
                continue
            else:
                print(f"[ATTENZIONE] [llm_classifier] Errore di classificazione con {model_name} per '{title}': {exc}")
                return {
                    "is_epidemic_signal": None,
                    "confidence": None,
                    "disease": None,
                    "location": None,
                    "justification": f"errore di classificazione con {model_name}: {exc}",
                    "llm_model": model_name,
                }

    msg = f"tutti i modelli candidati ({candidates}) sono risultati non disponibili o in errore"
    print(f"[ATTENZIONE] [llm_classifier] {msg} per '{title}'")
    return {
        "is_epidemic_signal": None,
        "confidence": None,
        "disease": None,
        "location": None,
        "justification": msg,
        "llm_model": None,
    }
