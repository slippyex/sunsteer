from datetime import UTC, datetime

from src.sun import sun_elevation


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
