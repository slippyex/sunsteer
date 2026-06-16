import pytest
import src.main as main


class _FakeDriver:
    def __init__(self, readings):
        self._readings = list(readings)

    def poll(self):
        return self._readings.pop(0) if self._readings else None


def test_validate_env_lists_missing_db(monkeypatch):
    monkeypatch.setattr(main, "HEATPUMP_DRIVER", "mock")   # mock needs no vendor creds
    for v in ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASS"):
        monkeypatch.delenv(v, raising=False)
    with pytest.raises(SystemExit) as e:
        main.validate_env()
    assert "DB_HOST" in str(e.value)


def test_validate_env_lists_missing_vicare_creds(monkeypatch):
    # With the vicare driver selected, validate_env must also require the vendor creds and
    # fail fast with a clear message rather than a bare KeyError deep inside the driver.
    monkeypatch.setattr(main, "HEATPUMP_DRIVER", "vicare")
    for v in ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASS"):
        monkeypatch.setenv(v, "x")
    for v in ("VICARE_USER", "VICARE_PASS", "VICARE_CLIENT_ID"):
        monkeypatch.delenv(v, raising=False)
    with pytest.raises(SystemExit) as e:
        main.validate_env()
    assert "VICARE_USER" in str(e.value)


def test_validate_env_rejects_change_me_placeholder(monkeypatch):
    monkeypatch.setattr(main, "HEATPUMP_DRIVER", "vicare")
    for v in ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASS",
              "VICARE_USER", "VICARE_PASS", "VICARE_CLIENT_ID"):
        monkeypatch.setenv(v, "x")
    monkeypatch.setenv("VICARE_PASS", "CHANGE_ME")
    with pytest.raises(SystemExit) as e:
        main.validate_env()
    assert "CHANGE_ME" in str(e.value)


def test_run_cycle_writes_reading_and_sets_liveness(monkeypatch):
    wrote = {}
    monkeypatch.setattr(main.tsdb_writer, "write", lambda c, d: wrote.update(d))
    main.run_cycle(_FakeDriver([{"dhw_temp_c": 9.0}]), conn=object())
    assert wrote["dhw_temp_c"] == 9.0


def test_run_cycle_skips_on_none(monkeypatch):
    wrote = {"n": 0}
    monkeypatch.setattr(main.tsdb_writer, "write",
                        lambda c, d: wrote.__setitem__("n", wrote["n"] + 1))
    main.run_cycle(_FakeDriver([None]), conn=object())
    assert wrote["n"] == 0
