"""Test automatici per il prompt e il modulo di classificazione semantica."""
from unittest.mock import MagicMock
import google.generativeai as genai

from src.classification.prompts import build_classification_prompt, PROMPT_VERSION
from src.classification import llm_classifier
from src.classification.llm_classifier import classify


def test_build_classification_prompt_struttura_e_troncamento():
    """Verifica che il prompt contenga titolo e testo, sia formattato con graffe singole e tronchi a 3000 caratteri."""
    assert PROMPT_VERSION == "v2"

    title = "Focolaio di West Nile a Latina"
    long_text = "Corpo della notizia. " * 300  # oltre 3000 caratteri
    prompt = build_classification_prompt(title, long_text)

    # Verifica presenza di titolo e testo
    assert "Titolo articolo:\n" + title in prompt
    assert "Testo articolo:\n" in prompt
    assert len(long_text[:3000]) == 3000
    assert long_text[:3000] in prompt
    assert long_text[:3001] not in prompt

    # Verifica che il blocco JSON di esempio contenga graffe singole (formattazione valida di .format())
    assert '{\n  "is_epidemic_signal": true/false,' in prompt
    assert '"justification": "<una frase>"\n}' in prompt
    assert "{{" not in prompt
    assert "}}" not in prompt


def test_classify_passa_generation_config_json(monkeypatch):
    """Verifica che classify passi temperature=0 e response_mime_type='application/json'."""
    monkeypatch.setattr(llm_classifier, "_configured", True)
    monkeypatch.setattr(llm_classifier, "GEMINI_API_KEY", "dummy-api-key")
    monkeypatch.setattr(llm_classifier, "get_ranked_gemini_models", lambda: ["gemini-2.5-flash"])

    mock_response = MagicMock()
    mock_response.text = (
        '{"is_epidemic_signal": true, "confidence": 0.95, "disease": "Dengue", '
        '"location": "Latina, Lazio", "justification": "Due nuovi casi confermati"}'
    )

    mock_model_instance = MagicMock()
    mock_model_instance.generate_content.return_value = mock_response
    mock_generative_model = MagicMock(return_value=mock_model_instance)
    monkeypatch.setattr(genai, "GenerativeModel", mock_generative_model)

    res = classify("Titolo di prova", "Testo dell'articolo")

    # Verifica parametri di chiamata
    assert mock_model_instance.generate_content.call_count == 1
    call_args, call_kwargs = mock_model_instance.generate_content.call_args
    gen_config = call_kwargs.get("generation_config")
    req_options = call_kwargs.get("request_options")

    assert gen_config is not None
    assert gen_config.temperature == 0
    assert gen_config.response_mime_type == "application/json"
    assert req_options == {"timeout": 15, "retry": None}

    # Verifica risultato e versione prompt
    assert res["is_epidemic_signal"] is True
    assert res["confidence"] == 0.95
    assert res["disease"] == "Dengue"
    assert res["location"] == "Latina, Lazio"
    assert res["llm_model"] == "gemini-2.5-flash"
    assert res["prompt_version"] == "v2"


def test_classify_fallback_quando_json_mode_non_supportata(monkeypatch):
    """Verifica che un errore di modalità JSON non supportata ritenti senza response_mime_type senza mettere il modello in blacklist."""
    monkeypatch.setattr(llm_classifier, "_configured", True)
    monkeypatch.setattr(llm_classifier, "GEMINI_API_KEY", "dummy-api-key")
    monkeypatch.setattr(llm_classifier, "_blacklisted_models", set())
    monkeypatch.setattr(llm_classifier, "_load_blacklisted_models_from_db", lambda: set())
    monkeypatch.setattr(llm_classifier, "get_ranked_gemini_models", lambda: ["gemma-2-9b-it"])

    mock_response = MagicMock()
    mock_response.text = (
        '```json\n{"is_epidemic_signal": false, "confidence": 0.85, "disease": null, '
        '"location": null, "justification": "Articolo generale"}\n```'
    )

    mock_model_instance = MagicMock()
    # La prima chiamata fallisce per mancato supporto a response_mime_type (es. errore 400), la seconda ha successo
    mock_model_instance.generate_content.side_effect = [
        Exception("400 Value 'application/json' in field 'response_mime_type' is not supported for this model"),
        mock_response,
    ]
    monkeypatch.setattr(genai, "GenerativeModel", MagicMock(return_value=mock_model_instance))

    res = classify("Titolo Gemma", "Testo Gemma")

    # Due chiamate sullo stesso modello
    assert mock_model_instance.generate_content.call_count == 2

    # Prima chiamata: con response_mime_type='application/json'
    first_call_kwargs = mock_model_instance.generate_content.call_args_list[0][1]
    assert first_call_kwargs["generation_config"].temperature == 0
    assert first_call_kwargs["generation_config"].response_mime_type == "application/json"

    # Seconda chiamata: senza response_mime_type
    second_call_kwargs = mock_model_instance.generate_content.call_args_list[1][1]
    assert second_call_kwargs["generation_config"].temperature == 0
    assert second_call_kwargs["generation_config"].response_mime_type is None

    # Il modello NON deve essere finito in blacklist
    assert "gemma-2-9b-it" not in llm_classifier._blacklisted_models

    # Risultato corretto con prompt_version "v2"
    assert res["is_epidemic_signal"] is False
    assert res["confidence"] == 0.85
    assert res["llm_model"] == "gemma-2-9b-it"
    assert res["prompt_version"] == "v2"


def test_classify_errore_restituisce_prompt_version_none(monkeypatch):
    """Verifica che in caso di errore di classificazione prompt_version sia None."""
    monkeypatch.setattr(llm_classifier, "_configured", True)
    monkeypatch.setattr(llm_classifier, "GEMINI_API_KEY", "dummy-api-key")
    monkeypatch.setattr(llm_classifier, "get_ranked_gemini_models", lambda: [])

    res = classify("Titolo", "Testo")
    assert res["is_epidemic_signal"] is None
    assert res["prompt_version"] is None
