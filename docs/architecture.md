# Architecture

Four small services around one TimescaleDB. Each is independently testable, speaks to
the others only via documented interfaces (HTTP JSON, SQL, Prometheus), and ships as
its own container image.

```mermaid
flowchart LR
  subgraph MEASURE
    SHM[SMA Home Manager 2.0<br/>Speedwire multicast] --> EXP[energy-exporter]
    SHELLY[Shelly Gen2 relay] -->|state poll| EXP
    INV[SMA inverter<br/>Modbus, optional] --> EXP
  end
  subgraph DECIDE
    EXP -->|/state JSON| CTRL[surplus-controller]
    OM[Open-Meteo GTI<br/>forecast.solar fallback] --> CTRL
    CFG[(control_config<br/>hot-reload)] --> CTRL
  end
  subgraph ACT
    CTRL -->|Switch.Set + auto-off watchdog| SHELLY
    SHELLY -->|SG-Ready contact| HP[Heat pump]
  end
  EXP --> TSDB[(TimescaleDB)]
  CTRL -->|decision_log| TSDB
  TSDB --> UI[control-ui]
  CTRL -->|/status| UI
  VICARE[vicare-exporter<br/>optional] --> TSDB
```

## Components

### energy-exporter — measure

Reads the grid meter through a selectable driver (`METER_DRIVER`): `sma_shm` joins the
SMA Speedwire multicast group (`239.12.255.254:9522`, hence `network_mode: host`) and
decodes the Home Manager's telegrams; `mock` generates a synthetic day curve for
demos. It also polls the Shelly relay state and, optionally, an SMA inverter via
Modbus TCP (per-string DC power, temperature, lifetime yield). Outputs: the versioned
[`/state` JSON](state-interface.md) for the controller, Prometheus `/metrics`, and
time-series rows flushed to TimescaleDB every 60 s. Strictly read-only — this service
never switches anything.

### surplus-controller — decide and act

A deliberately boring loop (default every 15 s):

1. **Read** `/state` and the hot-reloaded `control_config` from the DB.
2. **Compensate own load:** `available = surplus + (relay_on ? wp_nominal_power : 0)`.
   Once the heat pump runs, it consumes the very surplus that justified switching it
   on — without this, the controller would oscillate.
3. **Adaptive threshold:** `threshold = base − (base − min) × remaining_kwh / full_sun_ref_kwh`,
   with the forecast factor clamped to `[0, 1]`. While plenty of PV is still ahead,
   the threshold sits low — switching on early is safe because the day will sustain
   the run. As the remaining forecast shrinks (late in the day, overcast), the
   threshold rises toward its base value: committing the pump's minimum runtime then
   requires strong, real surplus right now. `remaining_kwh` comes from Open-Meteo GTI
   per roof plane (forecast.solar as fallback), converted with a **performance ratio
   that self-calibrates daily** against your actual production.
4. **Hysteresis state machine:** the threshold must be exceeded for `on_delay_cycles`
   consecutive cycles to switch ON (and the OFF condition for `off_delay_cycles` to
   switch OFF); `min_runtime_s` / `min_offtime_s` protect the compressor. Modes:
   `auto`, `manual`, `paused`.
5. **Act + audit:** switch the Shelly (every ON command re-arms its hardware auto-off
   watchdog) and write the decision with its reason to `decision_log`.

### control-ui — explain

FastAPI + htmx + Chart.js, bilingual (EN/DE), fail-closed behind HTTP Basic auth. The
"why" card translates the controller's current state into a sentence ("OFF — 465 W
below the 2382 W threshold, 2/3 cycles"), the decision log shows every switch with its
reason, history charts cover temperatures, runs, compressor, savings. Runtime tuning
(thresholds, delays, prices) is edited here and takes effect the next control cycle —
no restarts.

### vicare-exporter — optional telemetry

Polls the Viessmann ViCare cloud API for heat-pump internals (temperatures, compressor
speed/starts, energy counters) into TimescaleDB. Informative only — the control loop
never depends on it. Mind its [data quirks](hardware.md#viessmann-vicare-optional).

## The fail-safe chain

Layered so that each failure mode has a catcher, and every layer fails towards
"surplus mode off, heat pump runs normally":

| Failure | Catcher |
|---|---|
| Meter stops reporting (multicast lost, exporter down) | `shm_age_s` grows → controller switches OFF after a short grace period (`state_stale_failsafe`) |
| Controller dies mid-run | Shelly's **hardware auto-off watchdog** (`SHELLY_AUTOOFF_SECONDS`) fires because nothing re-arms it |
| Relay unreachable (WiFi drop) | Same watchdog; plus `shelly_reachable` metric + alert rule |
| Someone/something else switches the relay | The controller detects the external change, reconciles its state and logs `external_change` |
| Misconfigured UI deployment | UI without `ADMIN_PASS` serves 503 — never an open control panel |

What the system deliberately does **not** do: bypass the heat pump's own protections.
SG-Ready is an input to the pump's controller, not a motor switch.

## Data model (TimescaleDB)

| Table | Writer | Content |
|---|---|---|
| `energy_meter` | energy-exporter | 60-s aggregates: import/export/surplus, per-phase W, lifetime counters, optional inverter fields |
| `heatpump` | energy-exporter | Relay state + power per poll (~1 min cadence) |
| `decision_log` | surplus-controller | Every decision: mode, surplus, threshold, action, reason, audit fields |
| `control_config` | control-ui (writes), controller (reads each cycle) | Runtime tuning key/values |
| `heatpump_vicare` | vicare-exporter | Optional heat-pump telemetry |

Fresh installs get the full schema from `db/init.sql`; upgrades apply numbered,
idempotent scripts from `db/migrations/` (the compose stack does this automatically on
start).
