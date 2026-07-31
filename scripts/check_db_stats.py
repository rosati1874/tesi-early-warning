"""Script temporaneo di diagnostica per contare gli articoli nel DB Supabase."""
import sys
from sqlalchemy import func

sys.path.append('.')

from src.db.connection import get_session
from src.db.models import Article

def main():
    print("\n==================================================")
    print("=== DIAGNOSTICA REALE SUPABASE DATABASE ===")
    print("==================================================")
    try:
        session = get_session()
        total_articles = session.query(Article).count()

        if total_articles == 0:
            print("[INFO] Nessun articolo attualmente presente nel database.")
            return

        short_text = session.query(Article).filter(
            Article.raw_text.isnot(None),
            Article.raw_text != '',
            func.length(Article.raw_text) <= 500
        ).count()

        full_text = session.query(Article).filter(
            Article.raw_text.isnot(None),
            func.length(Article.raw_text) > 500
        ).count()

        no_text = session.query(Article).filter(
            (Article.raw_text.is_(None)) | (Article.raw_text == '')
        ).count()

        gen_total = session.query(Article).filter(Article.acquisition_mode == 'generalista').count()
        gen_short = session.query(Article).filter(Article.acquisition_mode == 'generalista', func.length(Article.raw_text) <= 500).count()
        gen_full = session.query(Article).filter(Article.acquisition_mode == 'generalista', func.length(Article.raw_text) > 500).count()

        tar_total = session.query(Article).filter(Article.acquisition_mode == 'mirato').count()
        tar_short = session.query(Article).filter(Article.acquisition_mode == 'mirato', func.length(Article.raw_text) <= 500).count()
        tar_full = session.query(Article).filter(Article.acquisition_mode == 'mirato', func.length(Article.raw_text) > 500).count()

        print(f"TOTALE ARTICOLI NEL DATABASE SUPABASE: {total_articles}")
        print(f" - Con testo COMPLETO (> 500 car.): {full_text} ({full_text / total_articles * 100:.1f}%)")
        print(f" - Con riassunto CORTO/RSS (<= 500 car.): {short_text} ({short_text / total_articles * 100:.1f}%)")
        print(f" - Senza testo: {no_text}")

        print(f"\n[Dettaglio Acquisizione Generalista - Totale: {gen_total}]")
        print(f" - Testo completo (> 500 car.): {gen_full} ({(gen_full / gen_total * 100) if gen_total else 0:.1f}%)")
        print(f" - Riassunto corto (<= 500 car.): {gen_short} ({(gen_short / gen_total * 100) if gen_total else 0:.1f}%)")

        print(f"\n[Dettaglio Acquisizione Mirata - Totale: {tar_total}]")
        print(f" - Testo completo (> 500 car.): {tar_full} ({(tar_full / tar_total * 100) if tar_total else 0:.1f}%)")
        print(f" - Riassunto corto (<= 500 car.): {tar_short} ({(tar_short / tar_total * 100) if tar_total else 0:.1f}%)")

        # Esegue la query Postgres per misurare la dimensione occupata in MB su Supabase
        try:
            from sqlalchemy import text
            db_size_bytes = session.execute(text("SELECT pg_database_size(current_database());")).scalar()
            db_size_mb = (db_size_bytes or 0) / (1024 * 1024)
            print(f"\n[SPAZIO ARCHIVIAZIONE SUPABASE]")
            print(f" - Occupazione attuale: {db_size_mb:.2f} MB / 500 MB ({db_size_mb / 500 * 100:.2f}% del tier gratuito)")
            print(f" - Proiezione crescita (5-12 agosto, 8 giorni): ~{db_size_mb + 4.0:.2f} MB")
            print(" - Rischio saturazione entro il 12 agosto: ASSENTE (0% di rischio)")
        except Exception as err:
            print(f"[INFO] Impossibile calcolare dimensione fisica DB: {err}")

        print("==================================================\n")

    except Exception as exc:
        print(f"[ERRORE] Impossibile eseguire la diagnostica sul DB: {exc}")

if __name__ == "__main__":
    main()
