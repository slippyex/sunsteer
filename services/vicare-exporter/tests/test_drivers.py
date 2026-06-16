import pytest
from src import drivers


def test_get_driver_unknown_raises_systemexit():
    with pytest.raises(SystemExit) as e:
        drivers.get_driver("nope")
    msg = str(e.value)
    assert "HEATPUMP_DRIVER" in msg and "nope" in msg


def test_supported_drivers_lists_vicare_and_mock():
    assert "vicare" in drivers.SUPPORTED_DRIVERS
    assert "mock" in drivers.SUPPORTED_DRIVERS
