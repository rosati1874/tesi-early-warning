"""Entry point della pipeline di acquisizione (RF-01 -> RF-05).

acquisizione (mirata + generalista) -> parsing -> filtro keyword ->
classificazione LLM -> storage.

Richiamato dal workflow .github/workflows/acquisition.yml.
"""
from datetime import datetime, timezone

from src.db.connection import get_session
from src.db.models import Article
from src.acquisition.targeted import fetch_targeted_articles
from src.acquisition.generalist import fetch_generalist_articles
from src.parsing.extractor import extract_article_text
from src.filtering.keywords import passes_keyword_filter
from src.classification.llm_classifier import classify
from src.config import ENABLE_LLM_CLASSIFICATION, MAX_LLM_CLASSIFICATIONS_PER_RUN


def run() -> None:
    print("[INFO] [pipeline] Avvio della pipeline di acquisizione...")
    try:
        session = get_session()
    except Exception as exc:
        msg = f"[ERRORE GRAVE] [pipeline] Impossibile inizializzare la sessione del database: {exc}"
        print(msg)
        raise RuntimeError(msg) from exc

    targeted = fetch_targeted_articles()
    generalist = fetch_generalist_articles()
    raw_articles = targeted + generalist
    print(f"[INFO] [pipeline] Acquisizione completata: {len(raw_articles)} articoli grezzi trovati ({len(targeted)} mirati, {len(generalist)} generalisti)")

    if not raw_articles:
        msg = "[ERRORE GRAVE] [pipeline] Nessun articolo acquisito da alcuna fonte. Impossibile proseguire la pipeline."
        print(msg)
        raise RuntimeError(msg)

    new_count = 0
    for raw in raw_articles:
        if not raw.get("url"):
            continue

        try:
            # RF-03: evita di rielaborare articoli già acquisiti in precedenza
            existing = session.query(Article).filter_by(url=raw["url"]).first()
            if existing:
                continue

            text = extract_article_text(raw["url"])
            if not text:
                # riserva: usa il riassunto già incluso nel feed RSS, quando
                # la pagina completa non è raggiungibile (es. blocco anti-bot,
                # osservato con Linkiesta). Meno ricco del testo completo, ma
                # evita di perdere del tutto l'articolo.
                text = raw.get("rss_summary")
                if text:
                    print(f"[INFO] [pipeline] Utilizzato rss_summary per l'articolo: {raw['url']}")

            if not text:
                print(f"[ATTENZIONE] [pipeline] Impossibile recuperare sia il testo che l'rss_summary per: {raw['url']}")
                continue

            passed_filter = passes_keyword_filter(text, raw.get("title", ""))
            if not passed_filter:
                print(f"[INFO] [pipeline] Articolo scartato dal filtro keyword: '{raw.get('title')}'")

            # Salva l'articolo nel database con is_epidemic_signal=None (in attesa di classificazione)
            article = Article(
                url=raw["url"],
                source=raw["source"],
                acquisition_mode=raw["acquisition_mode"],
                title=raw.get("title"),
                published_at=raw.get("published_at"),
                first_seen_at=datetime.now(timezone.utc),
                raw_text=text,
                passed_keyword_filter=passed_filter,
                is_epidemic_signal=None,
                llm_confidence=None,
                llm_disease=None,
                llm_location=None,
                llm_justification=None,
                llm_model=None,
            )
            session.add(article)
            session.commit()
            new_count += 1
        except Exception as exc:
            msg = f"[ERRORE GRAVE] [pipeline] Errore critico durante l'elaborazione/salvataggio dell'articolo '{raw.get('url')}': {exc}"
            print(msg)
            session.rollback()
            raise RuntimeError(msg) from exc

    print(f"[INFO] [pipeline] {new_count} nuovi articoli salvati nel database")

    # Fase di classificazione LLM (priorità agli articoli in arretrato/più vecchi)
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
            )
            .order_by(Article.first_seen_at.asc())  # Vengono classificati prima gli articoli più vecchi (arretrato)
            .limit(MAX_LLM_CLASSIFICATIONS_PER_RUN)
            .all()
        )

        if not pending_articles:
            print("[INFO] [pipeline] Nessun articolo in attesa di classificazione LLM")
        else:
            print(f"[INFO] [pipeline] Trovati {len(pending_articles)} articoli in attesa di classificazione (limite max per run: {MAX_LLM_CLASSIFICATIONS_PER_RUN})")
            classified_count = 0
            for art in pending_articles:
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
                except Exception as exc:
                    print(f"[ATTENZIONE] [pipeline] Errore nella classificazione dell'articolo ID {art.id}: {exc}")
                    session.rollback()

            print(f"[INFO] [pipeline] Classificazione LLM completata: {classified_count}/{len(pending_articles)} articoli classificati")

    print("[INFO] [pipeline] Pipeline di acquisizione completata con successo")


if __name__ == "__main__":
    run()
