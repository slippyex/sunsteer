"""Data access: Prometheus (live) + TimescaleDB (config/log). All read-tolerant:
any failure returns a safe empty/None so the UI degrades instead of 500-ing."""
import json
import time
import urllib.parse
import urllib.request

import psycopg2


def parse_prom_value(resp: dict):
    """First value of a Prometheus instant-vector response, as float, or None."""
    if not isinstance(resp, dict) or resp.get("status") != "success":
        return None
    result = resp.get("data", {}).get("result", [])
    if not result:
        return None
    try:
        return float(result[0]["value"][1])
    except (KeyError, IndexError, ValueError, TypeError):
        return None


def prom_query(base_url, expr, timeout=5.0):
    """Instant query -> float or None."""
    url = f"{base_url.rstrip('/')}/api/v1/query?" + urllib.parse.urlencode({"query": expr})
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return parse_prom_value(json.load(r))
    except Exception:
        return None


def prom_query_range(base_url, expr, start, end, step, timeout=8.0):
    """Range query -> list of [unix_ts, float]. Empty list on failure."""
    q = urllib.parse.urlencode({"query": expr, "start": start, "end": end, "step": step})
    url = f"{base_url.rstrip('/')}/api/v1/query_range?{q}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = json.load(r)
        res = data.get("data", {}).get("result", [])
        if not res:
            return []
        return [[float(ts), float(v)] for ts, v in res[0]["values"]]
    except Exception:
        return []


def connect(host, port, db, user, password):
    conn = psycopg2.connect(host=host, port=port, dbname=db, user=user, password=password)
    conn.autocommit = True
    return conn


_CONFIG_COLS = ["mode", "manual_relay_on", "threshold_base_w", "threshold_min_w",
                "threshold_off_w", "on_delay_cycles", "off_delay_cycles", "min_runtime_s",
                "min_offtime_s", "adapt_enabled", "full_sun_ref_kwh",
                "feed_in_tariff_eur_kwh", "grid_price_eur_kwh", "wp_nominal_power_w"]


def load_config(conn):
    with conn.cursor() as cur:
        cur.execute(f"SELECT {', '.join(_CONFIG_COLS)} FROM control_config WHERE id = 1")
        row = cur.fetchone()
    return dict(zip(_CONFIG_COLS, row)) if row else {}


def save_settings(conn, clean: dict):
    cols = [c for c in _CONFIG_COLS if c in clean]
    sets = ", ".join(f"{c} = %s" for c in cols) + ", updated_at = now()"
    with conn.cursor() as cur:
        cur.execute(f"UPDATE control_config SET {sets} WHERE id = 1", [clean[c] for c in cols])


def save_mode(conn, mode, manual_relay_on):
    with conn.cursor() as cur:
        cur.execute("UPDATE control_config SET mode=%s, manual_relay_on=%s, updated_at=now() "
                    "WHERE id=1", (mode, manual_relay_on))


def recent_decisions(conn, limit=30):
    """Switching history derived from the ACTUAL relay (heatpump table = ground truth), enriched
    with the controller's reason from decision_log. This way relay changes WE didn't command —
    the Shelly 60s auto-off watchdog (e.g. during a deploy) or the SMA/ennexOS dual-control —
    still show up (the controller's decision_log only records its own switches), so there are no
    invisible 'two EIN in a row' gaps. Unmatched transitions are labelled 'extern'."""
    with conn.cursor() as cur:
        cur.execute(
            "WITH trans AS ("
            "  SELECT time, relay_on FROM ("
            "    SELECT time, relay_on, lag(relay_on) OVER (ORDER BY time) prev"
            "    FROM heatpump WHERE time > now() - interval '7 days') s"
            "  WHERE relay_on IS DISTINCT FROM prev AND prev IS NOT NULL) "
            "SELECT t.time, d.mode, d.surplus_w, d.effective_threshold_w, t.relay_on, d.reason "
            "FROM trans t "
            "LEFT JOIN LATERAL ("
            "  SELECT mode, surplus_w, effective_threshold_w, reason FROM decision_log dl "
            "  WHERE dl.relay_target = t.relay_on "
            "    AND dl.time BETWEEN t.time - interval '90 seconds' AND t.time + interval '90 seconds' "
            "  ORDER BY abs(extract(epoch FROM dl.time - t.time)) LIMIT 1) d ON true "
            "ORDER BY t.time DESC LIMIT %s", (limit,))
        rows = cur.fetchall()
    return [{"time": t, "mode": m or "auto",
             "surplus_w": s, "threshold_w": th,
             "action": "switched_on" if relay_on else "switched_off",
             "reason": r or "extern (Watchdog/SMA)"}
            for (t, m, s, th, relay_on, r) in rows]


def solar_forecast_today(conn):
    """Latest forecast.solar values for today: expected day kWh + remaining. {} on error/none."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT expected_kwh_day, expected_kwh_remaining FROM solar_forecast "
                        "WHERE forecast_date = current_date ORDER BY time DESC LIMIT 1")
            row = cur.fetchone()
    except Exception:
        return {}
    if not row:
        return {}
    return {"expected_kwh_day": float(row[0] or 0), "expected_kwh_remaining": float(row[1] or 0)}


# window -> days back before today (incl. today). Whitelisted, so safe to bind as ::interval.
_EFF_WINDOWS = {"7d": 6, "30d": 29, "90d": 89, "365d": 364}


def effectiveness_daily(conn, window, nominal_w, grid_price, feed_in):
    """Per-day WP self-used estimate over the window incl. today. Run-time from the raw heatpump
    table (count of relay_on rows / 60, 1-min cadence) × nominal power. Tolerant -> [] on error."""
    days_back = _EFF_WINDOWS.get(window, _EFF_WINDOWS["7d"])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT date_trunc('day', time) AS day, "
                "       count(*) FILTER (WHERE relay_on)/60.0 AS runtime_h "
                "FROM heatpump WHERE time >= date_trunc('day', now()) - %s::interval "
                "GROUP BY day ORDER BY day", (f"{days_back} days",))
            rows = cur.fetchall()
    except Exception:
        return []
    nominal_kw = (nominal_w or 0) / 1000.0
    diff = (grid_price or 0) - (feed_in or 0)
    out = []
    for day, runtime_h in rows:
        rh = float(runtime_h or 0)
        kwh = nominal_kw * rh
        out.append({"day": day.strftime("%d.%m"), "runtime_h": round(rh, 2),
                    "kwh": round(kwh, 2), "eur": round(kwh * diff, 2)})
    return out


# ── WP history (control-ui charts): time-bucketed series per window ─────────
def _num(x):
    return None if x is None else float(x)


# window -> (lookback interval, bucket width). Whitelisted, so safe to bind as ::interval.
_WP_WINDOWS = {
    "24h":  ("24 hours", "10 minutes"),
    "7d":   ("7 days", "1 hour"),
    "30d":  ("30 days", "6 hours"),
    "90d":  ("90 days", "12 hours"),     # Quartal
    "365d": ("365 days", "1 day"),       # Jahr (= Retention-Horizont)
}


def _wp_temps(conn, interval, bucket):
    """Temperatures (WW/buffer/supply/outside), bucket-averaged. Reliable ViCare telemetry."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT time_bucket(%s::interval, time) AS t, "
                "round(avg(dhw_temp_c)::numeric,1), round(avg(buffer_temp_c)::numeric,1), "
                "round(avg(supply_temp_c)::numeric,1), round(avg(outside_temp_c)::numeric,1) "
                "FROM heatpump_vicare WHERE time > now() - %s::interval "
                "GROUP BY t ORDER BY t", (bucket, interval))
            return [{"t": t.isoformat(), "dhw": _num(a), "buffer": _num(b),
                     "supply": _num(c), "outside": _num(d)} for t, a, b, c, d in cur.fetchall()]
    except Exception:
        return []


def _wp_run(conn, interval, bucket):
    """Surplus vs WP run-state: avg surplus and relay on-fraction per bucket, merged by time."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT time_bucket(%s::interval, time) AS t, round(avg(surplus_w)::numeric,0) "
                "FROM energy_meter WHERE time > now() - %s::interval GROUP BY t ORDER BY t",
                (bucket, interval))
            surplus = {t.isoformat(): _num(v) for t, v in cur.fetchall()}
            cur.execute(
                "SELECT time_bucket(%s::interval, time) AS t, "
                "round(avg(CASE WHEN relay_on THEN 1 ELSE 0 END)::numeric,2) "
                "FROM heatpump WHERE time > now() - %s::interval GROUP BY t ORDER BY t",
                (bucket, interval))
            onf = {t.isoformat(): _num(v) for t, v in cur.fetchall()}
        return [{"t": k, "surplus": surplus.get(k), "on_frac": onf.get(k)}
                for k in sorted(set(surplus) | set(onf))]
    except Exception:
        return []


def _wp_comp(conn, interval, bucket):
    """Compressor speed (avg rps) + starts-per-bucket (delta of the cumulative counter)."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT time_bucket(%s::interval, time) AS t, "
                "round(avg(compressor_speed_rps)::numeric,1), max(compressor_starts) "
                "FROM heatpump_vicare WHERE time > now() - %s::interval GROUP BY t ORDER BY t",
                (bucket, interval))
            rows = cur.fetchall()
    except Exception:
        return []
    out, prev = [], None
    for t, rps, starts_cum in rows:
        sc = _num(starts_cum)
        delta = None
        if sc is not None and prev is not None:
            delta = sc - prev if sc >= prev else sc   # counter reset -> use current count
        if sc is not None:
            prev = sc
        out.append({"t": t.isoformat(), "rps": _num(rps), "starts": delta})
    return out


def _wp_eff(conn, interval, nominal_w):
    """Per-day estimated WP energy (run-time x nominal, since the Shelly can't meter) + SCOP.
    Both are approximate — run-time is solid, ViCare energy/SCOP lag ~1-2 days."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT date_trunc('day', time) AS day, count(*) FILTER (WHERE relay_on)/60.0 "
                "FROM heatpump WHERE time > now() - %s::interval GROUP BY day ORDER BY day",
                (interval,))
            run = {d.date(): float(h or 0) for d, h in cur.fetchall()}
            cur.execute(
                "SELECT time_bucket('1 day', time) AS day, round(avg(scop_total)::numeric,2) "
                "FROM heatpump_vicare WHERE time > now() - %s::interval GROUP BY day ORDER BY day",
                (interval,))
            scop = {d.date(): _num(s) for d, s in cur.fetchall()}
    except Exception:
        return []
    nominal_kw = (nominal_w or 0) / 1000.0
    return [{"day": d.strftime("%d.%m"), "kwh": round(run.get(d, 0) * nominal_kw, 2),
             "scop": scop.get(d)} for d in sorted(set(run) | set(scop))]


def wp_savings(conn, window, nominal_w, grid_price, feed_in):
    """Per-day money saved by steering PV surplus into the WP (SG-Ready), from REAL data.

    Per minute the WP ran, the PV-covered share of its (estimated) draw is
    clamp(surplus_w + nominal, 0, nominal)/nominal — surplus_w is measured downstream of the
    WP, so +nominal reconstructs the surplus-without-WP. Each PV-covered kWh saves
    (grid_price - feed_in): without SG-Ready it would have been exported at feed_in and bought
    back for the WP at grid_price. Estimate (no WP meter) + upper bound (ignores coincidental
    overlap that would happen without SG-Ready). Tolerant -> [] on error."""
    win = window if window in _WP_WINDOWS else "24h"
    interval = _WP_WINDOWS[win][0]
    n = nominal_w or 0
    try:
        with conn.cursor() as cur:
            cur.execute(
                "WITH wp AS (SELECT time_bucket('1 minute'::interval, time) m, bool_or(relay_on) on_ "
                "  FROM heatpump WHERE time > now() - %s::interval GROUP BY m), "
                "sm AS (SELECT time_bucket('1 minute'::interval, time) m, avg(surplus_w) surplus "
                "  FROM energy_meter WHERE time > now() - %s::interval GROUP BY m) "
                "SELECT date_trunc('day', wp.m) AS day, "
                "  sum(CASE WHEN wp.on_ THEN least(greatest(sm.surplus + %s, 0), %s) ELSE 0 END)/60000.0 AS pv_kwh, "
                "  sum(CASE WHEN wp.on_ THEN %s - least(greatest(sm.surplus + %s, 0), %s) ELSE 0 END)/60000.0 AS grid_kwh "
                "FROM wp JOIN sm USING (m) GROUP BY day ORDER BY day",
                (interval, interval, n, n, n, n, n))
            rows = cur.fetchall()
    except Exception:
        return []
    diff = (grid_price or 0) - (feed_in or 0)
    out, cum = [], 0.0
    for day, pv, grid in rows:
        pv, grid = float(pv or 0), float(grid or 0)
        cum += pv * diff
        out.append({"day": day.strftime("%d.%m"), "pv_kwh": round(pv, 2), "grid_kwh": round(grid, 2),
                    "saved_eur": round(pv * diff, 2), "cum_eur": round(cum, 2)})
    return out


def wp_timeline_today(conn, start_epoch):
    """Relay on/off since local midnight from the heatpump table (Shelly-sourced, 1-min). Solid
    and independent of controller restarts — the Prometheus gauge has one series per pod, so a
    day with restarts breaks the old range-query timeline. Returns [[unix_ts, 0|1], ...] at
    5-min buckets to match the timeline renderer. Tolerant -> [] on error."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT extract(epoch FROM time_bucket('5 minutes'::interval, time))::bigint AS t, "
                "  CASE WHEN avg(CASE WHEN relay_on THEN 1 ELSE 0 END) >= 0.5 THEN 1 ELSE 0 END "
                "FROM heatpump WHERE time >= to_timestamp(%s) GROUP BY t ORDER BY t",
                (start_epoch,))
            return [[int(t), int(v)] for t, v in cur.fetchall()]
    except Exception:
        return []


def _wp_strings(conn, interval, bucket):
    """Inverter per-MPPT DC power (string A/B = the two array orientations), bucket-averaged."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT time_bucket(%s::interval, time) AS t, round(avg(dc_power_a_w)::numeric,0), "
                "round(avg(dc_power_b_w)::numeric,0) FROM energy_meter WHERE time > now() - %s::interval "
                "GROUP BY t ORDER BY t", (bucket, interval))
            return [{"t": t.isoformat(), "a": _num(a), "b": _num(b)} for t, a, b in cur.fetchall()]
    except Exception:
        return []


def wp_history(conn, window, nominal_w=2000):
    """Bucketed WP history for the given window (24h/7d/30d). Each section is independently
    tolerant -> a failing query yields [] for that chart, not a 500."""
    win = window if window in _WP_WINDOWS else "24h"
    interval, bucket = _WP_WINDOWS[win]
    return {"window": win,
            "temps": _wp_temps(conn, interval, bucket),
            "run": _wp_run(conn, interval, bucket),
            "comp": _wp_comp(conn, interval, bucket),
            "eff": _wp_eff(conn, interval, nominal_w),
            "strings": _wp_strings(conn, interval, bucket)}


# ── Open-Meteo weather (informational, cached) ─────────────────────────────
# WMO weather codes -> (icon, German text)
_WMO = {
    0: ("☀", "Klar"), 1: ("🌤", "Heiter"), 2: ("⛅", "Teils bewölkt"), 3: ("☁", "Bedeckt"),
    45: ("🌫", "Nebel"), 48: ("🌫", "Reifnebel"),
    51: ("🌦", "Leichter Niesel"), 53: ("🌦", "Niesel"), 55: ("🌧", "Starker Niesel"),
    61: ("🌧", "Leichter Regen"), 63: ("🌧", "Regen"), 65: ("🌧", "Starker Regen"),
    71: ("🌨", "Leichter Schnee"), 73: ("🌨", "Schnee"), 75: ("❄", "Starker Schnee"),
    80: ("🌦", "Schauer"), 81: ("🌧", "Schauer"), 82: ("⛈", "Heftige Schauer"),
    95: ("⛈", "Gewitter"), 96: ("⛈", "Gewitter + Hagel"), 99: ("⛈", "Schweres Gewitter"),
}


def wmo(code):
    return _WMO.get(code, ("•", "—"))


def parse_open_meteo(data: dict) -> dict:
    """Open-Meteo forecast response -> {current, today, tomorrow, hourly}. Tolerant of gaps."""
    cur = data.get("current") or {}
    cur_icon, cur_text = wmo(cur.get("weather_code"))
    daily = data.get("daily") or {}

    def day(i):
        try:
            icon, text = wmo(daily["weather_code"][i])
            return {"tmin": round(daily["temperature_2m_min"][i]),
                    "tmax": round(daily["temperature_2m_max"][i]),
                    "sun_h": round(daily["sunshine_duration"][i] / 3600.0, 1),
                    "icon": icon, "text": text, "code": daily["weather_code"][i]}
        except (KeyError, IndexError, TypeError):
            return None

    hourly = data.get("hourly") or {}
    return {
        # `code` lets the UI translate the condition at render time (the cache is
        # language-neutral); `text` stays the German default/fallback.
        "current": {"temp": cur.get("temperature_2m"), "cloud": cur.get("cloud_cover"),
                    "icon": cur_icon, "text": cur_text, "code": cur.get("weather_code")},
        "today": day(0), "tomorrow": day(1),
        "hourly": {"time": hourly.get("time", []),
                   "temp": hourly.get("temperature_2m", []),
                   "cloud": hourly.get("cloud_cover", [])},
    }


_meteo_cache = {"ts": 0.0, "data": None}


def open_meteo(lat, lon, tz, ttl=900, timeout=8.0):
    """Fetch + parse Open-Meteo, cached for `ttl` s (weather changes slowly).
    On error returns the last good value (or None)."""
    now = time.time()
    if _meteo_cache["data"] is not None and now - _meteo_cache["ts"] < ttl:
        return _meteo_cache["data"]
    q = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "timezone": tz, "forecast_days": 2,
        "current": "temperature_2m,cloud_cover,weather_code",
        "hourly": "temperature_2m,cloud_cover",
        "daily": "temperature_2m_max,temperature_2m_min,sunshine_duration,weather_code",
    })
    try:
        with urllib.request.urlopen(f"https://api.open-meteo.com/v1/forecast?{q}", timeout=timeout) as r:
            parsed = parse_open_meteo(json.load(r))
        _meteo_cache.update(ts=now, data=parsed)
        return parsed
    except Exception:
        return _meteo_cache["data"]


def controller_status(url, timeout=4.0):
    """GET the surplus-controller /status JSON. Returns dict or None."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.load(r)
    except Exception:
        return None


_EMPTY_SUMMARY = {"prod_kwh": 0.0, "export_kwh": 0.0, "import_kwh": 0.0,
                  "self_consumption": 0.0, "wp_runtime_h": 0.0, "wp_runtime_total_h": 0.0}


def today_summary(conn):
    """kWh balance + WP relay run-time (today & cumulative) from TimescaleDB.
    Tolerant -> a fully-populated zero dict on error (never {}), so the balance
    template can render unconditionally and the HTMX card never 500s on a DB hiccup.

    WP energy is NOT measured (the Shelly is an SG-Ready signal contact, power_w==0),
    so we return relay run-time only; the caller turns it into estimated kWh via
    wp_nominal_power_w. Run-time counts heatpump rows where relay_on, assuming the
    exporter's 1-minute write cadence (TSDB_FLUSH_SECONDS=60) — the /60 skews if that
    interval changes. The production/export/import counters are cadence-independent."""
    sql = """
      SELECT
        (SELECT max(production_kwh_total)-min(production_kwh_total) FROM energy_meter
           WHERE production_kwh_total IS NOT NULL AND time >= date_trunc('day', now())) AS prod_kwh,
        (SELECT max(export_kwh_total)-min(export_kwh_total) FROM energy_meter
           WHERE time >= date_trunc('day', now())) AS export_kwh,
        (SELECT max(import_kwh_total)-min(import_kwh_total) FROM energy_meter
           WHERE time >= date_trunc('day', now())) AS import_kwh,
        (SELECT coalesce(count(*) FILTER (WHERE relay_on),0)/60.0 FROM heatpump
           WHERE time >= date_trunc('day', now())) AS wp_runtime_h,
        (SELECT coalesce(count(*) FILTER (WHERE relay_on),0)/60.0 FROM heatpump) AS wp_runtime_total_h
    """
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            prod, exp, imp, runtime, runtime_total = cur.fetchone()
    except Exception:
        return dict(_EMPTY_SUMMARY)
    prod = float(prod or 0)
    sc = ((prod - float(exp or 0)) / prod) if prod > 0 else 0.0
    return {"prod_kwh": prod, "export_kwh": float(exp or 0), "import_kwh": float(imp or 0),
            "self_consumption": max(0.0, min(1.0, sc)),
            "wp_runtime_h": float(runtime or 0), "wp_runtime_total_h": float(runtime_total or 0)}
