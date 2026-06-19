import src.metrics as M


def _valid_inverter():
    return {"production_w": 5000.0, "total_yield_kwh": 100.0, "dc_power_a": 4000.0,
            "dc_power_b": 400.0, "dc_voltage_a": 400.0, "dc_voltage_b": 360.0,
            "dc_current_a": 10.0, "dc_current_b": 1.0, "temp_c": 43.3,
            "operating_state": 307, "riso_ohm": 740287, "ac_v_l1": 230.0,
            "ac_v_l2": 230.0, "ac_v_l3": 230.0, "grid_freq": 50.0}


def test_update_inverter_tolerates_none_total_yield():
    # A NaN lifetime counter now arrives as None; update_inverter must skip the gauge, not
    # crash the (guarded) poll cycle and inc POLL_ERRORS every night.
    r = _valid_inverter()
    r["total_yield_kwh"] = None
    before = M.POLL_ERRORS.labels("inverter")._value.get()
    M.update_inverter(r)                                   # must not raise
    assert M.INV_REACHABLE._value.get() == 1              # still reachable
    assert M.POLL_ERRORS.labels("inverter")._value.get() == before


def test_update_inverter_sets_per_idx_dc_gauges():
    from src import metrics
    r = {"production_w": 3000.0, "total_yield_kwh": 100.0, "temp_c": 40.0,
         "operating_state": 307, "riso_ohm": 700000, "ac_v_l1": 230.0, "ac_v_l2": 230.0,
         "ac_v_l3": 230.0, "grid_freq": 50.0,
         "strings": [{"idx": 1, "power": 1500.0, "voltage": 380.0, "current": 3.9},
                     {"idx": 2, "power": 700.0, "voltage": 360.0, "current": 1.9}]}
    metrics.update_inverter(r)
    samples = {(m.name, tuple(sorted(s.labels.items()))): s.value
               for m in metrics.INV_DC_POWER.collect() for s in m.samples if s.name.endswith("_watts")}
    assert samples[("sma_inverter_dc_power_watts", (("string", "1"),))] == 1500.0
    assert samples[("sma_inverter_dc_power_watts", (("string", "2"),))] == 700.0
