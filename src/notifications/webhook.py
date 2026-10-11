"""Modulo isolato per l'invio di notifiche webhook pub-sub per i segnali epidemici (RF-07, RF-06)."""
from datetime import datetime, timezone
import requests
from sqlalchemy.orm import Session

from src import config
from src.db.models import Article, Subscriber


def _send_webhook_events(session: Session, payloads: list[dict]) -> None:
    """Invia eventi HTTP POST a tutti gli iscritti attivi.
    
    Gestione robusta (timeout, failure_count, disattivazione dopo 5 errori).
    Le eccezioni non vengono mai propagate verso l'alto per non interrompere
    le pipeline principali (acquisizione o monitoraggio).
    """
    if not getattr(config, "ENABLE_WEBHOOK_NOTIFICATIONS", False):
        return

    if not payloads:
        return

    try:
        active_subscribers = (
            session.query(Subscriber)
            .filter(
                Subscriber.active.is_(True),
                Subscriber.webhook_url.isnot(None),
            )
            .all()
        )
    except Exception as exc:
        print(f"[ATTENZIONE] [webhook] Impossibile recuperare gli iscritti dal DB: {exc}")
        return

    if not active_subscribers:
        print("[INFO] [webhook] Nessun iscritto attivo nel database per la spedizione dei webhook")
        return

    print(f"[INFO] [webhook] Spedizione notifiche per {len(payloads)} eventi a {len(active_subscribers)} iscritti attivi...")

    now = datetime.now(timezone.utc)

    for payload in payloads:
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
                    print(f"[INFO] [webhook] Notifica '{payload.get('event')}' inviata con successo a {sub.webhook_url} per articolo ID {payload.get('article_id')}")
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


def notify_new_signals(session: Session, new_signals: list[Article]) -> None:
    """Invia notifiche HTTP POST a tutti gli iscritti attivi per i nuovi segnali epidemici (RF-07)."""
    payloads = []
    for article in new_signals:
        payloads.append({
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
        })
    _send_webhook_events(session, payloads)


def notify_monitoring_update(session: Session, article: Article, event_type: str, version=None, http_status: int = None) -> None:
    """Invia notifica per aggiornamento o rimozione di un segnale epidemico dal monitoraggio (RF-06)."""
    payload = {
        "event": event_type,  # 'epidemic_signal_updated' o 'epidemic_signal_removed'
        "article_id": article.id,
        "title": article.title,
        "url": article.url,
        "source": article.source,
    }
    
    if event_type == "epidemic_signal_removed":
        payload["http_status"] = http_status
    elif event_type == "epidemic_signal_updated":
        payload["captured_at"] = version.captured_at.isoformat() if version and version.captured_at else None
        payload["content_hash"] = version.content_hash if version else None

    _send_webhook_events(session, [payload])
