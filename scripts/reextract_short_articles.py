"""Script per ri-estrarre il testo completo tramite Jina AI Reader per gli articoli storici brevi (es. Linkiesta)."""
import sys
from sqlalchemy import func

sys.path.append('.')

from src.db.connection import get_session
from src.db.models import Article
from src.parsing.extractor import extract_article_text

def main():
    print("[INFO] Avvio ri-estrazione testo completo per articoli storici nel DB Supabase...")
    try:
        session = get_session()

        # Seleziona gli articoli che hanno raw_text corto (<= 500 car.)
        short_articles = (
            session.query(Article)
            .filter((Article.raw_text.is_(None)) | (Article.raw_text == '') | (func.length(Article.raw_text) <= 500))
            .limit(50)  # Limite per run per rimanere nei tempi
            .all()
        )

        print(f"[INFO] Trovati {len(short_articles)} articoli con testo corto nel database Supabase.")

        updated_count = 0
        for art in short_articles:
            print(f"[INFO] Ri-estrazione per articolo ID {art.id}: {art.url[:70]}...")
            new_text = extract_article_text(art.url)
            if new_text and len(new_text.strip()) > 500:
                art.raw_text = new_text
                session.commit()
                updated_count += 1
                print(f" -> [OK] Testo aggiornato ({len(new_text)} caratteri) per ID {art.id}")
            else:
                print(f" -> [SKIP] Impossibile recuperare testo completo per ID {art.id}")

        print(f"\n[INFO] Ri-estrazione completata: {updated_count}/{len(short_articles)} articoli aggiornati con testo completo nel DB.")

    except Exception as exc:
        print(f"[ERRORE] Errore durante la ri-estrazione nel DB: {exc}")

if __name__ == "__main__":
    main()
