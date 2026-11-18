from src.drivers.shelly import parse_em_status, parse_switch_status

SAMPLE = {
    "id": 0, "output": True, "apower": 1234.5, "voltage": 230.1,
    "current": 5.3, "aenergy": {"total": 6789.0}, "temperature": {"tC": 45.2},
}

def test_parse_full_status():
    r = parse_switch_status(SAMPLE)
    assert r["relay_on"] is True
    assert r["power_w"] == 1234.5
    assert r["energy_wh_total"] == 6789.0
    assert r["voltage"] == 230.1
    assert r["temperature_c"] == 45.2

def test_parse_handles_missing_optionals():
    r = parse_switch_status({"output": False, "apower": 0.0, "aenergy": {"total": 1.0}})
    assert r["relay_on"] is False
    assert r["power_w"] == 0.0
    assert r["energy_wh_total"] == 1.0
    assert r["voltage"] is None
    assert r["temperature_c"] is None


# Shelly Pro 3EM EM.GetStatus (triphase) — real WP power meter
EM_SAMPLE = {
    "id": 0,
    "a_act_power": 118.7, "b_act_power": 1.6, "c_act_power": 1611.1,
    "total_act_power": 1731.4,
}

def test_parse_em_status():
    r = parse_em_status(EM_SAMPLE)
    assert r["power_w"] == 1731.4
    assert r["l1_w"] == 118.7
    assert r["l2_w"] == 1.6
    assert r["l3_w"] == 1611.1

def test_parse_em_status_handles_missing():
    r = parse_em_status({})
    assert r["power_w"] == 0.0
    assert r["l1_w"] == 0.0
    assert r["l2_w"] == 0.0
    assert r["l3_w"] == 0.0
