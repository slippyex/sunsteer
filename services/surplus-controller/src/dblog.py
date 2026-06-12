"""Inserts into decision_log and solar_forecast (autocommit connection)."""
import psycopg2


def connect(host, port, db, user, password):
    conn = psycopg2.connect(host=host, port=port, dbname=db, user=user, password=password)
    conn.autocommit = True
    return conn


def live_conn(conn, connect_fn):
    """Return a usable connection, (re)connecting if the current one is dead/None.
    A TimescaleDB restart silently kills the held connection; pinging SELECT 1 detects
    that and reconnects, so the controller recovers instead of degrading forever."""
    try:
        if conn is not None and not conn.closed:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            return conn
    except Exception:
        pass
    try:
        if conn is not None:
            conn.close()
    except Exception:
        pass
    return connect_fn()


def write_decision(conn, mode, surplus_w, eff_threshold, forecast_remaining,
                   relay_target, action, reason, available_w=None, relay_on_before=None,
                   state_age_s=None, shelly_reachable=None):
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


def last_switch_ages(conn):
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


def write_forecast(conn, forecast_date, expected_kwh_day, expected_kwh_remaining):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO solar_forecast (time, forecast_date, expected_kwh_day, "
            "expected_kwh_remaining) VALUES (now(),%s,%s,%s)",
            (forecast_date, expected_kwh_day, expected_kwh_remaining),
        )


def daily_production(conn):
    """{date 'YYYY-MM-DD': produced_kWh} for COMPLETE past days (excludes today's partial day),
    used to self-calibrate the PV performance ratio against measured output."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT to_char(date_trunc('day', time), 'YYYY-MM-DD'), "
            "       max(production_kwh_total) - min(production_kwh_total) "
            "FROM energy_meter WHERE production_kwh_total IS NOT NULL "
            "AND time >= now() - interval '15 days' AND time < date_trunc('day', now()) "
            "GROUP BY 1")
        return {d: float(v) for d, v in cur.fetchall() if v is not None}


def update_pr(conn, pr):
    """Persist the self-calibrated performance ratio so it survives restarts and is visible."""
    with conn.cursor() as cur:
        cur.execute("UPDATE control_config SET pv_performance_ratio = %s WHERE id = 1", (pr,))
