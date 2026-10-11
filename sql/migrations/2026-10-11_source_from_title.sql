-- ============================================================
-- Migrazione: attribuzione retroattiva della testata dal titolo (2026-10-11)
-- ============================================================
-- GIÀ ESEGUITA sul database di produzione: conservata come riferimento storico.
-- Non è necessaria su un database nuovo.
--
-- Contesto: nelle prime settimane di funzionamento, per una parte degli
-- articoli acquisiti dal canale generalista non era stato possibile
-- decodificare il link di Google News né attribuire la testata, che era
-- stata registrata con il valore generico 'google_news' (368 articoli).
-- La migrazione ricava la testata dalla parte finale del titolo
-- ("Titolo dell'articolo - Nome testata"), con le stesse regole del passo 4
-- di _extract_source_name in src/acquisition/generalist.py: ultima parte
-- dopo un trattino circondato da spazi, lunga tra 2 e 60 caratteri e non
-- composta solo da cifre. Esito: 366 articoli aggiornati, 2 rimasti
-- 'google_news' perché privi di un suffisso utilizzabile.
--
-- Prima dell'aggiornamento le fonti originali sono state salvate nella
-- tabella backup_source_google_news_20261011.

CREATE TABLE IF NOT EXISTS backup_source_google_news_20261011 AS
SELECT id AS article_id, source AS source_originale, now() AS salvato_il
FROM articles WHERE source = 'google_news';
ALTER TABLE backup_source_google_news_20261011 ENABLE ROW LEVEL SECURITY;

WITH c AS (
  SELECT id,
    trim((regexp_split_to_array(title, '\s+[-–—]\s+'))[array_length(regexp_split_to_array(title, '\s+[-–—]\s+'),1)]) AS candidata,
    array_length(regexp_split_to_array(title, '\s+[-–—]\s+'),1) AS parti
  FROM articles WHERE source = 'google_news')
UPDATE articles a SET source = c.candidata
FROM c
WHERE a.id = c.id AND c.parti > 1 AND length(c.candidata) BETWEEN 2 AND 60 AND c.candidata !~ '^\d+$';

-- Per annullare la migrazione:
-- UPDATE articles a SET source = b.source_originale
-- FROM backup_source_google_news_20261011 b WHERE a.id = b.article_id;
