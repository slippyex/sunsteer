"""Controller Prometheus metrics."""
from prometheus_client import Counter, Gauge

MODE = Gauge("surplus_control_mode", "0=paused 1=manual 2=auto")
RELAY_ON = Gauge("surplus_control_relay_on", "Commanded relay state (1=surplus mode on)")
EFF_THRESHOLD = Gauge("surplus_control_effective_threshold_watts", "Current effective ON threshold")
FORECAST_REMAINING = Gauge("surplus_control_forecast_remaining_kwh", "Forecast remaining today (kWh)")
PV_PR = Gauge("surplus_control_pv_performance_ratio",
              "Self-calibrated PV performance ratio (Open-Meteo GTI -> measured production)")
WP_EST_POWER = Gauge("surplus_control_wp_estimated_power_watts",
                     "Estimated WP electrical power: nominal when relay on, else 0 (Shelly can't meter it)")
STATE_FRESH = Gauge("surplus_control_state_fresh",
                    "1 = SHM measurement fresh, 0 = stale/missing -> fail-safe OFF active")
STATE_AGE = Gauge("surplus_control_state_age_seconds", "Age of the SHM reading the last cycle used")
AVAILABLE = Gauge("surplus_control_available_watts",
                  "Load-compensated surplus the decision used (surplus + WP estimate when on). "
                  "This — not raw grid import — is what the controller acts on.")
SWITCHES = Counter("surplus_control_switch_total", "Switch actions", ["action"])
SHELLY_ERRORS = Counter("surplus_control_shelly_write_errors_total", "Failed Shelly writes")
LOOP_ERRORS = Counter("surplus_control_loop_errors_total", "Loop exceptions caught (degraded, not fatal)", ["stage"])

_MODE_NUM = {"paused": 0, "manual": 1, "auto": 2}


def update(mode, relay_on, eff_threshold, forecast_remaining, wp_estimated_power=0.0,
           state_fresh=True, state_age_s=None, available_w=None):
    MODE.set(_MODE_NUM.get(mode, 0))
    RELAY_ON.set(1 if relay_on else 0)
    EFF_THRESHOLD.set(eff_threshold)
    WP_EST_POWER.set(wp_estimated_power)
    STATE_FRESH.set(1 if state_fresh else 0)
    if state_age_s is not None:
        STATE_AGE.set(state_age_s)
    if available_w is not None:
        AVAILABLE.set(available_w)
    if forecast_remaining is not None:
        FORECAST_REMAINING.set(forecast_remaining)
