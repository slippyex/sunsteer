"""Persist a datapoint dict to heatpump_vicare. Tolerant: NULLs allowed."""
import psycopg2

from .extract import FIELDS

COLUMNS = list(FIELDS)  # column order == extract field order


def connect(host, port, db, user, password):
    conn = psycopg2.connect(host=host, port=port, dbname=db, user=user, password=password)
    conn.autocommit = True
    return conn


def live_conn(conn, connect_fn):
    """Return a usable connection, (re)connecting if the current one is dead/None.
    A TimescaleDB restart silently kills the held connection; pinging SELECT 1 detects
    that and reconnects, so the exporter recovers instead of degrading forever."""
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


def write(conn, data):
    cols = ", ".join(COLUMNS)
    placeholders = ", ".join(["%s"] * len(COLUMNS))
    params = [data.get(c) for c in COLUMNS]
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO heatpump_vicare (time, {cols}) VALUES (now(), {placeholders})",
            params)
