from src.contract import HEATPUMP_FIELDS
from src.drivers.mock import MockDriver


def test_mock_poll_returns_full_contract_reading():
    r = MockDriver().poll()
    assert set(r.keys()) == set(HEATPUMP_FIELDS)
    assert isinstance(r["dhw_temp_c"], float)


def test_mock_energy_counters_are_monotonic():
    d = MockDriver()
    r1, r2 = d.poll(), d.poll()
    assert r2["energy_total_kwh"] >= r1["energy_total_kwh"]
