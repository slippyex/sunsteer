"""Inserts into decision_log and solar_forecast (autocommit connection)."""
import logging
from collections.abc import Callable

import psycopg2

_log = logging.getLogger(__name__)


def connect(host: str, port: int, db: str, user: str, password: str):
    conn = psycopg2.connect(host=host, port=port, dbname=db, user=user, password=password)
    # autocommit so a single failed INSERT (e.g. table briefly missing on first boot)
    # cannot leave the connection in an aborted-transaction state and block all later writes.
    conn.autocommit = True
    return conn


def live_conn(conn, connect_fn: Callable[[], object]):
    """Return a usable connection, (re)connecting if the current one is dead/None.
    A TimescaleDB restart silently kills the held connection; pinging SELECT 1 detects
    that and reconnects, so the service recovers instead of degrading forever."""
    try:
        if conn is not None and not conn.closed:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            return conn
    except Exception:
        # Held connection is dead (e.g. TimescaleDB restarted). Log the cause, then reconnect
        # below — behaviour unchanged, just no longer silent.
        _log.warning("DB connection ping failed — reconnecting", exc_info=True)
    try:
        if conn is not None:
            conn.close()
    except Exception:
        pass
    try:
        return connect_fn()
    except Exception:
        # Reconnect failed; re-raise so the caller's loop degrades as before, but log the cause
        # so a persistent DB outage is visible instead of only counted.
        _log.warning("DB (re)connect failed", exc_info=True)
        raise


def write_decision(conn, mode: str, surplus_w: float, eff_threshold: float,
                   forecast_remaining: float | None, relay_target: bool, action: str,
                   reason: str, available_w: float | None = None,
                   relay_on_before: bool | None = None, state_age_s: float | None = None,
                   shelly_reachable: bool | None = None) -> None:
    """Append a decision. The extra inputs (available_w, relay_on_before, state_age_s,
    shelly_reachable) make a past switch fully reconstructable for later analysis."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO decision_log (time, mode, surplus_w, effective_threshold_w, "
            "forecast_remaining_kwh, relay_target, action, reason, available_w, "
            "relay_on_before, state_age_s, shelly_reachable) "
            "VALUES (now(),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (mode, surplus_w, eff_threshold, forecast_remaining, relay_target, action, reason,
             available_w, relay_on_before, state_age_s, shelly_reachable),
        )


def last_switch_ages(conn) -> tuple[float | None, float | None]:
    """Return (seconds_since_last_switched_on, seconds_since_last_switched_off), each None if
    no such event. Used at startup to restore min-runtime/min-offtime across a controller
    restart instead of resetting the timers to a dummy 'already satisfied' value."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXTRACT(EPOCH FROM now() - max(time) FILTER (WHERE action = 'switched_on')), "
            "       EXTRACT(EPOCH FROM now() - max(time) FILTER (WHERE action = 'switched_off')) "
            "FROM decision_log")
        on_age, off_age = cur.fetchone()
    return (float(on_age) if on_age is not None else None,
            float(off_age) if off_age is not None else None)


def recent_household_samples(conn, window_s):
    """Per-minute relay-OFF household consumption (production_w - surplus_w) over the last
    window_s seconds, for seeding the base-load estimator on startup. Returns a chronological
    list of (epoch_seconds, household_w), household >= 0 (impossible negatives from inverter/SHM
    sampling skew dropped, same rule as the live feed). Read-only."""
    with conn.cursor() as cur:
        cur.execute(
            "WITH wp AS (SELECT time_bucket('1 minute'::interval, time) m, bool_or(relay_on) on_ "
            "  FROM heatpump WHERE time >= now() - make_interval(secs => %s) GROUP BY m), "
            "sm AS (SELECT time_bucket('1 minute'::interval, time) m, "
            "  avg(production_w - surplus_w) hh FROM energy_meter "
            "  WHERE time >= now() - make_interval(secs => %s) AND production_w IS NOT NULL GROUP BY m) "
            "SELECT extract(epoch FROM sm.m), sm.hh FROM sm JOIN wp USING (m) "
            "WHERE NOT wp.on_ AND sm.hh >= 0 ORDER BY sm.m",
            (window_s, window_s))
        return [(float(e), float(h)) for e, h in cur.fetchall()]


def write_forecast(conn, forecast_date, expected_kwh_day: float,
                   expected_kwh_remaining: float) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO solar_forecast (time, forecast_date, expected_kwh_day, "
            "expected_kwh_remaining) VALUES (now(),%s,%s,%s)",
            (forecast_date, expected_kwh_day, expected_kwh_remaining),
        )


def daily_production(conn) -> dict[str, float]:
    """{date 'YYYY-MM-DD': produced_kWh} for COMPLETE past days (excludes today's partial day),
    used to self-calibrate the PV performance ratio against measured output.

    Summed from POSITIVE consecutive deltas of the monotonic lifetime counter, not
    max-min: if the inverter resets the counter mid-day, max-min would report the entire
    lifetime span (e.g. ~1004 kWh) as 'today'. A reset shows up as a negative delta, which
    greatest(...,0) drops, so the day's real production survives the reset."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT to_char(day, 'YYYY-MM-DD'), sum(delta) FROM ("
            "  SELECT date_trunc('day', time) AS day, "
            "         greatest(production_kwh_total - lag(production_kwh_total) "
            "                  OVER (ORDER BY time), 0) AS delta "
            "  FROM energy_meter WHERE production_kwh_total IS NOT NULL "
            "  AND time >= now() - interval '15 days' AND time < date_trunc('day', now())"
            ") d WHERE delta IS NOT NULL GROUP BY day")
        return {d: float(v) for d, v in cur.fetchall() if v is not None}


def update_pr(conn, pr: float) -> None:
    """Persist the self-calibrated performance ratio so it survives restarts and is visible.

    Called from the forecast THREAD on its own connection, while the main loop reads the same
    control_config row via load_config. The cross-thread access is safe: autocommit + a single
    independent column, and the value is re-clamped on read — no torn multi-column state."""
    with conn.cursor() as cur:
        cur.execute("UPDATE control_config SET pv_performance_ratio = %s WHERE id = 1", (pr,))
