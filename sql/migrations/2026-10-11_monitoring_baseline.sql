-- ============================================================
-- Migrazione: Supporto versioni baseline e metodo hash (2026-10-11)
-- ============================================================
-- Aggiunge le colonne is_baseline e hash_method alla tabella article_versions
-- per consentire la memorizzazione della versione di partenza (baseline)
-- e il disaccoppiamento dalle versioni storiche e da raw_text.

ALTER TABLE article_versions ADD COLUMN IF NOT EXISTS is_baseline BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE article_versions ADD COLUMN IF NOT EXISTS hash_method TEXT;
