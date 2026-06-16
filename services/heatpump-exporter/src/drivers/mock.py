"""Synthetic heat-pump telemetry so the demo (and tests) show the heat-pump card without real
vendor credentials — the heat-pump analogue of the mock grid meter."""
import math

from ..contract import HEATPUMP_FIELDS

_DEMO_PERIOD_S = 600.0   # one synthetic 'day' every 10 min (matches the mock meter cadence)


class MockDriver:
    def __init__(self):
        self._n = 0
        self._energy = 100.0   # kWh lifetime counters, monotonically rising

    def poll(self):
        self._n += 1
        phase = (self._n % _DEMO_PERIOD_S) / _DEMO_PERIOD_S
        warmth = 0.5 + 0.5 * math.sin(2 * math.pi * phase)   # 0..1 over the synthetic day
        self._energy += 0.05
        reading = {f: None for f in HEATPUMP_FIELDS}
        reading.update({
            "dhw_temp_c": round(45.0 + 5.0 * warmth, 1),
            "dhw_target_c": 50.0,
            "dhw_mode": "dhw",
            "buffer_temp_c": round(35.0 + 5.0 * warmth, 1),
            "outside_temp_c": round(2.0 + 12.0 * warmth, 1),
            "supply_temp_c": round(38.0 + 4.0 * warmth, 1),
            "energy_total_kwh": round(self._energy, 2),
            "energy_heating_kwh": round(self._energy * 0.7, 2),
            "energy_dhw_kwh": round(self._energy * 0.3, 2),
            "scop_total": 4.2, "spf_total": 4.0,
            "compressor_speed_rps": round(30.0 + 40.0 * warmth, 1),
            "compressor_starts": float(self._n),
            "compressor_hours": round(self._n * 0.1, 1),
            "heat_heating_kwh": round(self._energy * 2.0, 2),
            "heat_dhw_kwh": round(self._energy * 0.8, 2),
            "heatingrod_heating_kwh": 0.0, "heatingrod_dhw_kwh": 0.0,
            # energy_read_at left None (mock has no lag)
        })
        return reading
