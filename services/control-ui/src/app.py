"""control-ui: FastAPI + Jinja2 + HTMX. Live from Prometheus, config/log from TimescaleDB."""
import base64
import binascii
import logging
import os
import secrets
import time
import urllib.parse
from contextlib import contextmanager, suppress
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import explain, i18n, sources, validation

log = logging.getLogger(__name__)


def _pos_int(name, default, hi=65535):
    """Tolerant parse for the DB port: a typo'd value falls back to the default instead of
    crashing the UI at import."""
    try:
        v = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return v if 1 <= v <= hi else default


PROM = os.environ.get("PROMETHEUS_URL", "http://prometheus:9090")
GRAFANA = os.environ.get("GRAFANA_URL", "")        # empty -> Grafana link hidden in the UI
WEATHER_LOCATION = os.environ.get("WEATHER_LOCATION", "")  # empty -> weather panel shows just "Weather"
HEATPUMP_LABEL = os.environ.get("HEATPUMP_LABEL", "").strip()  # empty -> vendor tag hidden in heat-pump card

# Open-Meteo weather widget — reuse the PV array location
WLAT = os.environ.get("PV_LAT")                    # required — validated below
WLON = os.environ.get("PV_LON")                    # required — validated below
WTZ = os.environ.get("PV_TZ", "UTC")
CONTROLLER_STATUS_URL = os.environ.get(
    "CONTROLLER_STATUS_URL", "http://surplus-controller:9124/status")
DB = dict(host=os.environ.get("DB_HOST", "timescaledb"),
          port=_pos_int("DB_PORT", 5432), db=os.environ.get("DB_NAME", "energy"),
          user=os.environ.get("DB_USER"), password=os.environ.get("DB_PASS"))

REQUIRED_ENV = ("PV_LAT", "PV_LON", "DB_USER", "DB_PASS")


def validate_env():
    """Fail fast with one clear message instead of half-starting against nothing."""
    missing = [n for n in REQUIRED_ENV if not os.environ.get(n)]
    if missing:
        raise SystemExit("control-ui: missing required environment variables: "
                         + ", ".join(missing))
    # The k8s example manifests ship CHANGE_ME placeholders; starting against one (e.g.
    # PV_LAT=CHANGE_ME) is a misconfiguration, not a value — reject it as if it were absent.
    placeholder = [n for n in REQUIRED_ENV if "CHANGE_ME" in os.environ.get(n, "")]
    if placeholder:
        raise SystemExit("control-ui: required environment variables still set to a "
                         "CHANGE_ME placeholder: " + ", ".join(placeholder))


validate_env()

# HTTP Basic gate, FAIL-CLOSED: this UI drives real hardware, so a missing/misconfigured
# ADMIN_PASS must lock the UI down (503), never silently open it. With ADMIN_PASS set the
# browser prompts once and caches creds, so HTMX writes carry them automatically. /healthz
# stays open so the kubelet probe needs no credentials.


def _admin_secret(value):
    """Normalize an ADMIN_USER/ADMIN_PASS env value: blank or a CHANGE_ME k8s placeholder
    (secret.example.yaml ships ADMIN_PASS=CHANGE_ME) is a misconfiguration, not a credential
    — return None so the auth gate stays fail-closed/locked exactly as when it's unset."""
    if not value or "CHANGE_ME" in value:
        return None
    return value


# ADMIN_USER/ADMIN_PASS are NOT in REQUIRED_ENV (the UI may be locked on purpose), so the
# CHANGE_ME rejection there doesn't cover them — sanitize here. An un-edited deploy then
# locks (503) instead of accepting the literal "CHANGE_ME" as a valid password.
ADMIN_USER = _admin_secret(os.environ.get("ADMIN_USER", "admin"))
ADMIN_PASS = _admin_secret(os.environ.get("ADMIN_PASS"))

# CSRF defense: HTTP Basic creds are auto-sent by the browser, so a cross-site POST to
# /control or /settings would otherwise change operating state. Reject state-changing
# requests whose Origin/Referer host doesn't match Host. ALLOWED_ORIGIN lets a reverse
# proxy present a different external host.
def _norm_origin(v):
    """Reduce ALLOWED_ORIGIN to the host[:port] form the Origin/Referer check compares
    against. Accepts either a full URL (https://host:port, as documented) or a bare
    host[:port], so both spellings work."""
    if not v:
        return None
    parts = urllib.parse.urlsplit(v if "://" in v else "//" + v)
    return parts.netloc or None


ALLOWED_ORIGIN = _norm_origin(os.environ.get("ALLOWED_ORIGIN"))

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


def _basic_ok(header):
    if not header or not header.startswith("Basic "):
        return False
    try:
        user, _, pw = base64.b64decode(header[6:]).decode("utf-8").partition(":")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return False
    # Compute BOTH digests before combining: a short-circuiting `and` would skip the password
    # compare on a wrong username, leaking username validity through response timing.
    user_ok = secrets.compare_digest(user, ADMIN_USER)
    pw_ok = secrets.compare_digest(pw, ADMIN_PASS)
    return user_ok and pw_ok


def _origin_ok(request: Request) -> bool:
    """CSRF guard for state-changing requests. If an Origin header is present its host:port
    must match Host; else if a Referer is present its host must match Host. No Origin and no
    Referer (curl/scripts/non-browser) -> allowed. ALLOWED_ORIGIN (reverse proxy) also passes."""
    host = request.headers.get("host")
    allowed = {h for h in (host, ALLOWED_ORIGIN) if h}
    origin = request.headers.get("origin")
    if origin:
        return urllib.parse.urlsplit(origin).netloc in allowed
    referer = request.headers.get("referer")
    if referer:
        return urllib.parse.urlsplit(referer).netloc in allowed
    return True                                  # non-browser client -> no CSRF surface


@app.middleware("http")
async def _auth(request: Request, call_next):
    if request.url.path in ("/healthz", "/readyz") or request.url.path.startswith("/static/"):   # probe + static always open
        return await call_next(request)
    if not ADMIN_PASS or not ADMIN_USER:         # fail-closed: no credentials configured -> locked
        return Response("control-ui gesperrt: ADMIN_PASS nicht konfiguriert", status_code=503)
    if not _basic_ok(request.headers.get("Authorization")):
        return Response("Authentifizierung erforderlich", status_code=401,
                        headers={"WWW-Authenticate": 'Basic realm="control-ui"'})
    if request.method == "POST" and not _origin_ok(request):
        return Response("CSRF: Origin/Referer mismatch", status_code=403)
    return await call_next(request)


def _localtime(dt, fmt="%d.%m %H:%M"):
    """Render a (UTC/aware) datetime in the configured local tz (PV_TZ). '–' if None."""
    if dt is None:
        return "–"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(ZoneInfo(WTZ)).strftime(fmt)


templates.env.filters["localtime"] = _localtime

_MODE_NAME = {0: "paused", 1: "manual", 2: "auto"}

# Power tiles use a 2-min moving average so cloud/load flicker doesn't make the numbers
# jump (display only — the control loop reads the exporter /state raw). States are unaveraged.
# Consumption is computed inline (production - surplus) so the tile works even before the
# energy:consumption_watts recording rule has loaded.
_LIVE = {
    "surplus": "avg_over_time(sma_shm_surplus_watts[2m])",
    "production": "avg_over_time(sma_inverter_ac_power_watts[2m])",
    "consumption": "avg_over_time(sma_inverter_ac_power_watts[2m]) - avg_over_time(sma_shm_surplus_watts[2m])",
    "wp_power": "avg_over_time(surplus_control_wp_estimated_power_watts[2m])",
    "relay": "surplus_control_relay_on", "mode_num": "surplus_control_mode",
    "threshold": "surplus_control_effective_threshold_watts",
    "remaining_kwh": "surplus_control_forecast_remaining_kwh",
    "self_consumption": "energy:self_consumption_ratio", "autarky": "energy:autarky_ratio",
    "shm_last_ts": "sma_shm_last_telegram_timestamp_seconds",
    "shelly_reachable": "shelly_reachable", "inverter_reachable": "sma_inverter_reachable",
    "controller_up": 'up{job="surplus-controller"}',
    "sun_elevation": "surplus_control_sun_elevation_deg",
    "sun_rise_ts": "surplus_control_sun_rise_timestamp_seconds",
    "sun_set_ts": "surplus_control_sun_set_timestamp_seconds",
}


# Heat-pump telemetry (heatpump-exporter -> Prometheus). Slow-changing -> polled 60s.
_HEATPUMP = {
    "dhw_temp": "heatpump_dhw_temp_c", "dhw_target": "heatpump_dhw_target_c",
    "buffer_temp": "heatpump_buffer_temp_c", "outside_temp": "heatpump_outside_temp_c",
    "supply_temp": "heatpump_supply_temp_c",
    "scop": "heatpump_scop_total", "spf": "heatpump_spf_total",
    "comp_speed": "heatpump_compressor_speed_rps", "comp_starts": "heatpump_compressor_starts",
    "comp_hours": "heatpump_compressor_hours",
    "e_total": "heatpump_energy_total_kwh", "e_heating": "heatpump_energy_heating_kwh",
    "e_dhw": "heatpump_energy_dhw_kwh",
    "th_heating": "heatpump_heat_heating_kwh", "th_dhw": "heatpump_heat_dhw_kwh",
    "hr_heating": "heatpump_heatingrod_heating_kwh", "hr_dhw": "heatpump_heatingrod_dhw_kwh",
    "energy_read_at": "heatpump_energy_read_at_timestamp_seconds",
}

# Inverter (SMA Tripower X via Modbus). string a/b = the two MPPT inputs (the East/West arrays).
_INVERTER = {
    "ac_power": "sma_inverter_ac_power_watts", "reachable": "sma_inverter_reachable",
    "dc_power_a": 'sma_inverter_dc_power_watts{string="a"}',
    "dc_power_b": 'sma_inverter_dc_power_watts{string="b"}',
    "dc_v_a": 'sma_inverter_dc_voltage_volts{string="a"}',
    "dc_v_b": 'sma_inverter_dc_voltage_volts{string="b"}',
    "dc_i_a": 'sma_inverter_dc_current_amps{string="a"}',
    "dc_i_b": 'sma_inverter_dc_current_amps{string="b"}',
    "temp": "sma_inverter_temperature_celsius", "op_state": "sma_inverter_operating_state",
    "riso": "sma_inverter_insulation_resistance_ohms",
    "ac_v_l1": 'sma_inverter_ac_voltage_volts{phase="l1"}',
    "ac_v_l2": 'sma_inverter_ac_voltage_volts{phase="l2"}',
    "ac_v_l3": 'sma_inverter_ac_voltage_volts{phase="l3"}',
    "grid_freq": "sma_inverter_grid_frequency_hertz",
}
# SMA operating-state enum -> (i18n key, ok?). Unknown codes shown verbatim via inv_code.
_INV_STATE = {307: ("inv_ok", True), 455: ("inv_warning", False), 35: ("inv_fault", False),
              303: ("inv_off", True), 381: ("inv_stop", False)}


def render(request: Request, template: str, **ctx):
    """TemplateResponse with the request's language + a bound translate function `t` injected,
    so every template (and every include) can call {{ t('key') }}."""
    lang = i18n.get_lang(request)
    ctx.update(request=request, lang=lang,
               t=lambda key, default=None, **fmt: i18n.t(lang, key, default=default, **fmt))
    return templates.TemplateResponse(request, template, ctx)


@app.get("/lang/{code}")
def set_lang(code: str):
    """Switch UI language: persist as cookie and reload. Unknown codes fall back to default."""
    code = code if code in i18n.LANGS else i18n.DEFAULT
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie("lang", code, max_age=365 * 24 * 3600, samesite="lax")
    return resp


def _db():
    return sources.connect(**DB)


@contextmanager
def _db_optional():
    """Yield a DB connection, or None if the DB is unreachable. Every sources.* reader
    tolerates a None/failing connection (returns empty), so handlers degrade to dashes
    instead of 500-ing during a DB outage."""
    conn = None
    try:
        conn = _db()
    except Exception as e:
        log.warning("DB connect failed, degrading to empty reads: %s", e)
        conn = None
    try:
        yield conn
    finally:
        if conn is not None:
            with suppress(Exception):
                conn.close()


def _ratio_pct_ok(v):
    """Self-consumption / autarky are ratios in [0,1]. Their recording rules divide by
    production / consumption, which is ~0 while the inverter is in error (production=0) — the
    division then yields absurd values (e.g. -667 -> -66750 %). Treat anything outside a small
    tolerance as undefined (None -> the UI shows a dash); clamp small averaging overshoots."""
    if v is None or not (-0.1 <= v <= 1.1):   # within a small tolerance -> a real (clampable) ratio
        return None
    return max(0.0, min(1.0, v))


def _live():
    v = {k: sources.prom_query(PROM, e) for k, e in _LIVE.items()}
    # Ratios are only meaningful in [0,1]; guard against the rule dividing by ~0 production.
    v["self_consumption"] = _ratio_pct_ok(v.get("self_consumption"))
    v["autarky"] = _ratio_pct_ok(v.get("autarky"))
    now = time.time()
    v["mode"] = _MODE_NAME.get(int(v["mode_num"]), "?") if v.get("mode_num") is not None else "?"
    v["health"] = {
        "shm": v.get("shm_last_ts") is not None and (now - v["shm_last_ts"] < 120),
        "shelly": v.get("shelly_reachable") == 1,
        "wr": v.get("inverter_reachable") == 1,
        "controller": v.get("controller_up") == 1,
    }
    # Sun / PV window: rise/set are unix ts (NaN -> None via prom parse) -> local HH:MM.
    rts, sts = v.get("sun_rise_ts"), v.get("sun_set_ts")
    v["sun_rise"] = datetime.fromtimestamp(rts, ZoneInfo(WTZ)).strftime("%H:%M") if rts else None
    v["sun_set"] = datetime.fromtimestamp(sts, ZoneInfo(WTZ)).strftime("%H:%M") if sts else None
    v["sun_in_window"] = bool(rts and sts and rts <= now <= sts)
    return v


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    # Use the shared _db_optional() contract like every other read handler: on a DB outage
    # conn is None and the sources.* readers return empty, so the UI degrades to dashes
    # instead of 500-ing.
    with _db_optional() as conn:
        cfg = sources.load_config(conn)
        decisions = sources.recent_decisions(conn)
    return render(request, "index.html", live=_live(), cfg=cfg,
                  decisions=decisions, grafana=GRAFANA, weather_location=WEATHER_LOCATION)


@app.get("/partials/status", response_class=HTMLResponse)
def status(request: Request):
    return render(request, "partials/status.html", live=_live())


@app.post("/control", response_class=HTMLResponse)
def control(request: Request, mode: str = Form(...), manual_relay_on: str = Form(None)):
    if mode not in ("auto", "manual", "paused"):
        mode = "paused"
    # DB down -> skip the write (a write to a dead DB must not silently "succeed"). On a hardware
    # control UI we must NOT echo the requested mode as if applied, or the operator sees a
    # fake-applied highlight. So on db_down render an empty cfg (no active highlight) + a warning.
    with _db_optional() as conn:
        db_down = conn is None
        if not db_down:
            sources.save_mode(conn, mode, manual_relay_on == "on")
    cfg = {} if db_down else {"mode": mode, "manual_relay_on": manual_relay_on == "on"}
    return render(request, "partials/control.html", cfg=cfg, db_down=db_down)


@app.post("/settings", response_class=HTMLResponse)
async def settings(request: Request):
    form = dict(await request.form())
    clean, errors = validation.validate_settings(form)
    saved = False
    db_down = False
    if not errors:
        # Validation passed. DB down -> skip the write (don't fake success) and surface a
        # warning so the operator knows nothing was persisted, returning 200 not 500.
        with _db_optional() as conn:
            db_down = conn is None
            if not db_down:
                sources.save_settings(conn, clean)
                saved = True
    return render(request, "partials/settings.html",
                  form=form, errors=errors, saved=saved, db_down=db_down)


@app.get("/api/series")
def api_series():
    end = int(time.time())
    start = end - 16 * 3600
    # 5-min moving average so the line reads as a trend, not flicker (display only).
    # max() collapses per-pod series into one: controller/exporter restarts create multiple
    # series, and prom_query_range otherwise picks an arbitrary (often dead) one.
    surplus = sources.prom_query_range(PROM, "max(avg_over_time(sma_shm_surplus_watts[5m]))",
                                       start, end, "300")
    threshold = sources.prom_query_range(PROM, "max(surplus_control_effective_threshold_watts)",
                                         start, end, "300")
    return JSONResponse({"surplus": surplus, "threshold": threshold})


@app.get("/partials/weather", response_class=HTMLResponse)
def weather(request: Request):
    return render(request, "partials/weather.html", w=sources.open_meteo(WLAT, WLON, WTZ))


@app.get("/api/weather")
def api_weather():
    w = sources.open_meteo(WLAT, WLON, WTZ)
    return JSONResponse((w or {}).get("hourly", {"time": [], "temp": [], "cloud": []}))


@app.get("/partials/why", response_class=HTMLResponse)
def why(request: Request):
    with _db_optional() as conn:
        cfg = sources.load_config(conn)
    st = sources.controller_status(CONTROLLER_STATUS_URL)
    if st is not None:
        # show the SAME 2-min-smoothed surplus as the status tile, so the "Warum"-card and
        # the Überschuss KPI agree (controller decides on the raw spot value, which flickers
        # around 0 at dawn — displaying that next to the smoothed tile looked inconsistent).
        sm = sources.prom_query(PROM, "avg_over_time(sma_shm_surplus_watts[2m])")
        if sm is not None:
            st = {**st, "surplus_w": sm}
    return render(request, "partials/why.html",
                  why=explain.explain(st, cfg, lang=i18n.get_lang(request)))


@app.get("/partials/ticker", response_class=HTMLResponse)
def ticker(request: Request):
    """Compact status for the sticky scroll bar: WP on/off, smoothed surplus, mode."""
    st = sources.controller_status(CONTROLLER_STATUS_URL)
    sm = sources.prom_query(PROM, "avg_over_time(sma_shm_surplus_watts[2m])")
    t = {"relay_on": bool(st.get("relay_on")) if st else None,
         "mode": st.get("mode") if st else None,
         "surplus_w": round(sm) if sm is not None else None}
    return render(request, "partials/ticker.html", ticker=t)


@app.get("/partials/balance", response_class=HTMLResponse)
def balance(request: Request):
    with _db_optional() as conn:
        cfg = sources.load_config(conn)
        sm = sources.today_summary(conn)
        sm["forecast"] = sources.solar_forecast_today(conn)
    # `or default` (not get's default): a present-but-NULL column yields None, which the
    # default wouldn't catch -> float(None) would 500 this "never-500" card.
    grid = float(cfg.get("grid_price_eur_kwh") or 0.30)
    feed = float(cfg.get("feed_in_tariff_eur_kwh") or 0.08)
    # WP energy is not metered (Shelly is an SG-Ready signal) -> estimate from run-time × nominal power.
    nominal_kw = float(cfg.get("wp_nominal_power_w") or 2000) / 1000.0
    sm["wp_today_kwh"] = round(nominal_kw * sm.get("wp_runtime_h", 0), 2)
    sm["wp_total_kwh"] = round(nominal_kw * sm.get("wp_runtime_total_h", 0), 2)
    sm["eur_today"] = explain.effectiveness_eur(sm["wp_today_kwh"], grid, feed)
    sm["eur_total"] = explain.effectiveness_eur(sm["wp_total_kwh"], grid, feed)
    return render(request, "partials/balance.html", b=sm)


@app.get("/partials/heatpump", response_class=HTMLResponse)
def heatpump(request: Request):
    v = {k: sources.prom_query(PROM, e) for k, e in _HEATPUMP.items()}
    ra = v.get("energy_read_at")
    try:
        v["energy_read_at_str"] = (datetime.fromtimestamp(ra, ZoneInfo(WTZ)).strftime("%d.%m. %H:%M")
                                   if ra else None)
    except (ValueError, OSError, OverflowError):
        v["energy_read_at_str"] = None
    # Daily energy view: real COP only when both sides are reported. The heat-pump exporter lags
    # the electrical day-counter behind the thermal one, so guard the impossible 0-in/N-out pair.
    v.update(explain.energy_today(v.get("e_total"), v.get("th_heating"), v.get("th_dhw")))
    # backup heating rod (Heizstab) — running it is expensive/inefficient, surface it
    v["heatingrod_today"] = round((v.get("hr_heating") or 0) + (v.get("hr_dhw") or 0), 1)
    return render(request, "partials/heatpump.html", v=v, label=HEATPUMP_LABEL)


@app.get("/partials/inverter", response_class=HTMLResponse)
def inverter(request: Request):
    v = {k: sources.prom_query(PROM, e) for k, e in _INVERTER.items()}
    lang = i18n.get_lang(request)
    state = v.get("op_state")
    if state is not None:
        key, ok = _INV_STATE.get(int(state), (None, False))
        txt = i18n.t(lang, key) if key else i18n.t(lang, "inv_code", c=int(state))
    else:
        txt, ok = "–", True
    v["state_text"], v["state_ok"] = txt, ok
    riso = v.get("riso")
    v["riso_kohm"] = round(riso / 1000.0) if riso is not None else None
    return render(request, "partials/inverter.html", v=v)


@app.get("/partials/decisions", response_class=HTMLResponse)
def decisions_partial(request: Request):
    with _db_optional() as conn:
        decisions = sources.recent_decisions(conn)
    return render(request, "partials/decisions.html", decisions=decisions)


@app.get("/api/effectiveness")
def api_effectiveness(window: str = "7d"):
    with _db_optional() as conn:
        cfg = sources.load_config(conn)
        days = sources.effectiveness_daily(
            conn, window, cfg.get("wp_nominal_power_w", 2000),
            cfg.get("grid_price_eur_kwh", 0.30), cfg.get("feed_in_tariff_eur_kwh", 0.08))
    return JSONResponse({"days": days})


@app.get("/api/wp-timeline")
def api_wp_timeline():
    now = int(time.time())
    start = int(datetime.now(ZoneInfo(WTZ)).replace(
        hour=0, minute=0, second=0, microsecond=0).timestamp())
    # From the heatpump table, not Prometheus: the controller gauge has one series per pod, so a
    # day with restarts (crashloops/rollouts) yields the wrong/empty series in a range query.
    with _db_optional() as conn:
        relay = sources.wp_timeline_today(conn, start)
    return JSONResponse({"relay": relay, "start": start, "now": now})


@app.get("/api/wp-history")
def api_wp_history(window: str = "24h"):
    with _db_optional() as conn:
        cfg = sources.load_config(conn)
        nominal = cfg.get("wp_nominal_power_w", 2000)
        data = sources.wp_history(conn, window, nominal)
        data["savings"] = sources.wp_savings(
            conn, window, nominal,
            cfg.get("grid_price_eur_kwh", 0.30), cfg.get("feed_in_tariff_eur_kwh", 0.08))
    return JSONResponse(data)


@app.get("/healthz")
def healthz():
    # liveness: process is up. Stays 200 even when locked (no ADMIN_PASS) — restarting wouldn't
    # add the secret, so a locked pod must not be killed.
    return {"ok": True}


@app.get("/readyz")
def readyz():
    # readiness: only "ready to serve" when UNLOCKED. Without ADMIN_PASS every real route 503s
    # (fail-closed), so report NotReady -> the pod leaves the Service endpoints and the
    # misconfiguration is visible (kubectl/ArgoCD) instead of serving a silent 503 wall.
    if not ADMIN_PASS:
        return JSONResponse({"ready": False, "reason": "locked: ADMIN_PASS unset"}, status_code=503)
    return {"ready": True}
