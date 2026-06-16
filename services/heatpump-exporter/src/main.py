"""heatpump-exporter: poll the configured driver -> Prometheus + TimescaleDB. READ-ONLY."""
import logging
import os
import time

from prometheus_client import start_http_server

from . import drivers, metrics, tsdb_writer
from .ratebudget import clamp_interval

log = logging.getLogger(__name__)


def _pos_int(name, default, hi=3600):
    """Parse a sleep-/cadence-driving env into a safe positive int. A missing, non-numeric,
    zero/negative or absurd value falls back to the default — a bad value must never crash
    the exporter at import or spin a tight loop (sleep 0)."""
    try:
        v = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return v if 1 <= v <= hi else default


METRICS_PORT = _pos_int("METRICS_PORT", 9125, hi=65535)
HEATPUMP_DRIVER = os.environ.get("HEATPUMP_DRIVER", "vicare")
POLL_S = clamp_interval(os.environ.get("HEATPUMP_POLL_SECONDS",
                                       os.environ.get("VICARE_POLL_SECONDS", "300")))
REQUIRED_ENV = ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASS")


def validate_env():
    required = list(REQUIRED_ENV)
    if HEATPUMP_DRIVER == "vicare":
        from .drivers.vicare import REQUIRED_ENV as VICARE_ENV
        required += list(VICARE_ENV)
    missing = [n for n in required if not os.environ.get(n)]
    if missing:
        raise SystemExit("heatpump-exporter: missing required environment variables: "
                         + ", ".join(missing))
    placeholders = [n for n in required if "CHANGE_ME" in os.environ.get(n, "")]
    if placeholders:
        raise SystemExit("heatpump-exporter: unsubstituted CHANGE_ME placeholder in: "
                         + ", ".join(placeholders))


def run_cycle(driver, conn):
    """One poll cycle. The driver returns a reading or None (skip). Guarded by the caller."""
    reading = driver.poll()
    if reading is None:
        return
    metrics.set_from(reading)
    if conn is not None:
        tsdb_writer.write(conn, reading)
    metrics.LAST_SUCCESS.set(time.time())


def _db():
    return tsdb_writer.connect(
        os.environ["DB_HOST"], _pos_int("DB_PORT", 5432, hi=65535),
        os.environ["DB_NAME"], os.environ["DB_USER"], os.environ["DB_PASS"])


def main():
    validate_env()
    start_http_server(METRICS_PORT)
    driver = drivers.get_driver(HEATPUMP_DRIVER)   # the single validator for unknown driver names
    conn = None
    backoff = 0
    while True:
        try:
            conn = tsdb_writer.live_conn(conn, _db)
            run_cycle(driver, conn)
            backoff = 0
        except Exception:
            metrics.SCRAPE_ERRORS.labels("cycle").inc()
            conn = None
            backoff = min(backoff + POLL_S, 1800)
        time.sleep(POLL_S + backoff)


if __name__ == "__main__":
    main()
