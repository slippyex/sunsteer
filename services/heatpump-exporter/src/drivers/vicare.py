"""ViCare (Viessmann) heat-pump telemetry driver: OAuth/discovery, daily rate budget, token
hardening, and the Viessmann feature->contract mapping. Emits the generic HEATPUMP_FIELDS reading;
vendor-API ops tracked under vicare_* (vicare_metrics)."""
import logging
import os
import time

from .. import metrics, vicare_client
from ..auth import connect_device
from ..extract import extract
from ..ratebudget import RateBudget, clamp_interval
from . import vicare_metrics as vm

log = logging.getLogger(__name__)

def _pos_int(name, default, hi=3600):
    """Parse a positive-int env with a tolerant fallback. A missing, non-numeric,
    zero/negative or absurd value falls back to the default — a bad value must never crash
    the exporter at import."""
    try:
        v = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return v if 1 <= v <= hi else default


POLL_S = clamp_interval(os.environ.get("HEATPUMP_POLL_SECONDS",
                                       os.environ.get("VICARE_POLL_SECONDS", "300")))
DAILY_CAP = _pos_int("VICARE_DAILY_CAP", 1400, hi=100000)
_COOLDOWN_S = 1800
TOKEN_FILE = os.environ.get("VICARE_TOKEN_FILE", "/data/vicare_token.json")
BUDGET_FILE = os.environ.get("VICARE_BUDGET_FILE", "/data/vicare_budget.json")
REQUIRED_ENV = ("VICARE_USER", "VICARE_PASS", "VICARE_CLIENT_ID")


def secure_token_file(path):
    """Restrict the cached OAuth token to owner-only (0600). PyViCare writes it with the
    default umask (~0644); the token is a long-lived refresh grant to the user's Viessmann
    account, so anything sharing the PVC/UID shouldn't be able to read it. No-op if absent."""
    try:
        if os.path.exists(path):
            os.chmod(path, 0o600)
    except OSError:
        log.warning("could not chmod token file %s", path, exc_info=True)


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
            return connect_device(token_file)
        except Exception as e:
            rate_limited = _is_rate_limit(e)
            if rate_limited:
                vm.RATE_LIMITED.inc()
            if _is_invalid_credentials(e):
                invalid_attempts += 1
                vm.INVALID_CREDENTIALS.inc()
                log.error("ViCare credentials rejected as invalid (%s), attempt %d/%d. "
                          "Fix VICARE_USER/VICARE_PASS/VICARE_CLIENT_ID.",
                          e, invalid_attempts, max_invalid_attempts)
                if invalid_attempts >= max_invalid_attempts:
                    raise SystemExit(
                        "heatpump-exporter (vicare driver): ViCare credentials rejected "
                        f"{invalid_attempts}x in a row — exiting so the failure is visible "
                        "(CrashLoopBackOff) instead of silently burning the API budget. "
                        "Fix VICARE_USER/VICARE_PASS/VICARE_CLIENT_ID.") from e
            else:
                invalid_attempts = 0   # only CONSECUTIVE credential rejections count
            metrics.SCRAPE_ERRORS.labels("connect").inc()
            backoff = _next_backoff(rate_limited, backoff, max_backoff)
            time.sleep(POLL_S + backoff)


class VicareDriver:
    def __init__(self):
        self._device = None
        self._budget = RateBudget(cap=DAILY_CAP, window_s=86400, persist_path=BUDGET_FILE)
        self._cooldown_until = 0.0

    def _ensure_connected(self):
        if self._device is None:
            os.umask(0o077)
            self._device = connect_with_retry(TOKEN_FILE)
            secure_token_file(TOKEN_FILE)

    def poll(self):
        now = time.time()
        if now < self._cooldown_until:
            return None                      # stay quiet after a 429 — don't hammer the API
        self._ensure_connected()             # may SystemExit on permanent bad creds (intended crash)
        if not self._budget.allow(now):
            vm.BUDGET_EXHAUSTED.set(1)
            vm.BUDGET_USED.set(self._budget.count(now))
            return None
        vm.BUDGET_EXHAUSTED.set(0)
        try:
            features = vicare_client.poll(self._device)
        except Exception as e:
            if _is_rate_limit(e):
                vm.RATE_LIMITED.inc()
                metrics.SCRAPE_ERRORS.labels("rate_limited").inc()
                self._cooldown_until = now + _COOLDOWN_S
            else:
                metrics.SCRAPE_ERRORS.labels("cycle").inc()
            return None                      # degrade to None per the driver contract
        self._budget.record(now)
        vm.API_CALLS.inc()
        vm.BUDGET_USED.set(self._budget.count(now))
        return extract(features)
