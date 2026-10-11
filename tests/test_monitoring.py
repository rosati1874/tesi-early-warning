"""Test automatici per il monitoraggio periodico di disponibilità e contenuto."""
from datetime import datetime, timezone, timedelta
import pytest
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src import config
from src.db.models import Base, Article, ArticleVersion, AvailabilityCheck
from src.monitoring.checker import check_article, run_monitoring_cycle, _hash_text


@pytest.fixture
def db_session():
    """Inizializza un database SQLite in memoria con lo schema applicativo per i test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    yield session
    session.close()


def _create_test_article(session, article_id: int = 1, url: str = "https://example.com/art-1",
                         first_seen_at: datetime | None = None) -> Article:
    """Crea e inserisce un articolo di test nel database."""
    now = datetime.now(timezone.utc)
    art = Article(
        id=article_id,
        url=url,
        source="Test Source",
        acquisition_mode="mirato",
        title="Allarme sanitario di prova",
        first_seen_at=first_seen_at or now,
        published_at=now,
        raw_text="Testo grezzo iniziale acquisito dal feed rss o jina",
        is_epidemic_signal=True,
        status="active",
    )
    session.add(art)
    session.commit()
    return art


class DummyResponse:
    """Risposta fittizia per simulare requests.get nei test."""

    def __init__(self, status_code: int = 200, text: str = "<html>corpo</html>",
                 url: str = "https://example.com/art-1", history: list | None = None):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = text
        self.url = url
        self.history = history or []


SAMPLE_MAIN_TEXT = (
    "Questo è un testo valido e significativo dell'articolo che supera ampiamente "
    "il limite minimo di duecento caratteri richiesto dal filtro del monitoraggio. "
    "Contiene informazioni cliniche ed epidemiologiche rilevanti per il controllo "
    "della disponibilità e delle versioni."
)


def test_first_check_creates_baseline(monkeypatch, db_session):
    """Verifica che al primo controllo un articolo senza versioni 'main_text_v2' crei una baseline senza generare aggiornamenti."""
    art = _create_test_article(db_session, 1)

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: DummyResponse(200, "<html>art</html>"))
    monkeypatch.setattr("src.monitoring.checker.extract_main_text_for_monitoring", lambda html: SAMPLE_MAIN_TEXT)

    outcome = check_article(db_session, art)

    assert outcome["result"] == "available"
    assert outcome["is_baseline"] is True
    assert outcome["has_updated"] is False

    versions = db_session.query(ArticleVersion).filter_by(article_id=art.id).all()
    assert len(versions) == 1
    assert versions[0].is_baseline is True
    assert versions[0].hash_method == "main_text_v2"
    assert versions[0].content_hash == _hash_text(SAMPLE_MAIN_TEXT)

    checks = db_session.query(AvailabilityCheck).filter_by(article_id=art.id).all()
    assert len(checks) == 1
    assert checks[0].result == "available"


def test_second_check_same_text_no_new_version(monkeypatch, db_session):
    """Verifica che un successivo controllo con testo identico non crei nuove versioni."""
    art = _create_test_article(db_session, 1)

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: DummyResponse(200, "<html>art</html>"))
    monkeypatch.setattr("src.monitoring.checker.extract_main_text_for_monitoring", lambda html: SAMPLE_MAIN_TEXT)

    # Primo controllo -> baseline
    check_article(db_session, art)
    assert db_session.query(ArticleVersion).filter_by(article_id=art.id).count() == 1

    # Secondo controllo con medesimo testo
    outcome2 = check_article(db_session, art)
    assert outcome2["is_baseline"] is False
    assert outcome2["has_updated"] is False
    assert db_session.query(ArticleVersion).filter_by(article_id=art.id).count() == 1


def test_whitespace_and_case_normalization(monkeypatch, db_session):
    """Verifica che differenze di spaziatura o maiuscole/minuscole non generino versioni spurie."""
    art = _create_test_article(db_session, 1)

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: DummyResponse(200, "<html>art</html>"))
    monkeypatch.setattr("src.monitoring.checker.extract_main_text_for_monitoring", lambda html: SAMPLE_MAIN_TEXT)

    check_article(db_session, art)
    assert db_session.query(ArticleVersion).filter_by(article_id=art.id).count() == 1

    # Testo con variazioni di spazi, ritorni a capo e maiuscole
    altered_text = "\n\n  " + SAMPLE_MAIN_TEXT.upper().replace(" ", "   \n") + "   \n"
    monkeypatch.setattr("src.monitoring.checker.extract_main_text_for_monitoring", lambda html: altered_text)

    outcome = check_article(db_session, art)
    assert outcome["has_updated"] is False
    assert db_session.query(ArticleVersion).filter_by(article_id=art.id).count() == 1


def test_different_text_creates_update_not_baseline(monkeypatch, db_session):
    """Verifica che una reale variazione nel testo crei una nuova versione is_baseline=false conteggiata come aggiornamento."""
    art = _create_test_article(db_session, 1)

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: DummyResponse(200, "<html>art</html>"))
    monkeypatch.setattr("src.monitoring.checker.extract_main_text_for_monitoring", lambda html: SAMPLE_MAIN_TEXT)

    check_article(db_session, art)
    assert db_session.query(ArticleVersion).filter_by(article_id=art.id).count() == 1

    updated_text = (
        "Questo testo è stato completamente modificato rispetto alla versione precedente "
        "e descrive nuovi dati clinici ed epidemiologici che superano il limite minimo "
        "di duecento caratteri per il monitoraggio."
    )
    monkeypatch.setattr("src.monitoring.checker.extract_main_text_for_monitoring", lambda html: updated_text)

    outcome = check_article(db_session, art)
    assert outcome["has_updated"] is True
    assert outcome["is_baseline"] is False

    versions = db_session.query(ArticleVersion).filter_by(article_id=art.id).order_by(ArticleVersion.id.asc()).all()
    assert len(versions) == 2
    assert versions[0].is_baseline is True
    assert versions[1].is_baseline is False
    assert versions[1].hash_method == "main_text_v2"


def test_historical_version_triggers_new_baseline(monkeypatch, db_session):
    """Verifica che la presenza di una vecchia versione storica (hash_method=None) induca la creazione di una baseline v2."""
    art = _create_test_article(db_session, 1)

    # Inserimento di una versione storica antecedente alla migrazione
    historical_version = ArticleVersion(
        article_id=art.id,
        content_hash="old_historical_hash_123",
        text_snapshot="Testo storico salvato con vecchio estrattore",
        is_baseline=False,
        hash_method=None,
    )
    db_session.add(historical_version)
    db_session.commit()

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: DummyResponse(200, "<html>art</html>"))
    monkeypatch.setattr("src.monitoring.checker.extract_main_text_for_monitoring", lambda html: SAMPLE_MAIN_TEXT)

    outcome = check_article(db_session, art)
    assert outcome["is_baseline"] is True
    assert outcome["has_updated"] is False

    # Le versioni totali sono 2: la storica invariata + la nuova baseline
    versions = db_session.query(ArticleVersion).filter_by(article_id=art.id).order_by(ArticleVersion.id.asc()).all()
    assert len(versions) == 2
    assert versions[0].hash_method is None
    assert versions[1].hash_method == "main_text_v2"
    assert versions[1].is_baseline is True


def test_extraction_failure_records_availability_only(monkeypatch, db_session):
    """Verifica che se l'estrazione mirata fallisce venga registrata solo la disponibilità senza creare versioni."""
    art = _create_test_article(db_session, 1)

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: DummyResponse(200, "<html>art</html>"))
    monkeypatch.setattr("src.monitoring.checker.extract_main_text_for_monitoring", lambda html: None)

    outcome = check_article(db_session, art)
    assert outcome["result"] == "available"
    assert outcome["is_baseline"] is False
    assert outcome["has_updated"] is False

    # Nessuna versione creata
    assert db_session.query(ArticleVersion).filter_by(article_id=art.id).count() == 0

    # Disponibilità comunque registrata
    check = db_session.query(AvailabilityCheck).filter_by(article_id=art.id).first()
    assert check is not None
    assert check.result == "available"


def test_removals_and_access_errors(monkeypatch, db_session):
    """Verifica che 404, 410 e redirect alla home siano marcati come removed, mentre 403 sia access_error."""
    art1 = _create_test_article(db_session, 1, url="https://example.com/art-404")
    art2 = _create_test_article(db_session, 2, url="https://example.com/art-410")
    art3 = _create_test_article(db_session, 3, url="https://example.com/art-redirect-home")
    art4 = _create_test_article(db_session, 4, url="https://example.com/art-403")

    # 1. Caso HTTP 404
    monkeypatch.setattr(requests, "get", lambda *a, **k: DummyResponse(404))
    res1 = check_article(db_session, art1)
    assert res1["result"] == "removed"
    assert art1.status == "removed"

    # 2. Caso HTTP 410
    monkeypatch.setattr(requests, "get", lambda *a, **k: DummyResponse(410))
    res2 = check_article(db_session, art2)
    assert res2["result"] == "removed"
    assert art2.status == "removed"

    # 3. Caso Redirect alla Home (path "/")
    redirect_resp = DummyResponse(200, url="https://example.com/", history=[DummyResponse(301)])
    monkeypatch.setattr(requests, "get", lambda *a, **k: redirect_resp)
    res3 = check_article(db_session, art3)
    assert res3["result"] == "removed"
    assert art3.status == "removed"

    # 4. Caso HTTP 403 Forbidden -> access_error (articolo resta active)
    monkeypatch.setattr(requests, "get", lambda *a, **k: DummyResponse(403))
    res4 = check_article(db_session, art4)
    assert res4["result"] == "access_error"
    assert art4.status == "active"


def test_monitoring_window_filters_old_articles(monkeypatch, db_session):
    """Verifica che vengano controllati solo gli articoli pubblicati negli ultimi MONITORING_WINDOW_DAYS giorni."""
    monkeypatch.setattr(config, "MONITORING_WINDOW_DAYS", 30)

    now = datetime.now(timezone.utc)
    art_recent = _create_test_article(db_session, 1, url="https://example.com/recent",
                                      first_seen_at=now - timedelta(days=10))
    art_old = _create_test_article(db_session, 2, url="https://example.com/old",
                                   first_seen_at=now - timedelta(days=40))

    checked_urls = []

    def mock_get(url, *args, **kwargs):
        checked_urls.append(url)
        return DummyResponse(200)

    monkeypatch.setattr(requests, "get", mock_get)
    monkeypatch.setattr("src.monitoring.checker.extract_main_text_for_monitoring", lambda h: SAMPLE_MAIN_TEXT)

    run_monitoring_cycle(db_session)

    # Solo l'articolo recente è stato controllato
    assert "https://example.com/recent" in checked_urls
    assert "https://example.com/old" not in checked_urls

    db_session.refresh(art_recent)
    db_session.refresh(art_old)
    assert art_recent.last_checked_at is not None
    assert art_old.last_checked_at is None


def test_article_exception_isolation_and_all_fail_error(monkeypatch, db_session):
    """Verifica che un'eccezione su un articolo non blocchi gli altri, e che il fallimento di tutti sollevi eccezione."""
    monkeypatch.setattr(config, "MONITORING_WINDOW_DAYS", 30)

    now = datetime.now(timezone.utc)
    art_fail = _create_test_article(db_session, 1, url="https://example.com/fail", first_seen_at=now)
    art_ok = _create_test_article(db_session, 2, url="https://example.com/ok", first_seen_at=now)

    def mock_get(url, *args, **kwargs):
        if url == "https://example.com/fail":
            raise ValueError("Errore imprevisto simulato")
        return DummyResponse(200)

    monkeypatch.setattr(requests, "get", mock_get)
    monkeypatch.setattr("src.monitoring.checker.extract_main_text_for_monitoring", lambda h: SAMPLE_MAIN_TEXT)

    # L'articolo funzionante deve essere controllato nonostante il fallimento del primo
    run_monitoring_cycle(db_session)

    db_session.refresh(art_fail)
    db_session.refresh(art_ok)
    assert art_fail.last_checked_at is None
    assert art_ok.last_checked_at is not None

    # Se invece tutti gli articoli candidati falliscono con eccezione, solleva RuntimeError
    def mock_fail_all(url, *args, **kwargs):
        raise ValueError("Crash totale")

    monkeypatch.setattr(requests, "get", mock_fail_all)
    with pytest.raises(RuntimeError):
        run_monitoring_cycle(db_session)
