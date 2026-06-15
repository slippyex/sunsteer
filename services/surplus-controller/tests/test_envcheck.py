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


def test_validate_env_rejects_zero_autooff(monkeypatch):
    for k, v in REQUIRED.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(M, "AUTOOFF_S", 0)
    monkeypatch.setattr(M, "LOOP_S", 15)
    with pytest.raises(SystemExit) as e:
        M.validate_env()
    assert "AUTOOFF" in str(e.value)


def test_validate_env_rejects_autooff_not_above_loop(monkeypatch):
    # the watchdog must outlast the re-arm cadence, else it can fire between re-arms.
    for k, v in REQUIRED.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(M, "AUTOOFF_S", 15)
    monkeypatch.setattr(M, "LOOP_S", 15)
    with pytest.raises(SystemExit) as e:
        M.validate_env()
    assert "AUTOOFF" in str(e.value)


def test_validate_env_accepts_autooff_above_loop(monkeypatch):
    for k, v in REQUIRED.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(M, "AUTOOFF_S", 60)
    monkeypatch.setattr(M, "LOOP_S", 15)
    M.validate_env()   # must not raise


def test_validate_env_rejects_change_me_placeholder(monkeypatch):
    for k, v in REQUIRED.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("SHELLY_URL", "http://CHANGE_ME")
    with pytest.raises(SystemExit) as e:
        M.validate_env()
    assert "SHELLY_URL" in str(e.value) and "CHANGE_ME" in str(e.value)


def test_pos_int_clamps_bad_values(monkeypatch):
    # Bad port/sleep/cadence values fall back to the default — no import crash, no sleep(0).
    monkeypatch.setenv("X", "abc"); assert M._pos_int("X", 15) == 15
    monkeypatch.setenv("X", "0"); assert M._pos_int("X", 15) == 15
    monkeypatch.setenv("X", "-3"); assert M._pos_int("X", 30) == 30
    monkeypatch.setenv("X", "99999999"); assert M._pos_int("X", 10800) == 10800
    monkeypatch.setenv("X", "20"); assert M._pos_int("X", 15) == 20
    monkeypatch.delenv("X", raising=False); assert M._pos_int("X", 9123, hi=65535) == 9123


def test_pv_planes_invalid_json_fails_fast(monkeypatch):
    for k, v in REQUIRED.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("PV_PLANES", "not json")
    with pytest.raises(SystemExit) as e:
        importlib.reload(M)
    assert "PV_PLANES" in str(e.value)
    monkeypatch.setenv("PV_PLANES", REQUIRED["PV_PLANES"])
    importlib.reload(M)   # restore a sane module state for other tests
