-- ============================================================
-- Migrazione: tracciamento versione del prompt LLM (2026-10-11)
-- ============================================================
-- Aggiunge la colonna llm_prompt_version alla tabella articles per memorizzare
-- la versione del prompt utilizzata per la classificazione semantica.

ALTER TABLE articles ADD COLUMN IF NOT EXISTS llm_prompt_version VARCHAR(20);
