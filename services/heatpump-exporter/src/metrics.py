"""heatpump_* Prometheus metrics — the generic telemetry contract. Vendor-operational metrics
(e.g. vicare_*) live with their driver (drivers/vicare_metrics.py), not here."""
import datetime

from prometheus_client import Counter, Gauge

from .contract import HEATPUMP_FIELDS, HEATPUMP_STRING_FIELDS

# Numeric datapoint gauges (string/text fields like dhw_mode/energy_read_at are not gauged).
GAUGES = {f: Gauge(f"heatpump_{f}", f"Heat pump {f}")
          for f in HEATPUMP_FIELDS if f not in HEATPUMP_STRING_FIELDS}

# Generic liveness / health metrics.
SCRAPE_ERRORS = Counter("heatpump_scrape_errors_total", "Poll/parse errors", ["stage"])
LAST_SUCCESS = Gauge("heatpump_last_success_timestamp_seconds", "Unix ts of last successful poll")
# Some drivers' energy counters lag a few days; expose the source's own readAt so freshness
# is visible (drivers without a lag, e.g. mock, leave it unset).
ENERGY_READ_AT = Gauge("heatpump_energy_read_at_timestamp_seconds",
                       "Unix ts the energy counters were last computed by the source")


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
