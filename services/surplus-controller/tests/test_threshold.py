from src.threshold import adaptive_threshold, available_surplus

CFG = {"threshold_base_w": 2500, "threshold_min_w": 1500,
       "full_sun_ref_kwh": 40, "adapt_enabled": True}

def test_sunny_day_lowers_to_min():
    assert adaptive_threshold(CFG, 40) == 1500

def test_cloudy_day_stays_at_base():
    assert adaptive_threshold(CFG, 0) == 2500

def test_half_sun_is_midpoint():
    assert adaptive_threshold(CFG, 20) == 2000

def test_none_forecast_uses_base():
    assert adaptive_threshold(CFG, None) == 2500

def test_adapt_disabled_uses_base():
    assert adaptive_threshold({**CFG, "adapt_enabled": False}, 40) == 2500

def test_overcast_above_ref_clamped_to_min():
    assert adaptive_threshold(CFG, 999) == 1500


# --- load compensation (anti-oscillation) ---

def test_available_off_is_raw_surplus():
    # relay off -> no compensation, on-decision sees the real grid surplus
    assert available_surplus(1600, relay_on=False, wp_nominal_power_w=2000) == 1600

def test_available_on_adds_back_wp_load():
    # relay on -> add back the estimated WP draw so off-check sees surplus-without-WP
    assert available_surplus(-400, relay_on=True, wp_nominal_power_w=2000) == 1600

def test_available_zero_nominal_disables_compensation():
    assert available_surplus(-400, relay_on=True, wp_nominal_power_w=0) == -400

def test_available_prevents_false_off():
    # WP running, raw surplus 250 (< off 200? no) — but with a deeper draw it would
    # dip below off; compensation keeps the off-check on the real PV surplus.
    raw = -1200  # WP eating ~all surplus; off-threshold is 200 for this scenario
    assert available_surplus(raw, True, 1500) == 300  # 300 > 200 -> stays on (real PV ok)
    assert available_surplus(raw, True, 1000) == -200  # under-estimate -> would turn off


def test_adaptive_threshold_survives_zero_ref():
    # A raw/hand-built cfg with full_sun_ref_kwh == 0 must not ZeroDivisionError inside the
    # control cycle (the broad cycle guard would swallow it and silently skip actuation).
    cfg = {"threshold_base_w": 2500.0, "threshold_min_w": 1500.0,
           "full_sun_ref_kwh": 0.0, "adapt_enabled": True}
    assert adaptive_threshold(cfg, 10.0) == 2500.0    # degrade to base, no crash
