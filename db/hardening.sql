-- =============================================================
-- TimescaleDB Server Hardening (idempotent, safe to re-run)
-- =============================================================
--
-- Runs after init.sql in docker-entrypoint-initdb.d (ConfigMap).
-- Also re-runnable ad-hoc:
--   kubectl exec -n energy <timescaledb-pod> -- \
--     psql -U energy -d energy -f /docker-entrypoint-initdb.d/hardening.sql
--
-- History:
--   2026-04-19  25h hang from policy_compression on ohlcv deadlock with
--               idle-in-transaction session. Playbook written but never
--               actually applied server-side.
--   2026-04-23  Same pathology recurred (6h hang). Server-side fixes
--               finally applied AND checked into git via this file.
-- =============================================================

-- ----- Kill the idle-in-transaction leak pathology at the server level -----
-- Sessions that BEGIN a txn and go idle (cough, psycopg2 connection pool
-- callers that forget to commit/rollback) hold AccessShareLocks indefinitely.
-- This is what repeatedly wedges policy_compression on ohlcv.
ALTER SYSTEM SET idle_in_transaction_session_timeout = '300s';

-- Any single query running > 10min is almost certainly a leak or a bug.
-- Backtest/validator sweeps run per-query and all finish in well under 10min.
ALTER SYSTEM SET statement_timeout = '600s';

-- Apply without restart.
SELECT pg_reload_conf();

-- ----- Remove existing compression policy on ohlcv if present -----
-- The init.sql no longer creates one, but older DBs initialized before
-- 2026-04-23 still have it. delete_job is a no-op if the policy doesn't exist.
DO $$
DECLARE
    j_id int;
BEGIN
    FOR j_id IN
        SELECT job_id FROM timescaledb_information.jobs
        WHERE proc_name LIKE '%compress%' AND hypertable_name='ohlcv'
    LOOP
        PERFORM delete_job(j_id);
        RAISE NOTICE 'removed ohlcv compression policy job_id=%', j_id;
    END LOOP;
END $$;

-- ----- Verification (visible in pod logs on init run) -----
SELECT 'hardening applied' AS status,
       current_setting('idle_in_transaction_session_timeout') AS idle_in_tx_timeout,
       current_setting('statement_timeout') AS statement_timeout,
       (SELECT COUNT(*) FROM timescaledb_information.jobs
        WHERE proc_name LIKE '%compress%' AND hypertable_name='ohlcv') AS ohlcv_compress_jobs;
