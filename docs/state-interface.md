# The `/state` interface — bring your own exporter

The surplus-controller consumes exactly one input: a small JSON document served by the
energy-exporter at `GET /state` (default port `9121`). It does not know or care what
hardware produced the numbers. **This document is the contract.** If you serve it,
Sunsteer can control your heat pump — regardless of meter brand or programming
language.

## Schema (version 1)

```json
{
  "schema": 1,
  "surplus_w": 2480.5,
  "import_w": 0.0,
  "export_w": 2480.5,
  "shm_age_s": 0.8,
  "shelly_on": true,
  "shelly_power_w": 0.0,
  "shelly_reachable": true,
  "production_w": 3100.0
}
```

| Field | Required | Meaning |
|---|---|---|
| `schema` | yes | Contract version. Currently `1`; bumped only on breaking changes. |
| `surplus_w` | yes | Grid export minus import in watts. Positive = exporting (surplus available), negative = importing. |
| `import_w` | yes | Current grid import, W (≥ 0). |
| `export_w` | yes | Current grid export, W (≥ 0). |
| `shm_age_s` | yes | Seconds since the last **real meter reading**, or `null` if none was ever received. See freshness semantics below. |
| `shelly_on` | no | Last polled relay state. |
| `shelly_power_w` | no | Power measured by the relay, W. With the usual SG-Ready signal wiring this is `0.0` — see [hardware.md](hardware.md). |
| `shelly_reachable` | no | Whether the last relay poll succeeded. |
| `production_w` | no | Current inverter AC production, W (only with inverter telemetry enabled). |

Unknown extra fields are ignored by the controller — you may add your own.

## Freshness semantics (the safety-critical part)

`shm_age_s` is the controller's lifeline. The rules an exporter MUST follow:

1. **Only a real meter reading may refresh the timestamp** behind `shm_age_s`.
   Never refresh it from relay polls, inverter polls, retries, cache hits, or "the
   process is still alive" heartbeats. If the meter goes silent, `shm_age_s` must
   grow.
2. The controller treats a reading older than its `STATE_STALE_SECONDS` (default 30 s)
   — or an unreachable `/state`, or `shm_age_s: null` — as **blind** and fails safe:
   after a short grace period the heat-pump relay is switched **OFF**.
3. Readings should arrive at a cadence comfortably faster than the staleness limit.
   The SMA Sunny Home Manager broadcasts roughly every second; anything under ~10 s
   works with the default limits.

Faking freshness defeats the central safety mechanism of the system. Don't.

## Conventions

- Power unit is **watts** as JSON numbers; sign convention for `surplus_w` is
  `export - import`.
- The endpoint must answer fast (< 1 s) and must not block on the hardware — serve the
  last known reading and let `shm_age_s` reflect its age.
- Any non-200 response or connection error counts as blind (see rule 2), which is the
  correct behaviour when your exporter is down.

## Wiring it up

Point the controller at your exporter:

```bash
EXPORTER_STATE_URL=http://my-exporter:9121/state
```

Everything else (relay control via `SHELLY_URL`, forecast, thresholds) stays
unchanged. The built-in mock driver (`METER_DRIVER=mock`) is a working reference
implementation of this contract — readable in
`services/energy-exporter/src/drivers/mock.py` together with
`services/energy-exporter/src/state_server.py`.
