"""Prompt per la classificazione semantica (RF-05).

Criterio esplicito e documentato (richiesto da RF-05): il modello deve
distinguere un segnale epidemico reale da un uso figurato/non sanitario
della terminologia, e produrre un output JSON strutturato.
"""

PROMPT_VERSION = "v2"

CLASSIFICATION_PROMPT_TEMPLATE = """Sei un analista di epidemic intelligence per un sistema di allerta precoce
di sanità pubblica in Italia. Leggi l'articolo e stabilisci se contiene un
SEGNALE EPIDEMICO, cioè la notizia di un evento sanitario in corso o recente
che un servizio di sorveglianza vorrebbe verificare.

È UN SEGNALE (is_epidemic_signal = true) se l'articolo riporta almeno uno
di questi fatti, avvenuti di recente:
- casi umani, sospetti o confermati, di una malattia infettiva (basta anche
  un solo caso se la malattia è grave, rara o insolita per quel luogo);
- un focolaio, un gruppo di casi collegati o un aumento dei casi rispetto
  al solito;
- ricoveri o decessi anomali per una causa che si sospetta infettiva;
- focolai di malattie infettive negli animali, in allevamenti o nella fauna
  selvatica, soprattutto se trasmissibili all'uomo o accompagnati da misure
  come abbattimenti o zone di restrizione;
- alimenti o acqua contaminati da agenti infettivi con persone esposte o
  ammalate;
- misure sanitarie adottate in risposta a un evento concreto (quarantene,
  chiusure, disinfestazioni straordinarie, ordinanze).
Gli eventi avvenuti all'estero contano quanto quelli in Italia.
Un aggiornamento su un evento ancora in corso, con nuovi casi o nuove aree
coinvolte, è un segnale.

NON È UN SEGNALE (is_epidemic_signal = false) se l'articolo:
- dà solo informazioni generali su una malattia (sintomi, trasmissione,
  prevenzione, consigli) senza riferire casi nuovi;
- parla di ricerca, vaccini, farmaci, campagne vaccinali, politica o
  organizzazione sanitaria senza un evento concreto;
- ricostruisce eventi passati e conclusi (anniversari, bilanci annuali,
  processi, inchieste);
- usa parole come "virus", "epidemia", "contagio" o "focolaio" in senso
  figurato (informatica, economia, politica, incendi);
- riguarda problemi di salute non infettivi (tumori, malattie
  cardiovascolari, intossicazioni da sostanze chimiche, incidenti).
Se l'articolo tratta più argomenti, decidi in base al fatto principale.

REGOLE PER I CAMPI:
- "confidence": quanto sei sicuro della tua decisione, sia che sia true sia
  che sia false. Usa 0.9-1.0 se il caso è chiaro, 0.7-0.89 se hai qualche
  dubbio, 0.5-0.69 se l'articolo è ambiguo.
- "disease": nome comune della malattia in italiano, con la prima lettera
  maiuscola (es. "Covid-19", "Ebola", "Peste suina africana", "Influenza
  aviaria", "Febbre Dengue"). Non usare tutto maiuscolo o tutto minuscolo.
  Se la malattia non è identificabile, usa null.
- "location": il luogo più preciso in cui si verificano i casi, seguito
  dalla regione o dal Paese (es. "Latina, Lazio" oppure "Kinshasa,
  Repubblica Democratica del Congo"). Se i luoghi sono più d'uno, indica
  il principale. Se non è indicato, usa null.
- "justification": una frase in italiano che citi il fatto decisivo (es.
  "Riporta due nuovi casi confermati di West Nile in provincia di Latina").

Rispondi ESCLUSIVAMENTE con un oggetto JSON valido, senza testo aggiuntivo:

{{
  "is_epidemic_signal": true/false,
  "confidence": <numero tra 0 e 1>,
  "disease": "<nome della malattia o null>",
  "location": "<luogo o null>",
  "justification": "<una frase>"
}}

Titolo articolo:
{title}

Testo articolo:
{text}
"""


def build_classification_prompt(title: str, text: str) -> str:
    # Il testo viene troncato a 3000 caratteri per restare entro limiti di contesto/quota
    # ed accelerare i tempi di elaborazione.
    truncated_text = (text or "")[:3000]
    return CLASSIFICATION_PROMPT_TEMPLATE.format(title=title or "", text=truncated_text)

