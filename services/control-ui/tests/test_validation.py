from src.validation import validate_settings

def base_form():
    return {"threshold_base_w": "2500", "threshold_min_w": "1500", "threshold_off_w": "200",
            "on_delay_cycles": "3", "off_delay_cycles": "3",
            "min_runtime_min": "30", "min_offtime_min": "15",
            "adapt_enabled": "on", "full_sun_ref_kwh": "40",
            "feed_in_tariff_eur_kwh": "0.08", "grid_price_eur_kwh": "0.30",
            "wp_nominal_power_w": "2000"}


def test_wp_nominal_power_parses():
    clean, errors = validate_settings(base_form())
    assert errors == {} and clean["wp_nominal_power_w"] == 2000.0

def test_valid_form_parses_and_converts_minutes():
    clean, errors = validate_settings(base_form())
    assert errors == {}
    assert clean["min_runtime_s"] == 1800
    assert clean["min_offtime_s"] == 900
    assert clean["threshold_base_w"] == 2500.0
    assert clean["adapt_enabled"] is True

def test_unchecked_adapt_is_false():
    form = base_form(); del form["adapt_enabled"]
    clean, errors = validate_settings(form)
    assert clean["adapt_enabled"] is False

def test_off_must_be_below_min():
    form = base_form(); form["threshold_off_w"] = "1600"
    clean, errors = validate_settings(form)
    assert "threshold_off_w" in errors

def test_min_below_base_required():
    form = base_form(); form["threshold_min_w"] = "3000"
    clean, errors = validate_settings(form)
    assert "threshold_min_w" in errors

def test_min_runtime_floor():
    form = base_form(); form["min_runtime_min"] = "2"
    clean, errors = validate_settings(form)
    assert "min_runtime_min" in errors

def test_non_numeric_is_error():
    form = base_form(); form["threshold_base_w"] = "abc"
    clean, errors = validate_settings(form)
    assert "threshold_base_w" in errors
