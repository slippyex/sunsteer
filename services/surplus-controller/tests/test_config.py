from src.config import DEFAULTS, clamp_config


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


def test_none_numeric_field_degrades_to_default():
    # a NULL column in control_config must not poison hot-reload of the WHOLE config.
    c = clamp_config({**DEFAULTS, "threshold_base_w": None})
    assert c["threshold_base_w"] == DEFAULTS["threshold_base_w"]


def test_none_int_field_degrades_to_default():
    c = clamp_config({**DEFAULTS, "min_runtime_s": None})
    assert c["min_runtime_s"] == DEFAULTS["min_runtime_s"]


def test_off_below_min_invariant_holds_for_normal_values():
    c = clamp_config({**DEFAULTS, "threshold_min_w": 1500, "threshold_off_w": 1490})
    assert c["threshold_off_w"] < c["threshold_min_w"]


def test_base_load_percentile_default_and_clamp():
    from src.config import DEFAULTS, clamp_config
    assert DEFAULTS["base_load_percentile"] == 50.0
    assert clamp_config({"base_load_percentile": 2})["base_load_percentile"] == 5.0
    assert clamp_config({"base_load_percentile": 200})["base_load_percentile"] == 95.0
    assert clamp_config({"base_load_percentile": None})["base_load_percentile"] == 50.0
    assert clamp_config({"base_load_percentile": 40})["base_load_percentile"] == 40.0
