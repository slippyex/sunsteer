import logging

import src.main as M


def test_run_guarded_logs_the_cause_on_a_throw(monkeypatch, caplog):
    # Counting POLL_ERRORS without the exception cause makes failures undebuggable.
    # run_guarded must log the concrete cause AND the source name when it catches.
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("boom-cause")

    class StopLoop(Exception):
        pass

    def fake_sleep(_):
        if calls["n"] >= 2:
            raise StopLoop()

    monkeypatch.setattr(M.time, "sleep", fake_sleep)
    with caplog.at_level(logging.WARNING, logger=M.log.name):
        try:
            M.run_guarded("widget", flaky, sleep_s=0)
        except StopLoop:
            pass
    msg = caplog.text
    assert "boom-cause" in msg        # concrete exception cause surfaced
    assert "widget" in msg            # source name surfaced


def test_run_guarded_survives_a_raising_cycle(monkeypatch):
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("boom")

    class StopLoop(Exception):
        pass

    def fake_sleep(_):
        if calls["n"] >= 2:
            raise StopLoop()

    monkeypatch.setattr(M.time, "sleep", fake_sleep)
    before = M.metrics.POLL_ERRORS.labels("test")._value.get()
    try:
        M.run_guarded("test", flaky, sleep_s=0)
    except StopLoop:
        pass
    assert calls["n"] >= 2
    assert M.metrics.POLL_ERRORS.labels("test")._value.get() == before + 1


def test_on_meter_reading_survives_malformed_reading():
    before = M.metrics.POLL_ERRORS.labels("meter")._value.get()
    M.on_meter_reading({"surplus_w": 1.0})   # missing import_w/export_w/l1_w...
    assert M.metrics.POLL_ERRORS.labels("meter")._value.get() == before + 1


def test_meter_run_is_wrapped_so_a_throwing_run_restarts(monkeypatch):
    # A meter whose run() throws should NOT kill the thread: run_meter_guarded must catch,
    # count it, and retry (not propagate).
    calls = {"n": 0}

    class FlakyMeter:
        def run(self, on_reading):
            calls["n"] += 1
            raise RuntimeError("socket boom")

    class StopLoop(Exception):
        pass

    def fake_sleep(_):
        if calls["n"] >= 2:
            raise StopLoop()

    monkeypatch.setattr(M.time, "sleep", fake_sleep)
    before = M.metrics.POLL_ERRORS.labels("meter")._value.get()
    try:
        M.run_meter_guarded(FlakyMeter())
    except StopLoop:
        pass
    assert calls["n"] >= 2                                              # retried, didn't die on first throw
    assert M.metrics.POLL_ERRORS.labels("meter")._value.get() >= before + 1


def test_tsdb_flusher_survives_throw_outside_db_block(monkeypatch):
    # A throw from aggregate_samples (OUTSIDE the connect->write try) must NOT kill the
    # flush thread: it has to be counted under POLL_ERRORS{source=tsdb}, slept, survived.
    calls = {"n": 0}

    with M._buf_lock:
        M._buf[:] = [{"surplus_w": 1.0}]   # something in the buffer to flush

    def boom(_samples):
        calls["n"] += 1
        raise RuntimeError("aggregate boom")

    monkeypatch.setattr(M.tsdb_writer, "aggregate_samples", boom)

    class StopLoop(Exception):
        pass

    def fake_sleep(_):
        if calls["n"] >= 1:
            raise StopLoop()

    monkeypatch.setattr(M.time, "sleep", fake_sleep)
    before = M.metrics.POLL_ERRORS.labels("tsdb")._value.get()
    try:
        M.tsdb_flusher(lambda: None)
    except StopLoop:
        pass
    assert calls["n"] >= 1                                              # body ran, didn't die before aggregate
    assert M.metrics.POLL_ERRORS.labels("tsdb")._value.get() == before + 1
    # _buf was swapped out before the throw -> does not grow without bound across cycles
    with M._buf_lock:
        assert M._buf == []
