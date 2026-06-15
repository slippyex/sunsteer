# The `/status` interface — controller → UI

The surplus-controller publishes its live decision state as JSON at `GET /status`
(default port `9124`). The control-ui reads it to render the "why" card and the live
ticker. Like [`/state`](state-interface.md), it is **versioned**: a `schema` field lets a
consumer detect a breaking shape change instead of silently mis-rendering. The UI
warns-and-continues on a mismatch rather than crashing.

This endpoint is informational (the controller's decisions do not depend on anyone reading
it) and unauthenticated — see the network-trust-boundary note in
[SECURITY.md](../SECURITY.md).

## Schema (version 1)

```json
{
  "schema": 1,
  "mode": "auto",
  "relay_on": true,
  "surplus_w": 2480.5,
  "available_w": 4480.5,
  "effective_threshold_w": 2382.0,
  "on_streak": 3,
  "off_streak": 0,
  "on_delay_cycles": 3,
  "off_delay_cycles": 3,
  "secs_since_on": 540,
  "secs_since_off": 4200,
  "min_runtime_s": 1800,
  "min_offtime_s": 900,
  "loop_seconds": 15,
  "reason": "surplus_ok",
  "state_fresh": true,
  "state_age_s": 0.8
}
```

| Field | Meaning |
|---|---|
| `schema` | Contract version. Currently `1`; bumped only on breaking changes. |
| `mode` | `auto`, `manual` or `paused`. |
| `relay_on` | Commanded relay state (heat pump SG-Ready ON). |
| `surplus_w` | Grid surplus from `/state`, W. |
| `available_w` | Load-compensated surplus the decision compares against the threshold (adds back the estimated heat-pump draw while it runs). |
| `effective_threshold_w` | Current adaptive ON-threshold, W. |
| `on_streak` / `off_streak` | Consecutive cycles the ON / OFF condition has held (hysteresis). |
| `on_delay_cycles` / `off_delay_cycles` | Cycles required to switch ON / OFF. |
| `secs_since_on` / `secs_since_off` | Seconds since the last ON / OFF switch (drives the min-runtime/off-time guards). |
| `min_runtime_s` / `min_offtime_s` | Compressor-protection minimums, seconds. |
| `loop_seconds` | Control-loop cadence. |
| `reason` | Machine-readable reason for the current state (e.g. `surplus_ok`, `min_runtime`, `state_stale_failsafe`). |
| `state_fresh` | Whether the meter reading is fresh (not blind). |
| `state_age_s` | Age of the latest meter reading, seconds. |

The producer constant is `STATUS_SCHEMA` (`surplus-controller/src/status_server.py`); the
consumer constant is `KNOWN_STATUS_SCHEMA` (`control-ui/src/sources.py`).
