CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS energy_meter (
  time              TIMESTAMPTZ NOT NULL,
  import_w          DOUBLE PRECISION,
  export_w          DOUBLE PRECISION,
  surplus_w         DOUBLE PRECISION,
  l1_w              DOUBLE PRECISION,
  l2_w              DOUBLE PRECISION,
  l3_w              DOUBLE PRECISION,
  import_kwh_total  DOUBLE PRECISION,
  export_kwh_total  DOUBLE PRECISION,
  production_w          DOUBLE PRECISION,
  production_kwh_total  DOUBLE PRECISION,
  dc_power_a_w          DOUBLE PRECISION,   -- inverter MPPT string A (e.g. East) DC power
  dc_power_b_w          DOUBLE PRECISION,   -- inverter MPPT string B (e.g. West) DC power
  inverter_temp_c       DOUBLE PRECISION
);
SELECT create_hypertable('energy_meter', 'time', if_not_exists => TRUE);
-- additive columns for existing deployments (no-op if already present)
ALTER TABLE energy_meter ADD COLUMN IF NOT EXISTS production_w DOUBLE PRECISION;
ALTER TABLE energy_meter ADD COLUMN IF NOT EXISTS production_kwh_total DOUBLE PRECISION;
ALTER TABLE energy_meter ADD COLUMN IF NOT EXISTS dc_power_a_w DOUBLE PRECISION;
ALTER TABLE energy_meter ADD COLUMN IF NOT EXISTS dc_power_b_w DOUBLE PRECISION;
ALTER TABLE energy_meter ADD COLUMN IF NOT EXISTS inverter_temp_c DOUBLE PRECISION;

CREATE TABLE IF NOT EXISTS heatpump (
  time             TIMESTAMPTZ NOT NULL,
  relay_on         BOOLEAN,
  power_w          DOUBLE PRECISION,
  energy_wh_total  DOUBLE PRECISION
);
SELECT create_hypertable('heatpump', 'time', if_not_exists => TRUE);

-- ViCare cloud telemetry (read-only). Column order MUST match extract.FIELDS in vicare-exporter.
CREATE TABLE IF NOT EXISTS heatpump_vicare (
  time                   TIMESTAMPTZ NOT NULL,
  dhw_temp_c             DOUBLE PRECISION,
  dhw_target_c           DOUBLE PRECISION,
  dhw_mode               TEXT,
  buffer_temp_c          DOUBLE PRECISION,
  outside_temp_c         DOUBLE PRECISION,
  supply_temp_c          DOUBLE PRECISION,
  energy_total_kwh       DOUBLE PRECISION,
  energy_heating_kwh     DOUBLE PRECISION,
  energy_dhw_kwh         DOUBLE PRECISION,
  energy_read_at         TIMESTAMPTZ,
  heat_heating_kwh       DOUBLE PRECISION,
  heat_dhw_kwh           DOUBLE PRECISION,
  heatingrod_heating_kwh DOUBLE PRECISION,
  heatingrod_dhw_kwh     DOUBLE PRECISION,
  scop_total             DOUBLE PRECISION,
  spf_total              DOUBLE PRECISION,
  compressor_speed_rps   DOUBLE PRECISION,
  compressor_starts      DOUBLE PRECISION,
  compressor_hours       DOUBLE PRECISION
);
SELECT create_hypertable('heatpump_vicare', 'time', if_not_exists => TRUE);
SELECT add_retention_policy('heatpump_vicare', INTERVAL '365 days', if_not_exists => TRUE);

CREATE MATERIALIZED VIEW IF NOT EXISTS energy_daily
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 day', time) AS day,
       max(import_kwh_total) - min(import_kwh_total) AS import_kwh,
       max(export_kwh_total) - min(export_kwh_total) AS export_kwh
FROM energy_meter
GROUP BY day
WITH NO DATA;

SELECT add_continuous_aggregate_policy('energy_daily',
  start_offset => INTERVAL '3 days', end_offset => INTERVAL '1 hour',
  schedule_interval => INTERVAL '1 hour', if_not_exists => TRUE);

SELECT add_retention_policy('energy_meter', INTERVAL '365 days', if_not_exists => TRUE);
SELECT add_retention_policy('heatpump', INTERVAL '365 days', if_not_exists => TRUE);

-- ===== Phase C1: surplus controller =====
CREATE TABLE IF NOT EXISTS control_config (
  id                SMALLINT PRIMARY KEY DEFAULT 1,
  mode              TEXT NOT NULL DEFAULT 'paused',
  manual_relay_on   BOOLEAN NOT NULL DEFAULT FALSE,
  threshold_base_w  DOUBLE PRECISION NOT NULL DEFAULT 2500,
  threshold_min_w   DOUBLE PRECISION NOT NULL DEFAULT 1500,
  threshold_off_w   DOUBLE PRECISION NOT NULL DEFAULT 200,
  on_delay_cycles   INT NOT NULL DEFAULT 3,
  off_delay_cycles  INT NOT NULL DEFAULT 3,
  min_runtime_s     INT NOT NULL DEFAULT 1800,
  min_offtime_s     INT NOT NULL DEFAULT 900,
  adapt_enabled     BOOLEAN NOT NULL DEFAULT TRUE,
  full_sun_ref_kwh  DOUBLE PRECISION NOT NULL DEFAULT 70,
  feed_in_tariff_eur_kwh DOUBLE PRECISION NOT NULL DEFAULT 0.08,
  grid_price_eur_kwh     DOUBLE PRECISION NOT NULL DEFAULT 0.30,
  wp_nominal_power_w DOUBLE PRECISION NOT NULL DEFAULT 2000,
  pv_performance_ratio DOUBLE PRECISION NOT NULL DEFAULT 0.70,  -- Open-Meteo GTI -> kWh, self-calibrated
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (id = 1)
);
INSERT INTO control_config (id) VALUES (1) ON CONFLICT DO NOTHING;
ALTER TABLE control_config ADD COLUMN IF NOT EXISTS pv_performance_ratio DOUBLE PRECISION NOT NULL DEFAULT 0.70;

CREATE TABLE IF NOT EXISTS decision_log (
  time                   TIMESTAMPTZ NOT NULL,
  mode                   TEXT,
  surplus_w              DOUBLE PRECISION,
  effective_threshold_w  DOUBLE PRECISION,
  forecast_remaining_kwh DOUBLE PRECISION,
  relay_target           BOOLEAN,
  action                 TEXT,
  reason                 TEXT,
  available_w            DOUBLE PRECISION,   -- load-compensated surplus the decision used
  relay_on_before        BOOLEAN,            -- relay state just before this action
  state_age_s            DOUBLE PRECISION,   -- age of the SHM reading (NULL = was blind)
  shelly_reachable       BOOLEAN
);
-- CREATE TABLE IF NOT EXISTS won't add columns to an existing table — apply additively too:
ALTER TABLE decision_log ADD COLUMN IF NOT EXISTS available_w      DOUBLE PRECISION;
ALTER TABLE decision_log ADD COLUMN IF NOT EXISTS relay_on_before  BOOLEAN;
ALTER TABLE decision_log ADD COLUMN IF NOT EXISTS state_age_s      DOUBLE PRECISION;
ALTER TABLE decision_log ADD COLUMN IF NOT EXISTS shelly_reachable BOOLEAN;
SELECT create_hypertable('decision_log','time', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS solar_forecast (
  time                   TIMESTAMPTZ NOT NULL,
  forecast_date          DATE,
  expected_kwh_day       DOUBLE PRECISION,
  expected_kwh_remaining DOUBLE PRECISION
);
SELECT create_hypertable('solar_forecast','time', if_not_exists => TRUE);

CREATE MATERIALIZED VIEW IF NOT EXISTS heatpump_daily
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 day', time) AS day,
       avg(CASE WHEN relay_on THEN 1.0 ELSE 0.0 END) AS on_fraction,
       avg(power_w) AS avg_power_w
FROM heatpump
GROUP BY day
WITH NO DATA;
SELECT add_continuous_aggregate_policy('heatpump_daily',
  start_offset => INTERVAL '3 days', end_offset => INTERVAL '1 hour',
  schedule_interval => INTERVAL '1 hour', if_not_exists => TRUE);

SELECT add_retention_policy('decision_log', INTERVAL '365 days', if_not_exists => TRUE);
SELECT add_retention_policy('solar_forecast', INTERVAL '365 days', if_not_exists => TRUE);
