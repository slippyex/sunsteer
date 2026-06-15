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
