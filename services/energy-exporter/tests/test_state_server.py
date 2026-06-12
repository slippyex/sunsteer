import src.state_server as ss


def setup_function():
    # reset module state between tests
    ss._latest.clear()
    ss._shm_ts = None


def test_snapshot_age_none_when_no_shm():
    ss.set_state(shelly_on=True)
    snap = ss._snapshot()
    assert snap["shm_age_s"] is None
    assert snap["shelly_on"] is True


def test_set_shm_stamps_freshness(monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(ss.time, "time", lambda: t[0])
    ss.set_shm(surplus_w=1500.0, import_w=0.0, export_w=1500.0)
    t[0] = 1004.0   # 4 s later
    snap = ss._snapshot()
    assert snap["surplus_w"] == 1500.0
    assert snap["shm_age_s"] == 4.0


def test_set_state_does_not_refresh_shm(monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(ss.time, "time", lambda: t[0])
    ss.set_shm(surplus_w=1500.0)
    t[0] = 1030.0
    ss.set_state(shelly_reachable=False)   # secondary update must NOT reset the SHM stamp
    snap = ss._snapshot()
    assert snap["shm_age_s"] == 30.0
