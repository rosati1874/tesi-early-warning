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
    status          TEXT NOT NULL DEFAULT 'active', -- 'active' | 'removed' | 'error' | 'duplicate'
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

CREATE TABLE IF NOT EXISTS subscribers (
    id               SERIAL PRIMARY KEY,
    webhook_url      TEXT UNIQUE NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    active           BOOLEAN NOT NULL DEFAULT true,
    last_notified_at TIMESTAMPTZ,
    failure_count    INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_articles_signal ON articles (is_epidemic_signal);
CREATE INDEX IF NOT EXISTS idx_article_versions_article_id ON article_versions (article_id);
CREATE INDEX IF NOT EXISTS idx_availability_checks_article_id ON availability_checks (article_id);
CREATE INDEX IF NOT EXISTS idx_blacklisted_models_expires ON blacklisted_models (expires_at);
CREATE INDEX IF NOT EXISTS idx_subscribers_active ON subscribers (active);

CREATE INDEX IF NOT EXISTS idx_articles_pending_classification
ON articles (passed_keyword_filter, is_epidemic_signal, first_seen_at);

CREATE INDEX IF NOT EXISTS idx_articles_first_seen
ON articles (first_seen_at);

CREATE INDEX IF NOT EXISTS idx_articles_active_backlog
ON articles (classification_attempts, first_seen_at)
WHERE passed_keyword_filter = true AND is_epidemic_signal IS NULL AND raw_text IS NOT NULL;


-- ============================================================
-- Abilitazione Row Level Security (RLS) per Supabase Security
-- ============================================================

ALTER TABLE articles ENABLE ROW LEVEL SECURITY;
ALTER TABLE article_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE availability_checks ENABLE ROW LEVEL SECURITY;
ALTER TABLE blacklisted_models ENABLE ROW LEVEL SECURITY;
ALTER TABLE subscribers ENABLE ROW LEVEL SECURITY;


-- ============================================================
-- Migrazioni una tantum (già eseguite — mantenute solo come
-- riferimento storico, non necessarie su un database nuovo)
-- ============================================================

ALTER TABLE articles ADD COLUMN IF NOT EXISTS classification_attempts INTEGER NOT NULL DEFAULT 0;

UPDATE articles
SET source = regexp_replace(split_part(split_part(url, '//', 2), '/', 1), '^www\.', '')
WHERE source = 'google_news'
  AND url NOT LIKE '%news.google.com%';


-- ============================================================
-- Auto-iscrizione pubblica al canale di notifica (RF-07)
-- ============================================================

-- Vincolo CHECK: accetta solo URL con protocollo HTTPS
ALTER TABLE subscribers ADD CONSTRAINT subscribers_webhook_url_https CHECK (webhook_url ~ '^https://');

-- Policy RLS: permette l'inserimento pubblico (anon) solo con stato iniziale corretto
CREATE POLICY subscribers_public_self_register ON subscribers
FOR INSERT TO anon
WITH CHECK (active = true AND failure_count = 0 AND last_notified_at IS NULL);

-- Privilegi minimi espliciti per il ruolo pubblico anon
GRANT INSERT ON subscribers TO anon;
GRANT USAGE, SELECT ON SEQUENCE subscribers_id_seq TO anon;


-- ============================================================
-- Migrazione v2: iscrizione soggetta a verifica (sostituisce
-- l'auto-iscrizione diretta introdotta in precedenza)
-- ============================================================

CREATE TABLE IF NOT EXISTS subscription_requests (
    id                SERIAL PRIMARY KEY,
    webhook_url       TEXT NOT NULL,
    organization_name TEXT,
    contact_email     TEXT,
    requested_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    status            TEXT NOT NULL DEFAULT 'pending',  -- 'pending' | 'approved' | 'rejected'
    reviewed_at       TIMESTAMPTZ,
    notes             TEXT
);

ALTER TABLE subscription_requests ENABLE ROW LEVEL SECURITY;

ALTER TABLE subscription_requests DROP CONSTRAINT IF EXISTS subscription_requests_webhook_url_https;
ALTER TABLE subscription_requests
    ADD CONSTRAINT subscription_requests_webhook_url_https CHECK (webhook_url ~ '^https://');

ALTER TABLE subscription_requests DROP CONSTRAINT IF EXISTS subscription_requests_status_valid;
ALTER TABLE subscription_requests
    ADD CONSTRAINT subscription_requests_status_valid CHECK (status IN ('pending', 'approved', 'rejected'));

DROP POLICY IF EXISTS subscription_requests_public_submit ON subscription_requests;
CREATE POLICY subscription_requests_public_submit
    ON subscription_requests
    FOR INSERT
    TO anon
    WITH CHECK (
        (status IS NULL OR status = 'pending')
        AND reviewed_at IS NULL
    );

GRANT INSERT ON subscription_requests TO anon;
GRANT USAGE, SELECT ON SEQUENCE subscription_requests_id_seq TO anon;

DROP POLICY IF EXISTS subscribers_public_self_register ON subscribers;
REVOKE INSERT ON subscribers FROM anon;
REVOKE USAGE, SELECT ON SEQUENCE subscribers_id_seq FROM anon;

-- Esempio di approvazione manuale (SQL Editor Supabase, una richiesta alla volta):
--   UPDATE subscription_requests SET status = 'approved', reviewed_at = now() WHERE id = <ID>;
--   INSERT INTO subscribers (webhook_url) SELECT webhook_url FROM subscription_requests WHERE id = <ID>;
-- Esempio di rifiuto:
--   UPDATE subscription_requests SET status = 'rejected', reviewed_at = now(), notes = '<motivo>' WHERE id = <ID>;


