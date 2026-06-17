from src.explain import effectiveness_eur, explain

CFG = {"wp_nominal_power_w": 2000, "threshold_off_w": 200}

def s(**kw):
    base = dict(mode="auto", relay_on=False, surplus_w=465, effective_threshold_w=2382,
                on_streak=0, off_streak=0, on_delay_cycles=3, off_delay_cycles=3,
                secs_since_on=10000, secs_since_off=10000, min_runtime_s=1800,
                min_offtime_s=900, reason="waiting_surplus")
    base.update(kw); return base

def test_none_status_unknown_defaults_english():
    r = explain(None, CFG)
    assert r["state"] == "unknown" and "Status unavailable" in r["headline"]

def test_paused():
    r = explain(s(mode="paused"), CFG, lang="de")
    assert r["headline"] == "Pausiert (Not-Aus)"

def test_manual_on_off():
    assert explain(s(mode="manual", relay_on=True), CFG, lang="de")["headline"] == "WP manuell EIN"
    assert explain(s(mode="manual", relay_on=False), CFG, lang="de")["headline"] == "WP manuell AUS"

def test_auto_waiting_surplus_shows_streak():
    r = explain(s(reason="waiting_surplus", on_streak=2, on_delay_cycles=3), CFG, lang="de")
    assert r["headline"] == "WP aus"
    assert "465 W unter Schwelle 2382 W" in r["detail"]
    assert r["bar_label"] == "2/3 Zyklen über Schwelle"
    assert abs(r["bar_pct"] - 2/3) < 1e-6

def test_auto_waiting_min_offtime_countdown():
    r = explain(s(reason="waiting_min_offtime", secs_since_off=600, min_offtime_s=900), CFG, lang="de")
    assert "Mindestpause" in r["detail"]
    assert r["bar_label"] == "noch 5 min"
    assert abs(r["bar_pct"] - 600/900) < 1e-6

def test_auto_on_min_runtime_countdown():
    r = explain(s(relay_on=True, reason="min_runtime", secs_since_on=1320, min_runtime_s=1800), CFG, lang="de")
    assert r["headline"] == "WP läuft"
    assert r["bar_label"] == "Mindestlaufzeit noch 8 min"
    assert abs(r["bar_pct"] - 1320/1800) < 1e-6

def test_auto_on_surplus_ok_shows_compensated():
    # raw surplus 285 (net feed-in) -> available = 285 + 2000 = 2285 vs off-threshold 200
    r = explain(s(relay_on=True, reason="surplus_ok", surplus_w=285), CFG, lang="de")
    assert r["headline"] == "WP läuft"
    assert "netto +285 W Einspeisung" in r["detail"]
    assert "verfügbar 2285 W" in r["detail"]
    assert "Aus-Schwelle 200 W" in r["detail"]
    assert r["bar_pct"] == 0

def test_auto_on_net_draw_with_off_countdown():
    # WP running but raw surplus negative (drawing grid) and off-streak building toward switch-off
    r = explain(s(relay_on=True, reason="surplus_ok", surplus_w=-400,
                  off_streak=2, off_delay_cycles=3), CFG, lang="de")
    assert "netto -400 W Netzbezug" in r["detail"]
    assert r["bar_label"] == "2/3 Zyklen unter Aus-Schwelle (200 W)"
    assert abs(r["bar_pct"] - 2 / 3) < 1e-6

def test_auto_stale_state_shows_failsafe():
    r = explain(s(relay_on=False, state_fresh=False, state_age_s=47, reason="state_stale_failsafe"), CFG, lang="de")
    assert r["state"] == "stale"
    assert "veraltet" in r["headline"] and "47 s" in r["detail"]

def test_fresh_state_unaffected():
    # state_fresh True (or absent) -> normal explanation, not the stale branch
    r = explain(s(relay_on=False, state_fresh=True, on_streak=2), CFG, lang="de")
    assert r["state"] == "off" and r["headline"] == "WP aus"


def test_effectiveness_eur():
    assert effectiveness_eur(10, 0.30, 0.08) == 2.2
    assert effectiveness_eur(0, 0.30, 0.08) == 0.0


def test_energy_today_has_no_derived_cop():
    from src import explain
    # frozen ViCare case: tiny electrical, climbing thermal — must NOT yield a COP at all
    r = explain.energy_today(0.2, 14.0, 0.9)
    assert "cop_today" not in r
    assert r["th_total"] == 14.9
    assert explain.energy_today(None, None, None)["th_total"] is None


def test_explain_english():
    r = explain(s(relay_on=True, reason="surplus_ok", surplus_w=285), CFG, lang="en")
    assert r["headline"] == "HP running"
    assert "net +285 W feed-in" in r["detail"] and "off threshold 200 W" in r["detail"]

def test_explain_stale_english():
    r = explain(s(relay_on=False, state_fresh=False, state_age_s=47,
                  reason="state_stale_failsafe"), CFG, lang="en")
    assert "stale" in r["headline"].lower() and "for 47 s" in r["detail"]


def test_explain_sun_below_horizon():
    from src.explain import explain
    status = {"mode": "auto", "relay_on": False, "state_fresh": True,
              "surplus_w": -565, "effective_threshold_w": 1500,
              "reason": "sun_below_horizon"}
    out = explain(status, {}, lang="en")
    assert out["state"] == "off"
    assert "sun" in out["detail"].lower()
