import base64
import pytest
import src.sources as sources
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
