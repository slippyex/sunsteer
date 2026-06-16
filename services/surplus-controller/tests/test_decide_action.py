"""Unit tests for the pure decision core extracted from the main loop: load-compensation,
hysteresis streaks, and the decide() call — no I/O, no threads, no monkeypatching the loop."""
import src.main as M
from src.config import DEFAULTS, clamp_config


def cfg(**over):
    return clamp_config({**DEFAULTS, "mode": "auto", **over})


def test_blind_resets_streaks_and_fails_safe():
    avail, on_s, off_s, target, action, reason = M.decide_action(
        cfg(), relay_on=False, state_fresh=False, fresh_for_decide=False,
        surplus=500.0, eff=2000.0, on_streak=2, off_streak=0,
        secs_since_on=10000, secs_since_off=10000, sun_up=True)
    assert on_s == 0 and off_s == 0           # blind resets the hysteresis streaks
    assert avail == 500.0                      # no load-compensation when blind
    assert target is False and reason == "state_stale_failsafe"


def test_load_compensates_when_relay_on():
    avail, *_ = M.decide_action(
        cfg(wp_nominal_power_w=2000.0), relay_on=True, state_fresh=True, fresh_for_decide=True,
        surplus=300.0, eff=2000.0, on_streak=0, off_streak=0,
        secs_since_on=10000, secs_since_off=10000, sun_up=True)
    assert avail == 2300.0                     # 300 surplus + 2000 nominal WP draw added back


def test_on_streak_builds_until_switch():
    c = cfg(on_delay_cycles=2, threshold_base_w=2000.0)
    args = dict(relay_on=False, state_fresh=True, fresh_for_decide=True,
                surplus=3000.0, eff=2000.0, off_streak=0,
                secs_since_on=10000, secs_since_off=10000, sun_up=True)
    avail1, on1, _o1, t1, _a1, _r1 = M.decide_action(c, on_streak=0, **args)
    assert on1 == 1 and t1 is False            # one cycle in: not yet switched
    avail2, on2, _o2, t2, a2, _r2 = M.decide_action(c, on_streak=1, **args)
    assert on2 == 2 and t2 is True and a2 == "switched_on"
