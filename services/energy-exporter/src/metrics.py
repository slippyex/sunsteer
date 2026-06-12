"""Prometheus metric definitions + update helpers."""
import time
from prometheus_client import Gauge, Counter

# SHM
SHM_IMPORT = Gauge("sma_shm_grid_import_watts", "Grid import (W)")
SHM_EXPORT = Gauge("sma_shm_grid_export_watts", "Grid export (W)")
SHM_SURPLUS = Gauge("sma_shm_surplus_watts", "Surplus = export - import (W)")
SHM_PHASE = Gauge("sma_shm_phase_watts", "Per-phase power (W)", ["phase"])
SHM_IMPORT_KWH = Gauge("sma_shm_import_energy_kwh_total", "Lifetime import (kWh)")
SHM_EXPORT_KWH = Gauge("sma_shm_export_energy_kwh_total", "Lifetime export (kWh)")
SHM_LAST_TS = Gauge("sma_shm_last_telegram_timestamp_seconds", "Unix ts of last telegram")

# Shelly / heat pump
SHELLY_ON = Gauge("shelly_switch_on", "Relay state (1=on)")
SHELLY_POWER = Gauge("shelly_power_watts", "Heat-pump power via Shelly 1PM (W)")
SHELLY_ENERGY = Gauge("shelly_energy_wh_total", "Shelly lifetime energy (Wh)")
SHELLY_REACHABLE = Gauge("shelly_reachable", "1 if last poll succeeded")
SHELLY_VOLTAGE = Gauge("shelly_voltage", "Mains voltage (V)")
SHELLY_TEMP = Gauge("shelly_temperature_celsius", "Shelly internal temp (C)")

# Inverter (SMA Tripower X via Modbus TCP)
INV_POWER = Gauge("sma_inverter_ac_power_watts", "Inverter AC power = production (W)")
INV_TOTAL = Gauge("sma_inverter_energy_kwh_total", "Inverter lifetime yield (kWh)")
INV_REACHABLE = Gauge("sma_inverter_reachable", "1 if last inverter poll succeeded")
INV_DC_POWER = Gauge("sma_inverter_dc_power_watts", "DC power per MPPT string (W)", ["string"])
INV_DC_VOLTAGE = Gauge("sma_inverter_dc_voltage_volts", "DC voltage per MPPT string (V)", ["string"])
INV_DC_CURRENT = Gauge("sma_inverter_dc_current_amps", "DC current per MPPT string (A)", ["string"])
INV_TEMP = Gauge("sma_inverter_temperature_celsius", "Inverter device temperature (C)")
INV_OP_STATE = Gauge("sma_inverter_operating_state", "SMA operating state enum (307=Ok)")
INV_RISO = Gauge("sma_inverter_insulation_resistance_ohms", "DC insulation resistance (ohm)")
INV_AC_VOLTAGE = Gauge("sma_inverter_ac_voltage_volts", "AC voltage per phase (V)", ["phase"])
INV_GRID_FREQ = Gauge("sma_inverter_grid_frequency_hertz", "Grid frequency (Hz)")

POLL_ERRORS = Counter("energy_exporter_poll_errors_total", "Failed reads", ["source"])


def update_shm(r: dict) -> None:
    SHM_IMPORT.set(r["import_w"]); SHM_EXPORT.set(r["export_w"])
    SHM_SURPLUS.set(r["surplus_w"])
    SHM_PHASE.labels("L1").set(r["l1_w"])
    SHM_PHASE.labels("L2").set(r["l2_w"])
    SHM_PHASE.labels("L3").set(r["l3_w"])
    SHM_IMPORT_KWH.set(r["import_kwh_total"]); SHM_EXPORT_KWH.set(r["export_kwh_total"])
    SHM_LAST_TS.set(time.time())


def update_shelly(r) -> None:
    if r is None:
        SHELLY_REACHABLE.set(0); POLL_ERRORS.labels("shelly").inc(); return
    SHELLY_REACHABLE.set(1)
    SHELLY_ON.set(1 if r["relay_on"] else 0)
    SHELLY_POWER.set(r["power_w"]); SHELLY_ENERGY.set(r["energy_wh_total"])
    if r["voltage"] is not None: SHELLY_VOLTAGE.set(r["voltage"])
    if r["temperature_c"] is not None: SHELLY_TEMP.set(r["temperature_c"])


def _setg(gauge, value):
    if value is not None:
        gauge.set(value)


def update_inverter(r) -> None:
    if r is None:
        INV_REACHABLE.set(0); POLL_ERRORS.labels("inverter").inc(); return
    INV_REACHABLE.set(1)
    INV_POWER.set(r["production_w"])
    INV_TOTAL.set(r["total_yield_kwh"])
    _setg(INV_DC_POWER.labels("a"), r.get("dc_power_a"))
    _setg(INV_DC_POWER.labels("b"), r.get("dc_power_b"))
    _setg(INV_DC_VOLTAGE.labels("a"), r.get("dc_voltage_a"))
    _setg(INV_DC_VOLTAGE.labels("b"), r.get("dc_voltage_b"))
    _setg(INV_DC_CURRENT.labels("a"), r.get("dc_current_a"))
    _setg(INV_DC_CURRENT.labels("b"), r.get("dc_current_b"))
    _setg(INV_TEMP, r.get("temp_c"))
    _setg(INV_OP_STATE, r.get("operating_state"))
    _setg(INV_RISO, r.get("riso_ohm"))
    _setg(INV_AC_VOLTAGE.labels("l1"), r.get("ac_v_l1"))
    _setg(INV_AC_VOLTAGE.labels("l2"), r.get("ac_v_l2"))
    _setg(INV_AC_VOLTAGE.labels("l3"), r.get("ac_v_l3"))
    _setg(INV_GRID_FREQ, r.get("grid_freq"))
