# Generic heat-pump telemetry — design (0.4.0)

**Status:** approved (design), pending spec review
**Date:** 2026-06-15
**Type:** breaking architectural change (DB schema + Prometheus metrics + service/image rename)

## Motivation

The optional Viessmann ViCare telemetry is hardcoded as *the* heat pump throughout the
stack, which contradicts Sunsteer's own "bring your own" philosophy. The meter and relay
already sit behind generic `Protocol`-based drivers (`METER_DRIVER`, `RELAY_DRIVER`) that
emit generic contracts; the heat-pump telemetry is the lone vendor-locked path:

- **vicare-exporter** — vendor-named service, no driver seam; polls ViCare, writes
  `heatpump_vicare`, emits `vicare_*` metrics.
- **control-ui** — `_VICARE` metric dict, `heatpump_vicare` queries, i18n labels naming
  "Viessmann"/"Vitocal 250-A" (also factually stale — the device is a *Vitocal 250-A06*),
  a fixed `VICARE` tag.
- **Grafana/alerts** — `vicare_*` series.

Goal: make the heat-pump telemetry **generic with a pluggable vendor driver**, mirroring
`energy-exporter`'s `METER_DRIVER` pattern. ViCare becomes *one* driver, not *the* service.

## Decisions (agreed)

1. **Breaking** clean cut, shipped as **0.4.0** (pre-1.0 minor bump). Data preserved via
   rename; no compatibility shim.
2. **Neutral single-source contract + config label.** A household has one heat pump, so no
   `source`/vendor column. The displayed name comes from `HEATPUMP_LABEL`.
3. **Generic service with a driver abstraction**, exactly like `energy-exporter`:
   - Service renamed `vicare-exporter` → **`heatpump-exporter`**.
   - **`HEATPUMP_DRIVER`** (`vicare` | `mock`) behind a `HeatPumpDriver` Protocol + factory.
   - `vicare` driver = today's Viessmann logic (auth, rate budget, token, extract).
   - `mock` driver = synthetic telemetry, so the **demo shows the heat-pump card** (today
     empty without real ViCare creds), consistent with the `mock` meter.

## Goals / non-goals

**Goals**
- Generic, vendor-neutral heat-pump telemetry contract (DB table + metrics + UI).
- Pluggable vendor driver; ViCare as the first real driver, `mock` for demo/tests.
- Vendor name purely a display concern, set via `HEATPUMP_LABEL`.

**Non-goals**
- Multiple simultaneous heat-pump sources (one household = one pump).
- A second real vendor driver (none exists yet; the seam is enough — YAGNI).
- Changing the field set: the existing fields (temps, energy, COP/SCOP, compressor) are
  already generic heat-pump telemetry and stay as-is.

## The generic contract

### Database
- `heatpump_vicare` → **`heatpump_telemetry`**. Migration `db/migrations/003-*.sql`,
  idempotent: `ALTER TABLE IF EXISTS heatpump_vicare RENAME TO heatpump_telemetry`
  (TimescaleDB renames the hypertable in place; the 365-day retention policy follows the
  hypertable id, not the name — verified: no continuous aggregate depends on this table).
  The column set is unchanged.
- `db/init.sql`: the fresh-install snapshot declares `heatpump_telemetry` directly (init.sql
  is the post-release snapshot; the migration covers existing installs).

### Metrics (Prometheus)
- **Telemetry gauges** `vicare_*` → **`heatpump_*`** (e.g. `vicare_dhw_temp_c` →
  `heatpump_dhw_temp_c`). This is the contract the UI reads.
- **Generic liveness/health** → `heatpump_*`: `heatpump_last_success_timestamp_seconds`,
  `heatpump_scrape_errors_total`.
- **Driver-internal operational metrics stay vendor-scoped** under the `vicare` driver
  (`vicare_api_calls_total`, `vicare_rate_limited_total`, `vicare_budget_used`,
  `vicare_invalid_credentials_total`): they are genuinely Viessmann-API concerns and are not
  part of the telemetry contract. Only the `mock` driver omits them.

## Service: `heatpump-exporter`

Renamed from `vicare-exporter`. Generic shell + driver, mirroring `energy-exporter`.

### Driver abstraction (`src/drivers/`)
```
class HeatPumpDriver(Protocol):
    def poll(self) -> dict | None:
        """Return one telemetry reading (HeatPumpReading TypedDict shape, the extract.FIELDS
        keys) or None to skip this cycle (e.g. rate-budget exhausted, transient error)."""
```
- `get_driver(name)` / `SUPPORTED_DRIVERS = ("vicare", "mock")`, lazy imports (so PyViCare
  isn't needed for the mock driver / unit tests) — same shape as `drivers.get_meter`.
- **`vicare` driver** encapsulates today's logic: PyViCare connect-with-retry +
  invalid-credentials exit, the `RateBudget` (poll() returns `None` when exhausted and updates
  the budget gauges), token handling/`secure_token_file`, `vicare_client.poll` +
  `extract.extract`. The driver owns the `VICARE_*` env (creds, daily cap, token/budget files).
- **`mock` driver** returns a synthetic but plausible reading each poll (temps, slowly-rising
  energy counters, compressor figures); no creds, no budget.

### Generic shell (`src/main.py`)
- `validate_env()` requires `DB_*` always; `HEATPUMP_DRIVER` validated against
  `SUPPORTED_DRIVERS`; vendor creds required only for the `vicare` driver (mirrors
  energy-exporter's `mock`-needs-no-hardware split).
- Poll loop: `reading = driver.poll()`; on a non-None reading → `metrics.set_from(reading)`,
  `tsdb_writer.write(conn, reading)` (table `heatpump_telemetry`),
  `heatpump_last_success` set. Generic backoff on failure.
- `HEATPUMP_POLL_SECONDS` (generic) replaces `VICARE_POLL_SECONDS`; the vicare driver still
  spaces calls to fit its daily budget.

### Files
- **Field ownership:** the generic shell owns the contract field list `HEATPUMP_FIELDS`
  (kept equal to today's list), and `metrics.GAUGES` + `tsdb_writer.COLUMNS` derive from it.
  Today's `extract.py` (the Viessmann feature→field *mapping*) moves under the `vicare`
  driver; its `extract()` must produce readings whose keys are exactly `HEATPUMP_FIELDS`. The
  `mock` driver likewise produces `HEATPUMP_FIELDS`-keyed readings. So the shell stays
  driver-agnostic; each driver is responsible for emitting the contract shape.
- `tsdb_writer.py` (connect/live_conn/write) stays generic — `connect`/`live_conn` remain
  byte-identical to the other services (the cross-service consistency guard now covers
  `services/heatpump-exporter/src/tsdb_writer.py`).
- `metrics.py` stays generic (gauges from the field list + generic liveness; vendor-op
  metrics provided by the vicare driver).

## control-ui — vendor-neutral + config

- New env **`HEATPUMP_LABEL`** (default empty). Empty → the card title is just
  "Wärmepumpe" / "Heat pump" and the tag is omitted. Set (e.g. `Vitocal 250 A06`) → shown as
  the tag/suffix.
- i18n: `sec_vicare` → `sec_heatpump` = ("Wärmepumpe", "Heat pump"); Viessmann/Vitocal-named
  tooltips reworded generically (the device specifics live only in `HEATPUMP_LABEL`).
- `app.py`: `_VICARE` → `_HEATPUMP` with the new `heatpump_*` metric names; route
  `/partials/vicare` → `/partials/heatpump`; template `partials/vicare.html` →
  `partials/heatpump.html`; element `id="vicare"` → `id="heatpump"`; the `VICARE` tag driven
  by `HEATPUMP_LABEL` (passed into the render context).
- `sources.py`: `heatpump_vicare` queries → `heatpump_telemetry`; ViCare-named docstrings
  reworded.

## Cross-cutting

- **Grafana dashboards** + `deploy/compose/monitoring/alerts.yml` (the
  `vicare_last_success_timestamp_seconds` staleness alert) → `heatpump_*`.
- **Deploy renames** `vicare-exporter` → `heatpump-exporter`: directory, Dockerfile,
  image name `ghcr.io/slippyex/sunsteer/heatpump-exporter`, compose service + image refs (prod:
  driver `vicare`, opt-in profile; demo: driver `mock`, always on → the card renders),
  k8s manifest + kustomization (newTag + commented resource), CI `test`/`image-scan` matrix,
  the mypy-gate file paths, `.dockerignore`.
- **Consistency test** `tests/integration/test_config_consistency.py`:
  `test_vicare_fields_match_heatpump_vicare_ddl` → `heatpump_telemetry`; the live_conn/connect
  guard module list updated to the renamed service path.
- **Documentation — first-class deliverable, not a footnote.** Every product doc that names
  the vendor/old contract/old service must be updated; a grep for
  `vicare|viessmann|heatpump_vicare|vitocal|vicare-exporter` over `*.md` is the completeness
  gate. Concretely:
  - `README.md` (3 hits): the "bring your own" / optional-telemetry framing and the service
    name → present heat-pump telemetry as a generic exporter with a `vicare` driver.
  - `docs/architecture.md` (5 hits): the component section, the mermaid data-flow node
    (`vicare-exporter` → `heatpump-exporter`), and the **data-model table** (`heatpump_vicare`
    → `heatpump_telemetry`).
  - `docs/hardware.md` (5 hits): the "Viessmann ViCare (optional)" section reframed as **the
    `vicare` driver of the heat-pump exporter** (the ViCare data quirks stay — they're
    driver-specific), plus the new `mock` driver mention.
  - `docs/setup.md` (2 hits): env/setup references → `HEATPUMP_DRIVER`, `HEATPUMP_LABEL`,
    `VICARE_*` as the vicare-driver credentials.
  - `deploy/k8s/README.md` (1 hit): the `vicare-exporter` opt-in step → `heatpump-exporter`.
  - `SECURITY.md` (1 hit): the affected-services list → service rename.
  - `DISCLAIMER.md` (1 hit): check the Viessmann mention; reword generically or keep only as a
    trademark note.
  - `.env.example`: add `HEATPUMP_DRIVER`, `HEATPUMP_LABEL`, `HEATPUMP_POLL_SECONDS`; move the
    `VICARE_*` block under a "vicare driver" heading.
  - `CHANGELOG.md`: a `[0.4.0]` entry with the breaking-change upgrade note. **Historical
    entries are NOT rewritten** — past releases legitimately shipped `vicare-exporter`.
  - A new **`docs/heatpump-interface.md`**: the generic heat-pump telemetry contract (the
    `HEATPUMP_FIELDS` / `heatpump_*` metrics + the `HeatPumpDriver` seam), documenting "bring
    your own heat-pump driver" exactly like `state-interface.md` documents the meter contract
    and `status-interface.md` the controller `/status`. Linked from `architecture.md`.
  - `tasks/*` are session working files, not product docs — out of scope.
- **CHANGELOG** `[0.4.0]` documenting the breaking renames + the upgrade note (apply migration
  003; update any custom Grafana/queries from `vicare_*`/`heatpump_vicare` to
  `heatpump_*`/`heatpump_telemetry`; rename the image; set `HEATPUMP_LABEL`).
- **Version bump** all deploy strings 0.3.x → 0.4.0.

## Migration / rollout (0.4.0)

1. DB: apply `003` (rename, data preserved). Fresh installs get `heatpump_telemetry` from
   init.sql.
2. Metrics: `vicare_*` series stop; `heatpump_*` series begin. Old Prometheus series age out;
   the DB history is intact under the renamed table. Grafana/alerts updated in the same release.
3. Image: `vicare-exporter:0.3.x` is not continued; deployments switch to
   `heatpump-exporter:0.4.0` with `HEATPUMP_DRIVER=vicare` (+ existing `VICARE_*` secrets).

## Testing strategy (TDD throughout)

- **Driver factory:** `get_driver` returns the right driver; unknown fails fast; lazy imports
  (mock needs no PyViCare). Mirror `test_drivers.py`.
- **mock driver:** `poll()` returns a full `HEATPUMP_FIELDS`-shaped reading; energy counters
  monotonic across polls (like the mock meter tests).
- **vicare driver:** the existing auth/ratebudget/extract/invalid-creds/backoff tests move under
  the driver, unchanged in intent.
- **generic shell:** poll loop writes + sets liveness on a reading, skips on `None`, backs off
  on error (fake driver).
- **control-ui:** `HEATPUMP_LABEL` empty → no tag / neutral title; set → tag shown. Partial
  renders against `heatpump_*` mocks. No i18n key references "Viessmann"/"Vitocal".
- **integration:** `heatpump_telemetry` write/read against the real DB (the existing vicare DB
  test, retargeted); migration `003` idempotent (apply twice); consistency guard green.
- **mypy gate** extended to the renamed driver modules where already clean.

## Risks

- **Breaking by design:** anyone with custom Grafana panels/queries or external scrapers of
  `vicare_*` / `heatpump_vicare` must update. Documented in the CHANGELOG upgrade note.
- **Large mechanical rename surface** (service/image/CI/k8s/docs); covered explicitly above so
  the implementation plan enumerates each touch point. A grep for `vicare`/`viessmann`/
  `heatpump_vicare`/`vicare_` is the completeness check.
- **TimescaleDB hypertable rename + retention:** verify empirically in the plan that the
  retention policy survives the rename (expected: yes — policy is by hypertable id).

## Open questions

None blocking. (`HEATPUMP_LABEL` default empty; user sets `Vitocal 250 A06`. Vendor-op metrics
stay `vicare_*` as driver-internal. Service/image renamed.)
