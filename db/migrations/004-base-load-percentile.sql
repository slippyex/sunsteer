-- 0.5.2: configurable household base-load percentile, hot-reloaded from control_config.
-- See services/surplus-controller/src/baseload.py. Idempotent (safe to re-run).
ALTER TABLE control_config
  ADD COLUMN IF NOT EXISTS base_load_percentile DOUBLE PRECISION NOT NULL DEFAULT 50;
