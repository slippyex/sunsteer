"""surplus-controller: read /state + config -> decide -> drive Shelly. Headless."""
import json
import logging
import os
import threading
import time
import urllib.request
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from prometheus_client import start_http_server

from . import config, dblog, metrics, relays, status_server
from .baseload import BaseLoad
from .forecast import fetch_all, fetch_gti, pv_estimate
from .statemachine import decide
from .sun import sun_elevation, sun_window
from .threshold import adaptive_threshold, available_and_basis

_log = logging.getLogger(__name__)

def _pos_int(name, default, hi=86400):
    """Tolerant parse for port/sleep/cadence envs: a missing, non-numeric, zero/negative or
    absurd value falls back to the default, so a typo can't crash the controller at import
    (before validate_env can report it) or spin a tight loop (sleep 0)."""
    try:
        v = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return v if 1 <= v <= hi else default


STATE_URL = os.environ.get("EXPORTER_STATE_URL", "http://energy-exporter:9121/state")
SHELLY_URL = os.environ.get("SHELLY_URL")   # required — validated in main()
RELAY_DRIVER = os.environ.get("RELAY_DRIVER", "shelly")
METRICS_PORT = _pos_int("METRICS_PORT", 9123, hi=65535)
STATUS_PORT = _pos_int("STATUS_PORT", 9124, hi=65535)
# Interface /status + /healthz bind to. Default "" = all interfaces; set to a specific IP to
# restrict who can read the controller's operational telemetry (carries no secrets).
STATUS_BIND = os.environ.get("STATUS_BIND", "")
LOOP_S = _pos_int("LOOP_SECONDS", 15, hi=3600)
# Shelly hardware auto-off watchdog: the relay releases on its own if the controller stops
# re-arming it. Default 60s. Raise (e.g. 180s) if the relay sits on flaky WiFi that drops for
# up to ~1 min — otherwise a dropout outlasting the watchdog cycles the WP. See docs/hardware.md.
# validate_env() additionally enforces AUTOOFF_S > LOOP_S.
AUTOOFF_S = _pos_int("SHELLY_AUTOOFF_SECONDS", 60)
# SHM reading older than this (or missing) -> controller is "blind" -> fail-safe OFF.
# Generous vs the ~1-2 s SHM cadence so brief network blips don't flap the WP.
STALE_S = _pos_int("STATE_STALE_SECONDS", 30)
# Tolerate this many CONSECUTIVE blind cycles before the fail-safe forces OFF — a single missed
# read (deploy gap, blip) shouldn't cycle the WP. Still backed by the Shelly auto-off watchdog
# (SHELLY_AUTOOFF_SECONDS).
STALE_GRACE_CYCLES = _pos_int("STALE_GRACE_CYCLES", 2, hi=10000)
FORECAST_S = _pos_int("FORECAST_REFRESH_SECONDS", 10800)  # 3h
# After a failed forecast cycle, retry well before the full refresh interval so a transient
# hiccup can't strand the adaptive threshold on its base value for hours. Capped at FORECAST_S
# in case someone configures a very short refresh.
FORECAST_FAIL_BACKOFF_S = min(FORECAST_S, 300)
# Seed for last on/off switch time when decision_log has no prior event: "long ago" so the
# min-runtime / min-offtime guards are already satisfied at a cold start.
STARTUP_LONG_AGO_S = 10_000
# /healthz fails (503) if the loop hasn't beaten within this budget -> liveness restarts it.
# A few loops of slack so a single slow cycle doesn't trip a restart.
HEARTBEAT_BUDGET_S = max(60.0, 4 * LOOP_S)
PV_LAT = os.environ.get("PV_LAT")           # required — validated in main()
PV_LON = os.environ.get("PV_LON")           # required — validated in main()


def _sun_min_elev():
    try:
        v = float(os.environ.get("PV_SUN_MIN_ELEVATION_DEG", "3.0"))
    except (TypeError, ValueError):
        return 3.0
    return v if -18.0 <= v <= 90.0 else 3.0


SUN_MIN_ELEVATION_DEG = _sun_min_elev()

_sun_window_cache = {}   # local date -> (rise_ts, set_ts); today's PV window for the gauges


def _todays_sun_window(now_local):
    """(rise_ts, set_ts) unix timestamps of today's PV window (NaN if the sun never reaches
    the threshold). Cached per local date — the window is static for the day."""
    key = now_local.date()
    if key not in _sun_window_cache:
        _sun_window_cache.clear()
        day_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        rise, sset = sun_window(float(os.environ["PV_LAT"]), float(os.environ["PV_LON"]),
                                day_start, SUN_MIN_ELEVATION_DEG)
        _sun_window_cache[key] = (rise.timestamp() if rise else float("nan"),
                                  sset.timestamp() if sset else float("nan"))
    return _sun_window_cache[key]
PV_TZ = os.environ.get("PV_TZ", "UTC")      # forecast.solar returns local timestamps
# roof planes as JSON: [[declination, azimuth, kwp], ...]  (azimuth: 0=S, -90=E, +90=W)
try:
    PV_PLANES = json.loads(os.environ["PV_PLANES"]) if os.environ.get("PV_PLANES") else None
except json.JSONDecodeError:
    raise SystemExit("surplus-controller: PV_PLANES must be valid JSON: [[decl,az,kwp],...]") from None

REQUIRED_ENV = ("SHELLY_URL", "PV_LAT", "PV_LON", "PV_PLANES",
                "DB_HOST", "DB_NAME", "DB_USER", "DB_PASS")

# /state schema this controller understands. The exporter stamps the running schema; a
# mismatch is warned-and-continued in read_state() (don't crash on a contract bump).
KNOWN_STATE_SCHEMA = 1


def validate_env():
    """Fail fast with one clear message instead of half-starting against nothing."""
    missing = [n for n in REQUIRED_ENV if not os.environ.get(n)]
    if missing:
        raise SystemExit("surplus-controller: missing required environment variables: "
                         + ", ".join(missing))
    # Reject un-edited example manifests (SHELLY_URL=http://CHANGE_ME etc.) — presence alone
    # would let an unconfigured deploy start against a placeholder.
    placeholders = [n for n in REQUIRED_ENV if "CHANGE_ME" in os.environ.get(n, "")]
    if placeholders:
        raise SystemExit("surplus-controller: unedited CHANGE_ME placeholder in required "
                         "environment variables: " + ", ".join(placeholders))
    # The hardware auto-off watchdog must be armed for >= 1 s AND must outlast the loop re-arm
    # cadence, or it could fire between re-arms on a perfectly healthy controller.
    if AUTOOFF_S < 1 or AUTOOFF_S <= LOOP_S:
        raise SystemExit(
            f"surplus-controller: SHELLY_AUTOOFF_SECONDS={AUTOOFF_S} must be >= 1 and > "
            f"LOOP_SECONDS={LOOP_S} so the watchdog can never fire between re-arms")

_forecast_remaining = None   # kWh, updated by the slow timer
# Rolling household base-load (consumption minus the WP), driven from /state each fresh cycle.
# available = production - base_load is the real PV headroom; falls back to the nominal-load
# compensation until warmed up or while the inverter is stale.
_baseload = BaseLoad(window_s=3600, percentile=20, min_warmup_s=1200)


def _num(x):
    """Coerce a /state numeric field to float, or None if absent/non-numeric. A contract
    regression (e.g. surplus_w arriving as a string) must degrade to 'blind' -> fail-safe,
    never crash the cycle on a TypeError deep in the threshold math."""
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


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


def read_state():
    """GET the exporter /state JSON. Returns dict or None."""
    try:
        with urllib.request.urlopen(STATE_URL, timeout=5) as resp:
            state = json.load(resp)
    except Exception:
        # Blind read -> caller falls through to the stale/fail-safe path. Log the cause so a
        # flapping exporter / network is diagnosable; the fail-safe behaviour is unchanged.
        _log.warning("read_state failed (GET %s) — treating as blind", STATE_URL, exc_info=True)
        return None
    # The exporter stamps its /state schema. Warn-and-continue on a mismatch (a contract bump
    # may have changed/added fields) — never crash the controller over a version stamp.
    if isinstance(state, dict):
        schema = state.get("schema")
        if schema is not None and schema != KNOWN_STATE_SCHEMA:
            _log.warning("/state schema=%r != expected %r — using state anyway; the /state "
                         "contract may have changed", schema, KNOWN_STATE_SCHEMA)
    return state


def _compute_forecast(conn, cfg, now_str, day_str):
    """PV forecast: Open-Meteo GTI primary (self-calibrated PR from real production), forecast.solar
    fallback. Returns (day_kwh, remaining_kwh, pr_or_None) or None if every source failed."""
    hourly_by_plane = []
    for decl, az, kwp in PV_PLANES:
        h = fetch_gti(PV_LAT, PV_LON, decl, az, tz=PV_TZ)
        if h is None:                      # need every plane for an accurate sum
            hourly_by_plane = None
            break
        hourly_by_plane.append((h, kwp))
    if hourly_by_plane:
        actual = dblog.daily_production(conn)
        return pv_estimate(hourly_by_plane, now_str, day_str,
                           cfg.get("pv_performance_ratio", 0.70), actual)
    res = fetch_all(PV_LAT, PV_LON, PV_PLANES, now_str, day_str)   # fallback
    return (res[0], res[1], None) if res is not None else None


def forecast_loop(connect_fn):
    global _forecast_remaining
    conn = None
    while True:
        # timestamps are in the array's LOCAL timezone — compare in the same tz
        now = datetime.now(ZoneInfo(PV_TZ))
        now_str, day_str = now.strftime("%Y-%m-%d %H:%M:%S"), now.strftime("%Y-%m-%d")
        delay = FORECAST_S
        try:
            conn = dblog.live_conn(conn, connect_fn)  # reconnect across DB restarts
            cfg = config.load_config(conn)
            res = _compute_forecast(conn, cfg, now_str, day_str)
            if res is not None:
                day_kwh, remaining, pr = res
                _forecast_remaining = remaining
                dblog.write_forecast(conn, now.date(), day_kwh, remaining)
                if pr is not None:                       # self-calibrated -> persist + expose
                    dblog.update_pr(conn, pr)
                    metrics.PV_PR.set(pr)
        except Exception:
            # DB/forecast cycle failed -> drop the connection and retry SOON, not after the full
            # refresh interval: parking for 3h would leave the adaptive threshold stuck on its
            # base value (no remaining-kWh forecast) for hours after a transient hiccup. Log the
            # cause instead of swallowing it silently.
            _log.warning("forecast loop cycle failed — dropping DB connection, retry in %ss",
                         FORECAST_FAIL_BACKOFF_S, exc_info=True)
            conn = None
            delay = FORECAST_FAIL_BACKOFF_S
        time.sleep(delay)


def _db_connect():
    return dblog.connect(os.environ["DB_HOST"], _pos_int("DB_PORT", 5432, hi=65535),
                         os.environ["DB_NAME"], os.environ["DB_USER"], os.environ["DB_PASS"])


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    validate_env()
    relay = relays.get_relay(RELAY_DRIVER, SHELLY_URL)
    start_http_server(METRICS_PORT)
    conn = _db_connect()
    # the forecast thread gets its OWN connection — psycopg2 connections are not
    # safe to share concurrently across threads.
    threading.Thread(target=status_server.serve, args=(STATUS_PORT, STATUS_BIND), daemon=True).start()
    threading.Thread(target=forecast_loop, args=(_db_connect,), daemon=True).start()

    # Seed commanded state from the Shelly's real relay state so a controller
    # restart doesn't re-log a spurious 'switched_on' while the WP already runs.
    relay_on = bool(relay.get_state())
    on_streak = off_streak = stale_streak = 0
    # Restore min-runtime / min-offtime across restarts from the REAL last switch times in
    # decision_log — not a dummy "satisfied at boot" reset (which let the WP re-switch while
    # the 30 min / 15 min guards were still meant to be running).
    now0 = time.monotonic()
    try:
        age_on, age_off = dblog.last_switch_ages(conn)
    except Exception:
        age_on = age_off = None
    last_on = now0 - (age_on if age_on is not None else STARTUP_LONG_AGO_S)
    last_off = now0 - (age_off if age_off is not None else STARTUP_LONG_AGO_S)
    last_cfg = config.clamp_config(dict(config.DEFAULTS))  # safe (paused) fallback
    status_server.beat(HEARTBEAT_BUDGET_S)  # healthy from startup, before the first cycle

    while True:
        # The whole cycle is guarded: a transient DB error (the documented-flaky
        # TimescaleDB) must degrade to "skip cycle + keep re-arming the watchdog",
        # never kill the loop (a dead loop = no watchdog re-arm + no recovery).
        try:
            conn = dblog.live_conn(conn, _db_connect)  # reconnect across DB restarts
            try:
                last_cfg = config.load_config(conn)  # hot-reload; keep last good on failure
            except Exception:
                metrics.LOOP_ERRORS.labels("config").inc()
            cfg = last_cfg

            st = read_state()
            # Coerce to float (or None): a non-numeric value from a /state contract regression
            # must read as 'blind' -> fail-safe, not crash the threshold math mid-cycle.
            surplus_raw = _num(st.get("surplus_w")) if st else None
            age = _num(st.get("shm_age_s")) if st else None
            shelly_reachable = st.get("shelly_reachable") if st else None
            shelly_on = st.get("shelly_on") if st else None
            # "fresh" = a real, recent SHM reading. Missing JSON, missing surplus, or a
            # missing/old timestamp all mean "blind" -> decide() fails the WP safe-off.
            state_fresh = surplus_raw is not None and age is not None and age <= STALE_S
            surplus = surplus_raw if surplus_raw is not None else 0.0
            # Snapshot the forecast ONCE per cycle: the forecast thread updates the global
            # concurrently, and threshold / decision_log / metrics below must all see the same
            # value or the audit log can disagree with the decision it records.
            fc = _forecast_remaining
            eff = adaptive_threshold(cfg, fc)

            # Grace before failing safe-off: one blind blip (deploy gap, hiccup) must not cycle
            # the WP; only fail-safe after STALE_GRACE_CYCLES consecutive blind reads.
            stale_streak = stale_streak + 1 if not state_fresh else 0
            fresh_for_decide = state_fresh or stale_streak < STALE_GRACE_CYCLES
            now = time.monotonic()

            # Reconcile with the ACTUAL relay state. The Shelly can be flipped outside our control
            # — its auto-off watchdog (SHELLY_AUTOOFF_SECONDS, e.g. while we redeploy) or the
            # SMA/ennexOS dual-control.
            # decision_log only records OUR switches, so an external off/on would otherwise be
            # invisible (the "two EIN in a row" gap). Log it and resync.
            if state_fresh and shelly_reachable and shelly_on is not None and shelly_on != relay_on:
                try:
                    dblog.write_decision(conn, cfg["mode"], surplus, eff, fc,
                                         shelly_on, "switched_on" if shelly_on else "switched_off",
                                         "external_change", available_w=surplus,
                                         relay_on_before=relay_on, state_age_s=age,
                                         shelly_reachable=shelly_reachable)
                except Exception:
                    metrics.LOOP_ERRORS.labels("decision_log").inc()
                relay_on = shelly_on
                last_on, last_off = (now, last_off) if shelly_on else (last_on, now)

            # Pure decision core (load-compensation + hysteresis streaks + decide()).
            # Read lat/lon from the env at call time (validate_env guarantees they're present)
            # so the gate works regardless of import ordering. Keep the sun maths OUT of the
            # control-fault path: if the location can't be read, fail to the SAFE side
            # (sun_up=False -> no compensation -> the WP is released), never crash the cycle.
            try:
                sun_elev = sun_elevation(float(os.environ["PV_LAT"]), float(os.environ["PV_LON"]),
                                         datetime.now(UTC))
                sun_up = sun_elev >= SUN_MIN_ELEVATION_DEG
            except (KeyError, TypeError, ValueError):
                sun_elev, sun_up = None, False
            # Real PV headroom: production - base_load. Drive the base-load estimator with a
            # MONOTONIC timestamp (an NTP step can't corrupt the rolling window) from the WP-
            # excluded consumption (production - surplus). Fall back to nominal compensation
            # until the estimator is warmed up or while the inverter is stale.
            production = _num(st.get("production_w")) if st else None
            if production is not None and surplus_raw is not None and state_fresh:
                _baseload.update(time.monotonic(), production - surplus)
            base_load = _baseload.estimate()
            available, basis = available_and_basis(
                surplus, production, base_load, relay_on, sun_up, cfg["wp_nominal_power_w"])
            avail, on_streak, off_streak, target, action, reason = decide_action(
                cfg, relay_on, state_fresh, fresh_for_decide, surplus, available, eff,
                on_streak, off_streak, now - last_on, now - last_off)

            relay_before = relay_on
            if action in ("switched_on", "switched_off"):
                ok = relay.set(target, AUTOOFF_S)
                if ok:
                    relay_on = target
                    if target:
                        last_on = now
                    else:
                        last_off = now
                    metrics.SWITCHES.labels(action).inc()
                else:
                    metrics.SHELLY_ERRORS.inc()
                    reason = "shelly_write_failed"
                try:
                    dblog.write_decision(conn, cfg["mode"], surplus, eff, fc,
                                         target, action if ok else "no_change", reason,
                                         available_w=avail, relay_on_before=relay_before,
                                         state_age_s=age, shelly_reachable=shelly_reachable)
                except Exception:
                    metrics.LOOP_ERRORS.labels("decision_log").inc()
            elif relay_on:
                # re-arm the auto-off watchdog every cycle while ON. Reached on a 'surplus_ok'/
                # 'min_runtime' hold — including up to STALE_GRACE_CYCLES-1 BLIND cycles (the
                # grace deliberately tolerates one missed read, so one blind re-arm can happen).
                # After the grace, decide() returns switched_off above and re-arming stops, so a
                # persistently blind controller can extend the watchdog by at most one cycle.
                if not relay.set(True, AUTOOFF_S):
                    metrics.SHELLY_ERRORS.inc()

            # Non-safety reporting in its OWN try: a metrics/status failure is telemetry, not a
            # control fault — it must be categorised separately and can never share a failure
            # path with the decision/actuation logic above (which has already re-armed the relay).
            try:
                wp_est = cfg["wp_nominal_power_w"] if relay_on else 0.0
                metrics.update(cfg["mode"], relay_on, eff, fc, wp_est,
                               state_fresh=state_fresh, state_age_s=age, available_w=avail)
                if sun_elev is not None:
                    metrics.SUN_ELEVATION.set(sun_elev)
                if base_load is not None:
                    metrics.BASE_LOAD.set(base_load)
                metrics.AVAILABLE_BASIS.set(1 if basis == "production" else 0)
                rise_ts, set_ts = _todays_sun_window(datetime.now(ZoneInfo(PV_TZ)))
                metrics.SUN_RISE.set(rise_ts)
                metrics.SUN_SET.set(set_ts)
                status_reason = reason
                if not sun_up and not relay_on and action not in ("switched_on", "switched_off"):
                    status_reason = "sun_below_horizon"
                status_server.set_status(
                    mode=cfg["mode"], relay_on=relay_on, surplus_w=surplus, available_w=avail,
                    effective_threshold_w=eff, on_streak=on_streak, off_streak=off_streak,
                    on_delay_cycles=cfg["on_delay_cycles"], off_delay_cycles=cfg["off_delay_cycles"],
                    secs_since_on=int(now - last_on), secs_since_off=int(now - last_off),
                    min_runtime_s=cfg["min_runtime_s"], min_offtime_s=cfg["min_offtime_s"],
                    loop_seconds=LOOP_S, reason=status_reason, state_fresh=state_fresh, state_age_s=age)
            except Exception:
                metrics.LOOP_ERRORS.labels("reporting").inc()
        except Exception:
            metrics.LOOP_ERRORS.labels("cycle").inc()
        # Heartbeat AFTER the cycle (incl. handled errors): a true hang inside the try stops
        # this beat -> /healthz goes 503 -> liveness restarts the loop. Threshold = a few loops.
        status_server.beat(HEARTBEAT_BUDGET_S)
        time.sleep(LOOP_S)


if __name__ == "__main__":
    main()
