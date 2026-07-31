-- ============================================================
-- Schema per il sistema di early warning epidemico
-- ============================================================

CREATE TABLE IF NOT EXISTS articles (
    id              SERIAL PRIMARY KEY,
    url             TEXT UNIQUE NOT NULL,
    source          TEXT NOT NULL,           -- es. 'openonline', 'ilpost', 'FNOMCeO', 'Sky TG24'
    acquisition_mode TEXT NOT NULL,           -- 'mirato' | 'generalista'
    title           TEXT,
    published_at    TIMESTAMPTZ,
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_text        TEXT,
    passed_keyword_filter BOOLEAN,
    is_epidemic_signal    BOOLEAN,
    llm_confidence        REAL,
    llm_disease           TEXT,
    llm_location           TEXT,
    llm_justification      TEXT,
    llm_model               TEXT,             -- es. 'gemini-3.5-flash-lite'
    classification_attempts INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'active', -- 'active' | 'removed' | 'error'
    last_checked_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS article_versions (
    id          SERIAL PRIMARY KEY,
    article_id  INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    content_hash TEXT NOT NULL,
    text_snapshot TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS availability_checks (
    id          SERIAL PRIMARY KEY,
    article_id  INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    checked_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    http_status INTEGER,
    result      TEXT NOT NULL  -- 'available' | 'removed' | 'access_error'
);

CREATE TABLE IF NOT EXISTS blacklisted_models (
    id             SERIAL PRIMARY KEY,
    model_name     VARCHAR(100) UNIQUE NOT NULL,
    blacklisted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at     TIMESTAMPTZ NOT NULL,
    reason         TEXT
);

CREATE INDEX IF NOT EXISTS idx_articles_signal ON articles (is_epidemic_signal);
CREATE INDEX IF NOT EXISTS idx_article_versions_article_id ON article_versions (article_id);
CREATE INDEX IF NOT EXISTS idx_availability_checks_article_id ON availability_checks (article_id);
CREATE INDEX IF NOT EXISTS idx_blacklisted_models_expires ON blacklisted_models (expires_at);

CREATE INDEX IF NOT EXISTS idx_articles_pending_classification
ON articles (passed_keyword_filter, is_epidemic_signal, first_seen_at);

CREATE INDEX IF NOT EXISTS idx_articles_first_seen
ON articles (first_seen_at);

CREATE INDEX IF NOT EXISTS idx_articles_active_backlog
ON articles (classification_attempts, first_seen_at)
WHERE passed_keyword_filter = true AND is_epidemic_signal IS NULL AND raw_text IS NOT NULL;


-- ============================================================
-- Migrazioni una tantum (già eseguite — mantenute solo come
-- riferimento storico, non necessarie su un database nuovo)
-- ============================================================

ALTER TABLE articles ADD COLUMN IF NOT EXISTS classification_attempts INTEGER NOT NULL DEFAULT 0;

UPDATE articles
SET source = regexp_replace(split_part(split_part(url, '//', 2), '/', 1), '^www\.', '')
WHERE source = 'google_news'
  AND url NOT LIKE '%news.google.com%';
