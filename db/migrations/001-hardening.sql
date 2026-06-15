-- 001 — server hardening: prevent idle-in-transaction lock leaks and runaway queries.
-- Applied by the db-migrate one-shot (compose) or manually:
--   psql -U <user> -d <db> -f 001-hardening.sql
-- Idempotent: ALTER DATABASE ... SET just overwrites; safe to re-run.
DO $$
BEGIN
  EXECUTE format('ALTER DATABASE %I SET idle_in_transaction_session_timeout = %L',
                 current_database(), '300s');
  EXECUTE format('ALTER DATABASE %I SET statement_timeout = %L',
                 current_database(), '600s');
END $$;
