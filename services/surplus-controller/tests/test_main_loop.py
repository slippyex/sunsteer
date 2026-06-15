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
