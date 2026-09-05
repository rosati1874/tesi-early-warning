"""Entry point della pipeline di acquisizione (RF-01 -> RF-05).

acquisizione (mirata + generalista) -> parsing -> filtro keyword ->
classificazione LLM -> storage.

Richiamato dal workflow .github/workflows/acquisition.yml.
"""
from datetime import datetime, timezone
from sqlalchemy import func

from src.db.connection import get_session
from src.db.models import Article
from src.acquisition.targeted import fetch_targeted_articles
from src.acquisition.generalist import fetch_generalist_articles
from src.parsing.extractor import extract_article_text
from src.filtering.prefilter import (
    filter_by_freshness,
    deduplicate_in_batch,
    is_duplicate_in_db,
)
from src.filtering.keywords import passes_keyword_filter
from src.classification.llm_classifier import classify
from src.notifications.webhook import notify_new_signals
from src.config import (
    ENABLE_LLM_CLASSIFICATION,
    MAX_ARTICLE_AGE_DAYS,
    MAX_LLM_CLASSIFICATIONS_PER_RUN,
)


def run() -> None:
    print("[INFO] [pipeline] Avvio della pipeline di acquisizione...")
    try:
        session = get_session()
    except Exception as exc:
        msg = f"[ERRORE GRAVE] [pipeline] Impossibile inizializzare la sessione del database: {exc}"
        print(msg)
        raise RuntimeError(msg) from exc

    # -------------------------------------------------------------------------
    # FASE 1: ACQUISIZIONE ARTICOLI GREZZI (FEED MIRATI + QUERY GENERALISTE)
    # -------------------------------------------------------------------------
    targeted = fetch_targeted_articles()

    # Mappa di cross-referenziazione per associare le fonti del canale mirato ai generalisti
    targeted_sources_map = {}
    for art in targeted:
        if art.get("url") and art.get("source"):
            targeted_sources_map[art["url"]] = art["source"]
        if art.get("title") and art.get("source"):
            targeted_sources_map[art["title"].strip().lower()] = art["source"]

    generalist = fetch_generalist_articles(targeted_sources_map=targeted_sources_map)
    raw_articles = targeted + generalist
    print(f"[INFO] [pipeline] Acquisizione completata: {len(raw_articles)} articoli grezzi trovati ({len(targeted)} mirati, {len(generalist)} generalisti)")

    if not raw_articles:
        msg = "[ERRORE GRAVE] [pipeline] Nessun articolo acquisito da alcuna fonte. Impossibile proseguire la pipeline."
        print(msg)
        raise RuntimeError(msg)

    # -------------------------------------------------------------------------
    # FASE 2: FILTRO DI FRESCHEZZA (MAX_ARTICLE_AGE_DAYS, DEFAULT 30 GIORNI) (RF-09)
    # -------------------------------------------------------------------------
    fresh_articles = filter_by_freshness(raw_articles, MAX_ARTICLE_AGE_DAYS)

    # -------------------------------------------------------------------------
    # FASE 3: DEDUPLICAZIONE IN-BATCH (URL UNICI NELL'ESECUZIONE CORRENTE) (RF-08)
    # -------------------------------------------------------------------------
    deduped_raw_articles = deduplicate_in_batch(fresh_articles)

    # -------------------------------------------------------------------------
    # FASE 4: ESTRAZIONE TESTO, DEDUPLICAZIONE DB, FILTRO KEYWORD E SALVATAGGIO
    # -------------------------------------------------------------------------
    new_count = 0
    for raw in deduped_raw_articles:
        try:
            # Controllo duplicati nel database (URL esatto o titolo+fonte entro 48 ore)
            if is_duplicate_in_db(session, raw):
                continue

            # Estrazione testo completo (trafilatura -> Jina AI Reader -> BeautifulSoup)
            text = extract_article_text(raw["url"])
            if not text:
                # Riserva: usa il riassunto già incluso nel feed RSS, quando la pagina non è raggiungibile
                text = raw.get("rss_summary")
                if text:
                    print(f"[INFO] [pipeline] Utilizzato rss_summary per l'articolo: {raw['url']}")

            if not text:
                print(f"[INFO] [pipeline] Salvataggio articolo senza corpo/solo metadati: '{raw.get('title')}'")

            # Valutazione filtro keyword (epidemico + veterinario)
            passed_filter = passes_keyword_filter(text or "", raw.get("title", ""))
            if not passed_filter:
                print(f"[INFO] [pipeline] Articolo scartato dal filtro keyword: '{raw.get('title')}'")

            # Salva l'articolo nel database con la traccia minima (titolo, fonte, data, URL)
            article = Article(
                url=raw["url"],
                source=raw["source"],
                acquisition_mode=raw["acquisition_mode"],
                title=raw.get("title"),
                published_at=raw.get("published_at"),
                first_seen_at=datetime.now(timezone.utc),
                raw_text=text,  # Può essere None se privo di corpo/riassunto significativo
                passed_keyword_filter=passed_filter,
                is_epidemic_signal=None,
                llm_confidence=None,
                llm_disease=None,
                llm_location=None,
                llm_justification=None,
                llm_model=None,
                classification_attempts=0,
            )
            session.add(article)
            session.commit()
            new_count += 1
        except Exception as exc:
            print(f"[ATTENZIONE] [pipeline] Errore o duplicato durante il salvataggio dell'articolo '{raw.get('url')}': {exc}")
            session.rollback()

    print(f"[INFO] [pipeline] {new_count} nuovi articoli salvati nel database")

    # -------------------------------------------------------------------------
    # FASE 5: CLASSIFICAZIONE LLM (GEMINI CON FALLBACK E GESTIONE ARRETRATO)
    # -------------------------------------------------------------------------
    newly_classified_signals = []
    if not ENABLE_LLM_CLASSIFICATION:
        print("[INFO] [pipeline] Classificazione LLM disattivata (ENABLE_LLM_CLASSIFICATION=false)")
    elif MAX_LLM_CLASSIFICATIONS_PER_RUN <= 0:
        print(f"[INFO] [pipeline] Limite classificazioni per esecuzione impostato a {MAX_LLM_CLASSIFICATIONS_PER_RUN}, classificazione saltata")
    else:
        pending_articles = (
            session.query(Article)
            .filter(
                Article.passed_keyword_filter.is_(True),
                Article.is_epidemic_signal.is_(None),
                Article.raw_text.isnot(None),  # Classifica solo articoli con corpo/testo effettivo
                func.length(Article.raw_text) > 100,
                Article.classification_attempts < 3,
            )
            .order_by(Article.classification_attempts.asc(), Article.first_seen_at.asc())
            .limit(MAX_LLM_CLASSIFICATIONS_PER_RUN)
            .all()
        )

        if not pending_articles:
            print("[INFO] [pipeline] Nessun articolo in attesa di classificazione LLM")
        else:
            print(f"[INFO] [pipeline] Trovati {len(pending_articles)} articoli in attesa di classificazione (limite max per run: {MAX_LLM_CLASSIFICATIONS_PER_RUN})")
            classified_count = 0
            for art in pending_articles:
                # Incrementa il contatore dei tentativi per evitare che articoli problematici blocchino la coda
                art.classification_attempts = (art.classification_attempts or 0) + 1
                session.commit()

                try:
                    res = classify(art.title or "", art.raw_text or "")
                    if res.get("is_epidemic_signal") is not None:
                        art.is_epidemic_signal = res["is_epidemic_signal"]
                        art.llm_confidence = res.get("confidence")
                        art.llm_disease = res.get("disease")
                        art.llm_location = res.get("location")
                        art.llm_justification = res.get("justification")
                        art.llm_model = res.get("llm_model")
                        session.commit()
                        classified_count += 1

                        if res["is_epidemic_signal"] is True:
                            newly_classified_signals.append(art)
                except Exception as exc:
                    print(f"[ATTENZIONE] [pipeline] Errore nella classificazione dell'articolo ID {art.id} (tentativo {art.classification_attempts}/3): {exc}")
                    session.rollback()

            print(f"[INFO] [pipeline] Classificazione LLM completata: {classified_count}/{len(pending_articles)} articoli classificati")

    # -------------------------------------------------------------------------
    # FASE 6: NOTIFICA WEBHOOK PUB-SUB PER I NUOVI SEGNALI EPIDEMICI IDENTIFICATI
    # -------------------------------------------------------------------------
    if newly_classified_signals:
        try:
            notify_new_signals(session, newly_classified_signals)
        except Exception as exc:
            print(f"[ATTENZIONE] [pipeline] Errore imprevisto durante l'invio delle notifiche webhook: {exc}")

    print("[INFO] [pipeline] Pipeline di acquisizione completata con successo")


if __name__ == "__main__":
    run()
