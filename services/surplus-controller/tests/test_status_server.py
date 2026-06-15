import src.status_server as ss


def setup_function():
    ss._status.clear()
    ss._beat = None
    ss._beat_max = 60.0


def test_no_beat_is_not_alive():
    assert ss.heartbeat_age() is None
    assert ss._alive() is False          # never beaten -> liveness must fail


def test_fresh_beat_is_alive(monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(ss.time, "time", lambda: t[0])
    ss.beat(60.0)
    t[0] = 1030.0                        # 30 s later, within max
    assert ss._alive() is True
    assert round(ss.heartbeat_age()) == 30


def test_stale_beat_is_dead(monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(ss.time, "time", lambda: t[0])
    ss.beat(60.0)
    t[0] = 1075.0                        # 75 s later, past max -> loop hung
    assert ss._alive() is False


def test_snapshot_stamps_status_schema():
    # The /status JSON is a contract the UI reads ~17 keys off. Stamp a schema version (like
    # /state does) so the consumer can detect a breaking shape change instead of silently
    # rendering wrong/blank.
    import src.status_server as S
    S.set_status(mode="auto", relay_on=True)
    snap = S._snapshot()
    assert snap["schema"] == S.STATUS_SCHEMA
    assert snap["mode"] == "auto"        # real status still present alongside the stamp


def test_serve_binds_to_given_interface(monkeypatch):
    # /status carries operational telemetry on an unauthenticated port; allow restricting it to
    # a specific interface (STATUS_BIND) like the exporter's /state does, instead of 0.0.0.0.
    import src.status_server as S
    captured = {}

    class _FakeServer:
        def __init__(self, addr, handler):
            captured["addr"] = addr

        def serve_forever(self):
            pass

    monkeypatch.setattr(S, "ThreadingHTTPServer", _FakeServer)
    S.serve(9124, bind="127.0.0.1")
    assert captured["addr"] == ("127.0.0.1", 9124)
