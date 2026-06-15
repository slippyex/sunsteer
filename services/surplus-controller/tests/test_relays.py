import json
import urllib.request

import src.relays as relays
from src.relays.shelly import ShellyRelayActuator, build_set_url


class _FakeResp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, *a):
        return self._b


def test_get_state_reads_output(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _FakeResp({"output": True}))
    assert ShellyRelayActuator("http://192.0.2.90").get_state() is True
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _FakeResp({"output": False}))
    assert ShellyRelayActuator("http://192.0.2.90").get_state() is False


def test_get_state_none_on_error(monkeypatch):
    def boom(*a, **k):
        raise OSError("unreachable")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert ShellyRelayActuator("http://192.0.2.90").get_state() is None

def test_on_includes_toggle_after_watchdog():
    url = build_set_url("http://192.0.2.90", on=True, switch_id=0, auto_off_s=60)
    assert url == "http://192.0.2.90/rpc/Switch.Set?id=0&on=true&toggle_after=60"

def test_off_has_no_toggle_after():
    url = build_set_url("http://192.0.2.90", on=False, switch_id=0, auto_off_s=60)
    assert url == "http://192.0.2.90/rpc/Switch.Set?id=0&on=false"

def test_trailing_slash_stripped():
    url = build_set_url("http://192.0.2.90/", on=True, switch_id=0, auto_off_s=45)
    assert url == "http://192.0.2.90/rpc/Switch.Set?id=0&on=true&toggle_after=45"


class _Resp:
    def __init__(self, body, status=200):
        self._b = json.dumps(body).encode(); self.status = status
    def read(self): return self._b
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_set_false_on_rpc_error_body(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Resp({"error": {"code": -103}}))
    assert ShellyRelayActuator("http://192.0.2.90").set(True, 60) is False


def test_set_true_on_clean_body(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Resp({"was_on": False}))
    assert ShellyRelayActuator("http://192.0.2.90").set(True, 60) is True


def test_set_on_without_autooff_is_hard_failure(monkeypatch):
    # SAFETY: an ON command with a falsy auto_off_s would latch the relay forever if the
    # controller dies. It must be refused (return False) and emit nothing over the wire.
    calls = []
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: calls.append(a) or _Resp({"was_on": False}))
    r = ShellyRelayActuator("http://192.0.2.90")
    assert r.set(True, 0) is False
    assert r.set(True, None) is False
    assert calls == []   # never emitted a watchdog-less ON


def test_set_off_without_autooff_is_allowed(monkeypatch):
    # turning OFF needs no watchdog — it must still work with a falsy auto_off_s.
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Resp({"was_on": True}))
    assert ShellyRelayActuator("http://192.0.2.90").set(False, 0) is True


def test_get_relay_unknown_fails_fast():
    import pytest
    with pytest.raises(SystemExit) as e:
        relays.get_relay("bogus", "http://x")
    assert "bogus" in str(e.value) and "shelly" in str(e.value)


def test_get_relay_shelly_builds_driver():
    r = relays.get_relay("shelly", "http://192.0.2.90")
    assert isinstance(r, ShellyRelayActuator) and r.base_url == "http://192.0.2.90"
