import pytest
import src.main as M

REQUIRED = {"SHM_HOST": "192.0.2.44", "SHELLY_URL": "http://192.0.2.90",
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
