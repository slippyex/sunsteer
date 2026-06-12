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


def run_loop(monkeypatch, states, relay_seed=True, cycles=None, cfg_over=None):
    """Run main() for len(states) cycles. states[i] = the /state dict for cycle i (None = blind)."""
    rec = Recorder()
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
    monkeypatch.setattr(M, "get_switch", lambda url: relay_seed)
    monkeypatch.setattr(M, "set_switch", rec.set_switch)
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
