"""ViCare-driver-internal operational metrics (Viessmann API budget/limits) — NOT part of the
generic heatpump_* telemetry contract."""
from prometheus_client import Counter, Gauge

API_CALLS = Counter("vicare_api_calls_total", "ViCare API calls made")
RATE_LIMITED = Counter("vicare_rate_limited_total", "HTTP 429 / limit responses")
INVALID_CREDENTIALS = Counter("vicare_invalid_credentials_total",
                              "Connect attempts rejected as invalid credentials (permanent)")
BUDGET_EXHAUSTED = Gauge("vicare_budget_exhausted", "1 = daily call budget reached, poll skipped")
BUDGET_USED = Gauge("vicare_budget_used", "API calls used in the trailing 24h window")
