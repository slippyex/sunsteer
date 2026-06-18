"""Non-safety reporting (metrics + status writes) for the control loop.

Extracted from main.py verbatim. This block runs AFTER all decision/actuation and is pure
side-effects (telemetry). It keeps its OWN try/except so a metrics/status failure is
categorised as a `reporting` error — never sharing a failure path with the control logic.
"""
from dataclasses import dataclass

from . import metrics, status_server


@dataclass(frozen=True)
class ReportInputs:
    mode: str
    relay_on: bool
    eff: float
    fc: float | None
    sun_elev: float | None
    base_load: float | None
    basis: str
    avail: float
    surplus: float
    state_fresh: bool
    age: float | None
    reason: str
    sun_up: bool
    action: str
    on_streak: int
    off_streak: int
    on_delay_cycles: int
    off_delay_cycles: int
    min_runtime_s: int
    min_offtime_s: int
    secs_since_on: int
    secs_since_off: int
    wp_nominal_power_w: float
    loop_seconds: int


def write(inp, todays_sun_window, now_local):
    """Non-safety reporting in its OWN try: a metrics/status failure is telemetry, not a
    control fault — it must be categorised separately and can never share a failure
    path with the decision/actuation logic above (which has already re-armed the relay).

    `todays_sun_window` (owned by main.py, with its env config + per-day cache) is called
    INSIDE this try so a sun-window failure still lands in the `reporting` label."""
    try:
        wp_est = inp.wp_nominal_power_w if inp.relay_on else 0.0
        metrics.update(inp.mode, inp.relay_on, inp.eff, inp.fc, wp_est,
                       state_fresh=inp.state_fresh, state_age_s=inp.age, available_w=inp.avail)
        if inp.sun_elev is not None:
            metrics.SUN_ELEVATION.set(inp.sun_elev)
        if inp.base_load is not None:
            metrics.BASE_LOAD.set(inp.base_load)
        metrics.AVAILABLE_BASIS.set(1 if inp.basis == "production" else 0)
        rise_ts, set_ts = todays_sun_window(now_local)
        metrics.SUN_RISE.set(rise_ts)
        metrics.SUN_SET.set(set_ts)
        status_reason = inp.reason
        if not inp.sun_up and not inp.relay_on and inp.action not in ("switched_on", "switched_off"):
            status_reason = "sun_below_horizon"
        status_server.set_status(
            mode=inp.mode, relay_on=inp.relay_on, surplus_w=inp.surplus, available_w=inp.avail,
            effective_threshold_w=inp.eff, on_streak=inp.on_streak, off_streak=inp.off_streak,
            on_delay_cycles=inp.on_delay_cycles, off_delay_cycles=inp.off_delay_cycles,
            secs_since_on=inp.secs_since_on, secs_since_off=inp.secs_since_off,
            min_runtime_s=inp.min_runtime_s, min_offtime_s=inp.min_offtime_s,
            loop_seconds=inp.loop_seconds, reason=status_reason, state_fresh=inp.state_fresh,
            state_age_s=inp.age)
    except Exception:
        metrics.LOOP_ERRORS.labels("reporting").inc()
