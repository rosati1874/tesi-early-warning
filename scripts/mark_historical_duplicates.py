"""Script una tantum per la marcatura dei duplicati storici (RF-08, RF-09).

Identifica le coppie di articoli duplicate cross-canale acquisite prima dei fix di prefilter.py,
marcando un solo elemento della coppia con status='duplicate' secondo i seguenti criteri:
1. Se uno dei due ha is_epidemic_signal NOT NULL e l'altro no, marca come 'duplicate' quello NON classificato.
2. Se entrambi sono già classificati (o entrambi non classificati), marca come 'duplicate' quello con first_seen_at più recente.
3. Il canale di acquisizione non viene mai usato come criterio di scelta.

Uso:
  python scripts/mark_historical_duplicates.py           (Dry-run anteprima)
  python scripts/mark_historical_duplicates.py --execute (Esecuzione reale UPDATE sul DB)
"""
import argparse
import sys
from sqlalchemy import text

sys.path.append(".")
from src.db.connection import get_session
from src.db.models import Article


def find_and_mark_duplicates(dry_run: bool = True):
    session = get_session()

    query = text("""
        SELECT a1.id AS id_mirato, a2.id AS id_generalista
        FROM articles a1
        JOIN articles a2
          ON lower(trim(a1.title)) = lower(trim(a2.title))
         AND a1.acquisition_mode = 'mirato'
         AND a2.acquisition_mode = 'generalista'
         AND a1.id <> a2.id
         AND a1.status = 'active' AND a2.status = 'active';
    """)

    pairs = session.execute(query).fetchall()

    print(f"=== ANTEPRIMA MARCATURA DUPLICATI STORICI (Coppie trovate: {len(pairs)}, dry_run={dry_run}) ===\n")

    processed_pairs = set()
    updates = []

    for row in pairs:
        id_mirato, id_generalista = row.id_mirato, row.id_generalista
        pair_key = tuple(sorted([id_mirato, id_generalista]))
        if pair_key in processed_pairs:
            continue
        processed_pairs.add(pair_key)

        art1 = session.get(Article, id_mirato)
        art2 = session.get(Article, id_generalista)

        if not art1 or not art2:
            continue

        # Idempotenza: salta se uno dei due ha già status='duplicate'
        if art1.status == "duplicate" or art2.status == "duplicate":
            continue

        # Decisione basata sui tre criteri
        kept = None
        dup = None
        criterion = ""

        # Criterio 1: Uno classificato (is_epidemic_signal NOT NULL) e l'altro no
        art1_classified = art1.is_epidemic_signal is not None
        art2_classified = art2.is_epidemic_signal is not None

        if art1_classified and not art2_classified:
            kept, dup = art1, art2
            criterion = "Criterio 1 (Priorità a risorsa già classificata da LLM)"
        elif art2_classified and not art1_classified:
            kept, dup = art2, art1
            criterion = "Criterio 1 (Priorità a risorsa già classificata da LLM)"
        else:
            # Criterio 2: Entrambi classificati o entrambi non classificati -> Mantiene il più anziano (first_seen_at minore)
            if art1.first_seen_at <= art2.first_seen_at:
                kept, dup = art1, art2
            else:
                kept, dup = art2, art1
            criterion = "Criterio 2 (Mantenuta prima acquisizione per first_seen_at)"

        updates.append((kept, dup, criterion))

        print(f"Coppia #{len(updates)}:")
        print(f"  [MANTENUTO ATTIVO] ID: {kept.id} | Fonte: {kept.source} | Canale: {kept.acquisition_mode} | Classificato: {kept.is_epidemic_signal} | Data: {kept.first_seen_at}")
        print(f"                     URL: {kept.url}")
        print(f"  [MARCATO DUPLICATO] ID: {dup.id} | Fonte: {dup.source} | Canale: {dup.acquisition_mode} | Classificato: {dup.is_epidemic_signal} | Data: {dup.first_seen_at}")
        print(f"                      URL: {dup.url}")
        print(f"  [CRITERIO] {criterion}\n")

    print(f"Totale coppie distinte elaborate: {len(updates)}")

    if not dry_run:
        for kept, dup, _ in updates:
            dup.status = "duplicate"
        session.commit()
        print("\nMODIFICHE SALVATE SUL DATABASE SUPABASE CON SUCCESSO!")
    else:
        print("\nMODALITÀ DRY-RUN: Nessuna modifica è stata effettuata sul database.")

    session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Marca i duplicati storici nel database.")
    parser.add_argument("--execute", action="store_true", help="Esegue le modifiche reali sul DB (senza questa flag resta in dry-run)")
    args = parser.parse_args()

    find_and_mark_duplicates(dry_run=not args.execute)
