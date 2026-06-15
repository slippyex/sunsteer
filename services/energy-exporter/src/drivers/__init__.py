"""Driver registry + the protocols every hardware integration implements.

GridMeter is the load-bearing input of the whole system. Alternative hardware can be
supported two ways: implement these protocols in a new module here, or run a separate
exporter that serves the same /state JSON (see docs/state-interface.md, Phase 6).
For a new in-tree driver: add its key to SUPPORTED_METERS and a branch in get_meter().
The Protocols are structural typing specs — drivers do NOT inherit from them.
The write side of the relay (Switch.Set) intentionally lives in the surplus-controller
(relays/shelly.py) — this service is strictly READ-ONLY.
"""
import os
from collections.abc import Callable
from typing import Protocol

__all__ = ("GridMeter", "RelayReader", "SUPPORTED_METERS", "get_meter",
           "SUPPORTED_RELAYS", "get_relay")

SUPPORTED_METERS = ("sma_shm", "mock")
SUPPORTED_RELAYS = ("shelly",)


class GridMeter(Protocol):
    def run(self, on_reading: Callable[[dict], None]) -> None:
        """Blocking read loop; calls on_reading(reading) per measurement. The reading
        dict must carry the decoder shape: serial, import_w, export_w, surplus_w,
        import_kwh_total, export_kwh_total, l1_w, l2_w, l3_w."""


class RelayReader(Protocol):
    def get_state(self) -> dict | None:
        """Current relay state ({relay_on, power_w, ...}) or None if unreachable."""


def get_meter(name):
    """Meter factory for METER_DRIVER. Unknown names fail fast at startup."""
    if name == "sma_shm":
        from .sma_speedwire import SmaSpeedwireMeter
        return SmaSpeedwireMeter(os.environ.get("SHM_HOST"))
    if name == "mock":
        from .mock import MockMeter
        return MockMeter()
    raise SystemExit(f"energy-exporter: unknown METER_DRIVER '{name}' "
                     f"(supported: {', '.join(SUPPORTED_METERS)})")


def get_relay(name):
    """Read-only relay status reader for RELAY_DRIVER. Unknown names fail fast."""
    if name == "shelly":
        from .shelly import ShellyRelayReader
        return ShellyRelayReader(os.environ.get("SHELLY_URL"))
    raise SystemExit(f"energy-exporter: unknown RELAY_DRIVER '{name}' "
                     f"(supported: {', '.join(SUPPORTED_RELAYS)})")
