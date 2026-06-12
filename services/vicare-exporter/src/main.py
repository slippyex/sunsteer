"""vicare-exporter: poll ViCare -> Prometheus + TimescaleDB. READ-ONLY, budget-guarded."""
import os
import time

from prometheus_client import start_http_server

from . import metrics, tsdb_writer, vicare_client, auth
from .extract import extract
from .ratebudget import RateBudget, clamp_interval

METRICS_PORT = int(os.environ.get("METRICS_PORT", "9125"))
POLL_S = clamp_interval(os.environ.get("VICARE_POLL_SECONDS", "300"))
DAILY_CAP = int(os.environ.get("VICARE_DAILY_CAP", "1400"))
TOKEN_FILE = os.environ.get("VICARE_TOKEN_FILE", "/data/vicare_token.json")


def run_cycle(device, conn, budget, now):
    """One poll cycle. Guarded by the caller. Skips (no exception) when budget is spent."""
    if not budget.allow(now):
        metrics.BUDGET_EXHAUSTED.set(1)
        metrics.BUDGET_USED.set(budget.count(now))
        return
    metrics.BUDGET_EXHAUSTED.set(0)
    features = vicare_client.poll(device)
    budget.record(now)
    metrics.API_CALLS.inc()
    metrics.BUDGET_USED.set(budget.count(now))
    data = extract(features)
    metrics.set_from(data)
    if conn is not None:
        tsdb_writer.write(conn, data)
    metrics.LAST_SUCCESS.set(time.time())


def _db():
    return tsdb_writer.connect(
        os.environ["DB_HOST"], int(os.environ.get("DB_PORT", "5432")),
        os.environ["DB_NAME"], os.environ["DB_USER"], os.environ["DB_PASS"])


def main():
    start_http_server(METRICS_PORT)
    device = auth.connect_device(TOKEN_FILE)
    conn = None
    budget = RateBudget(cap=DAILY_CAP, window_s=86400)
    backoff = 0
    while True:
        try:
            conn = tsdb_writer.live_conn(conn, _db)  # reconnect across DB restarts
            run_cycle(device, conn, budget, now=time.monotonic())
            backoff = 0
        except Exception as e:
            stage = "rate_limited" if "429" in str(e) else "cycle"
            if stage == "rate_limited":
                metrics.RATE_LIMITED.inc()
            metrics.SCRAPE_ERRORS.labels(stage).inc()
            conn = None  # force reconnect next cycle
            backoff = min(backoff + POLL_S, 1800)
        time.sleep(POLL_S + backoff)


if __name__ == "__main__":
    main()
