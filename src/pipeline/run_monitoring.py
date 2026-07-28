"""Entry point della pipeline di monitoraggio periodico (RF-06, Cap. 4.6).

Richiamato dal workflow .github/workflows/monitoring.yml, con frequenza
più bassa rispetto all'acquisizione.
"""
from src.db.connection import get_session
from src.monitoring.checker import run_monitoring_cycle


def run() -> None:
    print("[INFO] [pipeline] Avvio della pipeline di monitoraggio...")
    try:
        session = get_session()
        run_monitoring_cycle(session)
    except Exception as exc:
        msg = f"[ERRORE GRAVE] [pipeline] Impossibile completare la pipeline di monitoraggio: {exc}"
        print(msg)
        raise RuntimeError(msg) from exc
    print("[INFO] [pipeline] Pipeline di monitoraggio completata con successo")


if __name__ == "__main__":
    run()
