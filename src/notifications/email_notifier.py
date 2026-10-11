"""Modulo per l'invio di notifiche riepilogative via email per i nuovi segnali epidemici."""
from datetime import datetime, timezone
import html
from email.message import EmailMessage
import smtplib
from sqlalchemy.orm import Session

try:
    from zoneinfo import ZoneInfo
    ROME_TZ = ZoneInfo("Europe/Rome")
except Exception:
    ROME_TZ = timezone.utc

from src import config
from src.db.models import Article, Subscriber


def _build_email_contents(new_signals: list[Article]) -> tuple[str, str, str]:
    """Genera l'oggetto, il corpo in testo semplice e il corpo HTML per la notifica."""
    now_rome = datetime.now(ROME_TZ)
    formatted_time = now_rome.strftime("%d/%m/%Y %H:%M")
    n_signals = len(new_signals)
    if n_signals == 1:
        label_segnali = "1 nuovo segnale epidemico"
        intro_text = f"Riepilogo nuovo segnale identificato: 1 (data rilevamento: {formatted_time})"
        intro_html = f"Durante l'ultima esecuzione è stato identificato <strong>1</strong> nuovo segnale epidemico (rilevamento: {html.escape(formatted_time)})."
    else:
        label_segnali = f"{n_signals} nuovi segnali epidemici"
        intro_text = f"Riepilogo nuovi segnali identificati: {n_signals} (data rilevamento: {formatted_time})"
        intro_html = f"Durante l'ultima esecuzione sono stati identificati <strong>{n_signals}</strong> nuovi segnali epidemici (rilevamento: {html.escape(formatted_time)})."

    subject = f"[Early Warning] {label_segnali} – {formatted_time}"

    text_lines = [
        "Sistema di Early Warning Epidemico",
        intro_text,
        "",
        "=" * 60,
    ]

    html_items = []

    for idx, art in enumerate(new_signals, start=1):
        title = art.title or "n.d."
        source = art.source or "n.d."
        if getattr(art, "published_at", None):
            pub = art.published_at
            if pub.tzinfo is not None:
                pub = pub.astimezone(ROME_TZ)
            pub_str = pub.strftime("%d/%m/%Y %H:%M")
        else:
            pub_str = "n.d."

        disease = art.llm_disease or "n.d."
        location = art.llm_location or "n.d."
        if getattr(art, "llm_confidence", None) is not None:
            conf_str = f"{art.llm_confidence:.2f}" if isinstance(art.llm_confidence, float) else str(art.llm_confidence)
        else:
            conf_str = "n.d."
        justification = art.llm_justification or "n.d."
        url = art.url or "n.d."

        text_lines.extend([
            f"Segnale #{idx}: {title}",
            f"- Fonte: {source}",
            f"- Data di pubblicazione: {pub_str}",
            f"- Malattia: {disease}",
            f"- Luogo: {location}",
            f"- Confidenza: {conf_str}",
            f"- Motivazione: {justification}",
            f"- Link: {url}",
            "-" * 60,
        ])

        link_html = f'<a href="{html.escape(url)}" style="color: #2980b9;">{html.escape(url)}</a>' if url != "n.d." else "n.d."

        html_items.append(f"""
        <div style="margin-bottom: 20px; padding: 15px; background-color: #f8f9fa; border: 1px solid #e9ecef; border-left: 4px solid #c0392b; border-radius: 4px;">
          <h3 style="margin-top: 0; margin-bottom: 10px; color: #2c3e50;">#{idx} {html.escape(title)}</h3>
          <table style="border-collapse: collapse; width: 100%; font-size: 14px;">
            <tr><td style="padding: 4px 8px; font-weight: bold; width: 160px;">Fonte:</td><td style="padding: 4px 8px;">{html.escape(source)}</td></tr>
            <tr><td style="padding: 4px 8px; font-weight: bold;">Data di pubblicazione:</td><td style="padding: 4px 8px;">{html.escape(pub_str)}</td></tr>
            <tr><td style="padding: 4px 8px; font-weight: bold;">Malattia:</td><td style="padding: 4px 8px;">{html.escape(disease)}</td></tr>
            <tr><td style="padding: 4px 8px; font-weight: bold;">Luogo:</td><td style="padding: 4px 8px;">{html.escape(location)}</td></tr>
            <tr><td style="padding: 4px 8px; font-weight: bold;">Confidenza:</td><td style="padding: 4px 8px;">{html.escape(conf_str)}</td></tr>
            <tr><td style="padding: 4px 8px; font-weight: bold;">Motivazione:</td><td style="padding: 4px 8px;">{html.escape(justification)}</td></tr>
            <tr><td style="padding: 4px 8px; font-weight: bold;">Link:</td><td style="padding: 4px 8px;">{link_html}</td></tr>
          </table>
        </div>
        """)

    text_lines.extend([
        "",
        "Nota: I segnali riportati sono preliminari, generati automaticamente e destinati a successiva verifica.",
    ])
    text_body = "\n".join(text_lines)

    html_body = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{html.escape(subject)}</title>
</head>
<body style="font-family: Arial, sans-serif; line-height: 1.5; color: #333333; max-width: 700px; margin: 0 auto; padding: 20px;">
  <h2 style="color: #2c3e50; border-bottom: 2px solid #ecf0f1; padding-bottom: 8px;">Sistema di Early Warning Epidemico</h2>
  <p style="font-size: 15px;">{intro_html}</p>
  {"".join(html_items)}
  <p style="margin-top: 30px; padding: 12px; background-color: #fcf8e3; border: 1px solid #faebcc; border-radius: 4px; font-size: 13px; color: #8a6d3b;">
    <strong>Nota:</strong> I segnali riportati sono preliminari, generati automaticamente e destinati a successiva verifica.
  </p>
</body>
</html>"""

    return subject, text_body, html_body


def notify_new_signals_by_email(session: Session, new_signals: list[Article]) -> None:
    """Invia un'email riepilogativa con tutti i nuovi segnali epidemici a ciascun destinatario attivo."""
    # Controllo interruttore: se disattivato, esce immediatamente senza interrogare DB o rete
    if not getattr(config, "ENABLE_EMAIL_NOTIFICATIONS", False):
        return

    # Se non ci sono nuovi segnali nell'esecuzione corrente, non effettua alcun invio
    if not new_signals:
        return

    # Verifica presenza dei parametri minimi per la connessione SMTP
    if not (config.SMTP_HOST and config.SMTP_USER and config.SMTP_PASSWORD):
        print("[ATTENZIONE] [email] Credenziali SMTP non configurate o incomplete (richiesti SMTP_HOST, SMTP_USER, SMTP_PASSWORD). Invio email saltato.")
        return

    # Recupera i destinatari attivi con indirizzo email valido
    try:
        recipients = (
            session.query(Subscriber)
            .filter(
                Subscriber.active.is_(True),
                Subscriber.email.isnot(None),
                Subscriber.email != "",
            )
            .all()
        )
    except Exception as exc:
        print(f"[ATTENZIONE] [email] Impossibile recuperare i destinatari email dal DB: {exc}")
        return

    if not recipients:
        print("[INFO] [email] Nessun destinatario email attivo nel database per la spedizione delle notifiche")
        return

    subject, text_body, html_body = _build_email_contents(new_signals)
    sender = config.EMAIL_SENDER or config.SMTP_USER
    sender_header = f"{config.EMAIL_SENDER_NAME} <{sender}>" if config.EMAIL_SENDER_NAME else sender

    # Apertura della connessione SMTP condivisa per tutti gli invii dell'esecuzione
    server = None
    try:
        if config.SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=15)
        else:
            server = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15)
            server.starttls()
        server.login(config.SMTP_USER, config.SMTP_PASSWORD)
    except Exception as exc:
        print(f"[ATTENZIONE] [email] Errore di connessione o autenticazione SMTP verso {config.SMTP_HOST}:{config.SMTP_PORT}: {exc}")
        if server is not None:
            try:
                server.close()
            except Exception:
                pass
        return

    # Invio separato a ciascun destinatario mantenendo isolati gli indirizzi
    try:
        now_utc = datetime.now(timezone.utc)
        for sub in recipients:
            try:
                msg = EmailMessage()
                msg["Subject"] = subject
                msg["From"] = sender_header
                msg["To"] = sub.email
                msg.set_content(text_body)
                msg.add_alternative(html_body, subtype="html")

                server.send_message(msg)
                sub.last_notified_at = now_utc
                session.commit()
                print(f"[INFO] [email] Notifica riepilogativa inviata con successo a {sub.email}")
            except Exception as exc:
                print(f"[ATTENZIONE] [email] Errore durante l'invio della notifica email a {sub.email}: {exc}")
                try:
                    session.rollback()
                except Exception:
                    pass
    finally:
        try:
            server.quit()
        except Exception:
            pass
