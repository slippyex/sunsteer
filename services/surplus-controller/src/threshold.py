"""Forecast-adaptive ON-threshold."""


def adaptive_threshold(cfg: dict, forecast_remaining_kwh) -> float:
    base = cfg["threshold_base_w"]
    ref = cfg["full_sun_ref_kwh"]
    # ref is clamped >= 1.0 by clamp_config on the real path; guard anyway so a raw/unclamped
    # cfg can't ZeroDivisionError inside the control cycle (which would silently skip actuation).
    if not cfg.get("adapt_enabled", True) or forecast_remaining_kwh is None or ref <= 0:
        return base
    factor = forecast_remaining_kwh / ref
    factor = max(0.0, min(1.0, factor))
    return base - (base - cfg["threshold_min_w"]) * factor


def available_surplus(surplus_w, relay_on, wp_nominal_power_w) -> float:
    """The surplus that WOULD exist without the WP running.

    The SHM measures total grid surplus, so while the WP runs its own draw is already
    subtracted. Add the estimated WP load back when the relay is on, so the ON and OFF
    decisions compare the SAME quantity (surplus-minus-WP). This removes the measurement
    feedback loop that would otherwise let the WP's own consumption drive a self-oscillation
    (turn on -> surplus drops -> turn off -> surplus jumps -> turn on -> ...).

    The compensation uses the (estimated) wp_nominal_power_w since the Shelly is an SG-Ready
    signal contact and can't meter the WP. Setting wp_nominal_power_w=0 disables it (raw
    surplus, old behaviour)."""
    return surplus_w + (wp_nominal_power_w if relay_on else 0.0)


def available_and_basis(surplus, production, base_load, relay_on, sun_up, wp_nominal_power_w):
    """The PV surplus genuinely free for the WP, plus which basis was used.

    Preferred: `production - base_load` (real headroom; needs fresh inverter production AND a
    warmed-up base-load). Fallback: today's load-compensation `surplus + wp_nominal` while the
    relay is on and the sun is up (0.4.1 behaviour) — used when production or base is missing."""
    if production is not None and base_load is not None:
        return production - base_load, "production"
    return available_surplus(surplus, relay_on, wp_nominal_power_w if sun_up else 0.0), "nominal"
