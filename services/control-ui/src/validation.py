"""Validate + clamp the settings form before writing control_config.
Mirrors the C1 controller bounds (defense-in-depth: the controller clamps again)."""


def _num(form, key, errors, cast, lo=None, hi=None, label=None):
    raw = form.get(key, "")
    try:
        v = cast(raw)
    except (TypeError, ValueError):
        errors[key] = f"{label or key}: keine gültige Zahl"
        return None
    if lo is not None and v < lo:
        errors[key] = f"{label or key}: min {lo}"
        return None
    if hi is not None and v > hi:
        errors[key] = f"{label or key}: max {hi}"
        return None
    return v


def validate_settings(form: dict):
    """form: dict of string values (HTML form). Returns (clean, errors).
    clean uses control_config column names (run-times in SECONDS). If errors
    is non-empty, do NOT write."""
    e: dict = {}
    base = _num(form, "threshold_base_w", e, float, lo=0, hi=15000)
    mn = _num(form, "threshold_min_w", e, float, lo=0, hi=15000)
    off = _num(form, "threshold_off_w", e, float, lo=0, hi=15000)
    on_delay = _num(form, "on_delay_cycles", e, int, lo=1, hi=1000)
    off_delay = _num(form, "off_delay_cycles", e, int, lo=1, hi=1000)
    run_min = _num(form, "min_runtime_min", e, float, lo=10, hi=720)
    off_min = _num(form, "min_offtime_min", e, float, lo=5, hi=720)
    ref = _num(form, "full_sun_ref_kwh", e, float, lo=1, hi=200)
    feed = _num(form, "feed_in_tariff_eur_kwh", e, float, lo=0, hi=2)
    grid = _num(form, "grid_price_eur_kwh", e, float, lo=0, hi=2)
    wp_nom = _num(form, "wp_nominal_power_w", e, float, lo=0, hi=20000)

    if base is not None and mn is not None and mn > base:
        e["threshold_min_w"] = "Min-Schwelle darf nicht über der Basis liegen"
    if off is not None and mn is not None and off >= mn:
        e["threshold_off_w"] = "Off-Schwelle muss unter der Min-Schwelle liegen"

    if e:
        return {}, e
    return {
        "threshold_base_w": base, "threshold_min_w": mn, "threshold_off_w": off,
        "on_delay_cycles": on_delay, "off_delay_cycles": off_delay,
        "min_runtime_s": int(run_min * 60), "min_offtime_s": int(off_min * 60),
        "adapt_enabled": form.get("adapt_enabled") is not None,
        "full_sun_ref_kwh": ref,
        "feed_in_tariff_eur_kwh": feed, "grid_price_eur_kwh": grid,
        "wp_nominal_power_w": wp_nom,
    }, {}
