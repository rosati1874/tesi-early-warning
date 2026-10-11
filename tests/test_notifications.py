"""Test automatici per i canali di notifica (email e webhook)."""
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src import config
from src.db.models import Base, Article, Subscriber
from src.notifications.email_notifier import notify_new_signals_by_email
from src.notifications.webhook import notify_new_signals


@pytest.fixture
def db_session():
    """Inizializza un database SQLite in memoria con lo schema applicativo per i test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    yield session
    session.close()


def _create_mock_article(article_id: int, disease: str, location: str, confidence: float) -> Article:
    """Crea un'istanza di Article adatta a simulare un segnale epidemico nei test."""
    return Article(
        id=article_id,
        url=f"https://example.com/article-{article_id}",
        source="Test Source",
        acquisition_mode="mirato",
        title=f"Focolaio di {disease} a {location}",
        published_at=datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc),
        is_epidemic_signal=True,
        llm_disease=disease,
        llm_location=location,
        llm_confidence=confidence,
        llm_justification=f"Rilevato aumento significativo di casi di {disease}.",
    )


class DummySMTPServer:
    """Oggetto fittizio che registra le chiamate SMTP e i messaggi inviati per i test."""

    def __init__(self, host=None, port=None, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.tls_started = False
        self.logged_in = False
        self.sent_messages = []
        self.fail_for_recipients = set()
        self.quit_called = False

    def starttls(self):
        self.tls_started = True

    def login(self, user, password):
        self.logged_in = True

    def send_message(self, msg):
        to_addr = msg["To"]
        if to_addr in self.fail_for_recipients:
            raise RuntimeError(f"Errore di invio simulato per {to_addr}")
        self.sent_messages.append(msg)

    def quit(self):
        self.quit_called = True

    def close(self):
        pass


def test_email_switch_off_no_connection(monkeypatch, db_session):
    """Verifica che con l'interruttore disattivato non venga effettuata alcuna connessione o query."""
    monkeypatch.setattr(config, "ENABLE_EMAIL_NOTIFICATIONS", False)
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(config, "SMTP_USER", "user@example.com")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "password123")

    def fail_smtp(*args, **kwargs):
        raise AssertionError("Non dovrebbe tentare la connessione SMTP con interruttore spento")

    monkeypatch.setattr("smtplib.SMTP", fail_smtp)
    monkeypatch.setattr("smtplib.SMTP_SSL", fail_smtp)

    art = _create_mock_article(1, "Dengue", "Roma", 0.95)
    notify_new_signals_by_email(db_session, [art])


def test_email_missing_credentials_no_connection(monkeypatch, db_session):
    """Verifica che con credenziali SMTP mancanti la funzione esca senza eccezioni né connessioni."""
    monkeypatch.setattr(config, "ENABLE_EMAIL_NOTIFICATIONS", True)
    monkeypatch.setattr(config, "SMTP_HOST", "")
    monkeypatch.setattr(config, "SMTP_USER", "")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "")

    sub = Subscriber(email="destinatario@example.com", active=True)
    db_session.add(sub)
    db_session.commit()

    def fail_smtp(*args, **kwargs):
        raise AssertionError("Non dovrebbe tentare la connessione SMTP se mancano le credenziali")

    monkeypatch.setattr("smtplib.SMTP", fail_smtp)
    monkeypatch.setattr("smtplib.SMTP_SSL", fail_smtp)

    art = _create_mock_article(1, "Morbillo", "Milano", 0.88)
    notify_new_signals_by_email(db_session, [art])


def test_email_3_signals_2_recipients(monkeypatch, db_session):
    """Verifica che 3 segnali e 2 destinatari generino esattamente 2 email con tutti i segnali inclusi."""
    monkeypatch.setattr(config, "ENABLE_EMAIL_NOTIFICATIONS", True)
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(config, "SMTP_PORT", 587)
    monkeypatch.setattr(config, "SMTP_USER", "mittente@example.com")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "password123")
    monkeypatch.setattr(config, "EMAIL_SENDER", "mittente@example.com")

    dummy_server = DummySMTPServer()
    monkeypatch.setattr("smtplib.SMTP", lambda host, port, timeout: dummy_server)

    sub1 = Subscriber(email="dest1@example.com", active=True)
    sub2 = Subscriber(email="dest2@example.com", active=True)
    db_session.add_all([sub1, sub2])
    db_session.commit()

    sig1 = _create_mock_article(1, "Dengue", "Brescia", 0.91)
    sig2 = _create_mock_article(2, "West Nile", "Padova", 0.89)
    sig3 = _create_mock_article(3, "Morbillo", "Napoli", 0.94)
    signals = [sig1, sig2, sig3]

    notify_new_signals_by_email(db_session, signals)

    # Esattamente 2 email inviate (una per destinatario)
    assert len(dummy_server.sent_messages) == 2
    assert dummy_server.tls_started is True
    assert dummy_server.logged_in is True
    assert dummy_server.quit_called is True

    recipient_addresses = [m["To"] for m in dummy_server.sent_messages]
    assert sorted(recipient_addresses) == ["dest1@example.com", "dest2@example.com"]

    # Ciascuna email contiene i dati di tutti e 3 i segnali sia in testo sia in HTML
    for msg in dummy_server.sent_messages:
        plain_body = msg.get_body(preferencelist=("plain",)).get_content()
        html_body = msg.get_body(preferencelist=("html",)).get_content()
        for body in (plain_body, html_body):
            assert "Dengue" in body
            assert "West Nile" in body
            assert "Morbillo" in body
            assert "Brescia" in body
            assert "Padova" in body
            assert "Napoli" in body

    # Verifica aggiornamento data ultima notifica per entrambi
    db_session.refresh(sub1)
    db_session.refresh(sub2)
    assert sub1.last_notified_at is not None
    assert sub2.last_notified_at is not None


def test_email_single_signal_grammar(monkeypatch, db_session):
    """Verifica la corretta concordanza grammaticale al singolare nel caso di 1 solo segnale."""
    monkeypatch.setattr(config, "ENABLE_EMAIL_NOTIFICATIONS", True)
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(config, "SMTP_PORT", 587)
    monkeypatch.setattr(config, "SMTP_USER", "mittente@example.com")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "password123")

    dummy_server = DummySMTPServer()
    monkeypatch.setattr("smtplib.SMTP", lambda host, port, timeout: dummy_server)

    sub = Subscriber(email="destinatario@example.com", active=True)
    db_session.add(sub)
    db_session.commit()

    sig = _create_mock_article(1, "Morbillo", "Firenze", 0.90)
    notify_new_signals_by_email(db_session, [sig])

    assert len(dummy_server.sent_messages) == 1
    msg = dummy_server.sent_messages[0]

    # Oggetto al singolare
    assert "1 nuovo segnale epidemico" in msg["Subject"]

    # Testo ed HTML al singolare
    plain_body = msg.get_body(preferencelist=("plain",)).get_content()
    html_body = msg.get_body(preferencelist=("html",)).get_content()

    assert "Riepilogo nuovo segnale identificato: 1" in plain_body
    assert "è stato identificato <strong>1</strong> nuovo segnale epidemico" in html_body
    assert "sono stati identificati" not in html_body


def test_email_recipient_error_isolation(monkeypatch, db_session):
    """Verifica che un errore di invio su un destinatario non blocchi l'altro e non alteri failure_count."""
    monkeypatch.setattr(config, "ENABLE_EMAIL_NOTIFICATIONS", True)
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(config, "SMTP_PORT", 587)
    monkeypatch.setattr(config, "SMTP_USER", "mittente@example.com")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "password123")

    dummy_server = DummySMTPServer()
    dummy_server.fail_for_recipients.add("errore@example.com")
    monkeypatch.setattr("smtplib.SMTP", lambda host, port, timeout: dummy_server)

    sub_fail = Subscriber(email="errore@example.com", active=True, failure_count=0)
    sub_ok = Subscriber(email="successo@example.com", active=True, failure_count=0)
    db_session.add_all([sub_fail, sub_ok])
    db_session.commit()

    sig = _create_mock_article(1, "Influenza aviaria", "Verona", 0.92)
    notify_new_signals_by_email(db_session, [sig])

    # Solo l'email al destinatario funzionante è stata inviata
    assert len(dummy_server.sent_messages) == 1
    assert dummy_server.sent_messages[0]["To"] == "successo@example.com"

    # Per il destinatario fallito: failure_count resta invariato (0), active resta True, data non impostata
    db_session.refresh(sub_fail)
    db_session.refresh(sub_ok)
    assert sub_fail.failure_count == 0
    assert sub_fail.active is True
    assert sub_fail.last_notified_at is None

    # Per il destinatario riuscito: data aggiornata
    assert sub_ok.last_notified_at is not None


def test_email_no_signals_no_email(monkeypatch, db_session):
    """Verifica che se la lista dei segnali è vuota non venga aperta alcuna connessione SMTP."""
    monkeypatch.setattr(config, "ENABLE_EMAIL_NOTIFICATIONS", True)
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(config, "SMTP_USER", "user@example.com")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "password123")

    def fail_smtp(*args, **kwargs):
        raise AssertionError("Nessuna connessione SMTP deve essere aperta se non ci sono segnali")

    monkeypatch.setattr("smtplib.SMTP", fail_smtp)
    monkeypatch.setattr("smtplib.SMTP_SSL", fail_smtp)

    sub = Subscriber(email="destinatario@example.com", active=True)
    db_session.add(sub)
    db_session.commit()

    notify_new_signals_by_email(db_session, [])


def test_webhook_excludes_subscribers_without_webhook_url(monkeypatch, db_session):
    """Verifica che la spedizione webhook escluda gli iscritti che non hanno un webhook_url configurato."""
    monkeypatch.setattr(config, "ENABLE_WEBHOOK_NOTIFICATIONS", True)

    sub_webhook_only = Subscriber(webhook_url="https://example.com/webhook1", email=None, active=True)
    sub_email_only = Subscriber(webhook_url=None, email="solo_email@example.com", active=True)
    sub_both = Subscriber(webhook_url="https://example.com/webhook2", email="entrambi@example.com", active=True)
    sub_inactive = Subscriber(webhook_url="https://example.com/inactive", email=None, active=False)
    db_session.add_all([sub_webhook_only, sub_email_only, sub_both, sub_inactive])
    db_session.commit()

    posted_urls = []

    class DummyResponse:
        status_code = 200

    def mock_post(url, json=None, timeout=None, headers=None):
        posted_urls.append(url)
        return DummyResponse()

    monkeypatch.setattr("requests.post", mock_post)

    sig = _create_mock_article(1, "Colera", "Taranto", 0.90)
    notify_new_signals(db_session, [sig])

    # Devono ricevere la POST solo sub_webhook_only e sub_both
    assert sorted(posted_urls) == [
        "https://example.com/webhook1",
        "https://example.com/webhook2",
    ]
    # L'iscritto solo email non deve ricevere alcuna chiamata webhook
    assert "solo_email@example.com" not in posted_urls


def test_config_smtp_port_empty_string_fallback(monkeypatch):
    """Verifica che una stringa vuota per SMTP_PORT (es. variabile GitHub non impostata) ricada sul default 587."""
    import importlib
    monkeypatch.setenv("SMTP_PORT", "")
    importlib.reload(config)
    assert config.SMTP_PORT == 587
