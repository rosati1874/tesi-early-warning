"""Test automatici per il prefiltraggio e la deduplicazione degli articoli."""
from datetime import datetime, timezone, timedelta
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, Article
from src.filtering.prefilter import (
    is_duplicate_in_db,
    normalize_title,
    filter_by_freshness,
    deduplicate_in_batch,
)


@pytest.fixture
def db_session():
    """Inizializza un database SQLite in memoria con lo schema applicativo per i test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    yield session
    session.close()


def test_rubrica_quotidiana_24h_non_duplicato(db_session):
    """Rubrica quotidiana con stesso titolo e dominio pubblicata a 24 ore di distanza: non duplicato."""
    base_time = datetime(2026, 10, 10, 8, 0, 0, tzinfo=timezone.utc)
    art = Article(
        url="https://www.ilpost.it/prime-pagine-2026-10-10",
        source="ilpost",
        acquisition_mode="mirato",
        title="Le prime pagine di oggi",
        published_at=base_time,
        first_seen_at=base_time,
    )
    db_session.add(art)
    db_session.commit()

    raw = {
        "url": "https://www.ilpost.it/prime-pagine-2026-10-11",
        "source": "ilpost",
        "acquisition_mode": "mirato",
        "title": "Le prime pagine di oggi",
        "published_at": base_time + timedelta(hours=24),
    }
    assert is_duplicate_in_db(db_session, raw) is False


def test_stesso_articolo_due_canali_duplicato(db_session):
    """Stesso articolo da canale mirato e generalista con suffisso testata: riconosciuto duplicato."""
    pub_time = datetime(2026, 10, 11, 10, 0, 0, tzinfo=timezone.utc)
    art = Article(
        url="https://www.ansa.it/canale_saluteebenessere/notizie/a.html",
        source="ansa_salute",
        acquisition_mode="mirato",
        title="Titolo X",
        published_at=pub_time,
        first_seen_at=pub_time,
    )
    db_session.add(art)
    db_session.commit()

    raw = {
        "url": "https://www.ansa.it/notizie/b.html",
        "source": "ANSA",
        "acquisition_mode": "generalista",
        "title": "Titolo X - ANSA",
        "published_at": pub_time,
    }
    assert is_duplicate_in_db(db_session, raw) is True


def test_stesso_articolo_generalista_in_db_poi_mirato(db_session):
    """Articolo generalista salvato per primo in DB e copia mirata in ingresso: riconosciuto duplicato."""
    pub_time = datetime(2026, 10, 11, 10, 0, 0, tzinfo=timezone.utc)
    art = Article(
        url="https://www.ansa.it/notizie/b.html",
        source="ANSA",
        acquisition_mode="generalista",
        title="Titolo X - ANSA",
        published_at=pub_time,
        first_seen_at=pub_time,
    )
    db_session.add(art)
    db_session.commit()

    raw = {
        "url": "https://www.ansa.it/canale_saluteebenessere/notizie/a.html",
        "source": "ansa_salute",
        "acquisition_mode": "mirato",
        "title": "Titolo X",
        "published_at": pub_time,
    }
    assert is_duplicate_in_db(db_session, raw) is True


def test_stesso_titolo_dominio_2h_duplicato(db_session):
    """Stesso titolo e dominio pubblicati a 2 ore di distanza: riconosciuto duplicato."""
    pub_time = datetime(2026, 10, 11, 12, 0, 0, tzinfo=timezone.utc)
    art = Article(
        url="https://www.open.online/news/1",
        source="openonline",
        acquisition_mode="mirato",
        title="Allarme sanitario",
        published_at=pub_time,
        first_seen_at=pub_time,
    )
    db_session.add(art)
    db_session.commit()

    raw = {
        "url": "https://www.open.online/news/2",
        "source": "openonline",
        "acquisition_mode": "mirato",
        "title": "Allarme sanitario",
        "published_at": pub_time + timedelta(hours=2),
    }
    assert is_duplicate_in_db(db_session, raw) is True


def test_stesso_titolo_date_dominio_diverso_non_duplicato(db_session):
    """Stesso titolo e date ma domini diversi: non duplicato."""
    pub_time = datetime(2026, 10, 11, 12, 0, 0, tzinfo=timezone.utc)
    art = Article(
        url="https://www.ansa.it/salute/art-1.html",
        source="ansa_salute",
        acquisition_mode="mirato",
        title="Nuovo focolaio epidemico",
        published_at=pub_time,
        first_seen_at=pub_time,
    )
    db_session.add(art)
    db_session.commit()

    raw = {
        "url": "https://www.repubblica.it/salute/art-2.html",
        "source": "repubblica",
        "acquisition_mode": "generalista",
        "title": "Nuovo focolaio epidemico",
        "published_at": pub_time,
    }
    assert is_duplicate_in_db(db_session, raw) is False


def test_copia_generalista_acquisita_5_giorni_dopo_duplicato(db_session):
    """Copia generalista acquisita 5 giorni dopo con stessa data di pubblicazione: duplicato."""
    pub_time = datetime(2026, 10, 1, 9, 0, 0, tzinfo=timezone.utc)
    art = Article(
        url="https://www.adnkronos.com/salute/dengue-1.html",
        source="adnkronos_salute",
        acquisition_mode="mirato",
        title="Casi Dengue nel Lazio",
        published_at=pub_time,
        first_seen_at=pub_time,
    )
    db_session.add(art)
    db_session.commit()

    raw = {
        "url": "https://www.adnkronos.com/salute/dengue-2.html",
        "source": "Adnkronos",
        "acquisition_mode": "generalista",
        "title": "Casi Dengue nel Lazio - Adnkronos",
        "published_at": pub_time,
    }
    assert is_duplicate_in_db(db_session, raw) is True


def test_published_at_mancante_finestra_acquisizione(db_session):
    """Quando published_at manca: duplicato entro 48 ore, non duplicato dopo 3 giorni."""
    now = datetime.now(timezone.utc)
    art_recent = Article(
        url="https://www.ilpost.it/recente",
        source="ilpost",
        acquisition_mode="mirato",
        title="Bollettino senza data",
        published_at=None,
        first_seen_at=now - timedelta(hours=10),
    )
    db_session.add(art_recent)
    db_session.commit()

    raw_recent = {
        "url": "https://www.ilpost.it/recente-copia",
        "source": "ilpost",
        "acquisition_mode": "mirato",
        "title": "Bollettino senza data",
        "published_at": None,
    }
    assert is_duplicate_in_db(db_session, raw_recent) is True

    art_old = Article(
        url="https://www.ilpost.it/vecchio",
        source="ilpost",
        acquisition_mode="mirato",
        title="Altro bollettino senza data",
        published_at=None,
        first_seen_at=now - timedelta(days=3),
    )
    db_session.add(art_old)
    db_session.commit()

    raw_old = {
        "url": "https://www.ilpost.it/vecchio-copia",
        "source": "ilpost",
        "acquisition_mode": "mirato",
        "title": "Altro bollettino senza data",
        "published_at": None,
    }
    assert is_duplicate_in_db(db_session, raw_old) is False


def test_titolo_generalista_trattino_non_corrispondente_a_source(db_session):
    """Titolo generalista con trattino interno non corrispondente alla testata: non viene troncato."""
    title = "Covid - nuovi casi in Lombardia"
    source = "Il Giorno"
    norm = normalize_title(title, acquisition_mode="generalista", source=source)
    assert norm == "covid - nuovi casi in lombardia"

    pub_time = datetime(2026, 10, 11, 10, 0, 0, tzinfo=timezone.utc)
    art = Article(
        url="https://www.ilgiorno.it/cronaca/covid.html",
        source="Il Giorno",
        acquisition_mode="generalista",
        title="Covid",
        published_at=pub_time,
        first_seen_at=pub_time,
    )
    db_session.add(art)
    db_session.commit()

    raw = {
        "url": "https://www.ilgiorno.it/cronaca/covid-lombardia.html",
        "source": "Il Giorno",
        "acquisition_mode": "generalista",
        "title": title,
        "published_at": pub_time,
    }
    assert is_duplicate_in_db(db_session, raw) is False


def test_titolo_spazi_multipli_e_maiuscole(db_session):
    """Titolo con spazi multipli e maiuscole diverse: riconosciuto uguale."""
    t1 = "  FOCOLAIO   di   Aviaria  nel   Veneto  "
    t2 = "focolaio di aviaria nel veneto"
    assert normalize_title(t1) == normalize_title(t2)

    pub_time = datetime(2026, 10, 11, 11, 0, 0, tzinfo=timezone.utc)
    art = Article(
        url="https://www.ansa.it/canale/aviaria-1.html",
        source="ansa_salute",
        acquisition_mode="mirato",
        title="Focolaio Di Aviaria Nel Veneto",
        published_at=pub_time,
        first_seen_at=pub_time,
    )
    db_session.add(art)
    db_session.commit()

    raw = {
        "url": "https://www.ansa.it/canale/aviaria-2.html",
        "source": "ansa_salute",
        "acquisition_mode": "mirato",
        "title": "  focolaio   di  aviaria   NEL veneto  ",
        "published_at": pub_time,
    }
    assert is_duplicate_in_db(db_session, raw) is True


def test_url_identico_duplicato_primo_livello(db_session):
    """URL identico: duplicato di primo livello anche con titoli totalmente differenti."""
    art = Article(
        url="https://www.example.com/articolo-uguale",
        source="test",
        acquisition_mode="mirato",
        title="Titolo Originale",
        published_at=datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc),
        first_seen_at=datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc),
    )
    db_session.add(art)
    db_session.commit()

    raw = {
        "url": "https://www.example.com/articolo-uguale",
        "source": "altra_fonte",
        "acquisition_mode": "generalista",
        "title": "Titolo Completamente Diverso",
        "published_at": datetime(2026, 10, 11, 10, 0, 0, tzinfo=timezone.utc),
    }
    assert is_duplicate_in_db(db_session, raw) is True


def test_trattini_tipografici_en_dash_em_dash():
    """Verifica che i trattini en-dash e em-dash con la testata vengano correttamente rimossi."""
    t_en = "Nuovo focolaio epidemico – Il Post"
    t_em = "Nuovo focolaio epidemico — Il Post"
    assert normalize_title(t_en, "generalista", "Il Post") == "nuovo focolaio epidemico"
    assert normalize_title(t_em, "generalista", "Il Post") == "nuovo focolaio epidemico"


def test_filter_by_freshness():
    """Verifica il filtro di freschezza per data di pubblicazione."""
    now = datetime.now(timezone.utc)
    articles = [
        {"url": "http://1", "published_at": now - timedelta(days=5)},
        {"url": "http://2", "published_at": now - timedelta(days=40)},
        {"url": "http://3", "published_at": None},
    ]
    fresh = filter_by_freshness(articles, max_age_days=30)
    assert len(fresh) == 2
    assert [a["url"] for a in fresh] == ["http://1", "http://3"]


def test_deduplicate_in_batch():
    """Verifica la deduplicazione in-batch per URL esatto."""
    batch = [
        {"url": "http://a", "title": "A1"},
        {"url": "http://b", "title": "B"},
        {"url": "http://a", "title": "A2"},
    ]
    deduped = deduplicate_in_batch(batch)
    assert len(deduped) == 2
    assert [a["url"] for a in deduped] == ["http://a", "http://b"]
    assert deduped[0]["title"] == "A1"


def test_due_copie_generaliste_titolo_identico_source_diverse_duplicato(db_session):
    """Due copie generaliste con titolo identico 'Titolo X - LatinaToday', una con source 'latinatoday.it' e una con 'LatinaToday': duplicato."""
    pub_time = datetime(2026, 10, 11, 10, 0, 0, tzinfo=timezone.utc)
    art = Article(
        url="https://www.latinatoday.it/cronaca/art-1.html",
        source="latinatoday.it",
        acquisition_mode="generalista",
        title="Titolo X - LatinaToday",
        published_at=pub_time,
        first_seen_at=pub_time,
    )
    db_session.add(art)
    db_session.commit()

    raw = {
        "url": "https://www.latinatoday.it/cronaca/art-2.html",
        "source": "LatinaToday",
        "acquisition_mode": "generalista",
        "title": "Titolo X - LatinaToday",
        "published_at": pub_time,
    }
    assert is_duplicate_in_db(db_session, raw) is True


def test_copia_mirata_1553_e_generalista_0700_stesso_giorno_duplicato(db_session):
    """Copia mirata pubblicata alle 15:53 e copia generalista con data 07:00:00 UTC dello stesso giorno: duplicato."""
    pub_mirato = datetime(2026, 10, 11, 15, 53, 0, tzinfo=timezone.utc)
    pub_generalista = datetime(2026, 10, 11, 7, 0, 0, tzinfo=timezone.utc)

    art = Article(
        url="https://www.ansa.it/canale_salute/notizie/aviaria-a.html",
        source="ansa_salute",
        acquisition_mode="mirato",
        title="Allarme aviaria in Veneto",
        published_at=pub_mirato,
        first_seen_at=pub_mirato,
    )
    db_session.add(art)
    db_session.commit()

    raw = {
        "url": "https://www.ansa.it/canale_salute/notizie/aviaria-b.html",
        "source": "ANSA",
        "acquisition_mode": "generalista",
        "title": "Allarme aviaria in Veneto - ANSA",
        "published_at": pub_generalista,
    }
    assert is_duplicate_in_db(db_session, raw) is True


def test_due_generalisti_0700_giorni_consecutivi_non_duplicati(db_session):
    """Due articoli generalisti con stesso titolo pubblicati alle 07:00:00 UTC di giorni consecutivi: non duplicati."""
    day1 = datetime(2026, 10, 10, 7, 0, 0, tzinfo=timezone.utc)
    day2 = datetime(2026, 10, 11, 7, 0, 0, tzinfo=timezone.utc)

    art = Article(
        url="https://www.ilpost.it/rubrica-day1",
        source="Il Post",
        acquisition_mode="generalista",
        title="Bollettino quotidiano - Il Post",
        published_at=day1,
        first_seen_at=day1,
    )
    db_session.add(art)
    db_session.commit()

    raw = {
        "url": "https://www.ilpost.it/rubrica-day2",
        "source": "Il Post",
        "acquisition_mode": "generalista",
        "title": "Bollettino quotidiano - Il Post",
        "published_at": day2,
    }
    assert is_duplicate_in_db(db_session, raw) is False


def test_due_mirati_9h_distanza_non_duplicati(db_session):
    """Due articoli mirati con stesso titolo a 9 ore di distanza: non duplicati (resta la tolleranza di 6 ore)."""
    t1 = datetime(2026, 10, 11, 8, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 10, 11, 17, 0, 0, tzinfo=timezone.utc)

    art = Article(
        url="https://www.ansa.it/canale/edizione-mattina.html",
        source="ansa_salute",
        acquisition_mode="mirato",
        title="Aggiornamento sanitario",
        published_at=t1,
        first_seen_at=t1,
    )
    db_session.add(art)
    db_session.commit()

    raw = {
        "url": "https://www.ansa.it/canale/edizione-sera.html",
        "source": "ansa_salute",
        "acquisition_mode": "mirato",
        "title": "Aggiornamento sanitario",
        "published_at": t2,
    }
    assert is_duplicate_in_db(db_session, raw) is False
