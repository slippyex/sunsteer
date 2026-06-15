-- 002 — query-path indexes: keep the hot read paths off full hypertable scans as
-- decision_log and energy_meter grow under the 365-day retention policy (matters on a
-- Pi-class host). Applied by the db-migrate one-shot (compose) or manually:
--   psql -U <user> -d <db> -f 002-query-indexes.sql
-- Idempotent: CREATE INDEX IF NOT EXISTS is safe to re-run.

-- last_switch_ages(): max(time) FILTER (WHERE action = 'switched_on'/'switched_off').
CREATE INDEX IF NOT EXISTS decision_log_action_time_idx
  ON decision_log (action, time DESC);

-- daily_production() / today_summary(): scan energy_meter WHERE production_kwh_total IS NOT NULL.
-- Partial index so it stays small (production rows only) and serves the ordered lag() window.
CREATE INDEX IF NOT EXISTS energy_meter_production_time_idx
  ON energy_meter (time DESC) WHERE production_kwh_total IS NOT NULL;
