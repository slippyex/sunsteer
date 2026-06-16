import pytest
import src.drivers.vicare as vicare
import src.drivers.vicare_metrics as vm


def test_is_rate_limit_detects_429_and_text():
    assert vicare._is_rate_limit(Exception("HTTP 429 Too Many Requests")) is True
    assert vicare._is_rate_limit(Exception("connection reset")) is False


def test_connect_with_retry_backs_off_then_succeeds(monkeypatch):
    attempts = {"n": 0}

    def flaky(token_file):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise Exception("HTTP 429 rate limited")
        return "DEVICE"

    monkeypatch.setattr(vicare, "connect_device", flaky)
    monkeypatch.setattr(vicare.time, "sleep", lambda _s: None)   # don't actually wait
    dev = vicare.connect_with_retry("tok", max_backoff=10)
    assert dev == "DEVICE" and attempts["n"] == 3


def test_is_invalid_credentials_detects_text():
    assert vicare._is_invalid_credentials(Exception("invalid credentials")) is True
    assert vicare._is_invalid_credentials(Exception("HTTP 429 rate limited")) is False


def test_connect_with_retry_surfaces_invalid_credentials(monkeypatch, caplog):
    import logging
    attempts = {"n": 0}
    before = vm.INVALID_CREDENTIALS._value.get()

    def bad_creds(token_file):
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise Exception("invalid credentials provided")
        return "DEVICE"   # not a crash-loop: backoff + retry still succeeds

    monkeypatch.setattr(vicare, "connect_device", bad_creds)
    monkeypatch.setattr(vicare.time, "sleep", lambda _s: None)
    with caplog.at_level(logging.ERROR):
        dev = vicare.connect_with_retry("tok", max_backoff=10)
    assert dev == "DEVICE"                                   # capped backoff, no crash
    assert vm.INVALID_CREDENTIALS._value.get() == before + 1
    assert any("credential" in r.message.lower() for r in caplog.records)


def test_connect_with_retry_exits_after_repeated_invalid_credentials(monkeypatch):
    # Invalid credentials are permanent; looping forever silently burns the (uncounted)
    # discovery-call budget against the rate-limited API. After a bounded number of attempts
    # it must exit so the failure is VISIBLE (CrashLoopBackOff), not hidden.
    calls = {"n": 0}

    def boom(_tf):
        calls["n"] += 1
        raise RuntimeError("invalid credentials")

    monkeypatch.setattr(vicare, "connect_device", boom)
    monkeypatch.setattr(vicare.time, "sleep", lambda *_: None)
    with pytest.raises(SystemExit):
        vicare.connect_with_retry("tok", max_invalid_attempts=3)
    assert calls["n"] == 3


def test_connect_with_retry_recovers_from_transient_errors(monkeypatch):
    # Transient errors (network blips) must NOT count toward the invalid-credentials exit:
    # the loop keeps retrying and succeeds once discovery works.
    calls = {"n": 0}
    sentinel = object()

    def flaky(_tf):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("network blip")
        return sentinel

    monkeypatch.setattr(vicare, "connect_device", flaky)
    monkeypatch.setattr(vicare.time, "sleep", lambda *_: None)
    out = vicare.connect_with_retry("tok", max_invalid_attempts=2)
    assert out is sentinel
    assert calls["n"] == 3


def test_next_backoff_jumps_to_cap_on_rate_limit():
    # A 429 means "be quiet" -> go straight to the cap regardless of the current backoff.
    assert vicare._next_backoff(True, 0, max_backoff=1800) == 1800
    assert vicare._next_backoff(True, 600, max_backoff=1800) == 1800


def test_next_backoff_ramps_linearly_otherwise():
    # Non-rate-limit errors ramp by POLL_S each time, capped at max_backoff.
    assert vicare._next_backoff(False, 0, max_backoff=1800) == vicare.POLL_S
    assert vicare._next_backoff(False, 100000, max_backoff=1800) == 1800


def test_secure_token_file_restricts_permissions(tmp_path):
    # The cached OAuth token is a long-lived refresh grant to the user's Viessmann account;
    # PyViCare writes it with the default umask (~0644). Lock it to owner-only.
    import os
    import stat
    p = tmp_path / "vicare_token.json"
    p.write_text("{}")
    os.chmod(p, 0o644)
    vicare.secure_token_file(str(p))
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600


def test_secure_token_file_noop_when_missing(tmp_path):
    # No file yet (first start) -> must not raise.
    vicare.secure_token_file(str(tmp_path / "nope.json"))


def test_required_env_lists_vicare_creds():
    assert "VICARE_USER" in vicare.REQUIRED_ENV
    assert "VICARE_PASS" in vicare.REQUIRED_ENV
    assert "VICARE_CLIENT_ID" in vicare.REQUIRED_ENV
