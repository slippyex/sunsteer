import base64

import pytest
import src.app as appmod
from fastapi.testclient import TestClient

_REAL_BASIC_OK = appmod._basic_ok


@pytest.fixture(autouse=True)
def _auth_satisfied(monkeypatch):
    # Auth is now fail-closed, so without this every render test would 503/401. Default each
    # test to "configured + credentials accepted"; auth-specific tests restore the real check.
    monkeypatch.setattr(appmod, "ADMIN_PASS", "testpass")
    monkeypatch.setattr(appmod, "_basic_ok", lambda h: True)


def _patch(monkeypatch):
    monkeypatch.setattr(appmod.sources, "prom_query", lambda *a, **k: 1000.0)
    monkeypatch.setattr(appmod.sources, "prom_query_range", lambda *a, **k: [[1.0, 2.0]])
    monkeypatch.setattr(appmod.sources, "connect", lambda **k: None)
    monkeypatch.setattr(appmod.sources, "load_config", lambda c: {
        "mode": "paused", "manual_relay_on": False, "threshold_base_w": 2500,
        "threshold_min_w": 1500, "threshold_off_w": 200, "on_delay_cycles": 3,
        "off_delay_cycles": 3, "min_runtime_s": 1800, "min_offtime_s": 900,
        "adapt_enabled": True, "full_sun_ref_kwh": 40,
        "feed_in_tariff_eur_kwh": 0.08, "grid_price_eur_kwh": 0.30,
        "wp_nominal_power_w": 2000})
    monkeypatch.setattr(appmod.sources, "recent_decisions", lambda c, limit=30: [])

def test_index_renders(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(appmod, "_db", lambda: type("C", (), {"close": lambda self: None})())
    r = TestClient(appmod.app).get("/?lang=de")
    assert r.status_code == 200
    assert "PV-Überschuss-Steuerung" in r.text


def test_weather_location_appended_when_set(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(appmod, "_db", lambda: type("C", (), {"close": lambda self: None})())
    monkeypatch.setattr(appmod, "WEATHER_LOCATION", "Testhausen")
    r = TestClient(appmod.app).get("/?lang=en")
    assert r.status_code == 200 and "Weather · Testhausen" in r.text


def test_weather_location_omitted_when_unset(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(appmod, "_db", lambda: type("C", (), {"close": lambda self: None})())
    monkeypatch.setattr(appmod, "WEATHER_LOCATION", "")
    r = TestClient(appmod.app).get("/?lang=en")
    assert r.status_code == 200 and "Weather ·" not in r.text

def test_status_partial_renders(monkeypatch):
    _patch(monkeypatch)
    r = TestClient(appmod.app).get("/partials/status?lang=de")
    assert r.status_code == 200
    assert "Überschuss" in r.text

def test_healthz():
    assert TestClient(appmod.app).get("/healthz").json() == {"ok": True}

def test_auth_fail_closed_when_no_pass(monkeypatch):
    # fail-closed: no ADMIN_PASS -> locked (503), NOT open
    monkeypatch.setattr(appmod, "ADMIN_PASS", None)
    monkeypatch.setattr(appmod, "_basic_ok", _REAL_BASIC_OK)
    assert TestClient(appmod.app).get("/partials/status").status_code == 503

def test_auth_healthz_open_even_when_locked(monkeypatch):
    monkeypatch.setattr(appmod, "ADMIN_PASS", None)        # probe path stays open even locked
    monkeypatch.setattr(appmod, "_basic_ok", _REAL_BASIC_OK)
    assert TestClient(appmod.app).get("/healthz").status_code == 200

def test_readyz_ready_when_unlocked(monkeypatch):
    monkeypatch.setattr(appmod, "ADMIN_PASS", "s3cret")
    assert TestClient(appmod.app).get("/readyz").status_code == 200

def test_readyz_not_ready_when_locked(monkeypatch):
    monkeypatch.setattr(appmod, "ADMIN_PASS", None)        # liveness 200 but readiness 503
    monkeypatch.setattr(appmod, "_basic_ok", _REAL_BASIC_OK)
    r = TestClient(appmod.app).get("/readyz")
    assert r.status_code == 503 and r.json()["ready"] is False

def test_api_wp_history(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(appmod, "_db", lambda: type("C", (), {"close": lambda self: None})())
    captured = {}
    def fake_hist(conn, window, nominal):
        captured["window"] = window
        return {"window": window, "temps": [], "run": [], "comp": [], "eff": []}
    monkeypatch.setattr(appmod.sources, "wp_history", fake_hist)
    monkeypatch.setattr(appmod.sources, "wp_savings", lambda *a, **k: [])
    r = TestClient(appmod.app).get("/api/wp-history?window=7d")
    assert r.status_code == 200
    assert captured["window"] == "7d"
    assert set(r.json()) == {"window", "temps", "run", "comp", "eff", "savings"}

def test_auth_required_when_pass_set(monkeypatch):
    monkeypatch.setattr(appmod, "ADMIN_PASS", "s3cret")
    monkeypatch.setattr(appmod, "_basic_ok", _REAL_BASIC_OK)
    r = TestClient(appmod.app).get("/partials/status")
    assert r.status_code == 401 and "WWW-Authenticate" in r.headers

def test_auth_accepts_valid_creds(monkeypatch):
    monkeypatch.setattr(appmod, "ADMIN_PASS", "s3cret")
    monkeypatch.setattr(appmod, "ADMIN_USER", "admin")
    monkeypatch.setattr(appmod, "_basic_ok", _REAL_BASIC_OK)
    _patch(monkeypatch)
    tok = base64.b64encode(b"admin:s3cret").decode()
    r = TestClient(appmod.app).get("/partials/status", headers={"Authorization": f"Basic {tok}"})
    assert r.status_code == 200

def test_auth_rejects_wrong_creds(monkeypatch):
    monkeypatch.setattr(appmod, "ADMIN_PASS", "s3cret")
    monkeypatch.setattr(appmod, "_basic_ok", _REAL_BASIC_OK)
    tok = base64.b64encode(b"admin:wrong").decode()
    r = TestClient(appmod.app).get("/partials/status", headers={"Authorization": f"Basic {tok}"})
    assert r.status_code == 401

def test_why_partial_renders(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(appmod, "_db", lambda: type("C", (), {"close": lambda self: None})())
    monkeypatch.setattr(appmod.sources, "controller_status", lambda url: {
        "mode": "auto", "relay_on": False, "surplus_w": 465, "effective_threshold_w": 2382,
        "on_streak": 2, "off_streak": 0, "on_delay_cycles": 3, "off_delay_cycles": 3,
        "secs_since_on": 9999, "secs_since_off": 9999, "min_runtime_s": 1800,
        "min_offtime_s": 900, "reason": "waiting_surplus"})
    r = TestClient(appmod.app).get("/partials/why?lang=de")
    assert r.status_code == 200 and "WP aus" in r.text

def test_balance_partial_renders(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(appmod, "_db", lambda: type("C", (), {"close": lambda self: None})())
    monkeypatch.setattr(appmod.sources, "today_summary", lambda c: {
        "prod_kwh": 38.0, "export_kwh": 31.0, "import_kwh": 4.0, "self_consumption": 0.18,
        "wp_runtime_h": 1.4, "wp_runtime_total_h": 5.0})
    r = TestClient(appmod.app).get("/partials/balance?lang=de")
    # nominal 2000 W × 1.4 h = 2.8 kWh today, × 5.0 h = 10.0 kWh total (estimated)
    assert r.status_code == 200 and "selbst genutzt" in r.text
    assert "2.8" in r.text and "10.0" in r.text


def test_vicare_partial_renders(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(appmod.sources, "prom_query", lambda *a, **k: 42.0)
    r = TestClient(appmod.app).get("/partials/vicare?lang=de")
    assert r.status_code == 200
    assert "SCOP" in r.text and "Verdichter" in r.text


def test_vicare_partial_tolerates_missing_metrics(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(appmod.sources, "prom_query", lambda *a, **k: None)
    r = TestClient(appmod.app).get("/partials/vicare")
    assert r.status_code == 200  # all None -> dashes, no 500


def test_inverter_partial_renders(monkeypatch):
    _patch(monkeypatch)  # prom_query -> 1000.0 for all metrics
    r = TestClient(appmod.app).get("/partials/inverter?lang=de")
    assert r.status_code == 200
    assert "Ost" in r.text and "West" in r.text and "Isolation" in r.text

def test_inverter_partial_tolerates_missing_metrics(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(appmod.sources, "prom_query", lambda *a, **k: None)
    r = TestClient(appmod.app).get("/partials/inverter")
    assert r.status_code == 200  # op_state None -> "–", reachable None -> renders, no 500


def test_ticker_partial_renders(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(appmod.sources, "controller_status",
                        lambda url: {"relay_on": True, "mode": "auto"})
    r = TestClient(appmod.app).get("/partials/ticker?lang=de")
    assert r.status_code == 200 and "WP läuft" in r.text

def test_ticker_partial_tolerates_no_controller(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(appmod.sources, "controller_status", lambda url: None)
    r = TestClient(appmod.app).get("/partials/ticker")
    assert r.status_code == 200  # relay_on None -> "WP –", no 500


def test_decisions_partial_renders(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(appmod, "_db", lambda: type("C", (), {"close": lambda self: None})())
    r = TestClient(appmod.app).get("/partials/decisions?lang=de")
    assert r.status_code == 200 and "Überschuss" in r.text

def test_decisions_partial_handles_external_change_with_nulls(monkeypatch):
    # external (watchdog/SMA) switch -> no decision_log match -> surplus/threshold are None
    _patch(monkeypatch)
    monkeypatch.setattr(appmod, "_db", lambda: type("C", (), {"close": lambda self: None})())
    from datetime import datetime
    monkeypatch.setattr(appmod.sources, "recent_decisions", lambda c, limit=30: [
        {"time": datetime(2026, 6, 9, 20, 27), "mode": "auto", "surplus_w": None,
         "threshold_w": None, "action": "switched_off", "reason": "extern (Watchdog/SMA)"}])
    r = TestClient(appmod.app).get("/partials/decisions?lang=de")
    assert r.status_code == 200 and "AUS" in r.text and "extern" in r.text  # no crash on None


def test_api_effectiveness_passes_window(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(appmod, "_db", lambda: type("C", (), {"close": lambda self: None})())
    seen = {}
    def _fake(c, window, n, g, f):
        seen["window"] = window
        return [{"day": "07.06", "runtime_h": 1.0, "kwh": 2.0, "eur": 0.44}]
    monkeypatch.setattr(appmod.sources, "effectiveness_daily", _fake)
    r = TestClient(appmod.app).get("/api/effectiveness?window=90d")
    assert r.status_code == 200 and r.json()["days"][0]["kwh"] == 2.0
    assert seen["window"] == "90d"
    TestClient(appmod.app).get("/api/effectiveness")
    assert seen["window"] == "7d"   # default


def test_api_wp_timeline(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(appmod, "_db", lambda: type("C", (), {"close": lambda self: None})())
    monkeypatch.setattr(appmod.sources, "wp_timeline_today", lambda c, s: [[1780900000, 1]])
    r = TestClient(appmod.app).get("/api/wp-timeline")
    body = r.json()
    assert r.status_code == 200 and body["relay"] == [[1780900000, 1]] and "start" in body


# ── i18n ───────────────────────────────────────────────────────────────────
def test_lang_endpoint_sets_cookie_and_redirects(monkeypatch):
    _patch(monkeypatch)
    r = TestClient(appmod.app).get("/lang/en", follow_redirects=False)
    assert r.status_code == 303 and "lang=en" in r.headers.get("set-cookie", "")

def test_lang_endpoint_rejects_unknown(monkeypatch):
    _patch(monkeypatch)
    r = TestClient(appmod.app).get("/lang/xx", follow_redirects=False)
    assert "lang=en" in r.headers.get("set-cookie", "")   # fallback to default

def test_status_partial_renders_english(monkeypatch):
    _patch(monkeypatch)
    c = TestClient(appmod.app)
    c.cookies.set("lang", "en")
    r = c.get("/partials/status")
    assert r.status_code == 200
    assert "Surplus" in r.text and "Überschuss" not in r.text

def test_status_partial_defaults_english(monkeypatch):
    _patch(monkeypatch)
    r = TestClient(appmod.app).get("/partials/status")
    assert "Surplus" in r.text and "Überschuss" not in r.text

def test_status_partial_german_via_query(monkeypatch):
    _patch(monkeypatch)
    r = TestClient(appmod.app).get("/partials/status?lang=de")
    assert "Überschuss" in r.text

def test_decisions_reason_translated(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(appmod, "_db", lambda: type("C", (), {"close": lambda self: None})())
    from datetime import datetime
    monkeypatch.setattr(appmod.sources, "recent_decisions", lambda c, limit=30: [
        {"time": datetime(2026, 6, 11, 8, 0), "mode": "auto", "surplus_w": 3000.0,
         "threshold_w": 2000.0, "action": "switched_on", "reason": "surplus_threshold_met"}])
    c = TestClient(appmod.app)
    c.cookies.set("lang", "en")
    r = c.get("/partials/decisions")
    assert "surplus above threshold" in r.text and ">ON" in r.text


# ── write paths (settings / control) ─────────────────────────────────────────
_VALID_SETTINGS = {
    "threshold_base_w": "2500", "threshold_min_w": "1500", "threshold_off_w": "200",
    "on_delay_cycles": "3", "off_delay_cycles": "3", "min_runtime_min": "30",
    "min_offtime_min": "15", "full_sun_ref_kwh": "40", "feed_in_tariff_eur_kwh": "0.08",
    "grid_price_eur_kwh": "0.30", "wp_nominal_power_w": "2000", "adapt_enabled": "on",
}


def test_post_settings_writes_validated_values(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(appmod, "_db", lambda: type("C", (), {"close": lambda self: None})())
    saved = {}
    monkeypatch.setattr(appmod.sources, "save_settings", lambda conn, clean: saved.update(clean))
    r = TestClient(appmod.app).post("/settings", data=dict(_VALID_SETTINGS))
    assert r.status_code == 200
    assert saved   # save_settings was called with cleaned values
    assert saved["min_runtime_s"] == 1800   # 30 min -> seconds


def test_post_settings_rejects_invalid_and_does_not_write(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(appmod, "_db", lambda: type("C", (), {"close": lambda self: None})())
    called = {"n": 0}
    monkeypatch.setattr(appmod.sources, "save_settings",
                        lambda conn, clean: called.__setitem__("n", called["n"] + 1))
    # off >= min is invalid (validation rejects); rest of the form is complete.
    bad = {**_VALID_SETTINGS, "threshold_off_w": "1500"}   # off == min -> reject
    r = TestClient(appmod.app).post("/settings", data=bad)
    assert r.status_code == 200
    assert called["n"] == 0   # rejected -> no write


def test_post_control_sets_mode(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(appmod, "_db", lambda: type("C", (), {"close": lambda self: None})())
    saved = {}
    monkeypatch.setattr(appmod.sources, "save_mode",
                        lambda conn, mode, manual_relay_on: saved.update(mode=mode))
    r = TestClient(appmod.app).post("/control", data={"mode": "auto"})
    assert r.status_code == 200 and saved.get("mode") == "auto"


def test_index_degrades_when_db_down(monkeypatch):
    _patch(monkeypatch)
    def _boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(appmod, "_db", _boom)
    r = TestClient(appmod.app).get("/?lang=en")
    assert r.status_code == 200   # degraded, not 500


def test_partials_and_apis_degrade_when_db_down(monkeypatch):
    _patch(monkeypatch)
    def _boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(appmod, "_db", _boom)
    # controller_status / prom are independent of the DB; the DB-backed endpoints must degrade, not 500
    c = TestClient(appmod.app)
    for path in ("/partials/why", "/partials/balance", "/partials/decisions",
                 "/api/effectiveness?window=7d", "/api/wp-timeline", "/api/wp-history?window=7d"):
        assert c.get(path).status_code == 200, path


def test_write_handlers_degrade_when_db_down(monkeypatch):
    _patch(monkeypatch)
    def _boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(appmod, "_db", _boom)
    c = TestClient(appmod.app)
    assert c.post("/control", data={"mode": "auto"}).status_code == 200
    # a valid settings form, DB down -> 200 (no write), not 500
    valid = {"threshold_base_w": "2500", "threshold_min_w": "1500", "threshold_off_w": "200",
             "on_delay_cycles": "3", "off_delay_cycles": "3", "min_runtime_min": "30",
             "min_offtime_min": "15", "full_sun_ref_kwh": "40", "feed_in_tariff_eur_kwh": "0.08",
             "grid_price_eur_kwh": "0.30", "wp_nominal_power_w": "2000"}
    assert c.post("/settings", data=valid).status_code == 200


# ── FIX 1: write handlers must surface a DB-unreachable warning ──────────────
import src.i18n as i18nmod  # noqa: E402


def _db_unreachable_msg(lang="en"):
    return i18nmod.t(lang, "db_unreachable")


def test_post_control_warns_when_db_down(monkeypatch):
    _patch(monkeypatch)
    def _boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(appmod, "_db", _boom)
    r = TestClient(appmod.app).post("/control?lang=en", data={"mode": "auto"})
    assert r.status_code == 200
    assert _db_unreachable_msg("en") in r.text


def test_post_control_does_not_fake_applied_mode_when_db_down(monkeypatch):
    # DB down: requested "auto" must NOT be highlighted as the active mode (no fake-applied
    # state). The active highlight uses class "on" — none of the mode buttons should carry it.
    _patch(monkeypatch)
    def _boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(appmod, "_db", _boom)
    r = TestClient(appmod.app).post("/control?lang=en", data={"mode": "auto"})
    assert r.status_code == 200
    # the auto button must not be marked active
    assert 'value="auto" class="on"' not in r.text


def test_post_control_shows_applied_mode_on_happy_path(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(appmod, "_db", lambda: type("C", (), {"close": lambda self: None})())
    monkeypatch.setattr(appmod.sources, "save_mode", lambda conn, mode, manual_relay_on: None)
    r = TestClient(appmod.app).post("/control?lang=en", data={"mode": "auto"})
    assert r.status_code == 200
    assert _db_unreachable_msg("en") not in r.text
    assert 'value="auto" class="on"' in r.text


def test_post_settings_warns_when_db_down(monkeypatch):
    _patch(monkeypatch)
    def _boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(appmod, "_db", _boom)
    r = TestClient(appmod.app).post("/settings?lang=en", data=dict(_VALID_SETTINGS))
    assert r.status_code == 200
    assert _db_unreachable_msg("en") in r.text


def test_post_settings_saved_on_happy_path_no_warning(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(appmod, "_db", lambda: type("C", (), {"close": lambda self: None})())
    monkeypatch.setattr(appmod.sources, "save_settings", lambda conn, clean: None)
    r = TestClient(appmod.app).post("/settings?lang=en", data=dict(_VALID_SETTINGS))
    assert r.status_code == 200
    assert _db_unreachable_msg("en") not in r.text
    assert i18nmod.t("en", "saved") in r.text


def test_db_unreachable_key_has_both_languages():
    assert i18nmod.t("de", "db_unreachable") != "db_unreachable"
    assert i18nmod.t("en", "db_unreachable") != "db_unreachable"
    assert i18nmod.t("de", "db_unreachable") != i18nmod.t("en", "db_unreachable")


# ── SECURITY FIX 1: ADMIN_PASS / ADMIN_USER reject the CHANGE_ME placeholder ──
def test_admin_secret_treats_change_me_as_unset():
    # a CHANGE_ME placeholder is a misconfiguration, not a credential -> treated as unset
    assert appmod._admin_secret("CHANGE_ME") is None
    assert appmod._admin_secret("prefix-CHANGE_ME-suffix") is None
    assert appmod._admin_secret("") is None
    assert appmod._admin_secret(None) is None
    assert appmod._admin_secret("s3cret") == "s3cret"


def test_app_locked_when_admin_pass_is_change_me(monkeypatch):
    # with ADMIN_PASS=CHANGE_ME the UI must be fail-closed (503), not accept "CHANGE_ME"
    monkeypatch.setattr(appmod, "ADMIN_PASS", appmod._admin_secret("CHANGE_ME"))
    monkeypatch.setattr(appmod, "_basic_ok", _REAL_BASIC_OK)
    assert TestClient(appmod.app).get("/partials/status").status_code == 503


def test_app_locked_when_admin_user_is_change_me(monkeypatch):
    # an ADMIN_USER left at CHANGE_ME locks the whole UI too (treat as unset)
    monkeypatch.setattr(appmod, "ADMIN_PASS", appmod._admin_secret("CHANGE_ME"))
    monkeypatch.setattr(appmod, "ADMIN_USER", appmod._admin_secret("admin_CHANGE_ME"))
    monkeypatch.setattr(appmod, "_basic_ok", _REAL_BASIC_OK)
    assert TestClient(appmod.app).get("/partials/status").status_code == 503


# ── SECURITY FIX 2: CSRF / Origin check on state-changing POSTs ───────────────
def test_post_rejects_mismatching_origin(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(appmod, "_db", lambda: type("C", (), {"close": lambda self: None})())
    monkeypatch.setattr(appmod.sources, "save_mode", lambda *a, **k: None)
    c = TestClient(appmod.app)
    r = c.post("/control", data={"mode": "auto"},
               headers={"Origin": "http://evil.example"})
    assert r.status_code == 403


def test_post_allows_matching_origin(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(appmod, "_db", lambda: type("C", (), {"close": lambda self: None})())
    saved = {}
    monkeypatch.setattr(appmod.sources, "save_mode",
                        lambda conn, mode, manual_relay_on: saved.update(mode=mode))
    c = TestClient(appmod.app)
    # TestClient default host is testserver -> a matching Origin must pass
    r = c.post("/control", data={"mode": "auto"},
               headers={"Origin": "http://testserver"})
    assert r.status_code == 200 and saved.get("mode") == "auto"


def test_post_allows_no_origin(monkeypatch):
    # curl/scripts/non-browser send no Origin -> allowed (existing tests rely on this)
    _patch(monkeypatch)
    monkeypatch.setattr(appmod, "_db", lambda: type("C", (), {"close": lambda self: None})())
    monkeypatch.setattr(appmod.sources, "save_mode", lambda *a, **k: None)
    r = TestClient(appmod.app).post("/control", data={"mode": "auto"})
    assert r.status_code == 200


def test_post_rejects_mismatching_referer(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(appmod, "_db", lambda: type("C", (), {"close": lambda self: None})())
    monkeypatch.setattr(appmod.sources, "save_mode", lambda *a, **k: None)
    c = TestClient(appmod.app)
    r = c.post("/control", data={"mode": "auto"},
               headers={"Referer": "http://evil.example/x"})
    assert r.status_code == 403


def test_post_allows_env_allowed_origin(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(appmod, "_db", lambda: type("C", (), {"close": lambda self: None})())
    monkeypatch.setattr(appmod.sources, "save_mode", lambda *a, **k: None)
    monkeypatch.setattr(appmod, "ALLOWED_ORIGIN", "proxy.example")
    c = TestClient(appmod.app)
    r = c.post("/control", data={"mode": "auto"},
               headers={"Origin": "https://proxy.example"})
    assert r.status_code == 200


def test_norm_origin_accepts_full_url_and_bare_host():
    # Documented form is a full URL; a bare host[:port] must also work. Both reduce to the
    # host[:port] that the Origin/Referer check compares against.
    assert appmod._norm_origin("https://sunsteer.example.com") == "sunsteer.example.com"
    assert appmod._norm_origin("https://sunsteer.example.com:8443") == "sunsteer.example.com:8443"
    assert appmod._norm_origin("sunsteer.example.com") == "sunsteer.example.com"
    assert appmod._norm_origin("") is None
    assert appmod._norm_origin(None) is None


def test_post_allows_full_url_allowed_origin(monkeypatch):
    # Regression: ALLOWED_ORIGIN set to the documented full-URL form must accept a matching
    # cross-host Origin (previously compared a full URL against a bare host -> 403).
    _patch(monkeypatch)
    monkeypatch.setattr(appmod, "_db", lambda: type("C", (), {"close": lambda self: None})())
    monkeypatch.setattr(appmod.sources, "save_mode", lambda *a, **k: None)
    monkeypatch.setattr(appmod, "ALLOWED_ORIGIN", appmod._norm_origin("https://proxy.example"))
    c = TestClient(appmod.app)
    r = c.post("/control", data={"mode": "auto"}, headers={"Origin": "https://proxy.example"})
    assert r.status_code == 200


def test_pos_int_clamps_bad_db_port(monkeypatch):
    monkeypatch.setenv("X", "abc"); assert appmod._pos_int("X", 5432) == 5432
    monkeypatch.setenv("X", "0"); assert appmod._pos_int("X", 5432) == 5432
    monkeypatch.setenv("X", "5432"); assert appmod._pos_int("X", 1) == 5432
    monkeypatch.delenv("X", raising=False); assert appmod._pos_int("X", 5432) == 5432


def test_basic_ok_compares_password_even_on_wrong_username(monkeypatch):
    # Constant-time: a wrong username must NOT short-circuit past the password compare, or the
    # response time leaks whether a username is valid. Assert BOTH digests are computed.
    calls = []
    real = appmod.secrets.compare_digest

    def counting(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(appmod.secrets, "compare_digest", counting)
    monkeypatch.setattr(appmod, "ADMIN_USER", "admin")
    monkeypatch.setattr(appmod, "ADMIN_PASS", "secret")
    header = "Basic " + base64.b64encode(b"wronguser:whatever").decode()
    assert _REAL_BASIC_OK(header) is False    # the real fn (a fixture stubs appmod._basic_ok)
    assert len(calls) == 2     # username AND password both compared (no early-out)


def test_balance_survives_null_config_prices(monkeypatch):
    # The balance card's contract is "degrade, never 500". A present-but-NULL price/power column
    # makes cfg.get(key, default) return None (key exists) -> float(None) would 500 the partial.
    _patch(monkeypatch)
    monkeypatch.setattr(appmod.sources, "load_config", lambda c: {
        "grid_price_eur_kwh": None, "feed_in_tariff_eur_kwh": None, "wp_nominal_power_w": None})
    monkeypatch.setattr(appmod.sources, "today_summary", lambda c: {
        "prod_kwh": 0.0, "export_kwh": 0.0, "import_kwh": 0.0,
        "self_consumption": 0.0, "wp_runtime_h": 0.0, "wp_runtime_total_h": 0.0})
    monkeypatch.setattr(appmod.sources, "solar_forecast_today", lambda c: {})
    r = TestClient(appmod.app).get("/partials/balance")
    assert r.status_code == 200
