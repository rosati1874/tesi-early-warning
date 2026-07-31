"""Script per testare live la risposta del modello Gemini sulla standardizzazione del campo disease."""
import os
import sys

sys.path.append(".")

from src.classification.llm_classifier import classify

def run_live_test():
    print("\n==================================================")
    print("=== TEST LIVE CLASSIFICAZIONE GEMINI: DISEASE STANDARDIZZATO ===")
    print("==================================================")

    test_articles = [
        {
            "id": 1,
            "title": "Nuova variante covid-19 e sars-cov-2 isolata nel laboratorio",
            "text": "Gli scienziati hanno identificato una nuova sotto-variante del virus covid-19 e sars-cov-2 che presenta mutazioni sulla proteina spike. I casi di covid si mantengono bassi.",
            "raw_disease_in_text": "covid-19 / sars-cov-2 (minuscolo)"
        },
        {
            "id": 2,
            "title": "ALLARME PESTE SUINA AFRICANA NEGLI ALLEVAMENTI DEL PAVESE",
            "text": "IL MINISTERO DELLA SALUTE HA DISPOSTO L'ABBATTIMENTO DEI SUINI COLPITI DA PESTE SUINA AFRICANA NEI FOCOLAI LOMBARDI PER EVITARE LA DIFFUSIONE DELLA PESTE SUINA.",
            "raw_disease_in_text": "PESTE SUINA AFRICANA (tutto maiuscolo)"
        },
        {
            "id": 3,
            "title": "Casi di febbre dengue e virus dengue registrati in Veneto",
            "text": "Le autorità sanitarie hanno confermato tre casi di febbre dengue trasmessi da zanzare tigre. Si raccomanda prudenza per il virus della dengue.",
            "raw_disease_in_text": "febbre dengue (minuscolo)"
        },
        {
            "id": 4,
            "title": "Epidemia di ebola e virus ebola in Congo",
            "text": "L'OMS ha inviato una missione speciale per contenere l'epidemia di ebola scoppiata nella provincia orientale. I campioni hanno confermato l'infezione da virus ebola.",
            "raw_disease_in_text": "ebola (minuscolo)"
        }
    ]

    for art in test_articles:
        print(f"\n[TEST ARTICOLO #{art['id']}] Formato nel testo originale: {art['raw_disease_in_text']}")
        print(f"  Titolo: '{art['title']}'")
        res = classify(art["title"], art["text"])
        print(f"  --> Risposta LLM Gemini:")
        print(f"      - is_epidemic_signal : {res.get('is_epidemic_signal')}")
        print(f"      - disease estratto    : '{res.get('disease')}'")
        print(f"      - location estratta   : '{res.get('location')}'")
        print(f"      - modello usato       : {res.get('llm_model')}")
        print(f"      - motivazione         : {res.get('justification')}")

    print("\n==================================================\n")

if __name__ == "__main__":
    run_live_test()
