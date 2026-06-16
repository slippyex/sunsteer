# The heat-pump telemetry contract — bring your own driver

The `heatpump-exporter` service writes one row per poll to `heatpump_telemetry` (TimescaleDB) and
exposes the same fields as Prometheus gauges under the `heatpump_*` namespace. It does not
know or care which vendor produced the numbers. **This contract is the seam.** If you
implement a driver that emits it, Sunsteer's UI and Grafana dashboards will show your
heat-pump data — regardless of brand or API.

The built-in drivers are `vicare` (Viessmann ViCare cloud API) and `mock` (synthetic
telemetry for the demo and tests). Select with `HEATPUMP_DRIVER`.

## Contract fields (`HEATPUMP_FIELDS`)

These are the canonical keys. Every driver's `poll()` must return a dict with exactly
these keys (missing / unavailable values → `None`).

| Field | Unit | Description |
|---|---|---|
| `dhw_temp_c` | °C | Domestic hot-water actual temperature |
| `dhw_target_c` | °C | DHW setpoint |
| `dhw_mode` | string | DHW operating mode (e.g. `dhw`, `dhwAndHeating`) |
| `buffer_temp_c` | °C | Heating-circuit buffer temperature |
| `outside_temp_c` | °C | Outdoor temperature (from heat-pump sensor) |
| `supply_temp_c` | °C | Supply / flow temperature |
| `energy_total_kwh` | kWh | Cumulative electrical energy consumed (total) |
| `energy_heating_kwh` | kWh | Cumulative electrical energy — space heating |
| `energy_dhw_kwh` | kWh | Cumulative electrical energy — DHW |
| `energy_read_at` | string | Timestamp string when the vendor counter was sampled (driver-internal; `None` when not applicable) |
| `heat_heating_kwh` | kWh | Cumulative thermal output — space heating |
| `heat_dhw_kwh` | kWh | Cumulative thermal output — DHW |
| `heatingrod_heating_kwh` | kWh | Electrical energy consumed by the heating rod — space heating |
| `heatingrod_dhw_kwh` | kWh | Electrical energy consumed by the heating rod — DHW |
| `scop_total` | — | Seasonal COP (total; requires both thermal and electrical counters to have a value) |
| `spf_total` | — | Seasonal performance factor (total; vendor labelling varies) |
| `compressor_speed_rps` | rps | Compressor rotational speed |
| `compressor_starts` | count | Cumulative compressor starts |
| `compressor_hours` | h | Cumulative compressor run hours |

`dhw_mode` and `energy_read_at` are string (text) fields; all others are numeric and become
Prometheus gauges.

The field list is the single source of truth in
`services/heatpump-exporter/src/contract.py` (`HEATPUMP_FIELDS` + `HEATPUMP_STRING_FIELDS`).
The DB writer and metrics layer both derive their column/gauge lists from it — add a field
there and it propagates everywhere.

## Database table — `heatpump_telemetry`

TimescaleDB hypertable. One row per successful driver `poll()`.

| Column | Type | Description |
|---|---|---|
| `time` | `timestamptz` (PK) | Wall-clock time the row was inserted |
| *(all HEATPUMP_FIELDS)* | `float8` / `text` | One column per field above |

Created by `db/init.sql` on fresh installs; existing installs apply
`db/migrations/003-*.sql` (idempotent `ALTER TABLE … RENAME` of the old `heatpump_vicare`
table — data is preserved, the hypertable's 365-day retention policy follows the
hypertable id, not the name).

## Prometheus metrics — `heatpump_*`

| Metric | Description |
|---|---|
| `heatpump_<field>` | One gauge per numeric `HEATPUMP_FIELDS` entry (e.g. `heatpump_dhw_temp_c`) |
| `heatpump_last_success_timestamp_seconds` | Unix timestamp of the last successful poll |
| `heatpump_scrape_errors_total` | Counter of failed poll attempts |

These are the **telemetry contract metrics** — the ones the control-ui queries and that
Grafana dashboards should target. The `vicare` driver additionally exposes
**driver-internal operational metrics** under `vicare_*` (`vicare_api_calls_total`,
`vicare_rate_limited_total`, `vicare_budget_used`, `vicare_invalid_credentials_total`).
Those are Viessmann-API concerns, not part of the generic contract, and absent in the
`mock` driver.

## The `HeatPumpDriver` seam

```python
class HeatPumpDriver(Protocol):
    def poll(self) -> dict | None:
        """Return one telemetry reading keyed by HEATPUMP_FIELDS, or None to skip
        this cycle (e.g. rate-budget exhausted, transient error)."""
```

The generic shell (`src/main.py`) calls `driver.poll()` on every cycle. A `None` return
skips the DB write and gauge update for that cycle — the liveness timestamp is not
refreshed, so a driver that returns `None` repeatedly will eventually trigger the
staleness alert. A non-`None` return must have exactly the `HEATPUMP_FIELDS` keys
(extras are silently dropped; missing keys cause a `KeyError` that counts as a scrape
error).

Driver selection: `HEATPUMP_DRIVER` (`vicare` | `mock`). The factory in
`src/drivers/__init__.py` uses lazy imports so PyViCare is not required when running the
`mock` driver or unit tests.

## Bring your own driver

To add a new heat-pump driver (in-tree or out-of-tree):

1. Create a class with a `poll(self) -> dict | None` method that returns a reading keyed
   by `HEATPUMP_FIELDS` (import from `contract.py`).
2. Register it in `src/drivers/__init__.py`'s `get_driver()` factory and add it to
   `SUPPORTED_DRIVERS`.
3. Vendor credentials / config should be read from env vars in the driver's own module;
   `validate_env()` in `src/main.py` only requires `DB_*` and the driver name — driver-
   specific validation is the driver's responsibility.

The `mock` driver (`src/drivers/mock.py`) is the minimal working reference: ~40 lines,
no dependencies beyond the standard library, returns a realistic-shaped reading with
monotonically rising energy counters.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `HEATPUMP_DRIVER` | `vicare` | Which driver to load (`vicare` or `mock`) |
| `HEATPUMP_LABEL` | *(empty)* | Display label for the heat-pump card in the UI (e.g. `Vitocal 250 A06`). Empty → neutral "Heat pump" / "Wärmepumpe" title |
| `HEATPUMP_POLL_SECONDS` | `300` | Poll cadence in seconds (generic shell) |

The `vicare` driver additionally reads `VICARE_USER`, `VICARE_PASS`, `VICARE_CLIENT_ID`,
`VICARE_DAILY_CAP`, `VICARE_BUDGET_FILE`, and `VICARE_TOKEN_FILE` — see
[`deploy/compose/.env.example`](../deploy/compose/.env.example) for descriptions.

## Related docs

- [`docs/state-interface.md`](state-interface.md) — the energy-exporter's `/state` contract (meter readings → controller)
- [`docs/architecture.md`](architecture.md) — service overview and data-flow diagram
- [`docs/hardware.md`](hardware.md) — ViCare API quirks (driver-specific), Shelly, SMA notes
