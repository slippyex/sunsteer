from src import main, metrics


class Budget:
    def __init__(self, allowed):
        self.allowed = allowed
        self.records = 0

    def allow(self, now):
        return self.allowed

    def record(self, now):
        self.records += 1

    def count(self, now):
        return self.records


def test_cycle_skips_when_budget_exhausted(monkeypatch):
    calls = {"poll": 0}
    monkeypatch.setattr(main.vicare_client, "poll",
                        lambda d: calls.__setitem__("poll", calls["poll"] + 1) or {"data": []})
    main.run_cycle(device=object(), conn=None, budget=Budget(allowed=False), now=0)
    assert calls["poll"] == 0
    assert metrics.BUDGET_EXHAUSTED._value.get() == 1


def test_cycle_polls_extracts_writes_records(monkeypatch):
    monkeypatch.setattr(main.vicare_client, "poll", lambda d: {"data": [
        {"feature": "heating.sensors.temperature.outside", "properties": {"value": {"value": 9.0}}}]})
    writes = {"n": 0}
    monkeypatch.setattr(main.tsdb_writer, "write", lambda c, d: writes.__setitem__("n", writes["n"] + 1))
    budget = Budget(allowed=True)
    main.run_cycle(device=object(), conn=object(), budget=budget, now=0)
    assert writes["n"] == 1
    assert budget.records == 1
    assert metrics.BUDGET_EXHAUSTED._value.get() == 0
    assert metrics.GAUGES["outside_temp_c"]._value.get() == 9.0


def test_is_rate_limit_detects_429_and_text():
    import src.main as M
    assert M._is_rate_limit(Exception("HTTP 429 Too Many Requests")) is True
    assert M._is_rate_limit(Exception("connection reset")) is False


def test_connect_with_retry_backs_off_then_succeeds(monkeypatch):
    import src.main as M
    attempts = {"n": 0}

    def flaky(token_file):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise Exception("HTTP 429 rate limited")
        return "DEVICE"

    monkeypatch.setattr(M.auth, "connect_device", flaky)
    monkeypatch.setattr(M.time, "sleep", lambda _s: None)   # don't actually wait
    dev = M.connect_with_retry("tok", max_backoff=10)
    assert dev == "DEVICE" and attempts["n"] == 3


def test_is_invalid_credentials_detects_text():
    import src.main as M
    assert M._is_invalid_credentials(Exception("invalid credentials")) is True
    assert M._is_invalid_credentials(Exception("HTTP 429 rate limited")) is False


def test_connect_with_retry_surfaces_invalid_credentials(monkeypatch, caplog):
    import logging

    import src.main as M
    attempts = {"n": 0}
    before = metrics.INVALID_CREDENTIALS._value.get()

    def bad_creds(token_file):
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise Exception("invalid credentials provided")
        return "DEVICE"   # not a crash-loop: backoff + retry still succeeds

    monkeypatch.setattr(M.auth, "connect_device", bad_creds)
    monkeypatch.setattr(M.time, "sleep", lambda _s: None)
    with caplog.at_level(logging.ERROR):
        dev = M.connect_with_retry("tok", max_backoff=10)
    assert dev == "DEVICE"                                   # capped backoff, no crash
    assert metrics.INVALID_CREDENTIALS._value.get() == before + 1
    assert any("credential" in r.message.lower() for r in caplog.records)


def test_pos_int_clamps_bad_values(monkeypatch):
    monkeypatch.setenv("X", "abc"); assert main._pos_int("X", 1400) == 1400
    monkeypatch.setenv("X", "0"); assert main._pos_int("X", 9125, hi=65535) == 9125
    monkeypatch.setenv("X", "1400"); assert main._pos_int("X", 1) == 1400
    monkeypatch.delenv("X", raising=False); assert main._pos_int("X", 42) == 42
