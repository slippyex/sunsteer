import json

import src.shelly_ctl as sc
from src.shelly_ctl import build_set_url


class _FakeResp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, *a):
        return self._b


def test_get_switch_reads_output(monkeypatch):
    monkeypatch.setattr(sc.urllib.request, "urlopen", lambda *a, **k: _FakeResp({"output": True}))
    assert sc.get_switch("http://192.168.2.90") is True
    monkeypatch.setattr(sc.urllib.request, "urlopen", lambda *a, **k: _FakeResp({"output": False}))
    assert sc.get_switch("http://192.168.2.90") is False


def test_get_switch_none_on_error(monkeypatch):
    def boom(*a, **k):
        raise OSError("unreachable")
    monkeypatch.setattr(sc.urllib.request, "urlopen", boom)
    assert sc.get_switch("http://192.168.2.90") is None

def test_on_includes_toggle_after_watchdog():
    url = build_set_url("http://192.168.2.90", on=True, switch_id=0, auto_off_s=60)
    assert url == "http://192.168.2.90/rpc/Switch.Set?id=0&on=true&toggle_after=60"

def test_off_has_no_toggle_after():
    url = build_set_url("http://192.168.2.90", on=False, switch_id=0, auto_off_s=60)
    assert url == "http://192.168.2.90/rpc/Switch.Set?id=0&on=false"

def test_trailing_slash_stripped():
    url = build_set_url("http://192.168.2.90/", on=True, switch_id=0, auto_off_s=45)
    assert url == "http://192.168.2.90/rpc/Switch.Set?id=0&on=true&toggle_after=45"
