"""Controller config: DB load + safety clamping."""

DEFAULTS = {
    "mode": "paused",
    "manual_relay_on": False,
    "threshold_base_w": 2500.0,
    "threshold_min_w": 1500.0,
    "threshold_off_w": 200.0,
    "on_delay_cycles": 3,
    "off_delay_cycles": 3,
    "min_runtime_s": 1800,
    "min_offtime_s": 900,
    "adapt_enabled": True,
    "full_sun_ref_kwh": 70.0,      # a real clear-summer-day total for this 15 kWp E-W array
    "feed_in_tariff_eur_kwh": 0.08,
    "grid_price_eur_kwh": 0.30,
    "wp_nominal_power_w": 2000.0,  # estimated WP electrical draw (Shelly can't meter it)
    "pv_performance_ratio": 0.70,  # Open-Meteo GTI -> kWh; self-calibrated from actual production
}
_VALID_MODES = ("auto", "manual", "paused")


def clamp_config(cfg: dict) -> dict:
    """Force every value into a safe range so a bad DB row can't harm the heat pump."""
    c = {**DEFAULTS, **cfg}
    if c["mode"] not in _VALID_MODES:
        c["mode"] = "paused"
    c["manual_relay_on"] = bool(c["manual_relay_on"])
    c["adapt_enabled"] = bool(c["adapt_enabled"])
    c["threshold_base_w"] = max(0.0, float(c["threshold_base_w"]))
    c["threshold_min_w"] = max(0.0, min(float(c["threshold_min_w"]), c["threshold_base_w"]))
    c["threshold_off_w"] = max(0.0, float(c["threshold_off_w"]))
    if c["threshold_off_w"] >= c["threshold_min_w"]:
        c["threshold_off_w"] = max(0.0, c["threshold_min_w"] - 50.0)
    c["on_delay_cycles"] = max(1, int(c["on_delay_cycles"]))
    c["off_delay_cycles"] = max(1, int(c["off_delay_cycles"]))
    c["min_runtime_s"] = max(600, int(c["min_runtime_s"]))
    c["min_offtime_s"] = max(300, int(c["min_offtime_s"]))
    c["full_sun_ref_kwh"] = max(1.0, float(c["full_sun_ref_kwh"]))
    c["feed_in_tariff_eur_kwh"] = max(0.0, float(c["feed_in_tariff_eur_kwh"]))
    c["grid_price_eur_kwh"] = max(0.0, float(c["grid_price_eur_kwh"]))
    c["wp_nominal_power_w"] = max(0.0, min(float(c["wp_nominal_power_w"]), 20000.0))
    c["pv_performance_ratio"] = max(0.3, min(float(c["pv_performance_ratio"]), 1.0))
    return c


def load_config(conn) -> dict:
    """Read the single control_config row and clamp it."""
    cols = list(DEFAULTS.keys())
    with conn.cursor() as cur:
        cur.execute(f"SELECT {', '.join(cols)} FROM control_config WHERE id = 1")
        row = cur.fetchone()
    if not row:
        return clamp_config(dict(DEFAULTS))
    return clamp_config(dict(zip(cols, row)))
