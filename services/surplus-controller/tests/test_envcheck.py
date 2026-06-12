import importlib

import pytest
import src.main as M

REQUIRED = {"SHELLY_URL": "http://192.0.2.90", "PV_LAT": "50.0", "PV_LON": "8.0",
            "PV_PLANES": "[[30,0,5.0]]",
            "DB_HOST": "db", "DB_NAME": "energy", "DB_USER": "u", "DB_PASS": "p"}


def test_validate_env_passes_when_all_set(monkeypatch):
    for k, v in REQUIRED.items():
        monkeypatch.setenv(k, v)
    M.validate_env()   # must not raise


def test_validate_env_lists_every_missing_var(monkeypatch):
    for k in REQUIRED:
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(SystemExit) as e:
        M.validate_env()
    for k in REQUIRED:
        assert k in str(e.value)


def test_pv_planes_invalid_json_fails_fast(monkeypatch):
    for k, v in REQUIRED.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("PV_PLANES", "not json")
    with pytest.raises(SystemExit) as e:
        importlib.reload(M)
    assert "PV_PLANES" in str(e.value)
    monkeypatch.setenv("PV_PLANES", REQUIRED["PV_PLANES"])
    importlib.reload(M)   # restore a sane module state for other tests
