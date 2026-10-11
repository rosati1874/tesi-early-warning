-- ============================================================
-- Migrazione: Normalizzazione retroattiva fonti Google News (2026-07-30)
-- ============================================================
-- Questa migrazione è già stata eseguita ed è conservata esclusivamente
-- come riferimento storico. Non è necessaria su un database nuovo.
--
-- Estrae il dominio dall'URL reale per gli articoli storici che avevano
-- come valore sorgente 'google_news', ripulendo il prefisso 'www.'.

UPDATE articles
SET source = regexp_replace(split_part(split_part(url, '//', 2), '/', 1), '^www\.', '')
WHERE source = 'google_news'
  AND url NOT LIKE '%news.google.com%';
