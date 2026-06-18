"""Parse the exporter /state dict into the controller's normalized inputs. Pure — no I/O."""
from dataclasses import dataclass


def num(x):
    """Coerce a /state numeric field to float, or None if absent/non-numeric. A contract
    regression (e.g. surplus_w arriving as a string) must degrade to 'blind' -> fail-safe,
    never crash the cycle on a TypeError deep in the threshold math."""
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class NormalizedState:
    surplus_raw: float | None
    age: float | None
    shelly_reachable: object
    shelly_on: object
    state_fresh: bool
    surplus: float


def normalize_state(st, stale_s):
    """Normalize a /state dict (or None) into NormalizedState. A missing dict, missing/non-numeric
    surplus, or a missing/old timestamp all read as 'blind' (state_fresh=False) so the decision
    path fails the WP safe-off. `surplus` is the fail-safe-coerced value (0.0 when blind)."""
    surplus_raw = num(st.get("surplus_w")) if st else None
    age = num(st.get("shm_age_s")) if st else None
    shelly_reachable = st.get("shelly_reachable") if st else None
    shelly_on = st.get("shelly_on") if st else None
    state_fresh = surplus_raw is not None and age is not None and age <= stale_s
    surplus = surplus_raw if surplus_raw is not None else 0.0
    return NormalizedState(surplus_raw, age, shelly_reachable, shelly_on, state_fresh, surplus)
