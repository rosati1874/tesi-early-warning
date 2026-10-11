-- ============================================================
-- Migrazione: Supporto canale di notifica email (2026-10-11)
-- ============================================================
-- Da eseguire su istanze esistenti del database per aggiungere
-- il supporto alle notifiche via email accanto ai webhook.
-- Su database creati ex novo tramite sql/schema.sql questa
-- migrazione non è necessaria.

-- 1. Aggiornamento tabella subscribers
ALTER TABLE subscribers ALTER COLUMN webhook_url DROP NOT NULL;
ALTER TABLE subscribers ADD COLUMN IF NOT EXISTS email TEXT UNIQUE;
ALTER TABLE subscribers ADD CONSTRAINT subscribers_email_format_check
    CHECK (email IS NULL OR email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$');
ALTER TABLE subscribers ADD CONSTRAINT subscribers_has_destination_check
    CHECK (webhook_url IS NOT NULL OR email IS NOT NULL);

-- 2. Aggiornamento tabella subscription_requests
ALTER TABLE subscription_requests ALTER COLUMN webhook_url DROP NOT NULL;
ALTER TABLE subscription_requests ADD COLUMN IF NOT EXISTS notification_email TEXT;
ALTER TABLE subscription_requests ADD CONSTRAINT subscription_requests_email_format_check
    CHECK (notification_email IS NULL OR notification_email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$');
ALTER TABLE subscription_requests ADD CONSTRAINT subscription_requests_has_destination_check
    CHECK (webhook_url IS NOT NULL OR notification_email IS NOT NULL);
