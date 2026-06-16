from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from src.sun import sun_elevation, sun_window


def _utc(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=UTC)


def test_summer_local_noon_is_high():
    e = sun_elevation(52.52, 13.40, _utc(2026, 6, 21, 11))
    assert 55 < e < 65


def test_local_midnight_is_negative():
    e = sun_elevation(52.52, 13.40, _utc(2026, 6, 21, 23))
    assert e < 0


def test_equator_noon_near_equinox_is_near_zenith():
    e = sun_elevation(0.0, 0.0, _utc(2026, 3, 20, 12))
    assert e > 85


def test_returns_float_degrees():
    assert isinstance(sun_elevation(0.0, 0.0, _utc(2026, 3, 20, 12)), float)


def test_sun_window_berlin_summer():
    day = datetime(2026, 6, 21, tzinfo=ZoneInfo("Europe/Berlin"))
    rise, sset = sun_window(52.52, 13.40, day, 3.0)
    assert rise is not None and sset is not None
    assert rise.hour < 7 and sset.hour > 19       # a long summer day
    assert rise < sset
    # the window edges sit at ~the threshold elevation
    assert abs(sun_elevation(52.52, 13.40, rise.astimezone(UTC)) - 3.0) < 1.5


def test_sun_window_polar_night_is_none():
    day = datetime(2026, 12, 21, tzinfo=ZoneInfo("UTC"))
    rise, sset = sun_window(78.0, 15.0, day, 3.0)   # Svalbard, deep winter: sun never up
    assert rise is None and sset is None
