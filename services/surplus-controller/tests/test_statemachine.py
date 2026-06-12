from src.statemachine import decide

BIG = 10_000  # plenty of seconds, min-times satisfied

def d(**kw):
    base = dict(mode="auto", relay_on=False, manual_relay_on=False,
                on_streak=0, off_streak=0, on_delay_cycles=3, off_delay_cycles=3,
                secs_since_on=BIG, secs_since_off=BIG, min_runtime_s=1800, min_offtime_s=900,
                state_fresh=True)
    base.update(kw)
    return decide(**base)

def test_paused_forces_off():
    assert d(mode="paused", relay_on=True) == (False, "switched_off", "paused")
    assert d(mode="paused", relay_on=False) == (False, "no_change", "paused")

def test_manual_on():
    assert d(mode="manual", manual_relay_on=True, relay_on=False) == (True, "switched_on", "manual")
    assert d(mode="manual", manual_relay_on=True, relay_on=True) == (True, "no_change", "manual_hold")

def test_manual_off():
    assert d(mode="manual", manual_relay_on=False, relay_on=True) == (False, "switched_off", "manual")

def test_auto_turns_on_when_streak_met_and_offtime_elapsed():
    assert d(on_streak=3)[0] is True
    assert d(on_streak=3)[1] == "switched_on"

def test_auto_waits_until_on_streak_met():
    assert d(on_streak=2) == (False, "no_change", "waiting_surplus")

def test_auto_blocked_by_min_offtime():
    assert d(on_streak=5, secs_since_off=10) == (False, "no_change", "waiting_min_offtime")

def test_auto_turns_off_when_off_streak_met_and_runtime_elapsed():
    assert d(relay_on=True, off_streak=3)[0] is False
    assert d(relay_on=True, off_streak=3)[1] == "switched_off"

def test_auto_holds_during_min_runtime():
    assert d(relay_on=True, off_streak=5, secs_since_on=10) == (True, "no_change", "min_runtime")

def test_auto_holds_while_surplus_present():
    assert d(relay_on=True, off_streak=0) == (True, "no_change", "surplus_ok")

def test_stale_state_forces_off_when_running():
    # blind controller must never keep the WP on grid power, even mid-min-runtime
    assert d(relay_on=True, off_streak=0, secs_since_on=10, state_fresh=False) \
        == (False, "switched_off", "state_stale_failsafe")

def test_stale_state_noop_when_already_off():
    assert d(relay_on=False, state_fresh=False) == (False, "no_change", "state_stale_failsafe")

def test_stale_state_does_not_override_manual_on():
    # manual is an explicit user override that ignores surplus/freshness
    assert d(mode="manual", manual_relay_on=True, relay_on=True, state_fresh=False) \
        == (True, "no_change", "manual_hold")

def test_stale_state_irrelevant_when_paused():
    assert d(mode="paused", relay_on=True, state_fresh=False) == (False, "switched_off", "paused")
