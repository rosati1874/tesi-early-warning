# Sistema di early warning epidemico — scaffold iniziale

Scaffold per la tesi magistrale "Sistema di early warning per il rilevamento
di possibili focolai epidemici tramite monitoraggio del web".

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

### 5. Iscrizione al canale di notifica (per applicazioni terze) (RF-07)
Le applicazioni terze possono registrare il proprio endpoint webhook per ricevere notifiche HTTP POST in tempo reale sui nuovi segnali epidemici rilevati, senza richiedere modifiche lato server. La registrazione sfrutta direttamente l'API REST automatica di Supabase (PostgREST) protetta via Row-Level Security (RLS).

Esempio di richiesta di auto-iscrizione via `curl`:
```bash
curl -X POST "https://<PROJECT_REF>.supabase.co/rest/v1/subscribers" \
  -H "apikey: <PUBLISHABLE_API_KEY>" \
  -H "Authorization: Bearer <PUBLISHABLE_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"webhook_url": "https://example.com/webhook"}'
```

**Dove reperire i parametri nella Dashboard Supabase:**
- `<PROJECT_REF>`: **Integration → Data API** (es. `xyz123abc`).
- `<PUBLISHABLE_API_KEY>`: **Settings → API Keys**, scheda **"Publishable and secret API keys"**, formato `sb_publishable_...` (o la chiave `anon` classica).

*Nota sulla sicurezza:* Le policy RLS su Supabase garantiscono che il ruolo pubblico `anon` possa solo effettuare `INSERT` con stato iniziale valido (`active = true`, `failure_count = 0`, `last_notified_at IS NULL`) e richiedono l'uso esclusivo del protocollo HTTPS. Le operazioni di lettura (`SELECT`), modifica (`UPDATE`) o cancellazione (`DELETE`) restano inaccessibili al pubblico.

```bash
python -m venv .venv
source .venv/bin/activate  # su Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # poi compila .env con le tue credenziali
python -m src.pipeline.run_acquisition
python -m src.pipeline.run_monitoring
```

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
