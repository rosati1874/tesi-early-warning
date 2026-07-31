"""Prompt per la classificazione semantica (RF-05).

Criterio esplicito e documentato (richiesto da RF-05): il modello deve
distinguere un segnale epidemico reale da un uso figurato/non sanitario
della terminologia, e produrre un output JSON strutturato.
"""

CLASSIFICATION_PROMPT_TEMPLATE = """Sei un analista di sorveglianza epidemiologica.
Il tuo compito è valutare se il seguente articolo giornalistico in italiano
descrive un possibile evento sanitario/epidemico reale (es. un focolaio,
un'epidemia, un caso di malattia infettiva rilevante), oppure se si tratta
di un contenuto non pertinente (cronaca generica, uso figurato di termini
come "focolaio" o "epidemia", argomento non sanitario, ecc.).

REGOLE PER IL CAMPO "disease":
- Deve essere in un formato standardizzato con prima lettera maiuscola ed il nome comune della malattia in italiano (es. "Covid-19", "Ebola", "Peste suina africana", "Hantavirus", "Influenza aviaria", "Febbre Dengue").
- Evita varianti in tutto maiuscolo (es. NON "COVID19", NON "EBOLA") o tutto minuscolo (es. NON "peste suina").
- Se la malattia non è identificabile con certezza, imposta il valore a null.

Rispondi ESCLUSIVAMENTE con un oggetto JSON valido, senza testo aggiuntivo,
con questa struttura esatta:

{{
  "is_epidemic_signal": true/false,
  "confidence": <numero tra 0 e 1>,
  "disease": "<nome della malattia/patogeno in formato standardizzato es. 'Covid-19', 'Peste suina africana', 'Ebola', altrimenti null>",
  "location": "<luogo geografico coinvolto se identificabile, altrimenti null>",
  "justification": "<breve motivazione in una frase>"
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
