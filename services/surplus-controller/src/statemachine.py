"""Safety-critical decision core. Pure: no I/O, no time, no globals."""


def decide(mode: str, relay_on: bool, manual_relay_on: bool,
           on_streak: int, off_streak: int, on_delay_cycles: int, off_delay_cycles: int,
           secs_since_on: float, secs_since_off: float, min_runtime_s: int, min_offtime_s: int,
           state_fresh: bool = True) -> tuple[bool, str, str]:
    """Return (relay_target: bool, action: str, reason: str).

    action ∈ {switched_on, switched_off, no_change}.

    `state_fresh` is False when the SHM measurement is missing/stale. A blind AUTO
    controller must never keep the WP on grid power (its load-compensated surplus would
    look fine forever and keep re-arming the auto-off watchdog) -> fail safe-OFF. Manual
    is an explicit user override and paused already forces off, so freshness only gates AUTO."""
    if mode == "paused":
        return (False, "switched_off" if relay_on else "no_change", "paused")

    if mode == "manual":
        target = bool(manual_relay_on)
        if target == relay_on:
            return (target, "no_change", "manual_hold")
        return (target, "switched_on" if target else "switched_off", "manual")

    # AUTO
    if not state_fresh:
        return (False, "switched_off" if relay_on else "no_change", "state_stale_failsafe")

    if not relay_on:
        if on_streak < on_delay_cycles:
            return (False, "no_change", "waiting_surplus")
        if secs_since_off < min_offtime_s:
            return (False, "no_change", "waiting_min_offtime")
        return (True, "switched_on", "surplus_threshold_met")
    else:
        if off_streak < off_delay_cycles:
            return (True, "no_change", "surplus_ok")
        if secs_since_on < min_runtime_s:
            return (True, "no_change", "min_runtime")
        return (False, "switched_off", "surplus_below_off_threshold")
