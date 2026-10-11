# Sistema di early warning epidemico (Progetto di Tesi)

Questo repository contiene il codice sorgente del mio progetto di tesi: un sistema di early warning in grado di rilevare automaticamente potenziali focolai epidemici monitorando le notizie sul web. 
Il sistema è attualmente attivo e raccoglie dati ogni 6 ore.

## Come funziona (Architettura)

```text
acquisizione (mirata: RSS testate + generalista: Google News RSS)
        |
        v
   parsing / estrazione testo (trafilatura, con ripiego su BeautifulSoup e Jina AI Reader)
        |
        v
   filtro lessicale (src/filtering)
        |
        v
   classificazione LLM (src/classification, tramite Gemini)
        |
        v
   salvataggio dati (Postgres su Supabase) e notifiche nuovi segnali (webhook ed email)
```

L'intero ciclo è orchestrato tramite due workflow di GitHub Actions eseguiti in modo programmato:
- **Acquisizione** (`.github/workflows/acquisition.yml`): esegue l'acquisizione, l'estrazione del testo, il filtro lessicale e la classificazione; al termine della classificazione salva i dati su Postgres (Supabase) e invia le notifiche per i nuovi segnali identificati (sia via webhook sia via email).
- **Monitoraggio** (`.github/workflows/monitoring.yml`): controlla periodicamente disponibilità e aggiornamenti dei segnali epidemici pubblicati negli ultimi `MONITORING_WINDOW_DAYS` giorni e non invia notifiche.

In questo modo non c'è bisogno di mantenere alcun server sempre acceso.

## Setup del progetto

Se vuoi far girare il sistema sul tuo account, ecco i passaggi:

### 1. GitHub
1. Crea un nuovo repository (anche privato) e copia al suo interno i file di questo progetto.
2. Vai su **Settings > Secrets and variables > Actions**:
   - **Repository secrets**:
     - `DATABASE_URL` (obbligatorio, stringa di connessione a Supabase)
     - `GEMINI_API_KEY` (obbligatorio per la classificazione)
     - `SMTP_USER` (facoltativo, se si attivano le notifiche email; es. account Gmail)
     - `SMTP_PASSWORD` (facoltativo, se si attivano le notifiche email; password per le app a 16 caratteri)
   - **Repository variables**:
     - `ENABLE_LLM_CLASSIFICATION` (default "false", impostare a "true" per classificare)
     - `ENABLE_WEBHOOK_NOTIFICATIONS` (default "false", impostare a "true" per abilitare webhook)
     - `ENABLE_EMAIL_NOTIFICATIONS` (default "false", impostare a "true" per abilitare email)
     - `MONITORING_WINDOW_DAYS` (default "30")
     - `SMTP_HOST` (es. `smtp.gmail.com`)
     - `SMTP_PORT` (default "587")
     - `EMAIL_SENDER` (indirizzo mittente, default = `SMTP_USER`)
     - `EMAIL_SENDER_NAME` (default "Early Warning Epidemico")

### 2. Supabase (Database Postgres)
1. Crea un progetto gratuito su https://supabase.com.
2. Dal **SQL Editor**, incolla ed esegui il codice che trovi in `sql/schema.sql` per creare tutte le tabelle, gli indici e le policy di sicurezza necessarie. Su un database nuovo l'esecuzione di `sql/schema.sql` è sufficiente a inizializzare l'intero schema aggiornato.
3. Se invece disponi già di un database attivo creato con una versione precedente dello schema, applica i file di migrazione presenti in `sql/migrations/` in ordine cronologico:
   - `sql/migrations/2026-07-30_source_normalization.sql`: normalizzazione retroattiva del dominio sorgente per gli articoli storici acquisiti da Google News (già eseguita sul database di produzione, conservata esclusivamente come riferimento storico).
   - `sql/migrations/2026-10-11_email.sql`: estensione delle tabelle `subscribers` e `subscription_requests` per il supporto alle notifiche via email.
   - `sql/migrations/2026-10-11_monitoring_baseline.sql`: aggiunta dei campi `is_baseline` e `hash_method` alla tabella `article_versions` per la gestione delle versioni di riferimento nel monitoraggio.
   - `sql/migrations/2026-10-11_source_from_title.sql`: attribuzione retroattiva della testata dal titolo per gli articoli storici di Google News (già eseguita sul database di produzione, conservata esclusivamente come riferimento storico).
   - `sql/migrations/2026-10-11_prompt_version.sql`: aggiunta del campo `llm_prompt_version` alla tabella `articles` per tracciare la versione del prompt impiegata nella classificazione semantica.
4. Vai su **Project Settings > Database > Connection string** (seleziona "URI" e assicurati di usare la porta *pooled*, consigliata per GitHub Actions). Copia la stringa e usala come valore per il secret `DATABASE_URL`.

### 3. Chiave API di Gemini
1. Vai su https://aistudio.google.com/apikey e genera una API key gratuita.
2. Copiala e usala come valore per il secret `GEMINI_API_KEY`.

### 4. Configurazione SMTP per le Notifiche Email (es. Gmail)
Per inviare le notifiche tramite un account Gmail dedicato:
1. Accedi al tuo account Google e vai su **Gestisci il tuo Account Google > Sicurezza**.
2. Assicurati che la **Verifica in due passaggi** sia attiva.
3. Nella barra di ricerca delle impostazioni cerca **Password per le app** (oppure sotto Sicurezza > Verifica in due passaggi > Password per le app).
4. Crea una nuova voce (es. denominata `Early Warning`): Google genererà una password dedicata di 16 caratteri.
5. Configura i parametri SMTP:
   - Host: `smtp.gmail.com`
   - Porta: `587` (con TLS)
   - Utente (`SMTP_USER`): il tuo indirizzo Gmail
   - Password (`SMTP_PASSWORD`): la password a 16 caratteri generata (senza spazi)
   - Mittente (`EMAIL_SENDER`): il tuo indirizzo Gmail

### 5. Sviluppo in locale (facoltativo)
Se preferisci eseguire la pipeline in locale sul tuo computer, puoi usare questi comandi:
```bash
python -m venv .venv
source .venv/bin/activate  # su Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # ricordati di inserire le tue credenziali nel file .env
python -m src.pipeline.run_acquisition
python -m src.pipeline.run_monitoring
```

### 6. Iscriversi alle notifiche (Webhook ed Email) (RF-07, RF-06)
Il sistema permette a enti e utenti esterni di registrarsi per ricevere notifiche su potenziali focolai epidemici. Un iscritto può ricevere notifiche via webhook HTTP POST, via email, o su entrambi i canali.

- **Canale Webhook**: riceve una chiamata POST JSON per ogni nuovo segnale rilevato. La funzione `notify_monitoring_update` è predisposta ma non attiva, perché il workflow di monitoraggio non abilita le notifiche.
- **Canale Email**: riceve una singola email riepilogativa per esecuzione della pipeline contenente tutti i nuovi segnali identificati in quel ciclo. Se l'esecuzione non rileva nuovi segnali, nessuna email viene inviata.

Il processo di iscrizione avviene in due fasi:
1. **Invio della richiesta**: Chiunque può inviare una richiesta all'API di Supabase (tabella `subscription_requests`). La richiesta deve specificare almeno una destinazione (`webhook_url` e/o `notification_email`).
2. **Approvazione manuale**: L'amministratore del sistema verifica le richieste in attesa dalla Dashboard di Supabase e le approva manualmente, copiando i recapiti nella tabella `subscribers`.

Esempio di richiesta di iscrizione tramite `curl` (con sia webhook sia email):
```bash
curl -X POST "https://<PROJECT_REF>.supabase.co/rest/v1/subscription_requests" \
  -H "apikey: <PUBLISHABLE_API_KEY>" \
  -H "Content-Type: application/json" \
  -H "Prefer: return=minimal" \
  -d '{
    "webhook_url": "https://example.com/webhook",
    "notification_email": "notifiche@example.com",
    "organization_name": "Istituto di Ricerca Salute",
    "contact_email": "referente@example.com"
  }'
```

*Comandi SQL per l'operatore (Supabase SQL Editor):*
```sql
-- Approvare una richiesta (copiando webhook_url ed email in subscribers):
UPDATE subscription_requests SET status = 'approved', reviewed_at = now() WHERE id = <ID>;
INSERT INTO subscribers (webhook_url, email)
SELECT webhook_url, notification_email FROM subscription_requests WHERE id = <ID>;

-- Rifiutare una richiesta:
UPDATE subscription_requests SET status = 'rejected', reviewed_at = now(), notes = 'Motivo del rifiuto' WHERE id = <ID>;
```

*Nota sul disaccoppiamento dei canali:*
Lo stato `active` e il contatore `failure_count` sono associati alla singola riga nella tabella `subscribers`. Se un iscritto registra sia `webhook_url` sia `email` sulla medesima riga e l'endpoint webhook fallisce per 5 volte consecutive, la riga viene disattivata (`active = false`), interrompendo di conseguenza anche l'invio delle email. Qualora si desideri garantire la piena indipendenza del canale email rispetto all'affidabilità dell'endpoint webhook, è consigliabile iscrivere i due canali come due righe distinte in `subscribers` (una con solo `webhook_url` e una con solo `email`).

## Test

Per eseguire i test del progetto, installare le dipendenze di sviluppo ed eseguire `pytest`:

```bash
pip install -r requirements-dev.txt
python -m pytest
```

## Note sull'implementazione

- Per l'acquisizione generalista, ho scelto di usare **Google News RSS** perché non richiede una chiave API, risultando molto più stabile e affidabile rispetto a librerie di scraping o alle API ufficiali di Google Search (che diventano a pagamento superata la soglia gratuita).
- Per quanto riguarda il rispetto dei siti monitorati, non ho inserito pause artificiali nel codice per rallentare il download. Dato che la pipeline gira solo ogni 6 ore e scarica pochissimi articoli alla volta (solo le notizie nuove), il carico sui server delle testate è minimo; alcune testate bloccano comunque le richieste automatiche (es. Linkiesta), gestite con il ripiego su Jina AI Reader.
- Cartella `docs/analisi/`: script usato per le statistiche sulle fonti del caso di studio, non parte della pipeline.
