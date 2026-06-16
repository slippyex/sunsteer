"""The generic heat-pump telemetry contract: the field list every driver must emit and the
DB/metric layers consume. Vendor-neutral — drivers map their own data onto these keys."""

# Ordered field list — single source of truth for DB columns + gauges (and their order).
HEATPUMP_FIELDS = [
    "dhw_temp_c", "dhw_target_c", "dhw_mode", "buffer_temp_c", "outside_temp_c",
    "supply_temp_c", "energy_total_kwh", "energy_heating_kwh", "energy_dhw_kwh",
    "energy_read_at", "heat_heating_kwh", "heat_dhw_kwh", "heatingrod_heating_kwh",
    "heatingrod_dhw_kwh", "scop_total", "spf_total", "compressor_speed_rps",
    "compressor_starts", "compressor_hours",
]
# Non-numeric fields: text columns only, not turned into Prometheus gauges.
HEATPUMP_STRING_FIELDS = {"dhw_mode", "energy_read_at"}
