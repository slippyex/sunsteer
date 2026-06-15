from src.forecast import day_kwh, remaining_kwh

RESULT = {
    "watt_hours_period": {
        "2026-06-06 08:00:00": 1000,
        "2026-06-06 12:00:00": 4000,
        "2026-06-06 16:00:00": 3000,
        "2026-06-06 20:00:00": 500,
        # forecast.solar always returns tomorrow too — must NOT count toward "remaining today":
        "2026-06-07 08:00:00": 2000,
        "2026-06-07 12:00:00": 9000,
    },
    "watt_hours_day": {"2026-06-06": 8500, "2026-06-07": 11000},
}

def test_remaining_sums_future_periods_to_kwh():
    assert remaining_kwh(RESULT, "2026-06-06 13:00:00") == 3.5

def test_remaining_before_sunrise_is_full_day_minus_nothing():
    assert remaining_kwh(RESULT, "2026-06-06 06:00:00") == 8.5

def test_remaining_after_sunset_excludes_tomorrow():
    # evening: today's remaining is 0, tomorrow's 11 kWh must be ignored
    assert remaining_kwh(RESULT, "2026-06-06 23:00:00") == 0.0

def test_day_kwh_for_today():
    assert day_kwh(RESULT, "2026-06-06") == 8.5


def test_fetch_all_sums_planes(monkeypatch):
    import src.forecast as f
    calls = []
    def fake_fetch(lat, lon, decl, az, kwp, now_str, day_str, timeout=15.0):
        calls.append((decl, az, kwp))
        return {(-90): (3.0, 1.0), (90): (4.0, 2.0)}[az]
    monkeypatch.setattr(f, "fetch", fake_fetch)
    day, remaining = f.fetch_all("49", "7", [(28, -90, 7.26), (28, 90, 7.92)], "n", "d")
    assert day == 7.0 and remaining == 3.0          # summed across both planes
    assert calls == [(28, -90, 7.26), (28, 90, 7.92)]

def test_fetch_all_partial_failure_sums_the_rest(monkeypatch):
    import src.forecast as f
    monkeypatch.setattr(f, "fetch", lambda *a, **k: None if a[3] == -90 else (4.0, 2.0))
    assert f.fetch_all("49", "7", [(28, -90, 7.26), (28, 90, 7.92)], "n", "d") == (4.0, 2.0)

def test_fetch_all_all_failed_returns_none(monkeypatch):
    import src.forecast as f
    monkeypatch.setattr(f, "fetch", lambda *a, **k: None)
    assert f.fetch_all("49", "7", [(28, -90, 7.26), (28, 90, 7.92)], "n", "d") is None


# ── Open-Meteo GTI forecast ────────────────────────────────────────────────
from src.forecast import fit_pr, gti_day_kwh_per_m2, gti_remaining_kwh_per_m2, pv_estimate

# one plane's hourly GTI (W/m2): yesterday (full) + today (partial day so far)
GTI = [
    ("2026-06-08T10:00", 500), ("2026-06-08T12:00", 800), ("2026-06-08T14:00", 600),
    ("2026-06-09T10:00", 400), ("2026-06-09T12:00", 1000), ("2026-06-09T14:00", 600),
]

def test_gti_day_kwh_sums_one_day():
    assert gti_day_kwh_per_m2(GTI, "2026-06-08") == 1.9      # (500+800+600)/1000
    assert gti_day_kwh_per_m2(GTI, "2026-06-09") == 2.0      # (400+1000+600)/1000

def test_gti_remaining_from_now():
    # from 12:00 today -> 12:00 + 14:00 = 1600 Wh/m2
    assert gti_remaining_kwh_per_m2(GTI, "2026-06-09 12:00:00") == 1.6

def test_fit_pr_aggregates_in_band_days():
    pot = {"d1": 10.0, "d2": 20.0, "d3": 10.0}
    act = {"d1": 7.0, "d2": 14.0, "d3": 7.0}        # all ratio 0.70 -> 28/40
    assert fit_pr(pot, act) == 0.7

def test_fit_pr_filters_low_and_high_outliers():
    # d1 partial-day (0.08) + d4 GTI-underestimate (0.99) dropped; only d2,d3 (in band) -> <3 -> None
    pot = {"d1": 81.0, "d2": 113.0, "d3": 10.0, "d4": 50.0}
    act = {"d1": 6.3, "d2": 75.0, "d3": 7.0, "d4": 49.5}
    assert fit_pr(pot, act) is None
    pot["d5"] = 20.0; act["d5"] = 14.0              # 3rd in-band day (0.70) -> now fits
    pr = fit_pr(pot, act)
    assert pr is not None and 0.4 <= pr <= 0.85

def test_fit_pr_none_when_too_few_days():
    assert fit_pr({"d1": 10.0}, {"d1": 7.0}) is None  # min_days=3

# 3 complete past days (each 1.0 kWh/m²) + today (1.0 so far), one plane
GTI3 = [
    ("2026-06-06T11:00", 1000), ("2026-06-07T11:00", 1000), ("2026-06-08T11:00", 1000),
    ("2026-06-09T10:00", 600), ("2026-06-09T12:00", 400),
]

def test_pv_estimate_calibrates_and_scales():
    # 2 planes (kWp 1 each) -> potential per past day = 1.0*2 = 2.0 kWh; actual 1.0 -> PR = 0.5.
    # today potential = 1.0*2 = 2.0 -> day = 2.0*0.5 = 1.0 kWh; remaining from 11:00 = 0.4*2*0.5.
    actual = {"2026-06-06": 1.0, "2026-06-07": 1.0, "2026-06-08": 1.0}
    day, rem, pr = pv_estimate([(GTI3, 1.0), (GTI3, 1.0)], "2026-06-09 11:00:00", "2026-06-09",
                               current_pr=0.7, actual_by_day=actual)
    assert pr == 0.5
    assert day == 1.0 and rem == 0.4       # remaining: 12:00 GTI 400 -> 0.4 kWh/m² *2 *0.5

def test_pv_estimate_keeps_current_pr_without_history():
    day, rem, pr = pv_estimate([(GTI3, 1.0)], "2026-06-09 11:00:00", "2026-06-09",
                               current_pr=0.7, actual_by_day={})   # no actuals -> keep 0.7
    assert pr == 0.7 and round(day, 2) == 0.7


from src.forecast import open_meteo_gti_url


def test_gti_url_uses_supplied_timezone():
    url = open_meteo_gti_url(50.0, 8.0, 30, 0, 14, 2, tz="America/New_York")
    assert "timezone=America%2FNew_York" in url


def test_gti_url_defaults_to_utc():
    url = open_meteo_gti_url(50.0, 8.0, 30, 0, 14, 2)
    assert "timezone=UTC" in url
