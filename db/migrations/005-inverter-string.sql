-- Generic per-MPPT-string DC power. Replaces the fixed energy_meter.dc_power_a_w/dc_power_b_w
-- columns (kept frozen for history). idx = 1-based MPPT number. Idempotent.
CREATE TABLE IF NOT EXISTS inverter_string (
  time    TIMESTAMPTZ      NOT NULL,
  idx     SMALLINT         NOT NULL,
  power_w DOUBLE PRECISION NOT NULL
);
SELECT create_hypertable('inverter_string', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS inverter_string_idx_time ON inverter_string (idx, time DESC);

-- One-time backfill from the legacy columns (only while the table is still empty, so re-running
-- the migration on every db-migrate sync is a no-op once the exporter has written real rows).
INSERT INTO inverter_string (time, idx, power_w)
  SELECT time, 1, dc_power_a_w FROM energy_meter
  WHERE dc_power_a_w IS NOT NULL AND NOT EXISTS (SELECT 1 FROM inverter_string);
INSERT INTO inverter_string (time, idx, power_w)
  SELECT time, 2, dc_power_b_w FROM energy_meter
  WHERE dc_power_b_w IS NOT NULL AND NOT EXISTS (SELECT 1 FROM inverter_string WHERE idx = 2);
