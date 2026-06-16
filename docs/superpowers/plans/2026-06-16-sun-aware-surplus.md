# Sun-aware surplus calculation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Git:** Do NOT commit. The user commits manually. Agents may stage (`git add`) but never `git commit`/`push`. The per-task "Commit" steps below are written as `git add` only.

**Goal:** Stop the controller holding the heat-pump relay ON when no PV is physically possible (after dark) by gating the load-compensated surplus on the sun's elevation; ship it as 0.4.1 with all docs updated.

**Architecture:** A new pure `sun.py` computes solar elevation from `PV_LAT`/`PV_LON`. `decide_action` disables the load-compensation when the sun is below `PV_SUN_MIN_ELEVATION_DEG`, so the existing off-hysteresis releases the WP through the normal path. A new gauge exposes the elevation; the live `/status` "why" reason shows a sun-specific message when idle after dark. No new dependency.

**Tech Stack:** Python 3.12, prometheus_client, pytest (via each service's Dockerfile `test` stage). Spec: `docs/superpowers/specs/2026-06-16-sun-aware-surplus-design.md`.

---

## File Structure

- **Create** `services/surplus-controller/src/sun.py` — `sun_elevation(lat, lon, when_utc)` pure function.
- **Create** `services/surplus-controller/tests/test_sun.py` — elevation reference tests.
- **Modify** `services/surplus-controller/src/main.py` — env parse, compute sun state each cycle, pass `sun_up` into `decide_action`, set the metric, override the live status reason.
- **Modify** `services/surplus-controller/src/metrics.py` — new `SUN_ELEVATION` gauge.
- **Modify** `services/surplus-controller/tests/test_main_loop.py` — `decide_action` sun tests.
- **Modify** `services/control-ui/src/i18n.py` — `why_sun_down` EN/DE.
- **Modify** `services/control-ui/src/explain.py` — off-branch for `sun_below_horizon`.
- **Modify** `services/control-ui/tests/test_explain.py` — why-card test.
- **Docs:** `docs/architecture.md`, `README.md`, `docs/setup.md`, `docs/hardware.md`, `deploy/compose/.env.example`, `CHANGELOG.md`.
- **Version bump:** `deploy/compose/docker-compose.yml`, `deploy/compose/docker-compose.demo.yml`, `deploy/compose/.env.example`, `deploy/k8s/kustomization.yaml`, `deploy/k8s/{energy-exporter,surplus-controller,control-ui,heatpump-exporter}.yaml`.

---

## Task 1: Solar elevation function

**Files:**
- Create: `services/surplus-controller/src/sun.py`
- Test: `services/surplus-controller/tests/test_sun.py`

- [ ] **Step 1: Write the failing tests**

```python
# services/surplus-controller/tests/test_sun.py
from datetime import datetime, timezone

from src.sun import sun_elevation


def _utc(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def test_summer_local_noon_is_high():
    # Berlin 52.52N 13.40E, ~summer solstice, ~13:00 local = 11:00 UTC -> elevation ~60deg
    e = sun_elevation(52.52, 13.40, _utc(2026, 6, 21, 11))
    assert 55 < e < 65


def test_local_midnight_is_negative():
    e = sun_elevation(52.52, 13.40, _utc(2026, 6, 21, 23))
    assert e < 0


def test_equator_noon_near_equinox_is_near_zenith():
    # Equator, equinox, local noon (~12:00 UTC at lon 0) -> elevation near 90
    e = sun_elevation(0.0, 0.0, _utc(2026, 3, 20, 12))
    assert e > 85


def test_returns_float_degrees():
    assert isinstance(sun_elevation(0.0, 0.0, _utc(2026, 3, 20, 12)), float)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd services/surplus-controller && python3 -m pytest tests/test_sun.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'src.sun'`).

- [ ] **Step 3: Implement `sun.py`**

```python
# services/surplus-controller/src/sun.py
"""Solar elevation angle — pure, dependency-free (NOAA solar-position approximation).

Used to gate the load-compensation: no real PV is possible when the sun is below the
horizon, so the surplus calculation must not keep the heat pump running after dark."""
import math


def sun_elevation(lat_deg: float, lon_deg: float, when_utc) -> float:
    """Solar elevation angle in degrees for a location and a UTC datetime.

    Accurate to well within a degree — ample for a few-degree gate. `when_utc` is a
    datetime whose wall-clock fields are UTC (aware-UTC or naive-UTC both work)."""
    n = when_utc.timetuple().tm_yday
    hour = when_utc.hour + when_utc.minute / 60.0 + when_utc.second / 3600.0
    gamma = 2.0 * math.pi / 365.0 * (n - 1 + (hour - 12) / 24.0)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
                       - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
    decl = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
            - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma)
            - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))
    tst = hour * 60.0 + eqtime + 4.0 * lon_deg          # true solar time, minutes (UTC -> tz offset 0)
    ha = math.radians(tst / 4.0 - 180.0)                # hour angle, radians
    lat = math.radians(lat_deg)
    cos_zenith = (math.sin(lat) * math.sin(decl)
                  + math.cos(lat) * math.cos(decl) * math.cos(ha))
    cos_zenith = max(-1.0, min(1.0, cos_zenith))
    return 90.0 - math.degrees(math.acos(cos_zenith))
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd services/surplus-controller && python3 -m pytest tests/test_sun.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Stage**

```bash
git add services/surplus-controller/src/sun.py services/surplus-controller/tests/test_sun.py
```

---

## Task 2: Gate the load-compensation on the sun

**Files:**
- Modify: `services/surplus-controller/src/main.py` (env parse + `decide_action` signature/body + caller)
- Test: `services/surplus-controller/tests/test_main_loop.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_main_loop.py`)

```python
def test_decide_action_sun_down_disables_compensation(_cfg=None):
    import src.main as M
    cfg = {"mode": "auto", "manual_relay_on": False, "wp_nominal_power_w": 2000.0,
           "threshold_off_w": 200.0, "on_delay_cycles": 1, "off_delay_cycles": 1,
           "min_runtime_s": 0, "min_offtime_s": 0}
    # Relay ON, raw surplus -565 (WP idle at night). Sun DOWN -> no compensation ->
    # avail == raw surplus (negative) -> off_streak builds -> released.
    avail, on_s, off_s, target, action, reason = M.decide_action(
        cfg, relay_on=True, state_fresh=True, fresh_for_decide=True,
        surplus=-565.0, eff=1500.0, on_streak=0, off_streak=0,
        secs_since_on=9999, secs_since_off=9999, sun_up=False)
    assert avail == -565.0
    assert target is False and action == "switched_off"


def test_decide_action_sun_up_keeps_compensation_unchanged():
    import src.main as M
    cfg = {"mode": "auto", "manual_relay_on": False, "wp_nominal_power_w": 2000.0,
           "threshold_off_w": 200.0, "on_delay_cycles": 1, "off_delay_cycles": 1,
           "min_runtime_s": 0, "min_offtime_s": 0}
    # Same inputs but sun UP -> compensation applies -> avail = -565 + 2000 = 1435 -> stays on.
    avail, on_s, off_s, target, action, reason = M.decide_action(
        cfg, relay_on=True, state_fresh=True, fresh_for_decide=True,
        surplus=-565.0, eff=1500.0, on_streak=0, off_streak=0,
        secs_since_on=9999, secs_since_off=9999, sun_up=True)
    assert avail == 1435.0
    assert target is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd services/surplus-controller && python3 -m pytest tests/test_main_loop.py -k sun -v`
Expected: FAIL (`decide_action() got an unexpected keyword argument 'sun_up'`).

- [ ] **Step 3: Add the env parse** — in `services/surplus-controller/src/main.py`, just after the `PV_LON = ...` line (currently line ~64), add:

```python
# No real PV below this solar elevation -> disable the load-compensation so the WP is
# released after dark instead of running on grid power (the SHM-surplus is negative then).
# Float, tolerant: a bad value falls back to the default.
def _sun_min_elev():
    try:
        v = float(os.environ.get("PV_SUN_MIN_ELEVATION_DEG", "3.0"))
    except (TypeError, ValueError):
        return 3.0
    return v if -18.0 <= v <= 90.0 else 3.0


SUN_MIN_ELEVATION_DEG = _sun_min_elev()
```

- [ ] **Step 4: Add the import** — at the top of `main.py`, add to the local imports block (next to `from .threshold import ...`):

```python
from datetime import datetime, timezone
from .sun import sun_elevation
```

> Note: `from datetime import datetime` already exists; extend it to `datetime, timezone`. Verify no duplicate import.

- [ ] **Step 5: Change `decide_action`** — add a `sun_up` parameter and gate the compensation. Replace the `if state_fresh:` block body:

```python
def decide_action(cfg, relay_on, state_fresh, fresh_for_decide, surplus, eff,
                  on_streak, off_streak, secs_since_on, secs_since_off, sun_up):
    """Pure core of one control cycle (no I/O). `sun_up` gates the load-compensation: with
    the sun below the configured elevation there is no PV to oscillate around, so we compare
    the RAW surplus (negative after dark) and the off-hysteresis releases the WP."""
    if state_fresh:
        # Load-compensate ONLY when the sun is up; otherwise the +wp_nominal would be a phantom
        # surplus that keeps the relay on grid power after sunset.
        comp_power = cfg["wp_nominal_power_w"] if sun_up else 0.0
        avail = available_surplus(surplus, relay_on, comp_power)
        on_streak = on_streak + 1 if avail > eff else 0
        off_streak = off_streak + 1 if avail < cfg["threshold_off_w"] else 0
    else:
        avail = surplus
        on_streak = off_streak = 0
    target, action, reason = decide(
        cfg["mode"], relay_on, cfg["manual_relay_on"],
        on_streak, off_streak, cfg["on_delay_cycles"], cfg["off_delay_cycles"],
        secs_since_on, secs_since_off, cfg["min_runtime_s"], cfg["min_offtime_s"],
        state_fresh=fresh_for_decide)
    return avail, on_streak, off_streak, target, action, reason
```

- [ ] **Step 6: Update the caller** — find the `decide_action(` call in the main loop (around line 291) and pass `sun_up`. Just before it, compute the sun state from wall-clock UTC:

```python
            sun_elev = sun_elevation(float(PV_LAT), float(PV_LON), datetime.now(timezone.utc))
            sun_up = sun_elev >= SUN_MIN_ELEVATION_DEG
            avail, on_streak, off_streak, target, action, reason = decide_action(
                cfg, relay_on, state_fresh, fresh_for_decide, surplus, eff,
                on_streak, off_streak, int(now_wall - last_on), int(now_wall - last_off),
                sun_up)
```

> Note: keep the existing `secs_since_on`/`secs_since_off` expressions the caller already uses (do not change how they are computed — only append `sun_up`). The two lines computing `sun_elev`/`sun_up` are new; reuse the existing wall-clock `now` the loop already has for `last_on`/`last_off` (it uses a wall-clock timestamp there, not `time.monotonic()`).

- [ ] **Step 7: Run to verify it passes**

Run: `cd services/surplus-controller && python3 -m pytest tests/test_main_loop.py -k sun -v`
Expected: PASS (2 passed).

- [ ] **Step 8: Stage**

```bash
git add services/surplus-controller/src/main.py services/surplus-controller/tests/test_main_loop.py
```

---

## Task 3: Metric + live status reason

**Files:**
- Modify: `services/surplus-controller/src/metrics.py` (new gauge)
- Modify: `services/surplus-controller/src/main.py` (set metric + override live status reason)

- [ ] **Step 1: Add the gauge** — in `services/surplus-controller/src/metrics.py`, after the `AVAILABLE = Gauge(...)` block add:

```python
SUN_ELEVATION = Gauge("surplus_control_sun_elevation_deg",
                      "Current solar elevation at the PV site (degrees). Below the configured "
                      "minimum the load-compensation is disabled so the WP is released after dark.")
```

- [ ] **Step 2: Set the metric + override the live status reason** — in `main.py`'s reporting try-block (the one that calls `metrics.update(...)` and `status_server.set_status(...)`), add the metric set and compute a display reason:

```python
                metrics.SUN_ELEVATION.set(sun_elev)
                # Live "why" only: when idle after dark, say so instead of the generic
                # "surplus below threshold". The decision_log (written only on switches) keeps
                # the real switch reason — this override never touches it.
                status_reason = reason
                if not sun_up and not relay_on and action not in ("switched_on", "switched_off"):
                    status_reason = "sun_below_horizon"
```

Then change the `status_server.set_status(..., reason=reason, ...)` argument to `reason=status_reason`.

- [ ] **Step 3: Run the full controller suite**

Run: `docker build --target test services/surplus-controller`
Expected: PASS (all tests green, including the new sun tests).

- [ ] **Step 4: Stage**

```bash
git add services/surplus-controller/src/metrics.py services/surplus-controller/src/main.py
```

---

## Task 4: control-ui "why" card for sun-down

**Files:**
- Modify: `services/control-ui/src/i18n.py` (new `why_sun_down` key)
- Modify: `services/control-ui/src/explain.py` (off-branch)
- Test: `services/control-ui/tests/test_explain.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_explain.py`)

```python
def test_explain_sun_below_horizon():
    from src.explain import explain
    status = {"mode": "auto", "relay_on": False, "state_fresh": True,
              "surplus_w": -565, "effective_threshold_w": 1500,
              "reason": "sun_below_horizon"}
    out = explain(status, {}, lang="en")
    assert out["state"] == "off"
    assert "sun" in out["detail"].lower()
```

- [ ] **Step 2: Run to verify it fails**

Run: `docker build --target test services/control-ui` (or local pytest if env set up)
Expected: FAIL (detail is the generic "below threshold" text, no "sun").

- [ ] **Step 3: Add the i18n key** — in `services/control-ui/src/i18n.py`, add to the dict (near the other `why_*` keys):

```python
    "why_sun_down":     ("Sonne unter dem Horizont – kein PV-Überschuss möglich",
                         "Sun below the horizon — no PV surplus possible"),
```

- [ ] **Step 4: Add the explain branch** — in `services/control-ui/src/explain.py`, in the `else:` (relay off) block, add BEFORE the `if reason == "waiting_min_offtime":` check:

```python
        if reason == "sun_below_horizon":
            return {"state": "off", "headline": t("why_off"),
                    "detail": t("why_sun_down"), "bar_label": "", "bar_pct": 0}
```

- [ ] **Step 5: Run to verify it passes**

Run: `docker build --target test services/control-ui`
Expected: PASS (all control-ui tests green).

- [ ] **Step 6: Stage**

```bash
git add services/control-ui/src/i18n.py services/control-ui/src/explain.py services/control-ui/tests/test_explain.py
```

---

## Task 5: Documentation

**Files:** `docs/architecture.md`, `README.md`, `docs/setup.md`, `docs/hardware.md`, `deploy/compose/.env.example`

- [ ] **Step 1:** `docs/architecture.md` — in the decision/fail-safe description, add a sentence: the load-compensated surplus is **sun-aware** — below `PV_SUN_MIN_ELEVATION_DEG` (default 3°) the compensation is disabled so the heat pump is released after dark instead of running on grid power. (Place it next to where load-compensation / the fail-safe chain is described.)

- [ ] **Step 2:** `README.md` — in the **Features** list, extend the "Hysteresis / Fail-safe" area with: "**Sun-aware** — the surplus calculation knows the sun's position; once it's down there's no PV to harvest, so the heat pump is released instead of being held on grid power."

- [ ] **Step 3:** `docs/setup.md` and `docs/hardware.md` — document `PV_SUN_MIN_ELEVATION_DEG` (optional, default `3.0`, solar elevation below which surplus switching is suppressed). Put it with the other `PV_*` site settings.

- [ ] **Step 4:** `deploy/compose/.env.example` — in the "Optional: behaviour" section add:

```
# Solar elevation (degrees) below which no PV surplus is possible -> the controller stops
# load-compensating and releases the heat pump (no running on grid power after dark).
# Default 3.0; needs PV_LAT/PV_LON (already required).
#PV_SUN_MIN_ELEVATION_DEG=3.0
```

- [ ] **Step 5:** Sanity-check the docs render (no broken markdown) and stage:

```bash
git add docs/architecture.md README.md docs/setup.md docs/hardware.md deploy/compose/.env.example
```

---

## Task 6: Version bump to 0.4.1 + CHANGELOG

**Files:** `deploy/compose/docker-compose.yml`, `deploy/compose/docker-compose.demo.yml`, `deploy/compose/.env.example`, `deploy/k8s/kustomization.yaml`, `deploy/k8s/{energy-exporter,surplus-controller,control-ui,heatpump-exporter}.yaml`, `CHANGELOG.md`

- [ ] **Step 1: Bump compose defaults**

```bash
sed -i '' 's/SUNSTEER_VERSION:-0.4.0/SUNSTEER_VERSION:-0.4.1/g' \
  deploy/compose/docker-compose.yml deploy/compose/docker-compose.demo.yml
sed -i '' 's/^#SUNSTEER_VERSION=0.4.0/#SUNSTEER_VERSION=0.4.1/; s/(default: 0.4.0)/(default: 0.4.1)/' \
  deploy/compose/.env.example
```

Verify: `grep -rn "SUNSTEER_VERSION:-0.4" deploy/compose` shows only `0.4.1`.

- [ ] **Step 2: Bump k8s manifests + kustomize newTag**

```bash
sed -i '' 's#\(sunsteer/[a-z-]*\):0.4.0#\1:0.4.1#' \
  deploy/k8s/energy-exporter.yaml deploy/k8s/surplus-controller.yaml \
  deploy/k8s/control-ui.yaml deploy/k8s/heatpump-exporter.yaml
sed -i '' 's/newTag: "0.4.0"/newTag: "0.4.1"/g' deploy/k8s/kustomization.yaml
```

Verify: `grep -rn "0.4.0" deploy/k8s` returns nothing (all `0.4.1`).

- [ ] **Step 3: CHANGELOG 0.4.1 entry + hygiene** — in `CHANGELOG.md`, replace the `## [Unreleased]\n\n_Nothing yet._` block with an empty Unreleased plus the new 0.4.1 section:

```markdown
## [Unreleased]

_Nothing yet._

## [0.4.1] - 2026-06-16

A correctness fix to the surplus calculation, plus its observability. No breaking changes.

### Fixed
- The load-compensated surplus is now **sun-aware**: below `PV_SUN_MIN_ELEVATION_DEG`
  (default 3°) the compensation is disabled, so the heat pump is released after dark instead
  of being held ON on grid power. Previously the fixed `+wp_nominal` compensation could keep
  the SG-Ready relay ON past sunset (observed: relay still on at ~00:00 with the WP idle).

### Added
- `PV_SUN_MIN_ELEVATION_DEG` (default `3.0`) to tune the elevation gate.
- Gauge `surplus_control_sun_elevation_deg`; the UI "why" card shows *"Sun below the horizon"*
  when idle after dark.
```

  Then update the comparison links at the bottom of `CHANGELOG.md`:
  - change `[Unreleased]: .../compare/v0.4.0...HEAD` to `.../compare/v0.4.1...HEAD`
  - add `[0.4.1]: https://github.com/slippyex/sunsteer/compare/v0.4.0...v0.4.1`

  Hygiene check: `[Unreleased]` is empty (`_Nothing yet._`), every released section has a date and a compare link, newest-first order is preserved.

- [ ] **Step 4: Stage**

```bash
git add deploy/ CHANGELOG.md
```

---

## Final verification (whole feature)

- [ ] All four Dockerfile test stages pass:

```bash
for s in surplus-controller energy-exporter control-ui vicare-exporter; do
  docker build --target test services/$s || echo "FAIL $s"
done
```

> Note: the repo's service dir for the heat-pump exporter is `services/heatpump-exporter` on 0.4.x — build that instead of `vicare-exporter` if the latter no longer exists.

- [ ] `ruff check .` clean (run in a `python:3.12-slim` container with `ruff==0.15.17` if not installed locally).
- [ ] `grep -rn "0.4.0" deploy/ | grep -v sha256` returns nothing (all bumped to 0.4.1; the TimescaleDB digest line is unrelated).
- [ ] Compose config valid: `docker compose -f deploy/compose/docker-compose.yml config -q`.
- [ ] kustomize build valid (with a throwaway secret), images show `:0.4.1`.
- [ ] Hand the uncommitted tree to the user to commit + tag `v0.4.1`.

---

## Self-review notes (author)

- **Spec coverage:** behaviour gate (T2), sun module (T1), env knob (T2), metric + why reason (T3/T4), docs (T5), version+CHANGELOG hygiene (T6). All spec sections mapped.
- **Out of scope (per spec):** daytime modulation cap — not in this plan.
- **Type consistency:** `sun_up: bool`, `SUN_MIN_ELEVATION_DEG: float`, reason token `"sun_below_horizon"`, i18n key `why_sun_down`, gauge `surplus_control_sun_elevation_deg` — used consistently across tasks.
- **Caller caveat (T2 Step 6):** the implementer must read the real `decide_action(` call site to keep the existing `secs_since_on/off` argument expressions and the loop's wall-clock variable name; only append `sun_up` and the two sun lines. Do not change `time.monotonic()` usage.
