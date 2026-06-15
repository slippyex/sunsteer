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
# When a bad row sets off-threshold >= min-threshold, drop off this far below min to keep the
# documented off < min invariant (prevents on/off bands from touching and chattering).
_OFF_THRESHOLD_GAP_W = 50.0
# Compressor-protection floors (seconds) and physical caps for the clamps below — a bad DB row
# must never push these below what protects the heat pump or above what's physically plausible.
_MIN_RUNTIME_FLOOR_S = 600
_MIN_OFFTIME_FLOOR_S = 300
_WP_POWER_CAP_W = 20000.0
_PR_MIN, _PR_MAX = 0.3, 1.0


def clamp_config(cfg: dict) -> dict:
    """Force every value into a safe range so a bad DB row can't harm the heat pump."""
    c = {**DEFAULTS, **cfg}
    # A NULL (None) column in control_config must degrade to its DEFAULT, not blow up float()/
    # int() and freeze hot-reload of the WHOLE config. Coerce per-field BEFORE casting.
    for k, default in DEFAULTS.items():
        if c.get(k) is None:
            c[k] = default
    if c["mode"] not in _VALID_MODES:
        c["mode"] = "paused"
    c["manual_relay_on"] = bool(c["manual_relay_on"])
    c["adapt_enabled"] = bool(c["adapt_enabled"])
    c["threshold_base_w"] = max(0.0, float(c["threshold_base_w"]))
    c["threshold_min_w"] = max(0.0, min(float(c["threshold_min_w"]), c["threshold_base_w"]))
    c["threshold_off_w"] = max(0.0, float(c["threshold_off_w"]))
    # Guarantee the claimed invariant off < min whenever min > 0. The degenerate min == 0 case
    # can't satisfy off < 0 (off is clamped >= 0), so it stays a no-op (off == min == 0).
    if c["threshold_min_w"] > 0 and c["threshold_off_w"] >= c["threshold_min_w"]:
        c["threshold_off_w"] = max(0.0, c["threshold_min_w"] - _OFF_THRESHOLD_GAP_W)
    c["on_delay_cycles"] = max(1, int(c["on_delay_cycles"]))
    c["off_delay_cycles"] = max(1, int(c["off_delay_cycles"]))
    c["min_runtime_s"] = max(_MIN_RUNTIME_FLOOR_S, int(c["min_runtime_s"]))
    c["min_offtime_s"] = max(_MIN_OFFTIME_FLOOR_S, int(c["min_offtime_s"]))
    c["full_sun_ref_kwh"] = max(1.0, float(c["full_sun_ref_kwh"]))
    c["feed_in_tariff_eur_kwh"] = max(0.0, float(c["feed_in_tariff_eur_kwh"]))
    c["grid_price_eur_kwh"] = max(0.0, float(c["grid_price_eur_kwh"]))
    c["wp_nominal_power_w"] = max(0.0, min(float(c["wp_nominal_power_w"]), _WP_POWER_CAP_W))
    c["pv_performance_ratio"] = max(_PR_MIN, min(float(c["pv_performance_ratio"]), _PR_MAX))
    return c


def load_config(conn) -> dict:
    """Read the single control_config row and clamp it."""
    cols = list(DEFAULTS.keys())
    with conn.cursor() as cur:
        cur.execute(f"SELECT {', '.join(cols)} FROM control_config WHERE id = 1")
        row = cur.fetchone()
    if not row:
        return clamp_config(dict(DEFAULTS))
    return clamp_config(dict(zip(cols, row, strict=False)))
