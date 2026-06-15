"""Relay drivers for the controller's actuator (write) side.

set(on, auto_off_s) is the SAFETY-CRITICAL path: when on=True the driver MUST arm a
hardware auto-off watchdog of auto_off_s seconds, so a dead/wedged controller releases
the relay on its own. A relay without a hardware auto-off is not supported (there is no
software-watchdog fallback). Add a driver: implement the RelayActuator protocol in a
module here, add its key to SUPPORTED_RELAYS and a branch in get_relay().
"""
from typing import Protocol

__all__ = ("RelayActuator", "SUPPORTED_RELAYS", "get_relay")

SUPPORTED_RELAYS = ("shelly",)


class RelayActuator(Protocol):
    def get_state(self):   # -> bool | None
        """Actual relay state (True/False), or None if unreachable."""

    def set(self, on, auto_off_s):   # -> bool
        """Command the relay. on=True MUST arm the hardware auto-off watchdog for
        auto_off_s. Returns True only on confirmed success."""


def get_relay(name, base_url):
    if name == "shelly":
        from .shelly import ShellyRelayActuator
        return ShellyRelayActuator(base_url)
    raise SystemExit(f"surplus-controller: unknown RELAY_DRIVER '{name}' "
                     f"(supported: {', '.join(SUPPORTED_RELAYS)})")
