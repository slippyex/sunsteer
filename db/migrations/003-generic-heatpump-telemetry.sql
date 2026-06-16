-- 003 — generic heat-pump telemetry: rename the vendor-named table to the generic contract.
-- Data + the hypertable + its 365-day retention policy are preserved (the policy references
-- the hypertable by id, not name). The writer names columns explicitly, so column order is
-- irrelevant. Idempotent: only renames if the old table still exists.
DO $$
BEGIN
  IF to_regclass('public.heatpump_vicare') IS NOT NULL
     AND to_regclass('public.heatpump_telemetry') IS NULL THEN
    ALTER TABLE heatpump_vicare RENAME TO heatpump_telemetry;
  END IF;
END $$;
