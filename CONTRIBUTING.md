# Contributing to Sunsteer

Thanks for considering a contribution! This page covers the local workflow and the two
ways to add support for new hardware.

## Development setup

Each service under `services/` is self-contained: `src/`, `tests/`, `requirements.txt`,
`pyproject.toml` and a multi-stage `Dockerfile` whose **`test` stage is the single
source of truth for "tests green"** — CI runs exactly this:

```bash
docker build --target test services/energy-exporter     # fails if the suite fails
```

For a fast local loop without Docker, run pytest from the service directory (the
`pyproject.toml` sets `pythonpath = ["."]`, so the working directory matters):

```bash
cd services/energy-exporter
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m pytest -q
```

`services/control-ui` additionally needs `httpx<0.28` for its test client.

## Adding support for new hardware

Sunsteer's load-bearing input is the grid meter; the relay and the heat-pump telemetry
are abstracted behind drivers the same way. For the meter, two extension paths by
increasing independence:

### 1. In-tree driver (Python, lives in this repo)

Implement the `GridMeter` protocol in `services/energy-exporter/src/drivers/`:

- `run(on_reading)` is a blocking loop that calls `on_reading(reading)` per
  measurement; the reading dict must carry the decoder shape (`serial`, `import_w`,
  `export_w`, `surplus_w`, `import_kwh_total`, `export_kwh_total`, `l1_w`, `l2_w`,
  `l3_w`). The Protocols are structural specs — do **not** inherit from them.
- Register the driver: add its key to `SUPPORTED_METERS` and a branch in
  `get_meter()` (both in `src/drivers/__init__.py`).
- `src/drivers/mock.py` is the smallest complete template; `sma_speedwire.py` shows a
  real one.
- Add tests (see `tests/test_drivers.py`) — reading shape, monotonic counters, and
  whatever your protocol parsing needs.

### 2. Bring your own exporter (any language, lives anywhere)

Run your own process that serves the documented `/state` JSON contract and point the
controller's `EXPORTER_STATE_URL` at it — see
[docs/state-interface.md](docs/state-interface.md). No changes to this repo needed.
If it works well, we'd still love a link or a write-up in an issue.

### Other pluggable drivers

The relay and the heat-pump telemetry are abstracted the same way — implement a small
driver and register it in `get_relay()` / `get_driver()`:

- **Relay** — `RelayActuator` (write side, in `services/surplus-controller/src/relays/`)
  and `RelayReader` (read side, in `services/energy-exporter/src/drivers/`), selected with
  `RELAY_DRIVER`. The actuator contract (including the **required** hardware auto-off
  watchdog) is in [docs/relay-interface.md](docs/relay-interface.md).
- **Heat-pump telemetry** — the `HeatPumpDriver` protocol in
  `services/heatpump-exporter/src/drivers/`, selected with `HEATPUMP_DRIVER` (`vicare` |
  `mock`). The generic telemetry contract is in
  [docs/heatpump-interface.md](docs/heatpump-interface.md).

## Pull requests

- Keep PRs focused; one concern per PR.
- All four test stages must be green (`.github/workflows/ci.yml` enforces this).
- New behaviour comes with tests; bug fixes come with a regression test.
- No hardcoded private values (IPs, coordinates, credentials) — use env vars with
  neutral defaults, and RFC-5737 addresses (`192.0.2.x`) in tests.
- User-facing strings in the UI go through the i18n table
  (`services/control-ui/src/i18n.py`) with English and German entries.
- **Schema changes:** add a numbered idempotent migration in `db/migrations/`, never
  edit `init.sql` for post-release changes (see `db/migrations/README.md`).

## Safety-relevant changes

Anything touching the fail-safe chain (staleness handling, the relay auto-off
watchdog, minimum runtimes) gets extra scrutiny — explain the behaviour change and its
failure modes in the PR description. When in doubt, open an issue first. For the relay
actuator contract (including the required hardware auto-off watchdog), see
[docs/relay-interface.md](docs/relay-interface.md).
