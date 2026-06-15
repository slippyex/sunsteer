import json
import os

import pytest
from src.extract import FIELDS, extract


def _feat(name, props):
    return {"feature": name, "properties": props}


def synthetic():
    """Mirrors the real E3_Vitocal_16 property shapes (2026-06-08 dump)."""
    return {"data": [
        _feat("heating.dhw.sensors.temperature.dhwCylinder", {"value": {"value": 52.6, "unit": "celsius"}}),
        _feat("heating.dhw.temperature.main", {"value": {"value": 50}}),
        _feat("heating.dhw.operating.modes.active", {"value": {"value": "efficient"}}),
        _feat("heating.bufferCylinder.sensors.temperature.main", {"value": {"value": 46}}),
        _feat("heating.sensors.temperature.outside", {"value": {"value": 16.8}}),
        _feat("heating.secondaryCircuit.sensors.temperature.supply", {"value": {"value": 45.3}}),
        _feat("heating.power.consumption.total",
              {"day": {"value": [0.7, 4.6]}, "dayValueReadAt": {"value": "2026-06-05T16:37:40.815Z"}}),
        _feat("heating.power.consumption.heating", {"day": {"value": [0.7, 2.9]}}),
        _feat("heating.power.consumption.dhw", {"day": {"value": [0.0, 1.7]}}),
        _feat("heating.heat.production.summary.heating", {"currentDay": {"value": 13.6}}),
        _feat("heating.heat.production.summary.dhw", {"currentDay": {"value": 4.2}}),
        _feat("heating.heatingRod.power.consumption.summary.heating", {"currentDay": {"value": 0}}),
        _feat("heating.heatingRod.power.consumption.summary.dhw", {"currentDay": {"value": 0}}),
        _feat("heating.scop.total", {"value": {"value": 5.2, "unit": ""}}),
        _feat("heating.spf.total", {"value": {"value": 5.2, "unit": ""}}),
        _feat("heating.compressors.0.speed.current", {"value": {"value": 0, "unit": "revolutionsPerSecond"}}),
        _feat("heating.compressors.0.statistics", {"starts": {"value": 194}, "hours": {"value": 271}}),
    ]}


def test_extract_maps_all_kinds():
    d = extract(synthetic())
    assert d["dhw_temp_c"] == 52.6
    assert d["dhw_target_c"] == 50
    assert d["dhw_mode"] == "efficient"
    assert d["buffer_temp_c"] == 46
    assert d["outside_temp_c"] == 16.8
    assert d["supply_temp_c"] == 45.3
    assert d["energy_total_kwh"] == 0.7          # day.value[0]
    assert d["energy_heating_kwh"] == 0.7
    assert d["energy_dhw_kwh"] == 0.0
    assert d["energy_read_at"] == "2026-06-05T16:37:40.815Z"
    assert d["heat_heating_kwh"] == 13.6         # currentDay.value
    assert d["heat_dhw_kwh"] == 4.2
    assert d["heatingrod_heating_kwh"] == 0
    assert d["scop_total"] == 5.2
    assert d["spf_total"] == 5.2
    assert d["compressor_speed_rps"] == 0
    assert d["compressor_starts"] == 194         # statistics.starts.value
    assert d["compressor_hours"] == 271          # statistics.hours.value


def test_missing_features_yield_none_not_raise():
    d = extract({"data": []})
    assert set(d.keys()) == set(FIELDS)
    assert all(v is None for v in d.values())


def test_handles_empty_day_array_and_garbage():
    d = extract({"data": [
        _feat("heating.power.consumption.total", {"day": {"value": []}}),           # empty
        _feat("heating.compressors.0.statistics", {"starts": {}}),                  # no value
        _feat("heating.scop.total", {}),                                            # no value key
    ]})
    assert d["energy_total_kwh"] is None
    assert d["compressor_starts"] is None
    assert d["scop_total"] is None


def test_real_fixture_core_fields_present():
    path = os.path.join(os.path.dirname(__file__), "fixtures", "features_real.json")
    if not os.path.exists(path):
        pytest.skip("probe fixture not captured")
    d = extract(json.load(open(path)))
    for k in ("dhw_temp_c", "outside_temp_c", "energy_total_kwh", "scop_total",
              "heat_heating_kwh", "compressor_hours"):
        assert d[k] is not None, f"{k} unexpectedly None in real fixture"
