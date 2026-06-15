"""forecast.solar fetch + parsing. Pure parse helpers + a fetch wrapper."""
import json
import logging
import urllib.parse
import urllib.request

_log = logging.getLogger(__name__)


def remaining_kwh(result: dict, now_str: str) -> float:
    """Sum TODAY's watt_hours_period for timestamps >= now_str, in kWh.

    forecast.solar returns today AND tomorrow; we bound to now_str's date so the
    'remaining today' figure can't be inflated by tomorrow's forecast (which would
    wrongly make every evening look sunny and lower the threshold).
    Timestamps are 'YYYY-MM-DD HH:MM:SS' (lexicographically sortable)."""
    periods = result.get("watt_hours_period", {})
    today = now_str[:10]
    wh = sum(v for ts, v in periods.items() if ts[:10] == today and ts >= now_str)
    return wh / 1000.0


def day_kwh(result: dict, day_str: str) -> float:
    return result.get("watt_hours_day", {}).get(day_str, 0.0) / 1000.0


def fetch(lat, lon, decl, az, kwp, now_str, day_str, timeout=15.0):
    """GET forecast.solar estimate for ONE roof plane.
    Returns (expected_kwh_day, expected_kwh_remaining) or None."""
    url = f"https://api.forecast.solar/estimate/{lat}/{lon}/{decl}/{az}/{kwp}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.load(resp)
        result = data["result"]
        day = day_kwh(result, day_str)
        rem = remaining_kwh(result, now_str)
        return day, min(rem, day)   # remaining-today can never exceed today's total
    except Exception:
        _log.warning("forecast.solar fetch/parse failed for plane decl=%s az=%s kwp=%s",
                     decl, az, kwp, exc_info=True)
        return None


def fetch_all(lat, lon, planes, now_str, day_str, timeout=15.0):
    """Query forecast.solar per roof plane and SUM (e.g. East+West split arrays).

    planes: list of (declination, azimuth, kwp). Returns
    (day_kwh_total, remaining_kwh_total) summed over all planes that responded,
    or None if EVERY plane query failed (so the controller keeps its last value)."""
    total_day = total_remaining = 0.0
    any_ok = False
    for decl, az, kwp in planes:
        r = fetch(lat, lon, decl, az, kwp, now_str, day_str, timeout)
        if r is not None:
            total_day += r[0]
            total_remaining += r[1]
            any_ok = True
    return (total_day, total_remaining) if any_ok else None


# ── Open-Meteo GTI forecast (primary source — far more accurate than the free forecast.solar
#    tier, no rate limit, self-calibrated against actual production) ─────────────────────────
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"


def open_meteo_gti_url(lat, lon, tilt, az, past_days, forecast_days, tz="UTC"):
    return (f"{OPEN_METEO}?latitude={lat}&longitude={lon}"
            f"&hourly=global_tilted_irradiance&tilt={tilt}&azimuth={az}"
            f"&timezone={urllib.parse.quote(tz, safe='')}&past_days={past_days}&forecast_days={forecast_days}")


def fetch_gti(lat, lon, tilt, az, past_days=14, forecast_days=2, timeout=20.0, tz="UTC"):
    """Hourly global tilted irradiance (W/m²) for one plane. One call covers past + future so it
    serves BOTH calibration and forecast. Returns [(local_ts 'YYYY-MM-DDTHH:MM', gti), ...] or None."""
    try:
        with urllib.request.urlopen(
                open_meteo_gti_url(lat, lon, tilt, az, past_days, forecast_days, tz), timeout=timeout) as resp:
            d = json.load(resp)
        h = d["hourly"]
        return [(t, g) for t, g in zip(h["time"], h["global_tilted_irradiance"], strict=False) if g is not None]
    except Exception:
        _log.warning("Open-Meteo GTI fetch/parse failed for plane tilt=%s az=%s",
                     tilt, az, exc_info=True)
        return None


def gti_day_kwh_per_m2(hourly, day_str):
    """Sum GTI (Wh/m²) for one calendar day -> kWh/m². (1 kWp @ 1000 W/m² = 1 kW.)"""
    return sum(g for t, g in hourly if t[:10] == day_str) / 1000.0


def gti_remaining_kwh_per_m2(hourly, now_str):
    """Today's GTI from now_str ('YYYY-MM-DD HH:MM:SS') onward -> kWh/m²."""
    day, hh = now_str[:10], now_str[11:13]
    return sum(g for t, g in hourly if t[:10] == day and t[11:13] >= hh) / 1000.0


def fit_pr(potential_by_day, actual_by_day, lo=0.4, hi=0.85, min_days=3):
    """Self-calibrated PV performance ratio = Σ actual_kWh / Σ potential_kWh, but ONLY over days
    whose per-day ratio falls in the plausible band [lo, hi]. That filter rejects the two ways a
    raw ratio lies: too LOW (partial first day of monitoring, inverter downtime/curtailment, or
    near-horizon shading the GTI model doesn't see) and too HIGH (Open-Meteo under-modelled the
    irradiance on a cloudy day). potential_by_day[d] = Σ_planes gti_day(d)·kWp (= kWh at PR=1).
    Returns None when fewer than `min_days` clean days — caller then keeps the configured PR."""
    clean = [(potential_by_day[d], actual_by_day[d]) for d in actual_by_day
             if potential_by_day.get(d, 0) > 0 and actual_by_day.get(d, 0) > 0
             and lo <= actual_by_day[d] / potential_by_day[d] <= hi]
    if len(clean) < min_days:
        return None
    pot = sum(p for p, _ in clean)
    return sum(a for _, a in clean) / pot if pot > 0 else None


def pv_estimate(hourly_by_plane, now_str, day_str, current_pr, actual_by_day):
    """Pure: from per-plane hourly GTI (list of (hourly, kwp)) + actual daily production, return
    (day_kwh, remaining_kwh, pr). PR is re-fit from the past days if possible, else `current_pr`."""
    all_days = {t[:10] for h, _ in hourly_by_plane for t, _ in h}
    potential = {d: sum(gti_day_kwh_per_m2(h, d) * kwp for h, kwp in hourly_by_plane) for d in all_days}
    pr = fit_pr(potential, actual_by_day)
    if pr is None:
        pr = current_pr
    day = sum(gti_day_kwh_per_m2(h, day_str) * kwp for h, kwp in hourly_by_plane) * pr
    rem = sum(gti_remaining_kwh_per_m2(h, now_str) * kwp for h, kwp in hourly_by_plane) * pr
    return day, min(rem, day), pr
