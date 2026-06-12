"""surplus-controller: read /state + config -> decide -> drive Shelly. Headless."""
import json
import os
import threading
import time
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from prometheus_client import start_http_server

from . import config, dblog, metrics, status_server
from .threshold import adaptive_threshold, available_surplus
from .statemachine import decide
from .shelly_ctl import set_switch, get_switch
from .forecast import fetch_all, fetch_gti, pv_estimate

STATE_URL = os.environ.get("EXPORTER_STATE_URL", "http://192.168.2.230:9121/state")
SHELLY_URL = os.environ.get("SHELLY_URL", "http://192.168.2.90")
METRICS_PORT = int(os.environ.get("METRICS_PORT", "9123"))
STATUS_PORT = int(os.environ.get("STATUS_PORT", "9124"))
LOOP_S = int(os.environ.get("LOOP_SECONDS", "15"))
AUTOOFF_S = int(os.environ.get("SHELLY_AUTOOFF_SECONDS", "60"))
# SHM reading older than this (or missing) -> controller is "blind" -> fail-safe OFF.
# Generous vs the ~1-2 s SHM cadence so brief network blips don't flap the WP.
STALE_S = int(os.environ.get("STATE_STALE_SECONDS", "30"))
# Tolerate this many CONSECUTIVE blind cycles before the fail-safe forces OFF — a single missed
# read (deploy gap, blip) shouldn't cycle the WP. Still backed by the Shelly auto-off
# (SHELLY_AUTOOFF_SECONDS, 180s).
STALE_GRACE_CYCLES = int(os.environ.get("STALE_GRACE_CYCLES", "2"))
FORECAST_S = int(os.environ.get("FORECAST_REFRESH_SECONDS", "10800"))  # 3h
PV_LAT = os.environ.get("PV_LAT", "49.44424")
PV_LON = os.environ.get("PV_LON", "7.44393")
PV_TZ = os.environ.get("PV_TZ", "Europe/Berlin")  # forecast.solar returns local timestamps
# roof planes as JSON: [[declination, azimuth, kwp], ...]  (azimuth: 0=S, -90=E, +90=W)
PV_PLANES = json.loads(os.environ.get("PV_PLANES", "[[28,-90,7.26],[28,90,7.92]]"))

_forecast_remaining = None   # kWh, updated by the slow timer


def read_state():
    """GET the exporter /state JSON. Returns dict or None."""
    try:
        with urllib.request.urlopen(STATE_URL, timeout=5) as resp:
            return json.load(resp)
    except Exception:
        return None


def _compute_forecast(conn, cfg, now_str, day_str):
    """PV forecast: Open-Meteo GTI primary (self-calibrated PR from real production), forecast.solar
    fallback. Returns (day_kwh, remaining_kwh, pr_or_None) or None if every source failed."""
    hourly_by_plane = []
    for decl, az, kwp in PV_PLANES:
        h = fetch_gti(PV_LAT, PV_LON, decl, az)
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
            conn = None
        time.sleep(FORECAST_S)


def _db_connect():
    return dblog.connect(os.environ["DB_HOST"], int(os.environ.get("DB_PORT", "5432")),
                         os.environ["DB_NAME"], os.environ["DB_USER"], os.environ["DB_PASS"])


def main():
    start_http_server(METRICS_PORT)
    conn = _db_connect()
    # the forecast thread gets its OWN connection — psycopg2 connections are not
    # safe to share concurrently across threads.
    threading.Thread(target=status_server.serve, args=(STATUS_PORT,), daemon=True).start()
    threading.Thread(target=forecast_loop, args=(_db_connect,), daemon=True).start()

    # Seed commanded state from the Shelly's real relay state so a controller
    # restart doesn't re-log a spurious 'switched_on' while the WP already runs.
    relay_on = bool(get_switch(SHELLY_URL))
    on_streak = off_streak = stale_streak = 0
    # Restore min-runtime / min-offtime across restarts from the REAL last switch times in
    # decision_log — not a dummy "satisfied at boot" reset (which let the WP re-switch while
    # the 30 min / 15 min guards were still meant to be running).
    now0 = time.monotonic()
    try:
        age_on, age_off = dblog.last_switch_ages(conn)
    except Exception:
        age_on = age_off = None
    last_on = now0 - (age_on if age_on is not None else 10_000)
    last_off = now0 - (age_off if age_off is not None else 10_000)
    last_cfg = config.clamp_config(dict(config.DEFAULTS))  # safe (paused) fallback
    status_server.beat(max(60.0, 4 * LOOP_S))  # healthy from startup, before the first cycle

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
            surplus_raw = st.get("surplus_w") if st else None
            age = st.get("shm_age_s") if st else None
            shelly_reachable = st.get("shelly_reachable") if st else None
            shelly_on = st.get("shelly_on") if st else None
            # "fresh" = a real, recent SHM reading. Missing JSON, missing surplus, or a
            # missing/old timestamp all mean "blind" -> decide() fails the WP safe-off.
            state_fresh = surplus_raw is not None and age is not None and age <= STALE_S
            surplus = surplus_raw if surplus_raw is not None else 0.0
            eff = adaptive_threshold(cfg, _forecast_remaining)

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
                    dblog.write_decision(conn, cfg["mode"], surplus, eff, _forecast_remaining,
                                         shelly_on, "switched_on" if shelly_on else "switched_off",
                                         "external_change", available_w=surplus,
                                         relay_on_before=relay_on, state_age_s=age,
                                         shelly_reachable=shelly_reachable)
                except Exception:
                    metrics.LOOP_ERRORS.labels("decision_log").inc()
                relay_on = shelly_on
                last_on, last_off = (now, last_off) if shelly_on else (last_on, now)

            if state_fresh:
                # Load-compensate so on/off compare "surplus without the WP" -> no self-oscillation
                # from the WP's own draw depressing the SHM reading while it runs.
                avail = available_surplus(surplus, relay_on, cfg["wp_nominal_power_w"])
                on_streak = on_streak + 1 if avail > eff else 0
                off_streak = off_streak + 1 if avail < cfg["threshold_off_w"] else 0
            else:
                # Blind: never compensate (that's what kept the WP on grid power), reset streaks.
                avail = surplus
                on_streak = off_streak = 0

            target, action, reason = decide(
                cfg["mode"], relay_on, cfg["manual_relay_on"],
                on_streak, off_streak, cfg["on_delay_cycles"], cfg["off_delay_cycles"],
                now - last_on, now - last_off, cfg["min_runtime_s"], cfg["min_offtime_s"],
                state_fresh=fresh_for_decide)

            relay_before = relay_on
            if action in ("switched_on", "switched_off"):
                ok = set_switch(SHELLY_URL, target, auto_off_s=AUTOOFF_S)
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
                    dblog.write_decision(conn, cfg["mode"], surplus, eff, _forecast_remaining,
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
                if not set_switch(SHELLY_URL, True, auto_off_s=AUTOOFF_S):
                    metrics.SHELLY_ERRORS.inc()

            wp_est = cfg["wp_nominal_power_w"] if relay_on else 0.0
            metrics.update(cfg["mode"], relay_on, eff, _forecast_remaining, wp_est,
                           state_fresh=state_fresh, state_age_s=age, available_w=avail)
            status_server.set_status(
                mode=cfg["mode"], relay_on=relay_on, surplus_w=surplus, available_w=avail,
                effective_threshold_w=eff, on_streak=on_streak, off_streak=off_streak,
                on_delay_cycles=cfg["on_delay_cycles"], off_delay_cycles=cfg["off_delay_cycles"],
                secs_since_on=int(now - last_on), secs_since_off=int(now - last_off),
                min_runtime_s=cfg["min_runtime_s"], min_offtime_s=cfg["min_offtime_s"],
                loop_seconds=LOOP_S, reason=reason, state_fresh=state_fresh, state_age_s=age)
        except Exception:
            metrics.LOOP_ERRORS.labels("cycle").inc()
        # Heartbeat AFTER the cycle (incl. handled errors): a true hang inside the try stops
        # this beat -> /healthz goes 503 -> liveness restarts the loop. Threshold = a few loops.
        status_server.beat(max(60.0, 4 * LOOP_S))
        time.sleep(LOOP_S)


if __name__ == "__main__":
    main()
