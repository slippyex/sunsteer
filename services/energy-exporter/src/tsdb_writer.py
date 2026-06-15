"""1-minute aggregation + INSERT into TimescaleDB."""
import logging
from collections.abc import Callable

import psycopg2

_log = logging.getLogger(__name__)

_MEAN_FIELDS = ("import_w", "export_w", "surplus_w", "l1_w", "l2_w", "l3_w")
_LAST_FIELDS = ("import_kwh_total", "export_kwh_total")


def aggregate_samples(samples):
    if not samples:
        return None
    out = {f: sum(s[f] for s in samples) / len(samples) for f in _MEAN_FIELDS}
    for f in _LAST_FIELDS:
        out[f] = samples[-1][f]
    return out


def write_meter(conn, agg: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO energy_meter (time, import_w, export_w, surplus_w, l1_w, l2_w, l3_w, "
            "import_kwh_total, export_kwh_total, production_w, production_kwh_total, "
            "dc_power_a_w, dc_power_b_w, inverter_temp_c) "
            "VALUES (now(),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (agg["import_w"], agg["export_w"], agg["surplus_w"], agg["l1_w"], agg["l2_w"],
             agg["l3_w"], agg["import_kwh_total"], agg["export_kwh_total"],
             agg.get("production_w"), agg.get("production_kwh_total"),
             agg.get("dc_power_a_w"), agg.get("dc_power_b_w"), agg.get("inverter_temp_c")),
        )
    conn.commit()


def write_heatpump(conn, r: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO heatpump (time, relay_on, power_w, energy_wh_total) VALUES (now(),%s,%s,%s)",
            (r["relay_on"], r["power_w"], r["energy_wh_total"]),
        )
    conn.commit()


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
