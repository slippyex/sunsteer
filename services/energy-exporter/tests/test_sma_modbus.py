from src.drivers.sma_modbus import build_strings


def test_build_strings_skips_nan_power():
    # MPPT 1 present, MPPT 2 power NaN (None) -> only idx 1 returned
    readings = [
        {"idx": 1, "power": 1500.0, "voltage": 380.0, "current": 3.9},
        {"idx": 2, "power": None,   "voltage": None,  "current": None},
    ]
    assert build_strings(readings) == [
        {"idx": 1, "power": 1500.0, "voltage": 380.0, "current": 3.9}]


def test_build_strings_keeps_zero_power():
    readings = [{"idx": 1, "power": 0.0, "voltage": 350.0, "current": 0.0}]
    assert build_strings(readings) == [
        {"idx": 1, "power": 0.0, "voltage": 350.0, "current": 0.0}]
