"""Acquisizione generalista (RF-02) via Google News RSS.

Che cosa fa il modulo
---------------------
Il canale generalista non monitora un elenco fisso di testate: interroga
Google News con alcune query testuali (definite in ``config.GENERALIST_QUERIES``)
e raccoglie gli articoli restituiti, qualunque sia la testata che li ha
pubblicati. In questo modo il sistema può intercettare anche fonti non note
a priori, come i quotidiani locali (Cap. 4.1).

Per ogni query il modulo:
    1. costruisce l'indirizzo del feed RSS di Google News, limitato a lingua
       italiana e area geografica Italia;
    2. scarica e legge il feed (con riparazione automatica dell'XML malformato);
    3. per ogni articolo del feed, converte il link intermedio di Google News
       nell'URL reale dell'articolo;
    4. ricava il nome della testata di provenienza;
    5. restituisce un dizionario con i metadati dell'articolo, nello stesso
       formato prodotto dal canale mirato (``targeted.py``), così che le fasi
       successive della pipeline trattino i due canali allo stesso modo.

Perché Google News RSS (Cap. 4.1)
---------------------------------
- Le API ufficiali di Google Search richiedono una chiave e diventano a
  pagamento oltre una soglia di utilizzo gratuito (contrasto con RNF-03).
- Le librerie di scraping non ufficiali dei risultati di ricerca
  (es. googlesearch-python) sono fragili e a rischio di violazione dei
  termini di servizio.
- Il feed RSS di Google News è gratuito, non richiede chiave API, accetta
  query testuali ed è filtrabile per lingua e area geografica.
"""
import time
from datetime import datetime, timezone
import re
from urllib.parse import quote_plus, urlparse
import feedparser
import requests
from googlenewsdecoder import new_decoderv1

from src.config import GENERALIST_QUERIES, HTTP_USER_AGENT, REQUEST_TIMEOUT_SECONDS
from src.parsing.extractor import clean_rss_summary

# Indirizzo del feed RSS di ricerca di Google News.
#   q={query}    -> termini di ricerca (inseriti già codificati per l'URL)
#   hl=it-IT     -> lingua dell'interfaccia e dei risultati: italiano
#   gl=IT        -> area geografica: Italia
#   ceid=IT:it   -> "edizione" di Google News: Italia, in italiano
# I tre parametri insieme limitano i risultati a contenuti in lingua italiana
# rilevanti per l'Italia (RNF-01).
GOOGLE_NEWS_RSS_TEMPLATE = (
    "https://news.google.com/rss/search?q={query}&hl=it-IT&gl=IT&ceid=IT:it"
)

# Espressione regolare che individua i caratteri "&" scritti "da soli".
# In XML il carattere & deve sempre introdurre un'entità (&amp; &lt; &gt;
# &quot; &apos; oppure un codice numerico come &#39; o &#x27;). Un "&" non
# seguito da una di queste forme rende il documento XML non valido e fa
# fallire la lettura del feed. La parte "(?!...)" è un "lookahead negativo":
# la regex trova un "&" solo se NON è seguito da una delle entità valide,
# così le & già corrette non vengono toccate.
_BARE_AMPERSAND = re.compile(r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)")


def _parse_generalist_feed(feed_url: str):
    """Scarica e legge un feed RSS di Google News, riparando l'XML se necessario.

    Nel complesso
    -------------
    Restituisce il feed già interpretato da feedparser: un oggetto la cui
    lista ``entries`` contiene un elemento per ciascun articolo (titolo,
    link, data, riassunto, testata). Se il feed non può essere scaricato o
    letto, restituisce un oggetto con ``entries`` vuota: il chiamante lo
    interpreta come "nessun risultato per questa query" e passa alla query
    successiva, senza interrompere la pipeline (RNF-07).

    Passo per passo
    ---------------
    1. Scarica il feed con ``requests``, presentandosi con lo User-Agent da
       browser definito in ``config.py`` e con un timeout, per non restare
       bloccati su una richiesta che non risponde. ``raise_for_status``
       trasforma in eccezione le risposte HTTP di errore (es. 403, 500).
    2. In caso di errore di rete o HTTP, registra un avviso e restituisce un
       feed vuoto.
    3. Prova a leggere il contenuto scaricato con feedparser. Se si ottiene
       almeno un articolo, il feed è valido e viene restituito subito.
    4. Se non si ottiene nessun articolo, l'ipotesi è che l'XML sia
       malformato: si converte il contenuto in testo, si sostituiscono le
       "&" isolate con "&amp;" e si riprova la lettura.
    5. Se la riparazione produce articoli, lo registra nei log e restituisce
       il feed riparato; altrimenti restituisce comunque il risultato (con
       ``entries`` vuota), che il chiamante gestirà come feed illeggibile.

    Args:
        feed_url: indirizzo completo del feed, già comprensivo della query.

    Returns:
        Oggetto ``FeedParserDict`` di feedparser (``entries`` eventualmente vuota).
    """
    # Passo 1: download del feed.
    try:
        resp = requests.get(
            feed_url,
            headers={"User-Agent": HTTP_USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS
        )
        resp.raise_for_status()
        raw = resp.content  # contenuto grezzo in byte
    except Exception as exc:
        # Passo 2: download fallito -> feed vuoto, la pipeline prosegue.
        print(f"[ATTENZIONE] [generalist] Impossibile scaricare feed Google News {feed_url}: {exc}")
        return feedparser.FeedParserDict(entries=[])

    # Passo 3: lettura diretta del feed.
    parsed = feedparser.parse(raw)
    if parsed.entries:
        return parsed

    # Passo 4: nessun articolo letto -> tentativo di riparazione dell'XML.
    try:
        if raw:
            text_xml = raw.decode("utf-8", errors="replace")  # byte -> testo
            fixed_xml = _BARE_AMPERSAND.sub("&amp;", text_xml)  # "&" isolate -> "&amp;"
            parsed_sanitized = feedparser.parse(fixed_xml.encode("utf-8"))
            # Passo 5: restituisce il feed riparato (con o senza articoli).
            if parsed_sanitized.entries:
                print("[INFO] [generalist] Feed Google News per query letto dopo riparazione XML automatica")
            return parsed_sanitized
    except Exception as exc:
        print(f"[ATTENZIONE] [generalist] Impossibile riparare feed Google News {feed_url}: {exc}")

    # Contenuto vuoto o riparazione fallita: si restituisce il primo tentativo.
    return parsed


def _resolve_article_url(raw_url: str | None) -> str | None:
    """Converte il link intermedio di Google News nell'URL reale dell'articolo.

    Nel complesso
    -------------
    I link presenti nel feed di Google News non puntano direttamente
    all'articolo, ma a un indirizzo intermedio del tipo
    ``https://news.google.com/rss/articles/CBMi...`` che contiene, in forma
    codificata, l'indirizzo vero. Ricavare l'URL reale serve a tre scopi:
    - scaricare il testo integrale dell'articolo dalla pagina originale
      (fase di estrazione, Cap. 4.3);
    - riconoscere i duplicati per URL, anche tra canale mirato e
      generalista (Cap. 4.2);
    - ricavare la testata dal dominio, quando serve (vedi
      ``_extract_source_name``).

    La funzione prova due strategie in sequenza e, se falliscono entrambe,
    conserva il link di Google News, così che l'articolo non vada perso.

    Passo per passo
    ---------------
    0. Se il link manca, restituisce None. Se il link non è di Google News,
       è già l'URL reale e viene restituito invariato.
    1. Livello 1, decodifica tramite la libreria ``googlenewsdecoder``
       (funzione ``new_decoderv1``). Nota: non è una decodifica offline. La
       libreria estrae dal link l'identificativo dell'articolo, scarica la
       pagina dell'articolo su Google News per ricavarne una firma e un
       timestamp, e infine invia questi dati a un servizio interno di Google
       News che restituisce l'URL originale. Sono quindi due richieste di
       rete verso Google. Se l'esito è un URL che non appartiene più a
       news.google.com, la decodifica è riuscita.
    2. Livello 2, se il livello 1 fallisce: si apre il link di Google News
       seguendo i reindirizzamenti HTTP, nella speranza che portino alla
       pagina dell'articolo. Se la risposta finale è positiva (200) e
       l'indirizzo finale non è più di Google News, quello è l'URL reale.
       In caso di errore di rete si fa un secondo tentativo dopo una pausa
       di 1 secondo (al massimo 2 tentativi). Se invece si ottiene una
       risposta ma l'indirizzo è ancora di Google News, non si riprova:
       l'esito non cambierebbe.
    3. Riserva finale: si registra un avviso e si restituisce il link
       originale di Google News invariato.

    Args:
        raw_url: link dell'articolo così come compare nel feed.

    Returns:
        L'URL reale dell'articolo, oppure il link originale se non è stato
        possibile decodificarlo, oppure None se il link mancava.
    """
    # Passo 0: link assente.
    if not raw_url:
        return None

    # Solo i link di Google News vanno decodificati.
    if "news.google.com" in raw_url:
        # Livello 1: decodifica tramite googlenewsdecoder.
        decoded_url = None
        try:
            res = new_decoderv1(raw_url)
            # La libreria restituisce un dizionario {"status": True/False,
            # "decoded_url": ...}. Per prudenza si accetta anche il caso in
            # cui restituisca direttamente una stringa con l'URL.
            if isinstance(res, dict) and res.get("status") and res.get("decoded_url"):
                decoded_url = res["decoded_url"]
            elif isinstance(res, str) and res.startswith("http"):
                decoded_url = res
        except Exception:
            # Qualunque errore della libreria viene ignorato: si passa al livello 2.
            pass

        # Successo solo se l'URL ottenuto non è più un indirizzo di Google News.
        if decoded_url and "news.google.com" not in decoded_url:
            return decoded_url

        # Livello 2: inseguimento dei reindirizzamenti HTTP (max 2 tentativi).
        max_retries = 2
        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.get(
                    raw_url,
                    allow_redirects=True,  # segue automaticamente i reindirizzamenti
                    timeout=REQUEST_TIMEOUT_SECONDS,
                    headers={"User-Agent": HTTP_USER_AGENT},
                )
                # resp.url è l'indirizzo finale, dopo tutti i reindirizzamenti.
                if resp.status_code == 200 and resp.url and "news.google.com" not in resp.url:
                    print(f"[INFO] [generalist] URL Google News decodificato tramite fallback HTTP redirect: {resp.url}")
                    return resp.url
                # Risposta ricevuta ma ancora su Google News: riprovare non serve.
                break
            except requests.exceptions.RequestException as exc:
                # Errore di rete (timeout, connessione rifiutata...): si riprova una volta.
                if attempt < max_retries:
                    print(f"[ATTENZIONE] [generalist] Tentativo {attempt}/{max_retries} per HTTP redirect su '{raw_url}' fallito ({exc}). Retry in 1s...")
                    time.sleep(1)
                else:
                    print(f"[ATTENZIONE] [generalist] Impossibile decodificare URL Google News '{raw_url}' via HTTP redirect dopo {max_retries} tentativi: {exc}")
                    return raw_url

        # Passo 3: entrambi i livelli falliti -> si conserva il link di Google News.
        print(f"[ATTENZIONE] [generalist] Impossibile decodificare URL Google News '{raw_url}': sia decoder sia HTTP redirect hanno restituito link Google News")

    return raw_url


def _extract_source_name(
    entry: dict,
    resolved_url: str | None = None,
    targeted_sources_map: dict[str, str] | None = None
) -> str:
    """Ricava il nome della testata che ha pubblicato un articolo trovato su Google News.

    Nel complesso
    -------------
    Per il canale mirato la testata è nota in partenza (è quella del feed
    letto). Per il canale generalista, invece, tutti gli articoli arrivano
    "da Google News" e la testata reale va ricostruita. La funzione prova
    cinque strategie in ordine di affidabilità e si ferma alla prima che
    produce un risultato.

    Passo per passo
    ---------------
    1. Tag ``<source>`` del feed: Google News indica per ogni articolo la
       testata di provenienza (es. "La Repubblica"). È l'informazione più
       affidabile e, in pratica, quella usata nella grande maggioranza dei
       casi.
    2. Confronto con il canale mirato: se lo stesso articolo (stesso URL
       reale o stesso titolo) è stato appena letto anche da un feed mirato,
       si riusa il nome di quella fonte (es. "ansa_salute"). La mappa di
       confronto è costruita in ``run_acquisition.py`` prima di interrogare
       Google News.
    3. Dominio dell'URL reale: se l'URL è stato decodificato, se ne prende il
       nome di dominio senza "www." (es. "repubblica.it").
    4. Suffisso del titolo: Google News scrive spesso i titoli nella forma
       "Titolo dell'articolo - Nome testata"; si prende l'ultima parte dopo
       un trattino circondato da spazi, purché abbia una lunghezza plausibile
       (2-60 caratteri), non coincida con l'intero titolo e non sia un numero.
    5. Riserva finale: il valore generico "google_news", che indica che la
       testata non è stata individuata.

    Args:
        entry: elemento del feed (un articolo) come restituito da feedparser.
        resolved_url: URL reale dell'articolo, se la decodifica è riuscita.
        targeted_sources_map: dizionario {URL o titolo in minuscolo -> fonte}
            costruito dagli articoli del canale mirato.

    Returns:
        Il nome della testata (mai vuoto).
    """
    # 1. Tag <source> del feed. feedparser può restituirlo come dizionario o
    #    come oggetto con attributi: si gestiscono entrambi i casi.
    source_obj = entry.get("source") if isinstance(entry, dict) else getattr(entry, "source", None)
    if isinstance(source_obj, dict) and source_obj.get("title"):
        s_name = source_obj["title"].strip()
        if s_name:
            return s_name
    elif hasattr(source_obj, "title") and getattr(source_obj, "title"):
        s_name = getattr(source_obj, "title").strip()
        if s_name:
            return s_name

    # 2. Confronto con il canale mirato: prima per URL reale, poi per titolo
    #    (confrontato senza spazi iniziali/finali e in minuscolo).
    if targeted_sources_map:
        if resolved_url and resolved_url in targeted_sources_map:
            return targeted_sources_map[resolved_url]
        raw_title = entry.get("title") if isinstance(entry, dict) else getattr(entry, "title", None)
        if raw_title and isinstance(raw_title, str) and raw_title.strip().lower() in targeted_sources_map:
            return targeted_sources_map[raw_title.strip().lower()]

    # 3. Dominio dell'URL reale (es. "https://www.repubblica.it/..." -> "repubblica.it").
    #    Se l'URL è rimasto un link di Google News, il dominio non è significativo.
    if resolved_url:
        try:
            domain = urlparse(resolved_url).netloc.lower()
            if domain:
                domain = domain.removeprefix("www.").strip()
                if domain and domain != "news.google.com":
                    return domain
        except Exception as exc:
            print(f"[ATTENZIONE] [generalist] Impossibile estrarre il dominio dall'URL '{resolved_url}': {exc}")

    # 4. Suffisso del titolo ("Titolo articolo - Nome testata").
    #    Il titolo viene diviso in corrispondenza di un trattino (-, – o —)
    #    preceduto e seguito da spazi; l'ultima parte è la candidata testata.
    title = entry.get("title") if isinstance(entry, dict) else getattr(entry, "title", None)
    if title and isinstance(title, str):
        parts = re.split(r"\s+[\-\–\—]\s+", title)
        if len(parts) > 1:
            candidate = parts[-1].strip()
            # Controlli di plausibilità: 2-60 caratteri, diversa dal titolo intero, non solo cifre.
            if candidate and 2 <= len(candidate) <= 60 and candidate.lower() != title.lower() and not candidate.isdigit():
                return candidate

    # 5. Nessuna strategia ha funzionato.
    return "google_news"


def fetch_generalist_articles(
    queries: list[str] | None = None,
    targeted_sources_map: dict[str, str] | None = None
) -> list[dict]:
    """Interroga Google News per ogni query e restituisce gli articoli trovati.

    Nel complesso
    -------------
    È la funzione pubblica del modulo, chiamata da ``run_acquisition.py``.
    Per ciascuna query costruisce il feed di ricerca, lo legge e trasforma
    ogni articolo in un dizionario con i metadati necessari alle fasi
    successive della pipeline. Una query che fallisce non blocca le altre.

    Passo per passo
    ---------------
    1. Se non vengono passate query, usa quelle di ``config.GENERALIST_QUERIES``.
    2. Per ogni query:
       a. codifica la query per l'URL (es. spazi -> "+") e la inserisce nel
          template di Google News;
       b. legge il feed con ``_parse_generalist_feed``; se non contiene
          articoli registra un avviso e passa alla query successiva;
       c. per ogni articolo del feed:
          - converte la data di pubblicazione in un ``datetime`` in UTC
            (feedparser la fornisce già normalizzata in UTC); se manca resta
            None, e il filtro di attualità tratterà l'articolo in modo
            conservativo (Cap. 4.2);
          - ricava l'URL reale con ``_resolve_article_url``;
          - ricava la testata con ``_extract_source_name``;
          - ripulisce il riassunto RSS con ``clean_rss_summary`` (rimozione
            dei tag HTML; il riassunto viene scartato se ripete solo il
            titolo, come accade spesso con Google News);
          - aggiunge l'articolo alla lista dei risultati.
    3. Registra nei log quanti articoli sono stati raccolti e restituisce la lista.

    Uno stesso articolo può comparire in più query: i duplicati non vengono
    rimossi qui ma nella fase di pre-filtraggio (Cap. 4.2).

    Args:
        queries: elenco di query testuali (facoltativo).
        targeted_sources_map: mappa {URL o titolo -> fonte} del canale mirato,
            usata per attribuire la testata (vedi ``_extract_source_name``).

    Returns:
        Lista di dizionari con chiavi: url, source, title, published_at,
        acquisition_mode ("generalista"), rss_summary.
    """
    # Passo 1: query di default.
    queries = queries or GENERALIST_QUERIES
    articles = []

    # Passo 2: una ricerca per ogni query.
    for query in queries:
        # 2a. Costruzione dell'indirizzo del feed.
        feed_url = GOOGLE_NEWS_RSS_TEMPLATE.format(query=quote_plus(query))
        # 2b. Lettura del feed.
        parsed = _parse_generalist_feed(feed_url)
        if not parsed.entries:
            print(f"[ATTENZIONE] [generalist] Impossibile leggere risultati per la query '{query}': "
                  f"{parsed.get('bozo_exception')}")
            continue

        # 2c. Elaborazione di ciascun articolo del feed.
        for entry in parsed.entries:
            # Data di pubblicazione: published_parsed è una tupla (anno, mese,
            # giorno, ore, minuti, secondi, ...) già in UTC.
            published_at = None
            if getattr(entry, "published_parsed", None):
                published_at = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)

            # URL reale e testata di provenienza.
            raw_link = entry.get("link")
            resolved_url = _resolve_article_url(raw_link)
            source_name = _extract_source_name(entry, resolved_url, targeted_sources_map)

            articles.append({
                "url": resolved_url,
                "source": source_name,  # nome della testata (es. "La Repubblica", "linkiesta.it")
                "title": entry.get("title"),
                "published_at": published_at,
                "acquisition_mode": "generalista",  # canale di provenienza
                # Riassunto del feed ripulito: riserva per l'estrazione del testo (Cap. 4.3).
                "rss_summary": clean_rss_summary(entry.get("summary"), entry.get("title")),
            })

    # Passo 3: riepilogo nei log.
    if not articles:
        print("[ATTENZIONE] [generalist] Nessun articolo recuperato da Google News RSS")
    else:
        print(f"[INFO] [generalist] Acquisizione generalista completata: {len(articles)} articoli estratti")

    return articles
