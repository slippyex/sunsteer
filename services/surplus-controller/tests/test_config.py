from src.config import clamp_config, DEFAULTS

def test_defaults_pass_through_unchanged():
    c = clamp_config(dict(DEFAULTS))
    assert c["threshold_base_w"] == 2500
    assert c["min_runtime_s"] == 1800

def test_min_runtime_floored_to_600():
    c = clamp_config({**DEFAULTS, "min_runtime_s": 5})
    assert c["min_runtime_s"] == 600

def test_off_threshold_forced_below_min_threshold():
    c = clamp_config({**DEFAULTS, "threshold_off_w": 5000, "threshold_min_w": 1500})
    assert c["threshold_off_w"] < c["threshold_min_w"]

def test_negative_thresholds_clamped_to_zero():
    c = clamp_config({**DEFAULTS, "threshold_min_w": -100})
    assert c["threshold_min_w"] == 0.0

def test_mode_invalid_falls_back_to_paused():
    c = clamp_config({**DEFAULTS, "mode": "bogus"})
    assert c["mode"] == "paused"
