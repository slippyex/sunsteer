from src.contract import HEATPUMP_FIELDS, HEATPUMP_STRING_FIELDS


def test_contract_fields_are_the_telemetry_keys():
    # The shell owns the contract; it must list exactly today's telemetry fields.
    assert "dhw_temp_c" in HEATPUMP_FIELDS and "compressor_hours" in HEATPUMP_FIELDS
    assert HEATPUMP_STRING_FIELDS == {"dhw_mode", "energy_read_at"}
    assert len(HEATPUMP_FIELDS) == 19
