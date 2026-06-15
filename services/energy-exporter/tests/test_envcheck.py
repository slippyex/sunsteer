import pytest
import src.main as M

REQUIRED = {"SHM_HOST": "192.0.2.44", "SHELLY_URL": "http://192.0.2.90",
            "DB_HOST": "db", "DB_NAME": "energy", "DB_USER": "u", "DB_PASS": "p"}


def test_validate_env_passes_when_all_set(monkeypatch):
    monkeypatch.delenv("METER_DRIVER", raising=False)
    for k, v in REQUIRED.items():
        monkeypatch.setenv(k, v)
    M.validate_env()   # must not raise


def test_validate_env_lists_every_missing_var(monkeypatch):
    monkeypatch.delenv("METER_DRIVER", raising=False)
    for k in REQUIRED:
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(SystemExit) as e:
        M.validate_env()
    for k in REQUIRED:
        assert k in str(e.value)


def test_validate_env_mock_meter_needs_only_db(monkeypatch):
    for k in REQUIRED:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("METER_DRIVER", "mock")
    for k in ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASS"):
        monkeypatch.setenv(k, "x")
    M.validate_env()   # SHM_HOST/SHELLY_URL not needed in mock mode


def test_validate_env_mock_meter_still_needs_db(monkeypatch):
    for k in REQUIRED:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("METER_DRIVER", "mock")
    with pytest.raises(SystemExit) as e:
        M.validate_env()
    assert "DB_HOST" in str(e.value) and "SHM_HOST" not in str(e.value)


def test_validate_env_rejects_change_me_placeholder(monkeypatch):
    monkeypatch.delenv("METER_DRIVER", raising=False)
    for k, v in REQUIRED.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("SHELLY_URL", "http://CHANGE_ME")   # unsubstituted example manifest
    with pytest.raises(SystemExit) as e:
        M.validate_env()
    assert "SHELLY_URL" in str(e.value)


def test_validate_env_unknown_meter_driver_fails_fast(monkeypatch):
    for k in REQUIRED:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("METER_DRIVER", "bogus")
    with pytest.raises(SystemExit) as e:
        M.validate_env()
    assert "bogus" in str(e.value) and "sma_shm" in str(e.value)


def test_pos_int_clamps_bad_values(monkeypatch):
    # Bad cadence/sleep values must fall back to the default, never crash or sleep(0).
    monkeypatch.setenv("X", "abc"); assert M._pos_int("X", 60) == 60
    monkeypatch.setenv("X", "0"); assert M._pos_int("X", 60) == 60
    monkeypatch.setenv("X", "-5"); assert M._pos_int("X", 10) == 10
    monkeypatch.setenv("X", "999999"); assert M._pos_int("X", 60) == 60
    monkeypatch.setenv("X", "30"); assert M._pos_int("X", 60) == 30
    monkeypatch.delenv("X", raising=False); assert M._pos_int("X", 42) == 42
