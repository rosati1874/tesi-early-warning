"""Script di analisi e conteggio fonti sul campione West Nile (135 articoli).

Applica il parsing livello 4 del titolo agli articoli storici con source='google_news'
ed effettua la normalizzazione tramite `normalize_source_name()`.
"""
import sys
from collections import Counter
from sqlalchemy import or_

sys.path.append(".")
from src.db.connection import get_session
from src.db.models import Article
from src.acquisition.generalist import _extract_source_name
from src.filtering.source_normalizer import normalize_source_name


def analyze_west_nile_sample():
    session = get_session()

    # 1. Ispezione degli 8 articoli storici specificati (id: 96, 98, 132, 133, 235, 236, 675, 680)
    target_ids = [96, 98, 132, 133, 235, 236, 675, 680]
    historical_arts = session.query(Article).filter(Article.id.in_(target_ids)).all()

    print("=== PARSING RETROATTIVO LIVELLO 4 (TITOLO) SUI 8 ARTICOLI STORICI GOOGLE_NEWS ===")
    resolved_historical = {}
    for art in historical_arts:
        parsed_source = _extract_source_name({"title": art.title})
        canonical_source = normalize_source_name(parsed_source)
        resolved_historical[art.id] = (art.title, parsed_source, canonical_source)
        print(f"ID {art.id}:")
        print(f"  Titolo: '{art.title}'")
        print(f"  Fonte Estratta (Livello 4): '{parsed_source}' -> Canonica: '{canonical_source}'\n")

    # 2. Selezione dell'intero campione dei 135 articoli West Nile
    query = session.query(Article).filter(
        Article.is_epidemic_signal.is_(True),
        or_(
            Article.llm_disease.ilike("%west nile%"),
            Article.llm_disease.ilike("%nilo%"),
        )
    )
    sample_articles = query.all()

    print(f"=== ANALISI CAMPIONE WEST NILE ({len(sample_articles)} articoli trovati) ===\n")

    raw_sources_counter = Counter()
    canonical_sources_counter = Counter()

    for art in sample_articles:
        raw_src = art.source
        raw_sources_counter[raw_src] += 1

        # Se il dato grezzo è 'google_news', tenta il recupero dal titolo via Livello 4
        effective_src = raw_src
        if raw_src == "google_news" and art.title:
            extracted_from_title = _extract_source_name({"title": art.title})
            if extracted_from_title != "google_news":
                effective_src = extracted_from_title

        canon_src = normalize_source_name(effective_src)
        canonical_sources_counter[canon_src] += 1

    distinct_raw_count = len(raw_sources_counter)
    distinct_canonical_count = len(canonical_sources_counter)

    print(f"Fonti distinte GREZZE (prima della normalizzazione): {distinct_raw_count}")
    print(f"Fonti distinte CANONICHE (dopo normalizzazione): {distinct_canonical_count}\n")

    print("=== TOP 15 FONTI CANONICHE NEL CAMPIONE ===")
    for i, (source, count) in enumerate(canonical_sources_counter.most_common(15), 1):
        print(f"{i:2d}. {source:35s}: {count} articoli")

    session.close()


if __name__ == "__main__":
    analyze_west_nile_sample()
