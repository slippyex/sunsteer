"""Orchestration tests for the REAL main() loop (not the pure state machine):
stale-grace re-arm semantics, fail-safe after grace, external-change reconciliation.
No production code is modified — dependencies are scripted, time.sleep ends the loop."""
import pytest
import src.main as M
from src.config import DEFAULTS, clamp_config


class StopLoop(Exception):
    pass


class Recorder:
    def __init__(self):
        self.switch_calls = []      # (target, auto_off_s)
        self.decisions = []         # kwargs/args of write_decision

    def set_switch(self, url, target, auto_off_s=None):
        self.switch_calls.append((target, auto_off_s))
        return True

    def write_decision(self, conn, mode, surplus, eff, fc, target, action, reason, **kw):
        self.decisions.append({"action": action, "reason": reason, "target": target, **kw})


def run_loop(monkeypatch, states, relay_seed=True, cycles=None, cfg_over=None, set_result=True):
    """Run main() for len(states) cycles. states[i] = the /state dict for cycle i (None = blind)."""
    rec = Recorder()
    for k, v in {"SHELLY_URL": "http://192.0.2.90", "PV_LAT": "50.0", "PV_LON": "8.0",
                 "PV_PLANES": "[[30,0,5.0]]", "DB_HOST": "db", "DB_NAME": "energy",
                 "DB_USER": "u", "DB_PASS": "p"}.items():
        monkeypatch.setenv(k, v)
    cfg = clamp_config({**DEFAULTS, "mode": "auto", **(cfg_over or {})})
    n_cycles = cycles or len(states)
    state_iter = iter(states)
    sleep_count = {"n": 0}

    def fake_sleep(_):
        sleep_count["n"] += 1
        if sleep_count["n"] >= n_cycles:
            raise StopLoop()

    class DummyThread:
        def __init__(self, *a, **k): pass
        def start(self): pass

    monkeypatch.setattr(M, "start_http_server", lambda *a, **k: None)
    monkeypatch.setattr(M.threading, "Thread", DummyThread)
    monkeypatch.setattr(M, "_db_connect", lambda: object())
    monkeypatch.setattr(M.dblog, "live_conn", lambda conn, fn: conn)
    monkeypatch.setattr(M.dblog, "last_switch_ages", lambda conn: (None, None))
    monkeypatch.setattr(M.dblog, "write_decision", rec.write_decision)
    monkeypatch.setattr(M.config, "load_config", lambda conn: dict(cfg))
    class FakeRelay:
        def __init__(self): self.seed = relay_seed
        def get_state(self): return self.seed
        def set(self, on, auto_off_s):
            rec.set_switch(None, on, auto_off_s)   # Recorder records (on, auto_off_s)
            return set_result                       # honour the injected outcome
    monkeypatch.setattr(M.relays, "get_relay", lambda name, url: FakeRelay())
    monkeypatch.setattr(M.time, "sleep", fake_sleep)
    monkeypatch.setattr(M, "read_state", lambda: next(state_iter, None))

    with pytest.raises(StopLoop):
        M.main()
    return rec


def fresh(surplus, shelly_on=True):
    return {"surplus_w": surplus, "shm_age_s": 0.5,
            "shelly_reachable": True, "shelly_on": shelly_on}


def test_first_blind_cycle_still_rearms_then_failsafe_then_silence(monkeypatch):
    # relay ON; cycle1 fresh hold, cycle2 BLIND (grace -> one more re-arm),
    # cycle3 BLIND (grace exhausted -> fail-safe OFF), cycle4 BLIND (off -> no calls at all)
    rec = run_loop(monkeypatch, [fresh(500), None, None, None], relay_seed=True)
    # cycles 1+2: re-arm (True, AUTOOFF) — the grace deliberately allows ONE blind re-arm
    assert rec.switch_calls[0] == (True, M.AUTOOFF_S)
    assert rec.switch_calls[1] == (True, M.AUTOOFF_S)
    # cycle 3: fail-safe OFF
    assert rec.switch_calls[2][0] is False
    assert rec.decisions[-1]["reason"] == "state_stale_failsafe"
    # cycle 4: relay off + still blind -> NO further switch calls (no re-arm while blind)
    assert len(rec.switch_calls) == 3


def test_blind_blip_of_one_cycle_does_not_cycle_the_wp(monkeypatch):
    # ON -> one blind cycle -> fresh again: the WP must never have been switched off
    rec = run_loop(monkeypatch, [fresh(500), None, fresh(500), fresh(500)], relay_seed=True)
    assert all(target is True for target, _ in rec.switch_calls)
    assert not any(d["reason"] == "state_stale_failsafe" for d in rec.decisions)


def test_external_off_is_logged_and_state_resynced(monkeypatch):
    # controller thinks ON, but the Shelly reports OFF (watchdog/ennexOS switched it):
    # -> external_change logged, state synced, and NO watchdog re-arm for a relay that is off.
    rec = run_loop(monkeypatch, [fresh(500, shelly_on=False), fresh(500, shelly_on=False)],
                   relay_seed=True)
    ext = [d for d in rec.decisions if d["reason"] == "external_change"]
    assert len(ext) == 1 and ext[0]["action"] == "switched_off"
    assert ext[0]["relay_on_before"] is True
    # after sync: relay off, surplus below threshold -> waiting, min_offtime blocks ->
    # NO switch commands at all (especially no re-arm of an off relay)
    assert rec.switch_calls == []


def test_auto_cold_start_switches_on_after_streak(monkeypatch):
    # relay OFF; feed enough fresh cycles with surplus well above the 2500 W base threshold;
    # min-offtime is satisfied (last_switch_ages -> None). After on_delay_cycles the controller
    # commands ON with the auto-off watchdog and logs surplus_threshold_met.
    # shelly_on=False matches the seeded-OFF relay so no external resync interferes.
    s = fresh(3000, shelly_on=False)     # surplus 3000 > 2500 base threshold
    rec = run_loop(monkeypatch, [s, s, s, s], relay_seed=False)
    assert (True, M.AUTOOFF_S) in rec.switch_calls          # armed the watchdog on ON
    on = [d for d in rec.decisions if d["action"] == "switched_on"]
    assert on and on[-1]["reason"] == "surplus_threshold_met"


def test_shelly_write_failure_does_not_advance_relay_state(monkeypatch):
    # relay OFF, surplus above threshold, but the relay rejects the write (set -> False).
    # The controller must NOT treat the relay as ON and must log shelly_write_failed.
    s = fresh(3000, shelly_on=False)     # shelly OFF matches seeded-OFF relay (no resync)
    rec = run_loop(monkeypatch, [s, s, s, s], relay_seed=False, set_result=False)
    failed = [d for d in rec.decisions if d.get("reason") == "shelly_write_failed"]
    assert failed                                            # the failure was logged


import json
import urllib.request


class _StateResp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self, *a): return self._b


def test_read_state_warns_on_unknown_schema(monkeypatch, caplog):
    # /state stamps a schema; an unexpected value must warn-and-continue, not crash or drop data.
    payload = {"schema": 2, "surplus_w": 500, "shm_age_s": 0.5}
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _StateResp(payload))
    import logging
    with caplog.at_level(logging.WARNING):
        out = M.read_state()
    assert out == payload                                    # still returns the parsed state
    assert any("schema" in r.message.lower() for r in caplog.records)


def test_read_state_warns_on_fetch_failure(monkeypatch, caplog):
    # A failed /state fetch must not vanish silently: it returns None (blind -> fail-safe path)
    # AND logs the cause so a flapping exporter/network is diagnosable.
    def boom(*a, **k):
        raise OSError("connection refused")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    import logging
    with caplog.at_level(logging.WARNING):
        out = M.read_state()
    assert out is None                                      # behaviour unchanged: blind read
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    assert any("read_state" in r.message for r in caplog.records)


def test_read_state_no_warn_on_known_schema(monkeypatch, caplog):
    payload = {"schema": M.KNOWN_STATE_SCHEMA, "surplus_w": 500, "shm_age_s": 0.5}
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _StateResp(payload))
    import logging
    with caplog.at_level(logging.WARNING):
        out = M.read_state()
    assert out == payload
    assert not any("schema" in r.message.lower() for r in caplog.records)


def _run_forecast_loop_once(monkeypatch):
    """Drive forecast_loop for exactly one iteration; return the list of sleep() durations.
    time.sleep records its arg and raises StopLoop to break the otherwise-infinite loop."""
    for k, v in {"PV_LAT": "50.0", "PV_LON": "8.0", "PV_TZ": "UTC"}.items():
        monkeypatch.setenv(k, v)
    sleeps = []

    def fake_sleep(s):
        sleeps.append(s)
        raise StopLoop()

    monkeypatch.setattr(M.time, "sleep", fake_sleep)
    try:
        M.forecast_loop(lambda: object())
    except StopLoop:
        pass
    return sleeps


def test_forecast_loop_short_backoff_after_failure(monkeypatch):
    # A transient forecast/DB failure must NOT park the loop for the full 3h refresh —
    # that would leave the adaptive threshold stuck on its base value for hours. Retry soon.
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(M.dblog, "live_conn", boom)
    sleeps = _run_forecast_loop_once(monkeypatch)
    assert sleeps == [min(M.FORECAST_S, 300)]


def test_forecast_loop_full_interval_after_success(monkeypatch):
    # A clean cycle sleeps the full refresh interval — no needless re-polling of the
    # forecast API (and its rate limits) when nothing failed.
    monkeypatch.setattr(M.dblog, "live_conn", lambda conn, fn: object())
    monkeypatch.setattr(M.config, "load_config", lambda conn: {})
    monkeypatch.setattr(M, "_compute_forecast", lambda *a: None)
    sleeps = _run_forecast_loop_once(monkeypatch)
    assert sleeps == [M.FORECAST_S]


def test_forecast_remaining_is_snapshotted_per_cycle(monkeypatch):
    # The forecast thread writes _forecast_remaining concurrently. Within one control cycle the
    # threshold computation, the decision-log row and the metrics must all use ONE consistent
    # snapshot — otherwise the audit log can disagree with the decision it records. Simulate a
    # mid-cycle write and assert the value flowing to metrics is the start-of-cycle snapshot.
    seen = []

    def capture_update(mode, relay_on, eff, fc, wp_est, **kw):
        seen.append(fc)

    monkeypatch.setattr(M.metrics, "update", capture_update)
    monkeypatch.setattr(M, "_forecast_remaining", 5.0)

    def threshold_then_mutate(cfg, fc):
        M._forecast_remaining = 999.0    # forecast thread writes between threshold and logging
        return 2000.0

    monkeypatch.setattr(M, "adaptive_threshold", threshold_then_mutate)
    run_loop(monkeypatch, [fresh(500, shelly_on=False)], relay_seed=False)
    assert seen == [5.0]                  # snapshot, not the mid-cycle 999.0


def test_status_reporting_failure_is_isolated_from_the_safety_path(monkeypatch):
    # A failure in non-safety reporting (metrics/status) must be categorised as a 'reporting'
    # error, NOT a control 'cycle' error, and must not stop the watchdog re-arm that already
    # ran this cycle. Keeps the safety path observably separate from telemetry.
    def boom(**k):
        raise RuntimeError("status server down")
    monkeypatch.setattr(M.status_server, "set_status", boom)
    before_rep = M.metrics.LOOP_ERRORS.labels("reporting")._value.get()
    before_cycle = M.metrics.LOOP_ERRORS.labels("cycle")._value.get()
    rec = run_loop(monkeypatch, [fresh(3000)], relay_seed=True)
    assert (True, M.AUTOOFF_S) in rec.switch_calls               # re-arm happened
    assert M.metrics.LOOP_ERRORS.labels("reporting")._value.get() == before_rep + 1
    assert M.metrics.LOOP_ERRORS.labels("cycle")._value.get() == before_cycle


def test_non_numeric_state_field_degrades_to_blind_not_a_crash(monkeypatch):
    # A /state contract regression (e.g. surplus_w arriving as a string) must degrade to the
    # blind/fail-safe path, never crash the cycle on a TypeError deep in the threshold math.
    bad = {"surplus_w": "abc", "shm_age_s": 0.5, "shelly_reachable": True, "shelly_on": True}
    before_cycle = M.metrics.LOOP_ERRORS.labels("cycle")._value.get()
    rec = run_loop(monkeypatch, [bad], relay_seed=True)
    assert (True, M.AUTOOFF_S) in rec.switch_calls               # blind-grace re-arm, didn't crash
    assert M.metrics.LOOP_ERRORS.labels("cycle")._value.get() == before_cycle
