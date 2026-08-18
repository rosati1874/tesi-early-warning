"""Modulo isolato per l'invio di notifiche webhook pub-sub per i nuovi segnali epidemici identificati."""
from datetime import datetime, timezone
import requests
from sqlalchemy.orm import Session

from src import config
from src.db.models import Article, Subscriber


def notify_new_signals(session: Session, new_signals: list[Article]) -> None:
    """Invia notifiche HTTP POST a tutti gli iscritti attivi per gli articoli classificati come segnali epidemici.

    - Se config.ENABLE_WEBHOOK_NOTIFICATIONS è False, non legge dal DB né invia chiamate di rete (ritorna subito).
    - Timeout massimo di 5 secondi per ciascuna richiesta HTTP.
    - Se una chiamata fallisce (o va in timeout / 4xx / 5xx), incrementa failure_count.
    - Se failure_count raggiunge o supera 5, disattiva l'iscritto (active = False).
    - Le eccezioni non vengono mai propagate verso l'alto per non interrompere la pipeline principale.
    """
    if not getattr(config, "ENABLE_WEBHOOK_NOTIFICATIONS", False):
        return

    if not new_signals:
        return

    try:
        active_subscribers = (
            session.query(Subscriber)
            .filter(Subscriber.active.is_(True))
            .all()
        )
    except Exception as exc:
        print(f"[ATTENZIONE] [webhook] Impossibile recuperare gli iscritti dal DB: {exc}")
        return

    if not active_subscribers:
        print("[INFO] [webhook] Nessun iscritto attivo nel database per la spedizione dei webhook")
        return

    print(f"[INFO] [webhook] Spedizione notifiche per {len(new_signals)} nuovi segnali epidemici a {len(active_subscribers)} iscritti attivi...")

    now = datetime.now(timezone.utc)

    for article in new_signals:
        payload = {
            "event": "epidemic_signal_detected",
            "article_id": article.id,
            "title": article.title,
            "url": article.url,
            "source": article.source,
            "published_at": article.published_at.isoformat() if article.published_at else None,
            "disease": article.llm_disease,
            "location": article.llm_location,
            "confidence": article.llm_confidence,
            "justification": article.llm_justification,
        }

        for sub in active_subscribers:
            try:
                resp = requests.post(
                    sub.webhook_url,
                    json=payload,
                    timeout=5,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "EarlyWarningWebhookNotifier/1.0",
                    },
                )
                if 200 <= resp.status_code < 300:
                    sub.failure_count = 0
                    sub.last_notified_at = now
                    session.commit()
                    print(f"[INFO] [webhook] Notifica inviata con successo a {sub.webhook_url} per articolo ID {article.id}")
                else:
                    sub.failure_count = (sub.failure_count or 0) + 1
                    print(f"[ATTENZIONE] [webhook] Errore HTTP {resp.status_code} durante la notifica a {sub.webhook_url} (fallimenti consecutivi: {sub.failure_count}/5)")
                    if sub.failure_count >= 5:
                        sub.active = False
                        print(f"[ATTENZIONE] [webhook] Iscritto {sub.webhook_url} disattivato a causa del raggiungimento di 5 fallimenti consecutivi")
                    session.commit()
            except Exception as exc:
                sub.failure_count = (sub.failure_count or 0) + 1
                print(f"[ATTENZIONE] [webhook] Eccezione di rete o timeout ({exc}) verso {sub.webhook_url} (fallimenti consecutivi: {sub.failure_count}/5)")
                if sub.failure_count >= 5:
                    sub.active = False
                    print(f"[ATTENZIONE] [webhook] Iscritto {sub.webhook_url} disattivato a causa del raggiungimento di 5 fallimenti consecutivi")
                session.commit()
