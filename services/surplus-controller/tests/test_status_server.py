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
