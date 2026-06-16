# Sun-aware surplus calculation — design

**Goal:** Stop the controller from keeping the heat-pump relay ON when no PV is physically
possible (after sunset / before sunrise), by making the load-compensated surplus
calculation aware of the sun's elevation.

**Status:** approved (brainstorm 2026-06-16). Next: implementation plan.

## Motivation (diagnosed from live data)

A user observed a positive "surplus" reading and the relay still ON around midnight.
Investigation of the homelab TimescaleDB confirmed a real flaw, not a meter glitch:

- Raw grid `surplus_w` at night is always negative (no phantom PV). Correct.
- But on the night of 2026-06-14→15 the SG-Ready relay stayed ON until 00:00:49. At 23:57
  the meter showed only **−565 W** total import with the relay ON — i.e. the heat pump was
  *idle* (drawing ~0), yet the controller computed
  `available = surplus + wp_nominal = −565 + 2000 = +1435 W` and held the relay.

Root cause: `available_surplus()` adds the **full nominal WP power back whenever the relay
is ON**, regardless of whether the WP actually draws it (SG-Ready is a "may run" permission,
not a "is running" signal, and the Shelly can't meter the WP). With no PV present this
produces a phantom positive surplus that keeps the relay ON on grid power past sunset.

The load-compensation itself is correct *when there is PV to oscillate around*; its failure
mode is precisely "no sun". So the fix gates the compensation on the sun being up.

## Design

### 1. Behaviour (core)

In `decide_action` (surplus-controller `main.py`), gate the load-compensation on solar
elevation:

```python
sun_up = sun_elevation(PV_LAT, PV_LON, now_utc) >= SUN_MIN_ELEVATION_DEG
comp   = cfg["wp_nominal_power_w"] if sun_up else 0.0
avail  = available_surplus(surplus, relay_on, comp)
```

With the sun below the threshold, `comp = 0` → `avail = raw surplus` (negative at night).
The **existing** off-hysteresis then releases the WP through the normal path
(`off_delay_cycles`, respecting `min_runtime_s` for compressor protection). Turn-ON is
already impossible below the threshold because the raw surplus is negative. This is not a
bolt-on override — it lives inside the surplus calculation, so all the existing safety
timers and the decision log behave unchanged.

No extra hysteresis is needed on the gate itself: solar elevation is monotonic through the
threshold at the crossing (a few minutes around sunrise/sunset), and `off_delay_cycles`
already absorbs any micro-jitter.

### 2. Solar-elevation module

New `services/surplus-controller/src/sun.py`:

```python
def sun_elevation(lat_deg, lon_deg, when_utc) -> float:
    """Solar elevation angle in degrees for a location and UTC datetime.
    Standard solar-position approximation (day-of-year declination + equation of time +
    hour angle). Accurate to well within a degree — ample for a ~3° gate."""
```

Pure function, no external dependency (the controller's requirements stay
`prometheus_client` / `psycopg2-binary` / `tzdata`). Reuses `PV_LAT` / `PV_LON` which the
controller already requires and validates.

### 3. Configuration

One env var, static like the other site/hardware config:

- `PV_SUN_MIN_ELEVATION_DEG` — default **3.0**. Below ~3° real PV is negligible and the
  near-horizon minutes are excluded. Parsed as a float with a tolerant fallback to the
  default on a bad value (mirroring the existing tolerant env parsing).

Not a DB/`control_config` knob: it is set-and-forget, so this avoids a migration + UI +
config-consistency-guard surface for no real benefit.

### 4. Observability

- New gauge `surplus_control_sun_elevation_deg`, set every cycle.
- Explainability: when the sun is below the threshold and the relay is OFF, the **live
  `/status` "why" reason** (what the UI card shows right now — not the decision_log switch
  row, which keeps recording the real `surplus_below_off_threshold` on the actual turn-off)
  reads *"Sun below the horizon — no PV surplus possible"* / *"Sonne unter dem Horizont —
  kein PV-Überschuss möglich"*. New i18n keys (EN + DE).

### 5. Testing

- `test_sun.py`: `sun_elevation` against known references (local solar noon strongly
  positive; local midnight negative; a sunrise-ish time near 0°), within a small tolerance.
- Decision tests: sun below threshold ⇒ compensation disabled ⇒ a running WP is released
  via the off path; sun above threshold ⇒ behaviour byte-for-byte unchanged from today.
- The existing config-consistency / fail-safe tests must stay green.

## Documentation (kept up-to-date as part of this change)

All Markdown that describes the surplus/decision behaviour or the configuration surface is
updated in the same change:

- `docs/architecture.md` — add sun-aware load-compensation to the decision/fail-safe
  description.
- `README.md` — Features: note the surplus calc is sun-aware (no grid-powered running after
  dark).
- `docs/setup.md` and/or `docs/hardware.md` — document `PV_SUN_MIN_ELEVATION_DEG`.
- `deploy/compose/.env.example` — add the new env var (commented, with the default and a
  one-line explanation).
- `CHANGELOG.md` — new entry under the next version (Fixed: relay no longer held on grid
  after sunset; Added: `PV_SUN_MIN_ELEVATION_DEG`, `surplus_control_sun_elevation_deg`).
- `CONTRIBUTING.md` "Safety-relevant changes" already covers the fail-safe chain — no change
  needed, but the PR description must explain the behaviour change per that policy.

## Out of scope (deferred)

- **Daytime modulation over-estimate.** The same fixed-nominal compensation can over-estimate
  during the day when the WP modulates below nominal. Truly fixing that needs a measured WP
  draw (a CT clamp — the Shelly can't meter it) or capping against measured PV production
  (which depends on the inverter Modbus telemetry). Both are larger and separately tracked;
  the sun gate fixes the demonstrated night/no-PV failure cleanly and meter-independently.

## Files

- New: `services/surplus-controller/src/sun.py`, `services/surplus-controller/tests/test_sun.py`
- Modified: `services/surplus-controller/src/main.py` (gate in `decide_action`, env, metric set),
  `services/surplus-controller/src/metrics.py` (new gauge),
  `services/surplus-controller/src/i18n.py` or the UI i18n table (why-reason keys — see note below),
  plus the documentation files listed above.

> Note: the "why" reason string is rendered by control-ui, so the EN/DE keys live in
> `services/control-ui/src/i18n.py`; the controller emits a stable reason token in the
> decision log / status that the UI maps. The plan will pin the exact token + mapping.
