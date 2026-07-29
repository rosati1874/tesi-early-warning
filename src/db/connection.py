"""Creazione di engine e sessione SQLAlchemy verso Supabase/Postgres."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.config import DATABASE_URL

from src.db.models import Base

_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        if not DATABASE_URL:
            msg = "[ERRORE GRAVE] [db] DATABASE_URL non impostata: vedi .env.example"
            print(msg)
            raise RuntimeError(msg)
        try:
            _engine = create_engine(DATABASE_URL, pool_pre_ping=True)
            # Verifica la connessione effettiva al database (es. verifica password, host e rete)
            with _engine.connect() as conn:
                pass
            # Assicura che le tabelle definite in models.py (es. blacklisted_models) siano create se mancanti
            Base.metadata.create_all(_engine)
        except Exception as exc:
            msg = f"[ERRORE GRAVE] [db] Impossibile connettersi al database (es. credenziali errate o server irraggiungibile): {exc}"
            print(msg)
            raise RuntimeError(msg) from exc
    return _engine


def get_session():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine())
    try:
        return _SessionLocal()
    except Exception as exc:
        msg = f"[ERRORE GRAVE] [db] Impossibile aprire una sessione verso il database: {exc}"
        print(msg)
        raise RuntimeError(msg) from exc
