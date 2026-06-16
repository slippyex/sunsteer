"""Heat-pump telemetry drivers. The generic exporter shell is driver-agnostic: every driver
returns a reading keyed by contract.HEATPUMP_FIELDS (or None to skip a cycle). New vendors add a
module here + a branch in get_driver() — like energy-exporter's get_meter()."""
from typing import Protocol

__all__ = ("HeatPumpDriver", "SUPPORTED_DRIVERS", "get_driver")

SUPPORTED_DRIVERS = ("vicare", "mock")


class HeatPumpDriver(Protocol):
    def poll(self) -> dict | None:
        """Return one telemetry reading (HEATPUMP_FIELDS-keyed dict) or None to skip this cycle
        (e.g. rate-budget exhausted). Owns its own vendor connection/retry/rate limits; transient
        vendor issues degrade to None rather than raising."""


def get_driver(name):
    if name == "vicare":
        from .vicare import VicareDriver
        return VicareDriver()
    if name == "mock":
        from .mock import MockDriver
        return MockDriver()
    raise SystemExit(f"heatpump-exporter: unknown HEATPUMP_DRIVER '{name}' "
                     f"(supported: {', '.join(SUPPORTED_DRIVERS)})")
