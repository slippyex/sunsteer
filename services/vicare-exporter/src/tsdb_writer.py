"""Persist a datapoint dict to heatpump_telemetry. Tolerant: NULLs allowed."""
import logging
from collections.abc import Callable

import psycopg2

from .contract import HEATPUMP_FIELDS

COLUMNS = list(HEATPUMP_FIELDS)  # writer names columns explicitly, so DDL order is irrelevant

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


def write(conn, data):
    cols = ", ".join(COLUMNS)
    placeholders = ", ".join(["%s"] * len(COLUMNS))
    params = [data.get(c) for c in COLUMNS]
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO heatpump_telemetry (time, {cols}) VALUES (now(), {placeholders})",
            params)
