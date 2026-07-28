"""Entry point della pipeline di monitoraggio periodico (RF-06, Cap. 4.6).

Richiamato dal workflow .github/workflows/monitoring.yml, con frequenza
più bassa rispetto all'acquisizione.
"""
from src.db.connection import get_session
from src.monitoring.checker import run_monitoring_cycle


def run() -> None:
    session = get_session()
    run_monitoring_cycle(session)


if __name__ == "__main__":
    run()
