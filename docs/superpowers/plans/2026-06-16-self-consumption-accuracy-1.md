# Self-consumption accuracy (#1, 0.5.0) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.
>
> **Git:** Do NOT commit. The user commits manually. Agents stage with `git add` at most.

**Goal:** Replace the fixed-nominal load-compensation with `available = production − base_load` (the real PV headroom for the heat pump), with a clean fallback to today's logic when inverter production is unavailable.

**Architecture:** The exporter publishes `production_w` in `/state` only while the inverter reading is fresh. The controller keeps a rolling base-load estimate (20th percentile of `consumption = production − surplus` over 60 min) and computes `available = production − base_load` when production is fresh, else falls back to `surplus + (wp_nominal if relay_on and sun_up)`. Hysteresis, fail-safe and the sun-gate are unchanged.

**Tech Stack:** Python 3.12, prometheus_client, pytest (Dockerfile `test` stage). Spec: `docs/superpowers/specs/2026-06-16-self-consumption-accuracy-design.md`.

---

## File Structure

- **Modify** `services/energy-exporter/src/state_server.py` — `set_production()` + `_production_ts`; `_snapshot()` drops `production_w` when stale.
- **Modify** `services/energy-exporter/src/main.py` — `_inverter_cycle` calls `set_production`.
- **Test** `services/energy-exporter/tests/test_state_server.py` (create if absent).
- **Create** `services/surplus-controller/src/baseload.py` — rolling base-load estimator.
- **Test** `services/surplus-controller/tests/test_baseload.py`.
- **Modify** `services/surplus-controller/src/threshold.py` — add `available_and_basis()`.
- **Test** `services/surplus-controller/tests/test_threshold.py` (or `test_available.py`).
- **Modify** `services/surplus-controller/src/main.py` — read production, drive the estimator, compute available, pass into `decide_action` (refactored to take `available`), set metrics.
- **Modify** `services/surplus-controller/src/metrics.py` — `BASE_LOAD`, `AVAILABLE_BASIS` gauges.
- **Modify** `services/surplus-controller/tests/test_main_loop.py`, `tests/test_decide_action.py` — adapt to the refactor.
- **Docs/version:** `docs/architecture.md`, `README.md`, `CHANGELOG.md`, `deploy/compose/*`, `deploy/k8s/*`.

---

## Task 1: Exporter — fresh-only `production_w` in /state

**Files:** Modify `services/energy-exporter/src/state_server.py`, `services/energy-exporter/src/main.py`; Test `services/energy-exporter/tests/test_state_server.py`.

- [ ] **Step 1: Write the failing test** (create `tests/test_state_server.py`)

```python
import src.state_server as ss


def _reset():
    ss._latest.clear()
    ss._shm_ts = None
    ss._production_ts = None


def test_production_present_when_fresh(monkeypatch):
    _reset()
    monkeypatch.setattr(ss.time, "time", lambda: 1000.0)
    ss.set_production(production_w=2500.0)
    snap = ss._snapshot()
    assert snap["production_w"] == 2500.0


def test_production_dropped_when_stale(monkeypatch):
    _reset()
    monkeypatch.setattr(ss.time, "time", lambda: 1000.0)
    ss.set_production(production_w=2500.0)
    monkeypatch.setattr(ss.time, "time", lambda: 1000.0 + ss.PRODUCTION_FRESH_S + 1)
    snap = ss._snapshot()
    assert "production_w" not in snap        # stale -> omitted, controller falls back


def test_set_production_does_not_stamp_shm(monkeypatch):
    _reset()
    monkeypatch.setattr(ss.time, "time", lambda: 1000.0)
    ss.set_production(production_w=1.0)
    assert ss._snapshot()["shm_age_s"] is None   # production freshness is separate from SHM
```

- [ ] **Step 2: Run it — FAIL** (`AttributeError: set_production` / `PRODUCTION_FRESH_S`)

Run: `docker build --target test services/energy-exporter`

- [ ] **Step 3: Implement** in `services/energy-exporter/src/state_server.py`. Add the module global and function, and gate the snapshot:

```python
_shm_ts = None          # wall-clock of the last SHM telegram -> freshness for the controller
_production_ts = None   # wall-clock of the last fresh inverter reading
_lock = threading.Lock()

PRODUCTION_FRESH_S = 90  # inverter polls ~10s; tolerate a few misses before dropping production
```

Add the setter (next to `set_state`):

```python
def set_production(production_w):
    """Inverter production + its own freshness stamp. Kept separate from set_state so a stale
    inverter (frozen last value) is DROPPED from /state, not served as if live — the
    controller computes consumption = production - surplus and must not trust a frozen value."""
    global _production_ts
    with _lock:
        _latest["production_w"] = production_w
        _production_ts = time.time()
```

In `_snapshot()`, drop stale production before returning:

```python
def _snapshot():
    with _lock:
        snap = dict(_latest)
        snap["schema"] = SCHEMA_VERSION
        snap["shm_age_s"] = round(time.time() - _shm_ts, 1) if _shm_ts is not None else None
        if _production_ts is None or (time.time() - _production_ts) > PRODUCTION_FRESH_S:
            snap.pop("production_w", None)
    return snap
```

- [ ] **Step 4: Point the inverter poller at it** — in `services/energy-exporter/src/main.py`, `_inverter_cycle`, replace `state_server.set_state(production_w=_last_inverter["production_w"])` with:

```python
        state_server.set_production(_last_inverter["production_w"])
```

(Leave the `else:` debug-log branch as is — not updating the stamp is what makes it go stale.)

- [ ] **Step 5: Run — PASS**

Run: `docker build --target test services/energy-exporter`  → all green.

- [ ] **Step 6: Stage** — `git add services/energy-exporter/src/state_server.py services/energy-exporter/src/main.py services/energy-exporter/tests/test_state_server.py`

---

## Task 2: Controller — base-load estimator

**Files:** Create `services/surplus-controller/src/baseload.py`; Test `services/surplus-controller/tests/test_baseload.py`.

- [ ] **Step 1: Write the failing test**

```python
from src.baseload import BaseLoad


def test_warmup_returns_none_until_enough_span():
    b = BaseLoad(window_s=3600, percentile=20, min_warmup_s=1200)
    b.update(0, 400)
    b.update(600, 450)                 # only 600 s of span -> not warmed up
    assert b.estimate() is None


def test_percentile_tracks_baseline_not_wp_peaks():
    b = BaseLoad(window_s=3600, percentile=20, min_warmup_s=1200)
    # WP cycles: long stretches at ~2400 W (base 400 + WP 2000), troughs at ~400 W base.
    t = 0
    for _ in range(30):
        b.update(t, 400);  t += 60      # base trough
        b.update(t, 2400); t += 60      # WP running
    base = b.estimate()
    assert 350 < base < 700             # ~the base trough, not the 2400 W peaks


def test_window_evicts_old_samples():
    b = BaseLoad(window_s=3600, percentile=20, min_warmup_s=0)
    b.update(0, 5000)                   # old high sample
    for t in range(3700, 5000, 60):     # all > window_s after the old one
        b.update(t, 400)
    assert b.estimate() < 600           # the 5000 W sample has been evicted
```

- [ ] **Step 2: Run — FAIL** (`ModuleNotFoundError: src.baseload`)

Run: `cd services/surplus-controller && python3 -m pytest tests/test_baseload.py -v`

- [ ] **Step 3: Implement** `services/surplus-controller/src/baseload.py`

```python
"""Rolling household base-load estimate (consumption excluding the heat pump).

available = production - base_load is the real PV headroom for the WP. base_load is the
low-percentile of recent consumption: the heat pump cycles, so the window holds WP-off
troughs, and a low percentile picks them out while ignoring cooking/load spikes."""
import collections


class BaseLoad:
    def __init__(self, window_s=3600, percentile=20, min_warmup_s=1200):
        self.window_s = window_s
        self.percentile = percentile
        self.min_warmup_s = min_warmup_s
        self._samples = collections.deque()   # (ts, consumption_w), ascending ts

    def update(self, now, consumption_w):
        if consumption_w is None:
            return
        self._samples.append((now, float(consumption_w)))
        cutoff = now - self.window_s
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def estimate(self):
        """Base-load watts, or None until the window spans at least min_warmup_s."""
        if not self._samples:
            return None
        span = self._samples[-1][0] - self._samples[0][0]
        if span < self.min_warmup_s:
            return None
        vals = sorted(v for _, v in self._samples)
        k = max(0, min(len(vals) - 1, int(round((self.percentile / 100.0) * (len(vals) - 1)))))
        return vals[k]
```

- [ ] **Step 4: Run — PASS**

Run: `cd services/surplus-controller && python3 -m pytest tests/test_baseload.py -v`

- [ ] **Step 5: Stage** — `git add services/surplus-controller/src/baseload.py services/surplus-controller/tests/test_baseload.py`

---

## Task 3: Controller — `available_and_basis()` + decide_action refactor

**Files:** Modify `services/surplus-controller/src/threshold.py`; Test `services/surplus-controller/tests/test_threshold.py`; Modify `tests/test_decide_action.py`, `tests/test_main_loop.py`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_threshold.py`)

```python
def test_available_production_basis():
    from src.threshold import available_and_basis
    # production fresh + base known -> production - base, regardless of relay/sun.
    a, basis = available_and_basis(surplus=-565, production=300, base_load=500,
                                   relay_on=True, sun_up=False, wp_nominal_power_w=2000)
    assert a == -200.0 and basis == "production"


def test_available_nominal_fallback_when_no_production():
    from src.threshold import available_and_basis
    # no production -> today's logic: surplus + wp_nominal when relay_on AND sun_up.
    a, basis = available_and_basis(surplus=-565, production=None, base_load=None,
                                   relay_on=True, sun_up=True, wp_nominal_power_w=2000)
    assert a == 1435.0 and basis == "nominal"
    a2, _ = available_and_basis(surplus=-565, production=None, base_load=None,
                                relay_on=True, sun_up=False, wp_nominal_power_w=2000)
    assert a2 == -565.0          # sun down -> no compensation (unchanged 0.4.1 behaviour)


def test_available_fallback_when_base_not_warmed():
    from src.threshold import available_and_basis
    a, basis = available_and_basis(surplus=100, production=2000, base_load=None,
                                   relay_on=False, sun_up=True, wp_nominal_power_w=2000)
    assert basis == "nominal" and a == 100.0     # base not ready -> fallback
```

- [ ] **Step 2: Run — FAIL** (`ImportError: available_and_basis`)

Run: `cd services/surplus-controller && python3 -m pytest tests/test_threshold.py -k available -v`

- [ ] **Step 3: Implement** in `services/surplus-controller/src/threshold.py` (keep `available_surplus` for the fallback):

```python
def available_and_basis(surplus, production, base_load, relay_on, sun_up, wp_nominal_power_w):
    """The PV surplus genuinely free for the WP, plus which basis was used.

    Preferred: `production - base_load` (real headroom; needs fresh inverter production AND a
    warmed-up base-load). Fallback: today's load-compensation `surplus + wp_nominal` while the
    relay is on and the sun is up (0.4.1 behaviour) — used when production or base is missing."""
    if production is not None and base_load is not None:
        return production - base_load, "production"
    return available_surplus(surplus, relay_on, wp_nominal_power_w if sun_up else 0.0), "nominal"
```

- [ ] **Step 4: Refactor `decide_action`** in `services/surplus-controller/src/main.py` to take a precomputed `available` instead of `sun_up` (the caller now owns the available computation). Replace the function:

```python
def decide_action(cfg, relay_on, state_fresh, fresh_for_decide, surplus, available, eff,
                  on_streak, off_streak, secs_since_on, secs_since_off):
    """Pure core of one control cycle (no I/O). `available` is the PV surplus the decision
    acts on (production-based or nominal-fallback, computed by the caller). The blind/stale
    path still ignores it and fails safe."""
    if state_fresh:
        on_streak = on_streak + 1 if available > eff else 0
        off_streak = off_streak + 1 if available < cfg["threshold_off_w"] else 0
        avail = available
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

- [ ] **Step 5: Update the existing decide_action tests** — in `tests/test_main_loop.py` and `tests/test_decide_action.py`, the calls now pass `available=` (the precomputed value) instead of `sun_up=`. For the two 0.4.1 sun tests in `test_main_loop.py`, replace them with `available_and_basis` assertions (already covered in Task 3 Step 1) and update the remaining `decide_action(` calls to pass `available` as the value that the old `surplus + comp` produced. Example replacement for a "sun up, stays on" case:

```python
def test_decide_action_high_available_stays_on():
    import src.main as M
    cfg = {"mode": "auto", "manual_relay_on": False, "wp_nominal_power_w": 2000.0,
           "threshold_off_w": 200.0, "on_delay_cycles": 1, "off_delay_cycles": 1,
           "min_runtime_s": 0, "min_offtime_s": 0}
    avail, *_rest, target, action, reason = M.decide_action(
        cfg, relay_on=True, state_fresh=True, fresh_for_decide=True,
        surplus=-565.0, available=1435.0, eff=1500.0, on_streak=0, off_streak=0,
        secs_since_on=9999, secs_since_off=9999)
    assert target is True


def test_decide_action_low_available_releases():
    import src.main as M
    cfg = {"mode": "auto", "manual_relay_on": False, "wp_nominal_power_w": 2000.0,
           "threshold_off_w": 200.0, "on_delay_cycles": 1, "off_delay_cycles": 1,
           "min_runtime_s": 0, "min_offtime_s": 0}
    avail, *_rest, target, action, reason = M.decide_action(
        cfg, relay_on=True, state_fresh=True, fresh_for_decide=True,
        surplus=-565.0, available=-200.0, eff=1500.0, on_streak=0, off_streak=0,
        secs_since_on=9999, secs_since_off=9999)
    assert target is False and action == "switched_off"
```

For `tests/test_decide_action.py` (3 pre-existing cases), pass `available` equal to what `surplus + wp_nominal` (sun up) produced in each case, preserving their intent.

- [ ] **Step 6: Run** — `cd services/surplus-controller && python3 -m pytest tests/test_threshold.py tests/test_main_loop.py tests/test_decide_action.py -v` → green.

- [ ] **Step 7: Stage** — `git add services/surplus-controller/src/threshold.py services/surplus-controller/src/main.py services/surplus-controller/tests/`

---

## Task 4: Controller — wire estimator + available into the loop, add metrics

**Files:** Modify `services/surplus-controller/src/main.py`, `services/surplus-controller/src/metrics.py`.

- [ ] **Step 1: Add the metrics** — in `services/surplus-controller/src/metrics.py`, after the `SUN_SET` gauge:

```python
BASE_LOAD = Gauge("surplus_control_base_load_watts",
                  "Estimated household base load (consumption excluding the heat pump); the "
                  "baseline subtracted from PV production to get the surplus available to the WP.")
AVAILABLE_BASIS = Gauge("surplus_control_available_basis",
                        "How 'available' was computed: 1 = production - base_load (accurate), "
                        "0 = surplus + wp_nominal fallback (no fresh inverter production).")
```

- [ ] **Step 2: Add the estimator + imports** — in `main.py`, add `from .baseload import BaseLoad` and `from .threshold import adaptive_threshold, available_and_basis, available_surplus`, and a module-level instance:

```python
_baseload = BaseLoad(window_s=3600, percentile=20, min_warmup_s=1200)
```

- [ ] **Step 3: Wire into the loop** — at the `decide_action(...)` call site in the main loop, read production, drive the estimator, compute `available`/`basis`, and pass `available` instead of `sun_up`:

```python
            sun_elev, sun_up = _sun_state()   # existing sun computation (keep your current lines)
            production = _num(state.get("production_w"))
            if production is not None and surplus is not None and state_fresh:
                # monotonic clock for the window so an NTP step can't corrupt the 60-min span
                _baseload.update(time.monotonic(), production - surplus)
            base_load = _baseload.estimate()
            available, basis = available_and_basis(
                surplus, production, base_load, relay_on, sun_up, cfg["wp_nominal_power_w"])
            avail, on_streak, off_streak, target, action, reason = decide_action(
                cfg, relay_on, state_fresh, fresh_for_decide, surplus, available, eff,
                on_streak, off_streak, now - last_on, now - last_off)
```

> Note: reuse the loop's existing wall-clock value for `now_wall`/`now` and the existing
> `state`/`surplus`/`state_fresh`/`sun_up` variables — do not rename them or change how
> `surplus`, the streaks, or `now - last_on/off` are computed. Only add the three new lines
> (production read, estimator update, `available_and_basis`) and swap the `decide_action` args.

- [ ] **Step 4: Set the new metrics** — in the reporting try-block (where `SUN_ELEVATION` is set), add:

```python
                if base_load is not None:
                    metrics.BASE_LOAD.set(base_load)
                metrics.AVAILABLE_BASIS.set(1 if basis == "production" else 0)
```

- [ ] **Step 5: Run the full suite**

Run: `docker build --target test services/surplus-controller` → green.

- [ ] **Step 6: Stage** — `git add services/surplus-controller/src/main.py services/surplus-controller/src/metrics.py`

---

## Task 5: Docs + version bump 0.5.0

**Files:** `docs/architecture.md`, `README.md`, `CHANGELOG.md`, `deploy/compose/docker-compose.yml`, `deploy/compose/docker-compose.demo.yml`, `deploy/compose/.env.example`, `deploy/k8s/kustomization.yaml`, `deploy/k8s/{energy-exporter,surplus-controller,control-ui,heatpump-exporter}.yaml`.

- [ ] **Step 1: architecture.md** — replace the "Compensate own load" description: the controller now uses `available = production − base_load` (the real PV headroom, base-load = 20th-percentile of recent consumption) when fresh inverter production is available, falling back to `surplus + wp_nominal` (sun-gated) otherwise. Note the sun-gate remains as an independent guard.

- [ ] **Step 2: README** — adjust the "Self-calibrating" / surplus feature bullet to mention the surplus is measured as production-minus-baseline (no fixed heat-pump nominal needed when the inverter is present).

- [ ] **Step 3: CHANGELOG** — new `## [0.5.0] - <date>` section above 0.4.2:

```markdown
## [0.5.0] - 2026-06-16

### Changed
- The controller now acts on **real PV headroom**: `available = production − base_load`
  (base_load = 20th-percentile of recent consumption) instead of a fixed `surplus + wp_nominal`
  load-compensation. The heat pump is no longer held on grid power when it modulates below its
  nominal draw. Falls back to the previous (sun-gated) logic when no fresh inverter production
  is available; the fail-safe chain and the sun-gate are unchanged.
- The exporter publishes `production_w` in `/state` only while the inverter reading is fresh.

### Added
- Gauges `surplus_control_base_load_watts` and `surplus_control_available_basis`.
```

Update the compare links: `[Unreleased]: .../compare/v0.5.0...HEAD`, add `[0.5.0]: .../compare/v0.4.2...v0.5.0`.

- [ ] **Step 4: Version bump** — run:

```bash
cd ~/workspaces/private/sunsteer
sed -i '' 's/SUNSTEER_VERSION:-0.4.2/SUNSTEER_VERSION:-0.5.0/g' deploy/compose/docker-compose.yml deploy/compose/docker-compose.demo.yml
sed -i '' 's/^#SUNSTEER_VERSION=0.4.2/#SUNSTEER_VERSION=0.5.0/; s/(default: 0.4.2)/(default: 0.5.0)/' deploy/compose/.env.example
sed -i '' 's#\(sunsteer/[a-z-]*\):0.4.2#\1:0.5.0#' deploy/k8s/energy-exporter.yaml deploy/k8s/surplus-controller.yaml deploy/k8s/control-ui.yaml deploy/k8s/heatpump-exporter.yaml
sed -i '' 's/newTag: "0.4.2"/newTag: "0.5.0"/g; s/already pin :0.4.2/already pin :0.5.0/' deploy/k8s/kustomization.yaml
```

Verify: `grep -rn "0.4.2" deploy/ | grep -v sha256` → nothing.

- [ ] **Step 5: Stage** — `git add docs/architecture.md README.md CHANGELOG.md deploy/`

---

## Final verification

- [ ] All four Dockerfile test stages pass: `for s in surplus-controller energy-exporter control-ui heatpump-exporter; do docker build --target test services/$s || echo FAIL $s; done`
- [ ] `ruff check .` clean (in a `python:3.12-slim` container with `ruff==0.15.17`).
- [ ] `docker compose -f deploy/compose/docker-compose.yml config -q` OK; kustomize build shows `:0.5.0`.
- [ ] Hand the uncommitted tree to the user to commit + tag `v0.5.0`.

---

## Self-review (author)

- **Spec coverage:** fresh-only production (T1), base-load estimator (T2), `available_and_basis` + decide_action refactor (T3), loop wiring + metrics (T4), docs + 0.5.0 (T5). Sun-gate kept (T3 fallback uses `sun_up`); fail-safe blind path untouched (T3 `else` branch). #2 report is explicitly out of scope.
- **Type consistency:** `available_and_basis(surplus, production, base_load, relay_on, sun_up, wp_nominal_power_w) -> (float, str)`; basis ∈ {"production","nominal"}; `decide_action(..., surplus, available, eff, ...)`; `BaseLoad.update(now, consumption_w)` / `.estimate() -> float|None`. Used consistently across tasks.
- **Caller caveat (T4):** the implementer must keep the existing loop variable names and only add the three new lines + swap `decide_action` args; `_sun_state()` is shorthand for the existing sun_elev/sun_up lines — keep whatever the current code does there.
