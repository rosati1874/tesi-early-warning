# Sistema di early warning epidemico (Progetto di Tesi)

Questo repository contiene il codice sorgente del mio progetto di tesi: un sistema di early warning in grado di rilevare automaticamente potenziali focolai epidemici monitorando le notizie sul web. 
Il sistema è attualmente attivo e raccoglie dati ogni 6 ore.

## Come funziona (Architettura)

```text
acquisizione (mirata: RSS testate + generalista: Google News RSS)
        |
        v
   parsing / estrazione testo (trafilatura + BeautifulSoup)
        |
        v
   filtro lessicale (src/filtering)
        |
        v
   classificazione LLM (src/classification, tramite Gemini)
        |
        v
   salvataggio dati (Postgres su Supabase)
        |
        v
   monitoraggio periodico e notifiche (workflow separato)
```

L'intero ciclo è orchestrato tramite due workflow di GitHub Actions (`.github/workflows/acquisition.yml` e `monitoring.yml`) eseguiti in modo programmato, quindi non c'è bisogno di mantenere alcun server sempre acceso.

## Setup del progetto

Se vuoi far girare il sistema sul tuo account, ecco i passaggi:

### 1. GitHub
1. Crea un nuovo repository (anche privato) e copia al suo interno i file di questo progetto.
2. Vai su **Settings > Secrets and variables > Actions** e crea due secret:
   - `DATABASE_URL` (vedi sotto)
   - `GEMINI_API_KEY` (vedi sotto)

### 2. Supabase (Database Postgres)
1. Crea un progetto gratuito su https://supabase.com.
2. Dal **SQL Editor**, incolla ed esegui il codice che trovi in `sql/schema.sql` per creare tutte le tabelle e le policy di sicurezza necessarie.
3. Vai su **Project Settings > Database > Connection string** (seleziona "URI" e assicurati di usare la porta *pooled*, consigliata per GitHub Actions). Copia la stringa e usala come valore per il secret `DATABASE_URL`.

### 3. Chiave API di Gemini
1. Vai su https://aistudio.google.com/apikey e genera una API key gratuita.
2. Copiala e usala come valore per il secret `GEMINI_API_KEY`.

### 4. Sviluppo e test in locale (facoltativo)
Se preferisci fare test in locale sul tuo computer, puoi usare questi comandi:
```bash
python -m venv .venv
source .venv/bin/activate  # su Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # ricordati di inserire le tue credenziali nel file .env
python -m src.pipeline.run_acquisition
python -m src.pipeline.run_monitoring
```

### 5. Iscriversi alle notifiche webhook (RF-07)
Il sistema prevede la possibilità, per applicazioni esterne, di registrarsi per ricevere una notifica HTTP POST in tempo reale ogni volta che viene rilevato un nuovo segnale epidemico. 

Il processo avviene in due fasi:
1. **Invio della richiesta**: Chiunque può inviare una richiesta all'API di Supabase (tabella `subscription_requests`). La richiesta parte in stato `pending`. È obbligatorio fornire un URL webhook basato su `https`.
2. **Approvazione manuale**: L'amministratore del sistema verifica le richieste in attesa dalla Dashboard di Supabase e le approva manualmente. Solo a quel punto l'URL viene inserito tra gli iscritti attivi (`subscribers`) e inizia a ricevere i dati.

Ecco un esempio di come inviare una richiesta tramite `curl`:
```bash
curl -X POST "https://<PROJECT_REF>.supabase.co/rest/v1/subscription_requests" \
  -H "apikey: <PUBLISHABLE_API_KEY>" \
  -H "Content-Type: application/json" \
  -H "Prefer: return=minimal" \
  -d '{
    "webhook_url": "https://example.com/webhook",
    "organization_name": "Istituto di Ricerca Salute",
    "contact_email": "referente@example.com"
  }'
```

- `<PROJECT_REF>` si trova nella dashboard di Supabase sotto **Integration > Data API**.
- `<PUBLISHABLE_API_KEY>` si trova sotto **Settings > API Keys** (è la chiave pubblica anonima). Questa chiave è volutamente pubblica per permettere a chiunque di inviare una richiesta di iscrizione senza esporre le vere credenziali amministrative.

Le regole di sicurezza (RLS) di Supabase garantiscono che gli utenti anonimi possano solo inserire richieste in attesa, senza poter leggere, modificare o cancellare i dati degli iscritti veri e propri.

*Comandi SQL utili per l'operatore:*
```sql
-- Approvare una richiesta:
UPDATE subscription_requests SET status = 'approved', reviewed_at = now() WHERE id = <ID>;
INSERT INTO subscribers (webhook_url) SELECT webhook_url FROM subscription_requests WHERE id = <ID>;

-- Rifiutare una richiesta:
UPDATE subscription_requests SET status = 'rejected', reviewed_at = now(), notes = 'Motivo del rifiuto' WHERE id = <ID>;
```

## Note sull'implementazione

- Per l'acquisizione generalista, ho scelto di usare **Google News RSS** perché non richiede una chiave API, risultando molto più stabile e affidabile rispetto a librerie di scraping o alle API ufficiali di Google Search (che diventano a pagamento superata la soglia gratuita).
- Per quanto riguarda il rispetto dei siti monitorati, non ho inserito pause artificiali (throttling) nel codice per rallentare il download. Dato che la pipeline gira solo ogni 6 ore e scarica pochissimi articoli alla volta (solo le notizie nuove), il carico sui server delle testate è minimo e non c'è rischio di violare i loro rate limit.
