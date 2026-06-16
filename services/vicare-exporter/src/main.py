"""heatpump-exporter: poll the configured driver -> Prometheus + TimescaleDB. READ-ONLY."""
import logging
import os
import time

from prometheus_client import start_http_server

from . import drivers, metrics, tsdb_writer
from .ratebudget import clamp_interval

log = logging.getLogger(__name__)

METRICS_PORT = int(os.environ.get("METRICS_PORT", "9125"))
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
        os.environ["DB_HOST"], int(os.environ.get("DB_PORT", "5432")),
        os.environ["DB_NAME"], os.environ["DB_USER"], os.environ["DB_PASS"])


def main():
    validate_env()
    start_http_server(METRICS_PORT)
    if HEATPUMP_DRIVER not in drivers.SUPPORTED_DRIVERS:
        raise SystemExit(f"heatpump-exporter: unknown HEATPUMP_DRIVER '{HEATPUMP_DRIVER}'")
    driver = drivers.get_driver(HEATPUMP_DRIVER)
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
