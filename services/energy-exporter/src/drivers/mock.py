"""Synthetic grid-meter driver: a plausible surplus curve so the exporter runs and
the UI shows live data without any PV hardware. NOT for production use."""
import math
import random
import time


class MockMeter:
    """GridMeter protocol; one synthetic 'day' every 10 minutes.

    Emits the same reading shape as the SMA Speedwire decoder so metrics, /state
    and the TimescaleDB writer work unchanged.
    """

    PERIOD_S = 600          # one full day curve every 10 minutes
    PEAK_W = 4000.0         # midday PV peak
    BASE_LOAD_W = 350.0     # house base load
    CADENCE_S = 2.0         # SHM-like cadence

    def __init__(self):
        self._import_kwh = 0.0
        self._export_kwh = 0.0

    def reading(self):
        phase = (time.time() % self.PERIOD_S) / self.PERIOD_S        # 0..1 "day"
        pv = max(0.0, math.sin(phase * math.pi)) * self.PEAK_W
        load = self.BASE_LOAD_W + random.uniform(-50.0, 150.0)
        net = pv - load                                              # >0 = export
        imp, exp = max(0.0, -net), max(0.0, net)
        self._import_kwh += imp * self.CADENCE_S / 3_600_000.0
        self._export_kwh += exp * self.CADENCE_S / 3_600_000.0
        third = round(net / 3.0, 1)
        return {"serial": 0,
                "import_w": round(imp, 1), "export_w": round(exp, 1),
                "surplus_w": round(net, 1),
                "import_kwh_total": round(self._import_kwh, 4),
                "export_kwh_total": round(self._export_kwh, 4),
                "l1_w": third, "l2_w": third, "l3_w": third}

    def run(self, on_reading):
        while True:
            on_reading(self.reading())
            time.sleep(self.CADENCE_S)
