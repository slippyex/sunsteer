"""heatpump_* Prometheus metrics (generic telemetry contract) + vicare_* vendor-op metrics."""
import datetime

from prometheus_client import Counter, Gauge

from .contract import HEATPUMP_FIELDS, HEATPUMP_STRING_FIELDS

# Numeric datapoint gauges (string/text fields like dhw_mode/energy_read_at are not gauged).
GAUGES = {f: Gauge(f"heatpump_{f}", f"Heat pump {f}")
          for f in HEATPUMP_FIELDS if f not in HEATPUMP_STRING_FIELDS}

# Vendor-operational metrics — stay vicare_* until the vendor driver is split out.
API_CALLS = Counter("vicare_api_calls_total", "ViCare API calls made")
RATE_LIMITED = Counter("vicare_rate_limited_total", "HTTP 429 / limit responses")
INVALID_CREDENTIALS = Counter("vicare_invalid_credentials_total",
                              "Connect attempts rejected as invalid credentials (permanent)")
BUDGET_EXHAUSTED = Gauge("vicare_budget_exhausted", "1 = daily call budget reached, poll skipped")
BUDGET_USED = Gauge("vicare_budget_used", "API calls used in the trailing 24h window")

# Generic liveness / health metrics.
SCRAPE_ERRORS = Counter("heatpump_scrape_errors_total", "Poll/parse errors", ["stage"])
LAST_SUCCESS = Gauge("heatpump_last_success_timestamp_seconds", "Unix ts of last successful poll")
# ViCare energy counters lag a few days; expose the API's own readAt so freshness is visible.
ENERGY_READ_AT = Gauge("heatpump_energy_read_at_timestamp_seconds",
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
        if v is True or v is False:
            g.set(1 if v else 0)
            continue
        try:
            g.set(float(v))           # skip (don't crash the cycle) on a non-numeric quirk value
        except (ValueError, TypeError):
            continue
    ts = _parse_ts(data.get("energy_read_at"))
    if ts is not None:
        ENERGY_READ_AT.set(ts)
