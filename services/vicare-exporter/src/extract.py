"""Pure: raw ViCare fetch_all_features() dict -> flat datapoint dict.
Every lookup is defensive: a missing/odd feature yields None, never raises.

Field map + property shapes confirmed against the live E3_Vitocal_16 dump 2026-06-08
(tests/fixtures/features_real.json). Property kinds:
  NUM/STR   -> properties.value.value
  DAY0      -> properties.day.value[0]          (el. energy, most-recent day, kWh)
  READAT    -> properties.dayValueReadAt.value   (ISO ts; energy lags a few days)
  CURDAY    -> properties.currentDay.value        (thermal/heatingRod summaries, kWh)
  STAT      -> properties.<sub>.value             (compressor starts/hours)
"""

_NUM = "num"
_STR = "str"
_DAY0 = "day0"
_READAT = "readat"
_CURDAY = "curday"
_STAT = "stat"

# key: (feature_name, kind, sub)
_FIELDS = {
    "dhw_temp_c":            ("heating.dhw.sensors.temperature.dhwCylinder", _NUM, None),
    "dhw_target_c":         ("heating.dhw.temperature.main", _NUM, None),
    "dhw_mode":             ("heating.dhw.operating.modes.active", _STR, None),
    "buffer_temp_c":        ("heating.bufferCylinder.sensors.temperature.main", _NUM, None),
    "outside_temp_c":       ("heating.sensors.temperature.outside", _NUM, None),
    "supply_temp_c":        ("heating.secondaryCircuit.sensors.temperature.supply", _NUM, None),
    "energy_total_kwh":     ("heating.power.consumption.total", _DAY0, None),
    "energy_heating_kwh":   ("heating.power.consumption.heating", _DAY0, None),
    "energy_dhw_kwh":       ("heating.power.consumption.dhw", _DAY0, None),
    "energy_read_at":       ("heating.power.consumption.total", _READAT, None),
    "heat_heating_kwh":     ("heating.heat.production.summary.heating", _CURDAY, None),
    "heat_dhw_kwh":         ("heating.heat.production.summary.dhw", _CURDAY, None),
    "heatingrod_heating_kwh": ("heating.heatingRod.power.consumption.summary.heating", _CURDAY, None),
    "heatingrod_dhw_kwh":   ("heating.heatingRod.power.consumption.summary.dhw", _CURDAY, None),
    "scop_total":           ("heating.scop.total", _NUM, None),
    "spf_total":            ("heating.spf.total", _NUM, None),
    "compressor_speed_rps": ("heating.compressors.0.speed.current", _NUM, None),
    "compressor_starts":    ("heating.compressors.0.statistics", _STAT, "starts"),
    "compressor_hours":     ("heating.compressors.0.statistics", _STAT, "hours"),
}

# Ordered field list — the single source of truth for column + gauge order.
FIELDS = list(_FIELDS.keys())
# Non-numeric fields: not turned into Prometheus gauges (text columns only).
STRING_FIELDS = {"dhw_mode", "energy_read_at"}


def _index(features):
    return {f.get("feature"): (f.get("properties") or {})
            for f in (features.get("data") or [])}


def _pull(props, kind, sub):
    try:
        if kind in (_NUM, _STR):
            return props["value"]["value"]
        if kind == _DAY0:
            arr = props["day"]["value"]
            return arr[0] if arr else None
        if kind == _READAT:
            return props["dayValueReadAt"]["value"]
        if kind == _CURDAY:
            return props["currentDay"]["value"]
        if kind == _STAT:
            return props[sub]["value"]
    except (KeyError, IndexError, TypeError):
        return None
    return None


def extract(features):
    idx = _index(features)
    out = {}
    for key, (name, kind, sub) in _FIELDS.items():
        props = idx.get(name)
        out[key] = _pull(props, kind, sub) if props is not None else None
    return out
