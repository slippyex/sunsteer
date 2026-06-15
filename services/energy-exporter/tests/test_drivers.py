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


def test_get_relay_unknown_fails_fast():
    import pytest
    with pytest.raises(SystemExit) as e:
        D.get_relay("bogus")
    assert "bogus" in str(e.value) and "shelly" in str(e.value)


def test_get_relay_shelly_uses_shelly_url(monkeypatch):
    monkeypatch.setenv("SHELLY_URL", "http://192.0.2.90")
    r = D.get_relay("shelly")
    assert r.base_url == "http://192.0.2.90"


def test_get_meter_resolves_shm_hostname_to_ip(monkeypatch):
    # The Speedwire source filter compares addr[0] (an IP) to shm_host. If SHM_HOST is a
    # hostname it must be resolved to its IP at startup, else the filter silently drops EVERY
    # telegram and the meter looks permanently dead.
    monkeypatch.setenv("SHM_HOST", "sma.local")
    monkeypatch.setattr(D.socket, "gethostbyname",
                        lambda h: "192.168.5.7" if h == "sma.local" else h)
    m = D.get_meter("sma_shm")
    assert m.shm_host == "192.168.5.7"


def test_get_meter_unresolvable_shm_host_fails_fast(monkeypatch):
    import socket as _s
    monkeypatch.setenv("SHM_HOST", "nope.invalid")

    def boom(_h):
        raise _s.gaierror("name resolution failed")

    monkeypatch.setattr(D.socket, "gethostbyname", boom)
    with pytest.raises(SystemExit) as e:
        D.get_meter("sma_shm")
    assert "SHM_HOST" in str(e.value)
