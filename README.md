# Sistema di early warning epidemico

Sistema di early warning per il rilevamento di possibili focolai epidemici tramite monitoraggio del web.
Il sistema è in produzione dal 28 luglio 2026, con acquisizione automatica ogni 6 ore. Caso di studio e validazione esterna completi.

## Architettura in breve

```
acquisizione (mirata: RSS testate + generalista: Google News RSS)
        │
        ▼
   parsing / estrazione (trafilatura + BeautifulSoup)
        │
        ▼
   filtro lessicale (src/filtering)
        │
        ▼
   classificazione LLM (src/classification, Gemini free tier)
        │
        ▼
   storage (Postgres su Supabase)
        │
        ▼
   monitoraggio periodico (workflow separato, solo su articoli rilevanti)
```

Orchestrazione: due GitHub Actions workflow schedulati
(`.github/workflows/acquisition.yml` e `monitoring.yml`), nessun server da
mantenere acceso.

## Setup — da fare una volta sola

### 1. GitHub
1. Crea un nuovo repository (anche privato) e carica il contenuto di questa
   cartella.
2. Vai in **Settings → Secrets and variables → Actions** e crea i secrets:
   - `DATABASE_URL` (vedi punto 2)
   - `GEMINI_API_KEY` (vedi punto 3)

### 2. Supabase (storage gratuito Postgres)
1. Crea un progetto gratuito su https://supabase.com
2. Vai in **SQL Editor**, incolla ed esegui il contenuto di `sql/schema.sql`
   per creare le tabelle.
3. Vai in **Project Settings → Database → Connection string** (modalità
   "URI", porta *pooled* consigliata per connessioni da ambienti serverless
   come GitHub Actions) e copia la stringa: sarà il valore di `DATABASE_URL`.

### 3. Gemini API (classificazione LLM, free tier)
1. Vai su https://aistudio.google.com/apikey e genera una API key gratuita.
2. Copiala come `GEMINI_API_KEY`.

### 5. Richiesta di iscrizione al canale di notifica (per applicazioni terze) (RF-07)
Le applicazioni terze interessate a ricevere notifiche HTTP POST in tempo reale sui nuovi segnali epidemici rilevati possono sottomettere una richiesta di iscrizione a due fasi. La richiesta viene inviata direttamente all'API REST di Supabase (`subscription_requests`) protetta da Row-Level Security (RLS) e viene presa in carico da un operatore per la verifica preliminare prima dell'attivazione effettiva del webhook.

**Flusso a due fasi:**
1. **Invio della richiesta (Pubblico)**: Chiunque può sottomettere una richiesta in stato `pending` specificando l'URL webhook (`https`, obbligatorio) ed eventualmente il nome dell'organizzazione e l'email di contatto.
2. **Approvazione dell'operatore (Riservato)**: L'operatore consulta le richieste in attesa dalla Dashboard Supabase o via SQL. Solo a seguito dell'approvazione manuale l'URL viene inserito nella tabella `subscribers` ed inizia a ricevere notifiche.

Esempio di invio richiesta di iscrizione via `curl`:
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

**Dove reperire i parametri nella Dashboard Supabase:**
- `<PROJECT_REF>`: **Integration → Data API** (es. `xyz123abc`).
- `<PUBLISHABLE_API_KEY>`: **Settings → API Keys**, scheda **"Publishable and secret API keys"**, formato `sb_publishable_...` (o la chiave `anon` classica). La chiave è pubblica per design per consentire la sottomissione delle richieste senza esporre credenziali amministrative.

*Esempi di gestione per l'operatore (SQL Editor Supabase):*
```sql
-- Approvazione richiesta:
UPDATE subscription_requests SET status = 'approved', reviewed_at = now() WHERE id = <ID>;
INSERT INTO subscribers (webhook_url) SELECT webhook_url FROM subscription_requests WHERE id = <ID>;

-- Rifiuto richiesta:
UPDATE subscription_requests SET status = 'rejected', reviewed_at = now(), notes = 'Motivazione' WHERE id = <ID>;
```

*Nota sulla sicurezza:* Le policy RLS su Supabase garantiscono che il ruolo pubblico `anon` possa solo inserire record in stato `pending` con `reviewed_at IS NULL` sulla tabella `subscription_requests`, imponendo l'uso del protocollo HTTPS. L'inserimento diretto sulla tabella `subscribers`, la lettura (`SELECT`), la modifica (`UPDATE`) e la cancellazione (`DELETE`) restano inaccessibili al pubblico.

## Note importanti

- **Feed RSS delle testate mirate**: gli URL in
  `src/acquisition/targeted.py` sono placeholder plausibili — VANNO
  verificati manualmente (spesso `<sito>/feed` o `<sito>/rss`) prima del
  primo run reale.
- **Google News RSS** non richiede chiave API: è il canale scelto per
  l'acquisizione generalista al posto di `googlesearch-python` (più
  fragile) o delle API ufficiali Google Search (a pagamento oltre la soglia
  gratuita). Da discutere/motivare nel Cap. 4.1 della tesi.
- **Confronto LLM locale vs API** (Cap. 4.4 / Cap. 6): questo scaffold
  implementa solo il classificatore via API (Gemini). L'aggiunta di un
  classificatore locale via Ollama è pensata come modulo separato e
  intercambiabile (`src/classification/`), da sviluppare in una seconda
  fase per l'esperimento comparativo sul caso di studio.
- Rispettare `robots.txt` e i rate limit delle fonti è responsabilità del
  chiamante: i moduli di acquisizione non implementano throttling
  aggressivo per default, va tarato in fase di implementazione (RNF-04).
