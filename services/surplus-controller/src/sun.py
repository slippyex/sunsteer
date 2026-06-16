"""Solar elevation angle — pure, dependency-free (NOAA solar-position approximation).

Used to gate the load-compensation: no real PV is possible when the sun is below the
horizon, so the surplus calculation must not keep the heat pump running after dark."""
import math


def sun_elevation(lat_deg: float, lon_deg: float, when_utc) -> float:
    """Solar elevation angle in degrees for a location and a UTC datetime.

    Accurate to well within a degree — ample for a few-degree gate. `when_utc` is a
    datetime whose wall-clock fields are UTC (aware-UTC or naive-UTC both work)."""
    n = when_utc.timetuple().tm_yday
    hour = when_utc.hour + when_utc.minute / 60.0 + when_utc.second / 3600.0
    gamma = 2.0 * math.pi / 365.0 * (n - 1 + (hour - 12) / 24.0)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
                       - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
    decl = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
            - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma)
            - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))
    tst = hour * 60.0 + eqtime + 4.0 * lon_deg
    ha = math.radians(tst / 4.0 - 180.0)
    lat = math.radians(lat_deg)
    cos_zenith = (math.sin(lat) * math.sin(decl)
                  + math.cos(lat) * math.cos(decl) * math.cos(ha))
    cos_zenith = max(-1.0, min(1.0, cos_zenith))
    return 90.0 - math.degrees(math.acos(cos_zenith))
