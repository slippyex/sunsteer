"""vicare_* Prometheus metrics."""
import datetime

from prometheus_client import Gauge, Counter

from .extract import FIELDS, STRING_FIELDS

# Numeric datapoint gauges (string/text fields like dhw_mode/energy_read_at are not gauged).
GAUGES = {f: Gauge(f"vicare_{f}", f"ViCare {f}")
          for f in FIELDS if f not in STRING_FIELDS}

API_CALLS = Counter("vicare_api_calls_total", "ViCare API calls made")
SCRAPE_ERRORS = Counter("vicare_scrape_errors_total", "Poll/parse errors", ["stage"])
RATE_LIMITED = Counter("vicare_rate_limited_total", "HTTP 429 / limit responses")
BUDGET_EXHAUSTED = Gauge("vicare_budget_exhausted", "1 = daily call budget reached, poll skipped")
BUDGET_USED = Gauge("vicare_budget_used", "API calls used in the trailing 24h window")
LAST_SUCCESS = Gauge("vicare_last_success_timestamp_seconds", "Unix ts of last successful poll")
# ViCare energy counters lag a few days; expose the API's own readAt so freshness is visible.
ENERGY_READ_AT = Gauge("vicare_energy_read_at_timestamp_seconds",
                       "Unix ts the energy counters were last computed by ViCare")


def _parse_ts(s):
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError, TypeError):
        return None


def set_from(data):
    for key, g in GAUGES.items():
        v = data.get(key)
        if v is None:
            continue
        g.set(1 if v is True else (0 if v is False else float(v)))
    ts = _parse_ts(data.get("energy_read_at"))
    if ts is not None:
        ENERGY_READ_AT.set(ts)
