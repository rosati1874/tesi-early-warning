# Handoff: Sistema di Iscrizione al Canale di Notifica (RF-07)

Questo documento riassume l'evoluzione e lo stato di avanzamento dell'infrastruttura di notifica pub-sub del sistema di early warning epidemico.

---

## 1. Evoluzione Architetturale (da Modello v1 a Modello v2)

### Modello v1: Auto-Iscrizione Diretta (Dismesso)
Inizialmente, l'iscrizione permetteva l'inserimento diretto da parte di applicazioni terze nella tabella `subscribers` tramite la policy RLS `subscribers_public_self_register`.
- **Limite individuato**: Non idoneo ad un contesto istituzionale (es. ISS / Ministero della Salute) in quanto privo di un meccanismo di controllo preventivo sui soggetti richiedenti e sugli endpoint registrati.

### Modello v2: Richiesta + Approvazione Manuale dell'Operatore (In Uso)
È stato introdotto un modello a due fasi senza aggiungere server o codice Python applicativo:
1. **Fase 1 (Invio Richiesta Pubblica)**: Le applicazioni terze inviano una richiesta `POST` alla nuova tabella `subscription_requests` via API REST di Supabase (PostgREST), specificando `webhook_url` (`https` obbligatorio), ed eventualmente `organization_name` e `contact_email`. La policy RLS forza l'inserimento esclusivo in stato `pending` con `reviewed_at IS NULL`.
2. **Fase 2 (Approvazione/Rifiuto Manuale)**: L'operatore visualizza le richieste pendenti dalla Dashboard Supabase o via SQL. Solo in caso di approvazione manuale (`status = 'approved'`), l'URL viene trasferito nella tabella `subscribers` ed inizia a ricevere notifiche.
3. **Revoca Iscrizione Diretta**: La policy RLS di inserimento diretto su `subscribers` è stata revocata (`REVOKE INSERT ON subscribers FROM anon`).

---

## 2. Dettaglio delle Modifiche al Database (`sql/schema.sql`)

- **Tabella `subscription_requests`**:
  - `id` (SERIAL PRIMARY KEY)
  - `webhook_url` (TEXT NOT NULL, `CHECK (webhook_url ~ '^https://')`)
  - `organization_name` (TEXT)
  - `contact_email` (TEXT)
  - `requested_at` (TIMESTAMPTZ DEFAULT now())
  - `status` (TEXT DEFAULT 'pending', `CHECK (status IN ('pending', 'approved', 'rejected'))`)
  - `reviewed_at` (TIMESTAMPTZ)
  - `notes` (TEXT)
- **Policy RLS `subscription_requests_public_submit`**:
  - Consente l'inserimento al ruolo `anon` solo con `status = 'pending'` e `reviewed_at IS NULL`.
- **Privilegi `anon`**:
  - `GRANT INSERT` ed uso della sequenza `subscription_requests_id_seq` a `anon`.
  - `REVOKE INSERT` ed uso della sequenza su `subscribers` da `anon`.

---

## 3. Test di Verifica End-to-End (E2E)

### Stato dei Test da Eseguire in Produzione
Dopo l'esecuzione della migrazione SQL v2 nell'SQL Editor di Supabase, eseguire la verifica end-to-end con `curl`:

1. **Invio richiesta valida a `subscription_requests`**:
   ```bash
   curl -i -X POST "https://<PROJECT_REF>.supabase.co/rest/v1/subscription_requests" \
     -H "apikey: <PUBLISHABLE_API_KEY>" \
     -H "Content-Type: application/json" \
     -H "Prefer: return=minimal" \
     -d '{
       "webhook_url": "https://esempio.it/webhook-test",
       "organization_name": "Ente Test",
       "contact_email": "test@esempio.it"
     }'
   ```
   *Esito Atteso*: `HTTP 201 Created`

2. **Tentativo di inserimento diretto su `subscribers` (vecchio endpoint v1)**:
   ```bash
   curl -i -X POST "https://<PROJECT_REF>.supabase.co/rest/v1/subscribers" \
     -H "apikey: <PUBLISHABLE_API_KEY>" \
     -H "Content-Type: application/json" \
     -d '{"webhook_url": "https://esempio.it/webhook-diretto"}'
   ```
   *Esito Atteso*: `HTTP 401 Unauthorized` / `403 Forbidden` (permesso negato, RLS revocata).

---

## 4. Attività Aperte e Note per la Tesi

- **Approvazione Operatore**: Gli esempi SQL per approvare o rifiutare le richieste sono documentati in `sql/schema.sql` e nel `README.md`.
- **Aggiornamento Tesi**: Nel Capitolo 5/6 della tesi è opportuno specificare l'adozione del modello v2 a due fasi (richiesta + approvazione) a garanzia di sicurezza e governance istituzionale.
- **Riferimenti Incrociati**: In sospeso l'allineamento della numerazione dei paragrafi del Capitolo 4 richiamati nei Capitoli 2, 7 e 8.

---

## 5. Esito Verifiche End-to-End e Chiarimento Tecnico

### Esito dei Test di Produzione
La verifica end-to-end sul database Supabase di produzione è stata completata con successo:

1. **Test 1 — Invio richiesta su `/rest/v1/subscription_requests`**:
   - Richiesta `POST` senza campo `status`, con header `apikey` e `Prefer: return=minimal`.
   - **Risultato**: **`HTTP 201 Created`** (Richiesta salvata correttamente in stato `pending`).

2. **Test 2 — Inserimento diretto su `/rest/v1/subscribers` (Vecchio Endpoint v1)**:
   - Richiesta `POST` diretta sulla tabella `subscribers`.
   - **Risultato**: **`HTTP 401 Unauthorized`** (`permission denied for table subscribers`).
   - **Conferma**: Il vecchio endpoint di auto-iscrizione diretta è sbarrato con successo.

### Chiarimento sul Falso Indizio dell'Header `Authorization`
L'errore `HTTP 401 / 42501` riscontrato nelle fasi intermedie di test quando si usava `Prefer: return=representation` era causato dal fatto che PostgREST, per restituire la rappresentazione del record inserito, tenta di eseguire una `SELECT` automatica sulla riga appena creata. Poiché la tabella `subscription_requests` non ha (giustamente) una policy di lettura pubblica (`SELECT`), l'operazione veniva bloccata con violazione di RLS.

L'uso dell'header `Authorization: Bearer` era stato una variazione coincidente e non rappresentava un requisito reale di autenticazione. Per le applicazioni terze, il flusso documentato nel `README.md` (con il solo header `apikey`, `Prefer: return=minimal` e nessun header `Authorization`) è quello corretto, valido ed operante.
