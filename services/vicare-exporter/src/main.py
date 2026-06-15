"""vicare-exporter: poll ViCare -> Prometheus + TimescaleDB. READ-ONLY, budget-guarded."""
import logging
import os
import time

from prometheus_client import start_http_server

from . import auth, metrics, tsdb_writer, vicare_client
from .extract import extract
from .ratebudget import RateBudget, clamp_interval

log = logging.getLogger(__name__)


def _pos_int(name, default, hi=86400):
    """Tolerant parse for port/cap envs: invalid, zero/negative or absurd values fall back
    to the default so a typo can't crash the exporter at start."""
    try:
        v = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return v if 1 <= v <= hi else default


METRICS_PORT = _pos_int("METRICS_PORT", 9125, hi=65535)
POLL_S = clamp_interval(os.environ.get("VICARE_POLL_SECONDS", "300"))
DAILY_CAP = _pos_int("VICARE_DAILY_CAP", 1400, hi=100000)
TOKEN_FILE = os.environ.get("VICARE_TOKEN_FILE", "/data/vicare_token.json")
BUDGET_FILE = os.environ.get("VICARE_BUDGET_FILE", "/data/vicare_budget.json")


REQUIRED_ENV = ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASS",
                "VICARE_USER", "VICARE_PASS", "VICARE_CLIENT_ID")


def secure_token_file(path):
    """Restrict the cached OAuth token to owner-only (0600). PyViCare writes it with the
    default umask (~0644); the token is a long-lived refresh grant to the user's Viessmann
    account, so anything sharing the PVC/UID shouldn't be able to read it. No-op if absent."""
    try:
        if os.path.exists(path):
            os.chmod(path, 0o600)
    except OSError:
        log.warning("could not chmod token file %s", path, exc_info=True)


def validate_env():
    """Fail fast with one clear message instead of a bare KeyError deep in _db()/connect."""
    missing = [n for n in REQUIRED_ENV if not os.environ.get(n)]
    if missing:
        raise SystemExit("vicare-exporter: missing required environment variables: "
                         + ", ".join(missing))
    placeholders = [n for n in REQUIRED_ENV if "CHANGE_ME" in os.environ.get(n, "")]
    if placeholders:
        raise SystemExit("vicare-exporter: unsubstituted CHANGE_ME placeholder in required "
                         "environment variables: " + ", ".join(placeholders))


def _is_rate_limit(e):
    try:
        from PyViCare.PyViCareUtils import PyViCareRateLimitError
        if isinstance(e, PyViCareRateLimitError):
            return True
    except Exception:
        pass
    # Last-resort substring match for when PyViCare wraps the 429 in a plain Exception (the
    # typed check above is the primary path); accepts a small false-positive risk to never
    # miss a real rate-limit and keep hammering the API.
    s = str(e).lower()
    return "429" in s or "rate limit" in s or "ratelimit" in s


def _is_invalid_credentials(e):
    try:
        from PyViCare.PyViCareUtils import PyViCareInvalidCredentialsError
        if isinstance(e, PyViCareInvalidCredentialsError):
            return True
    except Exception:
        pass
    s = str(e).lower()                    # last-resort substring match; typed check above is primary
    return "invalid credentials" in s


def _next_backoff(rate_limited, backoff, max_backoff=1800):
    """Next backoff seconds. A 429 jumps straight to the cap (the API is telling us to be
    quiet); any other error ramps linearly by POLL_S. Always capped at max_backoff. Shared
    by the connect and poll loops so the two can't drift apart. (No jitter: this is a single
    instance, so there's no thundering herd to spread out.)"""
    return max_backoff if rate_limited else min(backoff + POLL_S, max_backoff)


def connect_with_retry(token_file, max_backoff=1800, max_invalid_attempts=5):
    """Discover the ViCare device, retrying with backoff instead of crashing the process.
    A 429 during the (pre-budget) discovery call must NOT exit -> restart -> re-discover in a
    tight loop that hammers the API exactly while it's rate-limiting us.

    Invalid credentials are different: they're PERMANENT, so retrying forever only burns
    uncounted discovery calls against the rate-limited API in silence. After
    max_invalid_attempts CONSECUTIVE rejections we exit, turning a hidden quota leak into a
    visible CrashLoopBackOff. Any non-credential error resets the counter."""
    backoff = 0
    invalid_attempts = 0
    while True:
        try:
            return auth.connect_device(token_file)
        except Exception as e:
            rate_limited = _is_rate_limit(e)
            if rate_limited:
                metrics.RATE_LIMITED.inc()
            if _is_invalid_credentials(e):
                invalid_attempts += 1
                metrics.INVALID_CREDENTIALS.inc()
                log.error("ViCare credentials rejected as invalid (%s), attempt %d/%d. "
                          "Fix VICARE_USER/VICARE_PASS/VICARE_CLIENT_ID.",
                          e, invalid_attempts, max_invalid_attempts)
                if invalid_attempts >= max_invalid_attempts:
                    raise SystemExit(
                        "vicare-exporter: ViCare credentials rejected "
                        f"{invalid_attempts}x in a row — exiting so the failure is visible "
                        "(CrashLoopBackOff) instead of silently burning the API budget. "
                        "Fix VICARE_USER/VICARE_PASS/VICARE_CLIENT_ID.") from e
            else:
                invalid_attempts = 0   # only CONSECUTIVE credential rejections count
            metrics.SCRAPE_ERRORS.labels("connect").inc()
            backoff = _next_backoff(rate_limited, backoff, max_backoff)
            time.sleep(POLL_S + backoff)


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
        os.environ["DB_HOST"], _pos_int("DB_PORT", 5432, hi=65535),
        os.environ["DB_NAME"], os.environ["DB_USER"], os.environ["DB_PASS"])


def main():
    validate_env()
    os.umask(0o077)   # any token/budget file PyViCare or we write lands owner-only (0600)
    start_http_server(METRICS_PORT)
    device = connect_with_retry(TOKEN_FILE)
    secure_token_file(TOKEN_FILE)   # tighten the initial token (umask only affects new files)
    conn = None
    budget = RateBudget(cap=DAILY_CAP, window_s=86400, persist_path=BUDGET_FILE)
    backoff = 0
    while True:
        try:
            conn = tsdb_writer.live_conn(conn, _db)  # reconnect across DB restarts
            run_cycle(device, conn, budget, now=time.time())
            backoff = 0
        except Exception as e:
            rate_limited = _is_rate_limit(e)
            if rate_limited:
                metrics.RATE_LIMITED.inc()
            metrics.SCRAPE_ERRORS.labels("rate_limited" if rate_limited else "cycle").inc()
            conn = None  # force reconnect next cycle
            backoff = _next_backoff(rate_limited, backoff)
        time.sleep(POLL_S + backoff)


if __name__ == "__main__":
    main()
