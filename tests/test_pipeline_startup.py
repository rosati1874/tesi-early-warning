"""Test automatici per i controlli di avvio della pipeline di acquisizione."""
from unittest.mock import MagicMock
import pytest

from src import config
from src.pipeline.run_acquisition import run


class ExecutionReachedFetch(Exception):
    """Eccezione sentinella per verificare che l'esecuzione abbia superato i controlli iniziali."""
    pass


def test_keywords_mancanti_solleva_runtime_error_prima_di_fetch(monkeypatch):
    """Con il file delle keywords mancante, run() solleva RuntimeError prima di chiamare fetch_targeted_articles."""
    # Mock sessione DB per evitare connessioni reali
    monkeypatch.setattr("src.pipeline.run_acquisition.get_session", lambda: MagicMock())

    # Simula assenza del file keywords e reset cache
    monkeypatch.setattr("src.filtering.keywords._keywords_cache", None)
    monkeypatch.setattr("src.filtering.keywords.KEYWORDS_PATH", "percorso/inesistente/keywords.yaml")

    # Spy su fetch_targeted_articles che non deve mai essere chiamata
    fetch_mock = MagicMock()
    monkeypatch.setattr("src.pipeline.run_acquisition.fetch_targeted_articles", fetch_mock)

    with pytest.raises(RuntimeError) as exc_info:
        run()

    assert "Impossibile caricare il file di keywords" in str(exc_info.value)
    fetch_mock.assert_not_called()


def test_classificazione_attiva_e_chiave_vuota_solleva_runtime_error_prima_di_fetch(monkeypatch):
    """Con classificazione attiva e GEMINI_API_KEY vuota, run() solleva RuntimeError prima di chiamare fetch_targeted_articles."""
    # Mock sessione DB
    monkeypatch.setattr("src.pipeline.run_acquisition.get_session", lambda: MagicMock())

    # Assicura che le keywords siano valide
    monkeypatch.setattr("src.pipeline.run_acquisition.load_keywords", lambda: ["infezione", "virus"])

    # Configura classificazione attiva e chiave vuota/None
    monkeypatch.setattr(config, "ENABLE_LLM_CLASSIFICATION", True)
    monkeypatch.setattr("src.pipeline.run_acquisition.ENABLE_LLM_CLASSIFICATION", True)
    monkeypatch.setattr(config, "MAX_LLM_CLASSIFICATIONS_PER_RUN", 50)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    monkeypatch.setattr("src.pipeline.run_acquisition.GEMINI_API_KEY", "")

    fetch_mock = MagicMock()
    monkeypatch.setattr("src.pipeline.run_acquisition.fetch_targeted_articles", fetch_mock)

    with pytest.raises(RuntimeError) as exc_info:
        run()

    assert "GEMINI_API_KEY non impostata: impossibile classificare gli articoli" in str(exc_info.value)
    fetch_mock.assert_not_called()


def test_classificazione_disattivata_e_chiave_vuota_non_scatta_controllo(monkeypatch):
    """Con classificazione disattivata e chiave vuota, il controllo sulla chiave non scatta e la pipeline procede."""
    # Mock sessione DB
    monkeypatch.setattr("src.pipeline.run_acquisition.get_session", lambda: MagicMock())

    # Assicura che le keywords siano caricate
    monkeypatch.setattr("src.pipeline.run_acquisition.load_keywords", lambda: ["infezione", "virus"])

    # Configura classificazione disattivata e chiave vuota
    monkeypatch.setattr(config, "ENABLE_LLM_CLASSIFICATION", False)
    monkeypatch.setattr("src.pipeline.run_acquisition.ENABLE_LLM_CLASSIFICATION", False)
    monkeypatch.setattr(config, "MAX_LLM_CLASSIFICATIONS_PER_RUN", 50)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    monkeypatch.setattr("src.pipeline.run_acquisition.GEMINI_API_KEY", "")

    # fetch_targeted_articles solleva la sentinella per confermare che è stata raggiunta
    fetch_mock = MagicMock(side_effect=ExecutionReachedFetch)
    monkeypatch.setattr("src.pipeline.run_acquisition.fetch_targeted_articles", fetch_mock)

    with pytest.raises(ExecutionReachedFetch):
        run()

    fetch_mock.assert_called_once()
