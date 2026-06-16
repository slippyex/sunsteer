# Generic Heat-Pump Telemetry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Viessmann-hardcoded heat-pump telemetry path with a generic, vendor-neutral contract served by a renamed `heatpump-exporter` that pulls vendor data through a pluggable `HEATPUMP_DRIVER` (`vicare` | `mock`), mirroring `energy-exporter`'s `METER_DRIVER` pattern.

**Architecture:** A generic exporter shell (poll loop, DB writer, generic `heatpump_*` metrics) is driver-agnostic; each driver returns a reading keyed by the shell-owned contract `HEATPUMP_FIELDS`. The `vicare` driver encapsulates today's Viessmann logic (auth, rate budget, token, extract); the `mock` driver emits synthetic telemetry for the demo/tests. The DB table `heatpump_vicare` is renamed `heatpump_telemetry` and metrics `vicare_*` → `heatpump_*`. Shipped as breaking **0.4.0**.

**Tech Stack:** Python 3.12, psycopg2, prometheus_client, PyViCare (vicare driver only), TimescaleDB, pytest, ruff, mypy, Docker Compose + Kubernetes.

---

## Conventions for this plan

- **Spec:** `docs/superpowers/specs/2026-06-15-generic-heatpump-telemetry-design.md`. Read it first.
- **Git:** the repo owner performs all `git commit` / `git push` / tag operations manually
  (project rule). Treat every "Commit" step as a **checkpoint**: stage with `git add`, run the
  verification, then hand the staged change to the owner (or leave staged). Do **not** run
  `git commit`/`push`/`tag` yourself.
- **Service path:** until Task 8 the service still lives at `services/vicare-exporter/`. From
  Task 8 on it is `services/heatpump-exporter/`. Steps name the correct path per task.
- **Running tests locally:**
  - exporter (pre-rename): `cd services/vicare-exporter && .venv/bin/python -m pytest tests/ -q`
    (the `.venv` is the py3.12 env created earlier; recreate with
    `python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest` if missing).
  - control-ui: `cd services/control-ui && .venv/bin/python -m pytest tests/ -q`
  - energy / surplus: `cd services/<svc> && python3 -m pytest tests/ -q`
  - integration (needs a TimescaleDB): start one and apply schema —
    ```
    docker run -d --name sunsteer-testdb -e POSTGRES_USER=sunsteer -e POSTGRES_PASSWORD=sunsteer \
      -e POSTGRES_DB=energy -p 5544:5432 \
      timescale/timescaledb@sha256:22e8a5ae7aef121d1537afe946dd7cc5deeeb63ab36ce19849d671bd3b663509
    export PGPASSWORD=sunsteer
    psql -h localhost -p 5544 -U sunsteer -d energy -f db/init.sql
    for f in $(find db/migrations -name '*.sql' | sort); do psql -h localhost -p 5544 -U sunsteer -d energy -v ON_ERROR_STOP=1 -f "$f"; done
    ```
    then `PGHOST=localhost PGPORT=5544 PGDATABASE=energy PGUSER=sunsteer PGPASSWORD=sunsteer python -m pytest tests/integration -q`
- **mypy gate (local):** `mypy --config-file mypy.ini <files from .github/workflows/ci.yml>`.

---

## Phase 1 — Database contract

### Task 1: Rename `heatpump_vicare` → `heatpump_telemetry`

**Files:**
- Create: `db/migrations/003-generic-heatpump-telemetry.sql`
- Modify: `db/init.sql` (the `heatpump_vicare` CREATE/hypertable/retention block, ~lines 35–61)
- Test: `tests/integration/test_db.py` (add a rename-survival check)

- [ ] **Step 1: Write the failing integration test**

Add to `tests/integration/test_db.py`:

```python
def test_heatpump_telemetry_table_exists_and_vicare_is_gone():
    # The generic contract table replaces the vendor-named one; data is preserved by a RENAME.
    c = _conn()
    with c.cursor() as cur:
        cur.execute("SELECT to_regclass('public.heatpump_telemetry'), "
                    "to_regclass('public.heatpump_vicare')")
        new, old = cur.fetchone()
    c.close()
    assert new is not None        # heatpump_telemetry exists
    assert old is None            # heatpump_vicare no longer exists
```

- [ ] **Step 2: Run it to verify it fails**

Bring up a fresh DB (drop+recreate the test container, apply `db/init.sql` + existing
migrations 001/002 only — NOT 003 yet), then:
Run: `PGHOST=localhost PGPORT=5544 PGDATABASE=energy PGUSER=sunsteer PGPASSWORD=sunsteer python -m pytest tests/integration/test_db.py::test_heatpump_telemetry_table_exists_and_vicare_is_gone -q`
Expected: FAIL — `heatpump_telemetry` is None, `heatpump_vicare` still exists.

- [ ] **Step 3: Write the migration**

Create `db/migrations/003-generic-heatpump-telemetry.sql`:

```sql
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
```

- [ ] **Step 4: Update the init.sql snapshot**

In `db/init.sql`, in the heat-pump telemetry block:
- Change the comment to: `-- Heat-pump telemetry (read-only). Column NAMES must match the generic contract (HEATPUMP_FIELDS in heatpump-exporter), enforced by tests/integration/test_config_consistency.py.`
- `CREATE TABLE IF NOT EXISTS heatpump_vicare (` → `CREATE TABLE IF NOT EXISTS heatpump_telemetry (`
- `SELECT create_hypertable('heatpump_vicare', 'time', ...)` → `'heatpump_telemetry'`
- `SELECT add_retention_policy('heatpump_vicare', ...)` → `'heatpump_telemetry'`

- [ ] **Step 5: Run the test to verify it passes**

Re-apply migrations (now including 003) against the test DB, then:
Run: `... python -m pytest tests/integration/test_db.py -q`
Expected: PASS (the new test + the existing ones).

- [ ] **Step 6: Verify retention survived + idempotency**

```bash
psql -h localhost -p 5544 -U sunsteer -d energy -c \
  "SELECT hypertable_name FROM timescaledb_information.jobs j JOIN timescaledb_information.hypertables h ON true WHERE hypertable_name='heatpump_telemetry';" || true
# apply 003 twice -> second run is a no-op (no error)
psql -h localhost -p 5544 -U sunsteer -d energy -v ON_ERROR_STOP=1 -f db/migrations/003-generic-heatpump-telemetry.sql
```
Expected: second apply succeeds (idempotent); the retention job is attached to `heatpump_telemetry`.

- [ ] **Step 7: Checkpoint (owner commits)**

```bash
git add db/migrations/003-generic-heatpump-telemetry.sql db/init.sql tests/integration/test_db.py
# owner: git commit -m "feat(db): rename heatpump_vicare -> heatpump_telemetry (003)"
```

---

## Phase 2 — Generic output contract in the exporter (still at services/vicare-exporter/)

### Task 2: Shell-owned contract constants

**Files:**
- Create: `services/vicare-exporter/src/contract.py`
- Modify: `services/vicare-exporter/src/extract.py` (re-export FIELDS from contract)
- Test: `services/vicare-exporter/tests/test_contract.py`

- [ ] **Step 1: Write the failing test**

Create `services/vicare-exporter/tests/test_contract.py`:

```python
from src.contract import HEATPUMP_FIELDS, HEATPUMP_STRING_FIELDS


def test_contract_fields_are_the_telemetry_keys():
    # The shell owns the contract; it must list exactly today's telemetry fields.
    assert "dhw_temp_c" in HEATPUMP_FIELDS and "compressor_hours" in HEATPUMP_FIELDS
    assert HEATPUMP_STRING_FIELDS == {"dhw_mode", "energy_read_at"}
    assert len(HEATPUMP_FIELDS) == 19
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd services/vicare-exporter && .venv/bin/python -m pytest tests/test_contract.py -q`
Expected: FAIL — `No module named 'src.contract'`.

- [ ] **Step 3: Create the contract module**

Create `services/vicare-exporter/src/contract.py`:

```python
"""The generic heat-pump telemetry contract: the field list every driver must emit and the
DB/metric layers consume. Vendor-neutral — drivers map their own data onto these keys."""

# Ordered field list — single source of truth for DB columns + gauges (and their order).
HEATPUMP_FIELDS = [
    "dhw_temp_c", "dhw_target_c", "dhw_mode", "buffer_temp_c", "outside_temp_c",
    "supply_temp_c", "energy_total_kwh", "energy_heating_kwh", "energy_dhw_kwh",
    "energy_read_at", "heat_heating_kwh", "heat_dhw_kwh", "heatingrod_heating_kwh",
    "heatingrod_dhw_kwh", "scop_total", "spf_total", "compressor_speed_rps",
    "compressor_starts", "compressor_hours",
]
# Non-numeric fields: text columns only, not turned into Prometheus gauges.
HEATPUMP_STRING_FIELDS = {"dhw_mode", "energy_read_at"}
```

- [ ] **Step 4: Re-point extract.py at the contract (keep behaviour)**

In `services/vicare-exporter/src/extract.py`, replace the `FIELDS = list(_FIELDS.keys())` /
`STRING_FIELDS = {...}` lines with a re-export, so the Viessmann `_FIELDS` mapping stays but the
contract is shared:

```python
from .contract import HEATPUMP_FIELDS, HEATPUMP_STRING_FIELDS

# extract still owns the Viessmann feature->field MAPPING (_FIELDS above); the contract
# (which keys/order) is shell-owned. Guard that the mapping covers exactly the contract.
assert list(_FIELDS.keys()) == HEATPUMP_FIELDS, "vicare _FIELDS drifted from HEATPUMP_FIELDS"
FIELDS = HEATPUMP_FIELDS
STRING_FIELDS = HEATPUMP_STRING_FIELDS
```

- [ ] **Step 5: Run tests to verify pass**

Run: `cd services/vicare-exporter && .venv/bin/python -m pytest tests/ -q`
Expected: PASS (test_contract + all existing tests; the assert holds because the lists match).

- [ ] **Step 6: Checkpoint (owner commits)**

```bash
git add services/vicare-exporter/src/contract.py services/vicare-exporter/src/extract.py services/vicare-exporter/tests/test_contract.py
```

### Task 3: Generic telemetry metrics (`heatpump_*`)

**Files:**
- Modify: `services/vicare-exporter/src/metrics.py`
- Test: `services/vicare-exporter/tests/test_metrics.py`, `tests/test_metrics_inverter.py` n/a

- [ ] **Step 1: Write the failing test**

Add to `services/vicare-exporter/tests/test_metrics.py`:

```python
def test_gauges_use_generic_heatpump_prefix():
    from src import metrics
    # Telemetry gauges are the generic contract the UI reads — heatpump_*, not vicare_*.
    g = metrics.GAUGES["dhw_temp_c"]
    assert any(s.name == "heatpump_dhw_temp_c" for s in g.collect())


def test_liveness_metric_is_generic():
    from src import metrics
    assert any(s.name == "heatpump_last_success_timestamp_seconds"
               for s in metrics.LAST_SUCCESS.collect())
```

- [ ] **Step 2: Run to verify fail**

Run: `cd services/vicare-exporter && .venv/bin/python -m pytest tests/test_metrics.py -q -k generic`
Expected: FAIL — gauges are still named `vicare_*`.

- [ ] **Step 3: Rename the generic metrics**

In `services/vicare-exporter/src/metrics.py`:
- Import the contract: `from .contract import HEATPUMP_FIELDS, HEATPUMP_STRING_FIELDS` (replace the
  `from .extract import FIELDS, STRING_FIELDS` import).
- Build gauges generically:
  ```python
  GAUGES = {f: Gauge(f"heatpump_{f}", f"Heat pump {f}")
            for f in HEATPUMP_FIELDS if f not in HEATPUMP_STRING_FIELDS}
  ```
- Rename the **generic** liveness/health metrics to `heatpump_*`:
  - `SCRAPE_ERRORS = Counter("heatpump_scrape_errors_total", "Poll/parse errors", ["stage"])`
  - `LAST_SUCCESS = Gauge("heatpump_last_success_timestamp_seconds", "Unix ts of last successful poll")`
  - `ENERGY_READ_AT = Gauge("heatpump_energy_read_at_timestamp_seconds", ...)`
- **Leave the vendor-operational metrics named `vicare_*`** (they move to the vicare driver in
  Task 5): `API_CALLS`, `RATE_LIMITED`, `INVALID_CREDENTIALS`, `BUDGET_EXHAUSTED`, `BUDGET_USED`.

- [ ] **Step 4: Run to verify pass**

Run: `cd services/vicare-exporter && .venv/bin/python -m pytest tests/test_metrics.py -q`
Expected: PASS.

- [ ] **Step 5: Checkpoint (owner commits)**

```bash
git add services/vicare-exporter/src/metrics.py services/vicare-exporter/tests/test_metrics.py
```

### Task 4: Writer targets `heatpump_telemetry`

**Files:**
- Modify: `services/vicare-exporter/src/tsdb_writer.py`
- Test: `tests/integration/test_db.py` (retarget the vicare write test)

- [ ] **Step 1: Update the integration test**

In `tests/integration/test_db.py`, the test that imports the vicare `tsdb_writer` and calls
`w.write(...)` — assert it reads back from `heatpump_telemetry`:

```python
def test_heatpump_writer_against_real_schema():
    _drop_src_modules()
    sys.path.insert(0, os.path.join(ROOT, "services", "vicare-exporter"))  # path updated in Task 8
    from src import tsdb_writer as w  # type: ignore
    c = _conn()
    w.write(c, {"dhw_temp_c": 51.0, "compressor_starts": 5})
    with c.cursor() as cur:
        cur.execute("SELECT dhw_temp_c, compressor_starts FROM heatpump_telemetry ORDER BY time DESC LIMIT 1")
        row = cur.fetchone()
    c.close()
    assert row == (51.0, 5.0)
```

- [ ] **Step 2: Run to verify fail**

Run: `... python -m pytest tests/integration/test_db.py::test_heatpump_writer_against_real_schema -q`
Expected: FAIL — the writer still inserts into `heatpump_vicare`.

- [ ] **Step 3: Update the writer**

In `services/vicare-exporter/src/tsdb_writer.py`:
- `from .extract import FIELDS` → `from .contract import HEATPUMP_FIELDS`
- `COLUMNS = list(FIELDS)` → `COLUMNS = list(HEATPUMP_FIELDS)`
- In `write()`, `INSERT INTO heatpump_vicare (time, {cols})` → `INSERT INTO heatpump_telemetry (time, {cols})`

- [ ] **Step 4: Run to verify pass**

Run: `... python -m pytest tests/integration/test_db.py -q`
Expected: PASS.

- [ ] **Step 5: Checkpoint (owner commits)**

```bash
git add services/vicare-exporter/src/tsdb_writer.py tests/integration/test_db.py
```

---

## Phase 3 — Driver abstraction (the heart of the change)

### Task 5: Introduce `HeatPumpDriver` Protocol + factory + the `vicare` driver

**Files:**
- Create: `services/vicare-exporter/src/drivers/__init__.py`
- Create: `services/vicare-exporter/src/drivers/vicare.py`
- Create: `services/vicare-exporter/src/drivers/vicare_metrics.py`
- Test: `services/vicare-exporter/tests/test_drivers.py`

- [ ] **Step 1: Write the failing factory test**

Create `services/vicare-exporter/tests/test_drivers.py`:

```python
import pytest
import src.drivers as D


def test_get_driver_unknown_fails_fast():
    with pytest.raises(SystemExit) as e:
        D.get_driver("nope")
    assert "HEATPUMP_DRIVER" in str(e.value) and "nope" in str(e.value)


def test_supported_drivers_listed():
    assert "vicare" in D.SUPPORTED_DRIVERS and "mock" in D.SUPPORTED_DRIVERS
```

- [ ] **Step 2: Run to verify fail**

Run: `cd services/vicare-exporter && .venv/bin/python -m pytest tests/test_drivers.py -q`
Expected: FAIL — `No module named 'src.drivers'`.

- [ ] **Step 3: Create the driver package + Protocol + factory**

Create `services/vicare-exporter/src/drivers/__init__.py`:

```python
"""Heat-pump telemetry drivers. The generic exporter shell is driver-agnostic: every driver
returns a reading keyed by contract.HEATPUMP_FIELDS (or None to skip a cycle). New vendors add
a module here + a branch in get_driver() — exactly like energy-exporter's get_meter()."""
from typing import Protocol

__all__ = ("HeatPumpDriver", "SUPPORTED_DRIVERS", "get_driver")

SUPPORTED_DRIVERS = ("vicare", "mock")


class HeatPumpDriver(Protocol):
    def poll(self) -> dict | None:
        """Return one telemetry reading (HEATPUMP_FIELDS-keyed dict) or None to skip this
        cycle (e.g. rate-budget exhausted). Owns its own vendor connection/retry/rate limits;
        transient vendor issues degrade to None rather than raising."""


def get_driver(name):
    if name == "vicare":
        from .vicare import VicareDriver
        return VicareDriver()
    if name == "mock":
        from .mock import MockDriver
        return MockDriver()
    raise SystemExit(f"heatpump-exporter: unknown HEATPUMP_DRIVER '{name}' "
                     f"(supported: {', '.join(SUPPORTED_DRIVERS)})")
```

- [ ] **Step 4: Move the vendor-operational metrics into the driver**

Create `services/vicare-exporter/src/drivers/vicare_metrics.py` and MOVE the vendor-API metrics
out of `src/metrics.py` into it (cut from metrics.py, paste here):

```python
"""ViCare-driver-internal operational metrics (Viessmann API budget/limits) — NOT part of the
generic heatpump_* telemetry contract."""
from prometheus_client import Counter, Gauge

API_CALLS = Counter("vicare_api_calls_total", "ViCare API calls made")
RATE_LIMITED = Counter("vicare_rate_limited_total", "HTTP 429 / limit responses")
INVALID_CREDENTIALS = Counter("vicare_invalid_credentials_total",
                              "Connect attempts rejected as invalid credentials (permanent)")
BUDGET_EXHAUSTED = Gauge("vicare_budget_exhausted", "1 = daily call budget reached, poll skipped")
BUDGET_USED = Gauge("vicare_budget_used", "API calls used in the trailing 24h window")
```

Remove those five definitions from `src/metrics.py`.

- [ ] **Step 5: Create the vicare driver (wrap today's logic)**

Create `services/vicare-exporter/src/drivers/vicare.py`. Move `auth.connect_device`,
`vicare_client.poll`, `extract`, the `RateBudget`, `secure_token_file`, `connect_with_retry`,
`_is_rate_limit`, `_is_invalid_credentials`, `_next_backoff`, and the `VICARE_*`/`POLL_S` env
into this module (cut from `main.py`/keep `auth.py`,`vicare_client.py`,`extract.py`,`ratebudget.py`
as-is and import them). The driver owns connection + budget; `poll()` returns a reading or None:

```python
"""The ViCare (Viessmann) heat-pump telemetry driver. Encapsulates OAuth/discovery, the daily
rate budget, token hardening and the Viessmann feature->contract mapping. Emits the generic
HEATPUMP_FIELDS reading; vendor-API ops are tracked under vicare_* (vicare_metrics)."""
import logging
import os
import time

from .. import vicare_client
from ..auth import connect_device
from ..extract import extract
from ..ratebudget import RateBudget, clamp_interval
from . import vicare_metrics as vm

log = logging.getLogger(__name__)

POLL_S = clamp_interval(os.environ.get("VICARE_POLL_SECONDS",
                                       os.environ.get("HEATPUMP_POLL_SECONDS", "300")))
DAILY_CAP = int(os.environ.get("VICARE_DAILY_CAP", "1400"))
TOKEN_FILE = os.environ.get("VICARE_TOKEN_FILE", "/data/vicare_token.json")
BUDGET_FILE = os.environ.get("VICARE_BUDGET_FILE", "/data/vicare_budget.json")

REQUIRED_ENV = ("VICARE_USER", "VICARE_PASS", "VICARE_CLIENT_ID")


def secure_token_file(path):
    try:
        if os.path.exists(path):
            os.chmod(path, 0o600)
    except OSError:
        log.warning("could not chmod token file %s", path, exc_info=True)


# _is_rate_limit / _is_invalid_credentials / _next_backoff / connect_with_retry:
# MOVE verbatim from main.py (they already reference vm-style metrics — update
# metrics.RATE_LIMITED -> vm.RATE_LIMITED, metrics.INVALID_CREDENTIALS -> vm.INVALID_CREDENTIALS,
# metrics.SCRAPE_ERRORS stays generic: import it from .. import metrics).


class VicareDriver:
    def __init__(self):
        self._device = None
        self._budget = RateBudget(cap=DAILY_CAP, window_s=86400, persist_path=BUDGET_FILE)

    def _ensure_connected(self):
        if self._device is None:
            os.umask(0o077)
            self._device = connect_with_retry(TOKEN_FILE)
            secure_token_file(TOKEN_FILE)

    def poll(self):
        self._ensure_connected()
        now = time.time()
        if not self._budget.allow(now):
            vm.BUDGET_EXHAUSTED.set(1)
            vm.BUDGET_USED.set(self._budget.count(now))
            return None
        vm.BUDGET_EXHAUSTED.set(0)
        features = vicare_client.poll(self._device)
        self._budget.record(now)
        vm.API_CALLS.inc()
        vm.BUDGET_USED.set(self._budget.count(now))
        return extract(features)
```

- [ ] **Step 6: Move the vicare validate-env + tests**

Move `validate_env`'s `VICARE_*` requirement and the `connect_with_retry` / `_next_backoff` /
`secure_token_file` / `_is_*` tests from `tests/test_main.py` into a new
`tests/test_vicare_driver.py`, importing from `src.drivers.vicare`. Keep their assertions
identical (the behaviour is unchanged, only the home moved). Update monkeypatch targets:
`main.auth` → `vicare.connect_device`, `main.time` → `vicare.time`, `metrics.RATE_LIMITED` →
`vicare_metrics.RATE_LIMITED`, etc.

- [ ] **Step 7: Run to verify pass**

Run: `cd services/vicare-exporter && .venv/bin/python -m pytest tests/test_drivers.py tests/test_vicare_driver.py -q`
Expected: PASS.

- [ ] **Step 8: Checkpoint (owner commits)**

```bash
git add services/vicare-exporter/src/drivers/ services/vicare-exporter/tests/test_drivers.py services/vicare-exporter/tests/test_vicare_driver.py
```

### Task 6: The `mock` driver

**Files:**
- Create: `services/vicare-exporter/src/drivers/mock.py`
- Test: `services/vicare-exporter/tests/test_mock_driver.py`

- [ ] **Step 1: Write the failing test**

Create `services/vicare-exporter/tests/test_mock_driver.py`:

```python
from src.contract import HEATPUMP_FIELDS
from src.drivers.mock import MockDriver


def test_mock_poll_returns_full_contract_reading():
    r = MockDriver().poll()
    assert set(r.keys()) == set(HEATPUMP_FIELDS)
    assert isinstance(r["dhw_temp_c"], float)


def test_mock_energy_counters_are_monotonic():
    d = MockDriver()
    r1, r2 = d.poll(), d.poll()
    assert r2["energy_total_kwh"] >= r1["energy_total_kwh"]
```

- [ ] **Step 2: Run to verify fail**

Run: `cd services/vicare-exporter && .venv/bin/python -m pytest tests/test_mock_driver.py -q`
Expected: FAIL — `No module named 'src.drivers.mock'`.

- [ ] **Step 3: Implement the mock driver**

Create `services/vicare-exporter/src/drivers/mock.py`:

```python
"""Synthetic heat-pump telemetry so the demo (and tests) show the heat-pump card without real
vendor credentials — the heat-pump analogue of the mock grid meter."""
import math

from ..contract import HEATPUMP_FIELDS

_DEMO_PERIOD_S = 600.0   # one synthetic 'day' every 10 min (matches the mock meter cadence)


class MockDriver:
    def __init__(self):
        self._n = 0
        self._energy = 100.0   # kWh lifetime counters, monotonically rising

    def poll(self):
        self._n += 1
        phase = (self._n % _DEMO_PERIOD_S) / _DEMO_PERIOD_S
        warmth = 0.5 + 0.5 * math.sin(2 * math.pi * phase)   # 0..1 over the synthetic day
        self._energy += 0.05
        reading = {f: None for f in HEATPUMP_FIELDS}
        reading.update({
            "dhw_temp_c": round(45.0 + 5.0 * warmth, 1),
            "dhw_target_c": 50.0,
            "dhw_mode": "dhw",
            "buffer_temp_c": round(35.0 + 5.0 * warmth, 1),
            "outside_temp_c": round(2.0 + 12.0 * warmth, 1),
            "supply_temp_c": round(38.0 + 4.0 * warmth, 1),
            "energy_total_kwh": round(self._energy, 2),
            "energy_heating_kwh": round(self._energy * 0.7, 2),
            "energy_dhw_kwh": round(self._energy * 0.3, 2),
            "scop_total": 4.2, "spf_total": 4.0,
            "compressor_speed_rps": round(30.0 + 40.0 * warmth, 1),
            "compressor_starts": float(self._n),
            "compressor_hours": round(self._n * 0.1, 1),
            "heat_heating_kwh": round(self._energy * 2.0, 2),
            "heat_dhw_kwh": round(self._energy * 0.8, 2),
            "heatingrod_heating_kwh": 0.0, "heatingrod_dhw_kwh": 0.0,
            # energy_read_at left None (mock has no lag)
        })
        return reading
```

- [ ] **Step 4: Run to verify pass**

Run: `cd services/vicare-exporter && .venv/bin/python -m pytest tests/test_mock_driver.py -q`
Expected: PASS.

- [ ] **Step 5: Checkpoint (owner commits)**

```bash
git add services/vicare-exporter/src/drivers/mock.py services/vicare-exporter/tests/test_mock_driver.py
```

### Task 7: Generic shell loop (`main.py`) uses the driver

**Files:**
- Modify: `services/vicare-exporter/src/main.py`
- Test: `services/vicare-exporter/tests/test_main.py`

- [ ] **Step 1: Write the failing tests**

Replace the loop-specific tests in `tests/test_main.py` (the ones referencing `run_cycle`,
`connect_with_retry`, etc. — those moved to the driver) with shell tests:

```python
import src.main as main


class _FakeDriver:
    def __init__(self, readings):
        self._readings = list(readings)
    def poll(self):
        return self._readings.pop(0) if self._readings else None


def test_validate_env_lists_missing(monkeypatch):
    for v in ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASS"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("HEATPUMP_DRIVER", "mock")   # mock needs no vendor creds
    import pytest
    with pytest.raises(SystemExit) as e:
        main.validate_env()
    assert "DB_HOST" in str(e.value)


def test_run_cycle_writes_reading_and_sets_liveness(monkeypatch):
    wrote = {}
    monkeypatch.setattr(main.tsdb_writer, "write", lambda c, d: wrote.update(d))
    main.run_cycle(_FakeDriver([{"dhw_temp_c": 9.0}]), conn=object())
    assert wrote["dhw_temp_c"] == 9.0


def test_run_cycle_skips_on_none(monkeypatch):
    wrote = {"n": 0}
    monkeypatch.setattr(main.tsdb_writer, "write", lambda c, d: wrote.__setitem__("n", wrote["n"] + 1))
    main.run_cycle(_FakeDriver([None]), conn=object())
    assert wrote["n"] == 0
```

- [ ] **Step 2: Run to verify fail**

Run: `cd services/vicare-exporter && .venv/bin/python -m pytest tests/test_main.py -q -k "run_cycle or validate_env"`
Expected: FAIL — `run_cycle` signature/`validate_env` env set changed; vendor creds still required.

- [ ] **Step 3: Rewrite main.py as the generic shell**

Replace `services/vicare-exporter/src/main.py` with the driver-based shell. Key points:
- `REQUIRED_ENV = ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASS")` (vendor creds are the driver's
  concern — the `vicare` driver validates `VICARE_*` itself via its `REQUIRED_ENV`; call it from
  `validate_env()` when the selected driver is `vicare`).
- `HEATPUMP_DRIVER = os.environ.get("HEATPUMP_DRIVER", "vicare")`.
- `POLL_S = clamp_interval(os.environ.get("HEATPUMP_POLL_SECONDS", os.environ.get("VICARE_POLL_SECONDS", "300")))`.

```python
"""heatpump-exporter: poll the configured driver -> Prometheus + TimescaleDB. READ-ONLY."""
import logging
import os
import time

from prometheus_client import start_http_server

from . import drivers, metrics, tsdb_writer
from .ratebudget import clamp_interval

log = logging.getLogger(__name__)

METRICS_PORT = int(os.environ.get("METRICS_PORT", "9125"))
HEATPUMP_DRIVER = os.environ.get("HEATPUMP_DRIVER", "vicare")
POLL_S = clamp_interval(os.environ.get("HEATPUMP_POLL_SECONDS",
                                       os.environ.get("VICARE_POLL_SECONDS", "300")))
REQUIRED_ENV = ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASS")


def validate_env():
    required = list(REQUIRED_ENV)
    if HEATPUMP_DRIVER == "vicare":
        from .drivers.vicare import REQUIRED_ENV as VICARE_ENV
        required += list(VICARE_ENV)
    missing = [n for n in required if not os.environ.get(n)]
    if missing:
        raise SystemExit("heatpump-exporter: missing required environment variables: "
                         + ", ".join(missing))
    placeholders = [n for n in required if "CHANGE_ME" in os.environ.get(n, "")]
    if placeholders:
        raise SystemExit("heatpump-exporter: unsubstituted CHANGE_ME placeholder in: "
                         + ", ".join(placeholders))


def run_cycle(driver, conn):
    """One poll cycle. The driver returns a reading or None (skip). Guarded by the caller."""
    reading = driver.poll()
    if reading is None:
        return
    metrics.set_from(reading)
    if conn is not None:
        tsdb_writer.write(conn, reading)
    metrics.LAST_SUCCESS.set(time.time())


def _db():
    return tsdb_writer.connect(
        os.environ["DB_HOST"], int(os.environ.get("DB_PORT", "5432")),
        os.environ["DB_NAME"], os.environ["DB_USER"], os.environ["DB_PASS"])


def main():
    validate_env()
    start_http_server(METRICS_PORT)
    if HEATPUMP_DRIVER not in drivers.SUPPORTED_DRIVERS:
        raise SystemExit(f"heatpump-exporter: unknown HEATPUMP_DRIVER '{HEATPUMP_DRIVER}'")
    driver = drivers.get_driver(HEATPUMP_DRIVER)
    conn = None
    backoff = 0
    while True:
        try:
            conn = tsdb_writer.live_conn(conn, _db)
            run_cycle(driver, conn)
            backoff = 0
        except Exception:
            metrics.SCRAPE_ERRORS.labels("cycle").inc()
            conn = None
            backoff = min(backoff + POLL_S, 1800)
        time.sleep(POLL_S + backoff)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the full exporter suite**

Run: `cd services/vicare-exporter && .venv/bin/python -m pytest tests/ -q`
Expected: PASS. Run `ruff check services/vicare-exporter` and the mypy gate subset — clean.

- [ ] **Step 5: Checkpoint (owner commits)**

```bash
git add services/vicare-exporter/src/main.py services/vicare-exporter/tests/test_main.py
```

---

## Phase 4 — Rename the service to `heatpump-exporter`

### Task 8: Mechanical rename `vicare-exporter` → `heatpump-exporter`

**Files (rename + reference updates):**
- `git mv services/vicare-exporter services/heatpump-exporter`
- Modify: `.github/workflows/ci.yml` (test + image-scan matrices, mypy file paths),
  `.github/workflows/release.yml` (matrix if present), `.github/dependabot.yml` (pip directory),
  `tests/integration/test_db.py` (sys.path insert), `mypy.ini` comment, the per-service
  `.dockerignore` (moves with the dir)

- [ ] **Step 1: Rename the directory**

```bash
git mv services/vicare-exporter services/heatpump-exporter
```

- [ ] **Step 2: Update CI + dependabot + integration path references**

- `.github/workflows/ci.yml`: in both `matrix: service: [...]` lists, `vicare-exporter` →
  `heatpump-exporter`; in the mypy step, `services/vicare-exporter/src/...` →
  `services/heatpump-exporter/src/...` (extract, ratebudget, metrics, auth — and add
  `services/heatpump-exporter/src/drivers/mock.py` if mypy-clean).
- `.github/workflows/release.yml`: same matrix rename if it lists services.
- `.github/dependabot.yml`: `directory: /services/vicare-exporter` → `/services/heatpump-exporter`
  and the `commit-message.prefix` `deps(vicare-exporter)` → `deps(heatpump-exporter)`.
- `tests/integration/test_db.py`: the `sys.path.insert(..., "vicare-exporter")` →
  `"heatpump-exporter"`.

- [ ] **Step 3: Verify nothing still points at the old path**

Run: `grep -rn "vicare-exporter" .github/ tests/ mypy.ini deploy/ | grep -v node_modules`
Expected: only intentional historical CHANGELOG lines (handled in Task 13); no live path refs.

- [ ] **Step 4: Run the renamed service's tests + mypy + ruff**

Run: `cd services/heatpump-exporter && .venv/bin/python -m pytest tests/ -q` (recreate `.venv`
if the move invalidated it). Run the repo `ruff check .` and the mypy gate (now with
`heatpump-exporter` paths) — clean.

- [ ] **Step 5: Checkpoint (owner commits)**

```bash
git add -A services/heatpump-exporter .github/ tests/integration/test_db.py mypy.ini
```

### Task 9: Deploy manifests — service rename + driver wiring

**Files:**
- Rename: `deploy/k8s/vicare-exporter.yaml` → `deploy/k8s/heatpump-exporter.yaml`
- Modify: `deploy/k8s/kustomization.yaml`, `deploy/compose/docker-compose.yml`,
  `deploy/compose/docker-compose.demo.yml`

- [ ] **Step 1: Rename + update the k8s manifest**

```bash
git mv deploy/k8s/vicare-exporter.yaml deploy/k8s/heatpump-exporter.yaml
```
In it: `name: vicare-exporter` → `heatpump-exporter`, image
`ghcr.io/slippyex/sunsteer/vicare-exporter` → `.../heatpump-exporter`, add env
`{ name: HEATPUMP_DRIVER, value: "vicare" }`. Keep the `VICARE_*` secret env (vicare-driver
config) and the token PVC.

- [ ] **Step 2: kustomization**

In `deploy/k8s/kustomization.yaml`: the commented `# - vicare-exporter.yaml` →
`# - heatpump-exporter.yaml`; the `images:` entry name
`.../vicare-exporter` → `.../heatpump-exporter`.

- [ ] **Step 3: compose (prod) — vicare driver, opt-in**

In `deploy/compose/docker-compose.yml`: service `vicare-exporter:` → `heatpump-exporter:`, image
`.../heatpump-exporter:${SUNSTEER_VERSION:-...}`, keep `profiles: ["vicare"]` (or rename to
`["heatpump"]` — pick one and update README), add `HEATPUMP_DRIVER: vicare`, keep `VICARE_*`.

- [ ] **Step 4: compose (demo) — mock driver, always on (shows the card)**

In `deploy/compose/docker-compose.demo.yml`, add a `heatpump-exporter` service (no profile, so
it runs in the zero-config demo):

```yaml
  heatpump-exporter:
    image: ghcr.io/slippyex/sunsteer/heatpump-exporter:${SUNSTEER_VERSION:-0.4.0}
    build: ../../services/heatpump-exporter
    environment:
      HEATPUMP_DRIVER: mock
      DB_HOST: timescaledb
      DB_NAME: energy
      DB_USER: sunsteer
      DB_PASS: sunsteer
    depends_on:
      timescaledb: { condition: service_healthy }
      db-migrate: { condition: service_completed_successfully }
    security_opt: [ "no-new-privileges:true" ]
    cap_drop: [ "ALL" ]
    deploy: { resources: { limits: { memory: 128M } } }
```

- [ ] **Step 5: Validate compose**

Run: `docker compose -f deploy/compose/docker-compose.yml config >/dev/null && echo prod-OK`
Run: `docker compose -f deploy/compose/docker-compose.demo.yml config >/dev/null && echo demo-OK`
Expected: both OK.

- [ ] **Step 6: Checkpoint (owner commits)**

```bash
git add deploy/
```

---

## Phase 5 — control-ui (vendor-neutral + HEATPUMP_LABEL)

### Task 10: Generic metric dict, queries, route, template

**Files:**
- Modify: `services/control-ui/src/app.py` (`_VICARE` → `_HEATPUMP`, route, label),
  `services/control-ui/src/sources.py` (queries), `services/control-ui/src/i18n.py`
- Rename: `services/control-ui/templates/partials/vicare.html` → `partials/heatpump.html`
- Modify: `services/control-ui/templates/index.html` (the `#vicare` hx-get block)
- Test: `services/control-ui/tests/test_app.py`, `tests/test_sources.py`

- [ ] **Step 1: Write the failing tests**

Add to `services/control-ui/tests/test_app.py`:

```python
def test_heatpump_label_empty_hides_tag(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(appmod, "HEATPUMP_LABEL", "")
    monkeypatch.setattr(appmod.sources, "prom_query", lambda *a, **k: 1.0)
    r = TestClient(appmod.app).get("/partials/heatpump")
    assert r.status_code == 200
    assert "VICARE" not in r.text          # no vendor tag when unset


def test_heatpump_label_shown_as_tag(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(appmod, "HEATPUMP_LABEL", "Vitocal 250 A06")
    monkeypatch.setattr(appmod.sources, "prom_query", lambda *a, **k: 1.0)
    r = TestClient(appmod.app).get("/partials/heatpump")
    assert "Vitocal 250 A06" in r.text
```

- [ ] **Step 2: Run to verify fail**

Run: `cd services/control-ui && .venv/bin/python -m pytest tests/test_app.py -q -k heatpump_label`
Expected: FAIL — route `/partials/heatpump` and `HEATPUMP_LABEL` don't exist.

- [ ] **Step 3: app.py — metric dict, label, route**

- Add near the other env reads: `HEATPUMP_LABEL = os.environ.get("HEATPUMP_LABEL", "").strip()`.
- `_VICARE = { "dhw_temp": "vicare_dhw_temp_c", ... }` → `_HEATPUMP = { "dhw_temp": "heatpump_dhw_temp_c", ... }`
  (replace every `vicare_` prefix with `heatpump_`; the staleness/read_at metric becomes
  `heatpump_energy_read_at_timestamp_seconds`).
- Route `@app.get("/partials/vicare")` def `vicare(...)` → `@app.get("/partials/heatpump")` def
  `heatpump(...)`; iterate `_HEATPUMP`; pass `label=HEATPUMP_LABEL` into the render context;
  render `partials/heatpump.html`.

- [ ] **Step 4: sources.py — queries**

Replace `heatpump_vicare` → `heatpump_telemetry` in the three queries (`wp_history`/temps/
efficiency around lines 243/281/311). Reword ViCare-named docstrings to "heat-pump telemetry".

- [ ] **Step 5: i18n.py — neutralize**

- `"sec_vicare": ("Wärmepumpe · ViCare", "Heat pump · ViCare")` → `"sec_heatpump": ("Wärmepumpe", "Heat pump")`.
- Reword the `scop_tip`, `el_pending_tip`, `hist_eff_note` strings to drop "Viessmann"/"Vitocal
  250-A"/"ViCare" — phrase generically (e.g. "Reported by the heat pump; energy/efficiency may
  lag a day or two"). The concrete model name lives only in `HEATPUMP_LABEL`.

- [ ] **Step 6: templates — rename + tag from label**

```bash
git mv services/control-ui/templates/partials/vicare.html services/control-ui/templates/partials/heatpump.html
```
In `partials/heatpump.html`: `{{ t('sec_vicare') }}` → `{{ t('sec_heatpump') }}`; the fixed
`<span class="tag">VICARE</span>` → `{% if label %}<span class="tag">{{ label }}</span>{% endif %}`.
In `templates/index.html`: the `<div id="vicare" ... hx-get="/partials/vicare" ...>` →
`id="heatpump"` + `hx-get="/partials/heatpump"`.

- [ ] **Step 7: Run control-ui suite**

Run: `cd services/control-ui && .venv/bin/python -m pytest tests/ -q`
Expected: PASS. `ruff check services/control-ui` clean.

- [ ] **Step 8: Checkpoint (owner commits)**

```bash
git add services/control-ui/
```

---

## Phase 6 — Observability, consistency guard, docs, release

### Task 11: Grafana dashboards + alerts

**Files:**
- Modify: `deploy/compose/monitoring/alerts.yml`, any `deploy/compose/monitoring/**/*.json`
  Grafana dashboards.

- [ ] **Step 1: Find every metric reference**

Run: `grep -rn "vicare_\|heatpump_vicare" deploy/compose/monitoring/`

- [ ] **Step 2: Update them**

- `alerts.yml`: `vicare_last_success_timestamp_seconds` → `heatpump_last_success_timestamp_seconds`
  (and the alert name/labels if they say "vicare").
- Grafana dashboard JSON: replace `vicare_<telemetry>` panel exprs with `heatpump_<telemetry>`.
  The vendor-op panels (budget/rate-limit/invalid-creds), if any, keep `vicare_*`.

- [ ] **Step 3: Verify**

Run: `grep -rn "vicare_dhw\|vicare_scop\|vicare_compressor\|vicare_energy\|heatpump_vicare" deploy/compose/monitoring/`
Expected: no telemetry/`heatpump_vicare` hits (only possibly `vicare_budget_*`/`vicare_rate_*`).

- [ ] **Step 4: Checkpoint (owner commits)**

```bash
git add deploy/compose/monitoring/
```

### Task 12: Consistency guard for the generic contract

**Files:**
- Modify: `tests/integration/test_config_consistency.py`

- [ ] **Step 1: Update the field↔DDL + live_conn guards**

- `test_vicare_fields_match_heatpump_vicare_ddl` → `test_heatpump_fields_match_telemetry_ddl`:
  parse `HEATPUMP_FIELDS` (a list literal) from
  `services/heatpump-exporter/src/contract.py` via `_literal_assign` and compare to
  `_ddl_columns_for("heatpump_telemetry") - {"time"}`.
- `_DB_MODULES`: the third entry path `("vicare-exporter", "tsdb_writer.py")` →
  `("heatpump-exporter", "tsdb_writer.py")`.

- [ ] **Step 2: Run to verify pass**

Run: `python -m pytest tests/integration/test_config_consistency.py -q` (no DB needed).
Expected: PASS (fields match the renamed DDL; live_conn still identical across services).

- [ ] **Step 3: Checkpoint (owner commits)**

```bash
git add tests/integration/test_config_consistency.py
```

### Task 13: Documentation (first-class — completeness-gated)

**Files:**
- Create: `docs/heatpump-interface.md`
- Modify: `README.md`, `docs/architecture.md`, `docs/hardware.md`, `docs/setup.md`,
  `deploy/k8s/README.md`, `SECURITY.md`, `DISCLAIMER.md`, `deploy/compose/.env.example`

- [ ] **Step 1: Write the contract doc**

Create `docs/heatpump-interface.md` mirroring `state-interface.md`/`status-interface.md`: explain
the generic `heatpump_telemetry` table + `heatpump_*` metrics + the `HeatPumpDriver` seam
(`HEATPUMP_DRIVER` = `vicare` | `mock`), and how to add a vendor driver (implement `poll() ->
HEATPUMP_FIELDS reading`). List the fields from `HEATPUMP_FIELDS`.

- [ ] **Step 2: Update each markdown (per the spec's docs checklist)**

- `README.md`: heat-pump telemetry framed as a generic exporter with a `vicare` driver; service
  name `heatpump-exporter`; link `docs/heatpump-interface.md`.
- `docs/architecture.md`: component section + the mermaid node `VICARE[vicare-exporter ...]` →
  `HP_EXP[heatpump-exporter<br/>HEATPUMP_DRIVER]`; the data-model table row `heatpump_vicare` →
  `heatpump_telemetry` (writer `heatpump-exporter`); link the new interface doc.
- `docs/hardware.md`: the "Viessmann ViCare (optional)" section reframed as "the `vicare` driver";
  add a one-line `mock` driver note for the demo.
- `docs/setup.md`: env references → `HEATPUMP_DRIVER`/`HEATPUMP_LABEL`; `VICARE_*` = vicare-driver
  credentials.
- `deploy/k8s/README.md`: `vicare-exporter` opt-in step → `heatpump-exporter`.
- `SECURITY.md`: affected-services list service name.
- `DISCLAIMER.md`: reword the Viessmann mention generically (or keep only as a trademark note).
- `deploy/compose/.env.example`: add a "heat-pump telemetry" block — `HEATPUMP_DRIVER` (vicare |
  mock), `HEATPUMP_LABEL` (e.g. `Vitocal 250 A06`), `HEATPUMP_POLL_SECONDS`; move `VICARE_*`
  under a "vicare driver" sub-heading.

- [ ] **Step 3: Completeness gate**

Run: `grep -rniE "vicare|viessmann|heatpump_vicare|vitocal|vicare-exporter" --include='*.md' . | grep -v "/.venv/" | grep -v "superpowers/" | grep -v CHANGELOG.md | grep -v tasks/`
Expected: only intentional `vicare`-driver references (e.g. "the `vicare` driver", `VICARE_*`
env) — no stray `heatpump_vicare`, `vicare-exporter` service refs, or hardcoded "Vitocal 250-A".

- [ ] **Step 4: Checkpoint (owner commits)**

```bash
git add docs/ README.md SECURITY.md DISCLAIMER.md deploy/k8s/README.md deploy/compose/.env.example
```

### Task 14: CHANGELOG 0.4.0 + version bump + final verification

**Files:**
- Modify: `CHANGELOG.md`, all deploy version strings, `deploy/compose/.env.example`

- [ ] **Step 1: CHANGELOG [0.4.0]**

Add a new `## [0.4.0] - <date>` entry under `[Unreleased]` (keep `[Unreleased]` = "Nothing yet"),
with the breaking note and upgrade steps:

```markdown
## [0.4.0] - <date>

Generic, vendor-neutral heat-pump telemetry. **Breaking:** the ViCare-specific service, DB
table and metric names are replaced by a generic contract behind a pluggable driver.

### Changed
- **`vicare-exporter` → `heatpump-exporter`** with a `HEATPUMP_DRIVER` (`vicare` | `mock`)
  behind a `HeatPumpDriver` protocol — the heat-pump analogue of `METER_DRIVER`. ViCare is now
  one driver; a `mock` driver renders the heat-pump card in the zero-config demo.
- DB table `heatpump_vicare` → **`heatpump_telemetry`** (migration `003`, data preserved).
- Prometheus telemetry metrics `vicare_*` → **`heatpump_*`** (vendor-API ops stay `vicare_*`).
- control-ui is vendor-neutral; the heat-pump card name comes from **`HEATPUMP_LABEL`**.

### Added
- `docs/heatpump-interface.md` — the generic telemetry contract + "bring your own driver".

### Upgrade
- Apply migration `003` (the compose `db-migrate` one-shot does this automatically).
- Switch the image `vicare-exporter:0.3.x` → `heatpump-exporter:0.4.0` with
  `HEATPUMP_DRIVER=vicare` (keep your existing `VICARE_*` secrets).
- Update any custom Grafana panels / external scrapers from `vicare_*`/`heatpump_vicare` to
  `heatpump_*`/`heatpump_telemetry`. Set `HEATPUMP_LABEL` (e.g. `Vitocal 250 A06`).
```
Add the `[0.4.0]` compare link at the bottom; update `[Unreleased]` to `...v0.4.0...HEAD`.

- [ ] **Step 2: Bump version strings 0.3.x → 0.4.0**

```bash
for f in deploy/k8s/*.yaml deploy/compose/docker-compose.yml deploy/compose/docker-compose.demo.yml deploy/compose/.env.example deploy/k8s/kustomization.yaml; do
  perl -pi -e 's/0\.3\.\d+/0.4.0/g' "$f"; done
grep -rn "0\.3\." deploy/ | grep -v compare/v || echo "no 0.3.x left in deploy"
```

- [ ] **Step 3: Full verification sweep**

```bash
# unit suites
(cd services/energy-exporter && python3 -m pytest tests/ -q)
(cd services/surplus-controller && python3 -m pytest tests/ -q)
(cd services/control-ui && .venv/bin/python -m pytest tests/ -q)
(cd services/heatpump-exporter && .venv/bin/python -m pytest tests/ -q)
# integration (DB up + migrations incl 003 applied)
PGHOST=localhost PGPORT=5544 PGDATABASE=energy PGUSER=sunsteer PGPASSWORD=sunsteer python -m pytest tests/integration -q
# lint + types + compose
ruff check .
mypy --config-file mypy.ini <the file list from ci.yml, with heatpump-exporter paths>
docker compose -f deploy/compose/docker-compose.yml config >/dev/null && echo prod-OK
docker compose -f deploy/compose/docker-compose.demo.yml config >/dev/null && echo demo-OK
# final vendor-leak grep (should show only intended `vicare` driver refs)
grep -rniE "heatpump_vicare|vicare-exporter|vitocal 250-a\b" --include='*.py' --include='*.md' --include='*.yml' --include='*.yaml' . | grep -v "/.venv/" | grep -v "superpowers/" | grep -v CHANGELOG.md | grep -v tasks/
```
Expected: all suites green; ruff + mypy clean; compose OK; the grep returns nothing (only the
intended `vicare` driver module/`VICARE_*` env remain, which the pattern excludes).

- [ ] **Step 4: Checkpoint (owner commits + releases)**

```bash
git add CHANGELOG.md deploy/
# owner: git commit -m "feat!: generic heat-pump telemetry (heatpump-exporter, 0.4.0)"
# owner: git tag v0.4.0 && git push origin main --tags   # triggers the release workflow
# owner: gh release create v0.4.0 --notes "$(awk '/^## \[0.4.0\]/{f=1;next} /^## \[0.3/{f=0} f' CHANGELOG.md)"
```

---

## Self-review notes (author)

- **Spec coverage:** DB rename (T1), generic contract constants (T2), `heatpump_*` metrics (T3),
  writer table (T4), driver Protocol + factory + vicare driver (T5), mock driver (T6), generic
  shell (T7), service/image/CI/k8s/compose rename + driver wiring (T8/T9), control-ui neutral +
  `HEATPUMP_LABEL` (T10), Grafana/alerts (T11), consistency guard (T12), full docs incl. new
  interface doc (T13), CHANGELOG 0.4.0 + version bump + verification (T14). All spec sections map
  to a task.
- **Risk controls:** every behaviour move (driver split) keeps the existing tests, only relocated;
  the migration is idempotent and verified twice; completeness greps gate both the rename and the
  docs; the cross-service `live_conn`/contract consistency tests catch drift introduced by the
  rename.
- **Ordering:** DB first (foundation), then output-generic (metrics/table) while structure is
  unchanged, then the driver split, then the mechanical rename, then UI, then observability/docs/
  release — each step keeps the suite green.
