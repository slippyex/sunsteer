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
import socket
from collections.abc import Callable
from typing import Protocol, TypedDict

__all__ = ("GridMeter", "MeterReading", "RelayReader", "SUPPORTED_METERS", "get_meter",
           "SUPPORTED_RELAYS", "get_relay")

SUPPORTED_METERS = ("sma_shm", "mock")
SUPPORTED_RELAYS = ("shelly",)


class MeterReading(TypedDict):
    """The reading dict every GridMeter yields — the decoder's shape, consumed downstream by
    metrics, state_server and tsdb_writer. A single checkable contract instead of a prose list."""
    serial: int
    import_w: float
    export_w: float
    surplus_w: float
    import_kwh_total: float
    export_kwh_total: float
    l1_w: float
    l2_w: float
    l3_w: float


class GridMeter(Protocol):
    def run(self, on_reading: Callable[[MeterReading], None]) -> None:
        """Blocking read loop; calls on_reading(reading) per measurement. The reading
        dict carries the MeterReading shape."""


class RelayReader(Protocol):
    def get_state(self) -> dict | None:
        """Current relay state ({relay_on, power_w, ...}) or None if unreachable."""


def get_meter(name):
    """Meter factory for METER_DRIVER. Unknown names fail fast at startup."""
    if name == "sma_shm":
        from .sma_speedwire import SmaSpeedwireMeter
        # Resolve SHM_HOST to an IP: the Speedwire source filter compares against addr[0] (an
        # IP), so a hostname would silently drop every telegram and look like a dead meter.
        # gethostbyname is a no-op for an IP literal; fail fast (not silently) if it can't resolve.
        shm_host = os.environ.get("SHM_HOST")
        if shm_host:
            try:
                shm_host = socket.gethostbyname(shm_host)
            except OSError as e:
                raise SystemExit(f"energy-exporter: SHM_HOST '{shm_host}' could not be "
                                 f"resolved to an IP: {e}") from e
        return SmaSpeedwireMeter(shm_host, iface_ip=os.environ.get("SMA_IFACE_IP") or None)
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
