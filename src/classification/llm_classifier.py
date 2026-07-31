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

NON_TEXT_MODEL_KEYWORDS = [
    "-image",
    "image",
    "-tts",
    "tts",
    "-audio",
    "audio",
    "-vision",
    "vision",
    "realtime",
    "embedding",
    "imagen",
    "veo",
    "sound",
    "speech",
    "aqa",
]


def _ensure_configured():
    global _configured
    if not _configured:
        if not GEMINI_API_KEY:
            msg = "[ERRORE GRAVE] [llm_classifier] GEMINI_API_KEY non impostata: vedi .env.example"
            print(msg)
            raise RuntimeError(msg)
        genai.configure(api_key=GEMINI_API_KEY)
        _configured = True


def _is_text_generation_model(model_name: str) -> bool:
    """Restituisce True solo se il modello è dedicato alla generazione/classificazione di testo,
    escludendo rigorosamente varianti per immagini, tts, audio, vision, embedding o multimodalità speciale.
    """
    name = model_name.lower()
    return not any(kw in name for kw in NON_TEXT_MODEL_KEYWORDS)


def _is_per_minute_quota_error(reason: Exception | str) -> bool:
    """Verifica se l'errore è dovuto al superamento del limite al minuto (RPM), che dura pochi secondi/minuti."""
    msg = str(reason).lower()
    pm_phrases = [
        "generaterequestsperminute",
        "requestsperminute",
        "per minute",
        "perminute",
        "rpm",
    ]
    pd_phrases = [
        "generaterequestsperday",
        "requestsperday",
        "per day",
        "perday",
        "rpd",
    ]
    return any(p in msg for p in pm_phrases) and not any(p in msg for p in pd_phrases)


def _load_blacklisted_models_from_db() -> set[str]:
    """Carica dal DB solo i modelli la cui blacklist non è ancora scaduta (expires_at > now), pulendo quelle vecchie."""
    try:
        from datetime import datetime, timezone
        from src.db.connection import get_session
        from src.db.models import BlacklistedModel

        session = get_session()
        now = datetime.now(timezone.utc)

        # Pulizia automatica delle righe di blacklist già scadute nel DB
        session.query(BlacklistedModel).filter(BlacklistedModel.expires_at <= now).delete(synchronize_session=False)
        session.commit()

        rows = (
            session.query(BlacklistedModel)
            .filter(BlacklistedModel.expires_at > now)
            .all()
        )
        session.close()
        return {r.model_name for r in rows}
    except Exception:
        return set()


def _blacklist_model(model_name: str, reason: str = ""):
    """Inserisce un modello nella blacklist (in memoria e DB).

    Se l'errore indica un limite al minuto (RPM), il TTL è di 2 minuti.
    Se l'errore indica un limite giornaliero (RPD) o modello 404, il TTL è di 12 ore (720 minuti).
    """
    _blacklisted_models.add(model_name)

    is_rpm = _is_per_minute_quota_error(reason)
    ttl_minutes = 2 if is_rpm else 720
    ttl_desc = "2 minuti (limite RPM al minuto)" if is_rpm else "12 ore (limite RPD giornaliero o 404)"

    print(f"[INFO] [llm_classifier] Modello '{model_name}' inserito in blacklist per {ttl_desc}")

    try:
        from datetime import datetime, timedelta, timezone
        from src.db.connection import get_session
        from src.db.models import BlacklistedModel

        session = get_session()
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=ttl_minutes)

        existing = session.query(BlacklistedModel).filter_by(model_name=model_name).first()
        if existing:
            existing.blacklisted_at = now
            existing.expires_at = expires_at
            existing.reason = str(reason)
        else:
            bm = BlacklistedModel(
                model_name=model_name,
                blacklisted_at=now,
                expires_at=expires_at,
                reason=str(reason),
            )
            session.add(bm)
        session.commit()
        session.close()
    except Exception as exc:
        print(f"[ATTENZIONE] [llm_classifier] Impossibile persistere blacklist nel DB per '{model_name}': {exc}")


def _parse_model_sort_key(model_name: str) -> tuple[bool, bool, bool, float]:
    """Criterio di ordinamento per i modelli Gemini.

    Restituisce una tupla (è_variante_lite, è_variante_flash, è_versione_stabile, versione_numerica):
    1. è_variante_lite: True se 'lite' è presente nel nome (priorità massima per quote gratuite più ampie).
    2. è_variante_flash: True se 'flash' è presente nel nome.
    3. è_versione_stabile: True se non contiene marchi sperimentali o preview ('-exp', 'experimental', '-preview').
    4. versione_numerica: estrae la versione numerica (es. "gemini-3.1-flash-lite" -> 3.1, "gemini-2.5-flash" -> 2.5).
    """
    name = model_name.lower()

    match = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
    version = float(match.group(1)) if match else 0.0

    is_lite = "lite" in name
    is_flash = "flash" in name
    is_stable = not any(tag in name for tag in ["-exp", "experimental", "-preview"])

    return (is_lite, is_flash, is_stable, version)


def get_ranked_gemini_models() -> list[str]:
    """Interroga `genai.list_models()` e restituisce la lista ordinata dei modelli candidati testuali validi,
    escludendo quelli non testuali (image/tts/vision) e quelli blacklistati (dismessi o in quota esaurita).
    """
    db_blacklisted = _load_blacklisted_models_from_db()
    all_blacklisted = _blacklisted_models.union(db_blacklisted)

    env_model = os.environ.get("GEMINI_MODEL") or GEMINI_MODEL
    if env_model and env_model.strip():
        m_name = env_model.strip().removeprefix("models/")
        if m_name not in all_blacklisted:
            return [m_name]

    try:
        models = list(genai.list_models(request_options={"timeout": 15, "retry": None}))
        supported = [
            m for m in models
            if "generateContent" in getattr(m, "supported_generation_methods", [])
            and _is_text_generation_model(m.name)
        ]

        if supported:
            supported.sort(key=lambda m: _parse_model_sort_key(m.name), reverse=True)
            candidates = [m.name.removeprefix("models/") for m in supported]
            valid_candidates = [c for c in candidates if c not in all_blacklisted]
            return valid_candidates
        else:
            print("[ATTENZIONE] [llm_classifier] Nessun modello testuale con supporto 'generateContent' trovato da list_models().")

    except Exception as exc:
        print(f"[ATTENZIONE] [llm_classifier] Impossibile interrogare list_models(): {exc}.")

    return []


def _is_unavailability_error(exc: Exception) -> bool:
    """Verifica se l'eccezione indica che il modello è dismesso/non disponibile (404) o ha la quota esaurita (429/resource exhausted)."""
    msg = str(exc).lower()
    phrases = [
        "no longer available",
        "not available to new users",
        "404",
        "not_found",
        "is not supported",
        "not found",
        "429",
        "resource_exhausted",
        "resource has been exhausted",
        "quota",
        "rate limit",
    ]
    return any(p in msg for p in phrases)


def classify(title: str, text: str) -> dict:
    """Restituisce un dict con is_epidemic_signal, confidence, disease,
    location, justification. In caso di modello non disponibile o quota esaurita (404 / 429),
    inserisce il modello in blacklist (in memoria e DB) e ritenta immediatamente con il successivo candidato.
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
            request_options = {"timeout": 15, "retry": None}
            response = model.generate_content(prompt, request_options=request_options)
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
                print(f"[ATTENZIONE] [llm_classifier] Il modello '{model_name}' non è disponibile o quota esaurita ({exc}). Aggiunto alla blacklist, proviamo il successivo candidato...")
                _blacklist_model(model_name, str(exc))
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
