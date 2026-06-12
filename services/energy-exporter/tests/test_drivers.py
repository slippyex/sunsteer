import pytest

import src.drivers as D
from src.drivers.mock import MockMeter

READING_FIELDS = ("serial", "import_w", "export_w", "surplus_w",
                  "import_kwh_total", "export_kwh_total", "l1_w", "l2_w", "l3_w")


def test_get_meter_unknown_fails_fast():
    with pytest.raises(SystemExit) as e:
        D.get_meter("nope")
    assert "METER_DRIVER" in str(e.value) and "nope" in str(e.value)


def test_get_meter_mock_returns_runnable_meter():
    m = D.get_meter("mock")
    assert callable(m.run)


def test_get_meter_sma_uses_shm_host(monkeypatch):
    monkeypatch.setenv("SHM_HOST", "192.0.2.44")
    m = D.get_meter("sma_shm")
    assert m.shm_host == "192.0.2.44"


def test_mock_reading_has_decoder_shape_and_is_consistent():
    m = MockMeter()
    r = m.reading()
    for f in READING_FIELDS:
        assert f in r, f"missing field {f}"
    assert r["import_w"] >= 0 and r["export_w"] >= 0
    assert r["surplus_w"] == pytest.approx(r["export_w"] - r["import_w"], abs=0.01)


def test_mock_energy_counters_are_monotonic():
    m = MockMeter()
    r1, r2 = m.reading(), m.reading()
    assert r2["import_kwh_total"] >= r1["import_kwh_total"]
    assert r2["export_kwh_total"] >= r1["export_kwh_total"]
