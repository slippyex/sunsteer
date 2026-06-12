from src.sources import parse_prom_value

def test_parse_instant_vector_value():
    resp = {"status": "success", "data": {"resultType": "vector",
            "result": [{"metric": {}, "value": [1717740000, "2480.5"]}]}}
    assert parse_prom_value(resp) == 2480.5

def test_parse_empty_result_is_none():
    resp = {"status": "success", "data": {"resultType": "vector", "result": []}}
    assert parse_prom_value(resp) is None

def test_parse_error_status_is_none():
    assert parse_prom_value({"status": "error"}) is None

def test_parse_garbage_is_none():
    assert parse_prom_value({}) is None


from src.sources import parse_open_meteo

OM = {
    "current": {"temperature_2m": 18.4, "cloud_cover": 45, "weather_code": 2},
    "daily": {"time": ["2026-06-07", "2026-06-08"],
              "temperature_2m_max": [22.1, 19.3], "temperature_2m_min": [11.8, 10.2],
              "sunshine_duration": [25560, 15480], "weather_code": [2, 3]},
    "hourly": {"time": ["2026-06-07T00:00", "2026-06-07T01:00"],
               "temperature_2m": [14.0, 13.5], "cloud_cover": [80, 60]},
}

def test_parse_open_meteo_current_and_days():
    w = parse_open_meteo(OM)
    assert w["current"]["temp"] == 18.4 and w["current"]["cloud"] == 45
    assert w["current"]["text"] == "Teils bewölkt"
    assert w["today"]["tmax"] == 22 and w["today"]["tmin"] == 12   # rounded
    assert w["today"]["sun_h"] == 7.1                              # 25560/3600
    assert w["tomorrow"]["icon"] == "☁"
    assert w["hourly"]["cloud"] == [80, 60]

def test_parse_open_meteo_tolerates_missing():
    w = parse_open_meteo({})
    assert w["today"] is None and w["current"]["temp"] is None
    assert w["hourly"]["time"] == []


# ── wp_history ─────────────────────────────────────────────────────────────
from datetime import datetime, date
import src.sources as S


class _Cur:
    """Returns the queued result-sets in execute order (one fetchall per execute)."""
    def __init__(self, results): self._results = list(results)
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, params=None): pass
    def fetchall(self): return self._results.pop(0) if self._results else []


class _Conn:
    def __init__(self, results): self._cur = _Cur(results)
    def cursor(self): return self._cur


def test_wp_window_whitelist_defaults_to_24h():
    assert S.wp_history(_Conn([]), "bogus")["window"] == "24h"
    for w in ("7d", "30d", "90d", "365d"):
        assert S.wp_history(_Conn([]), w)["window"] == w


def test_effectiveness_daily_window_whitelist_and_mapping():
    class _RecCur(_Cur):
        def execute(self, sql, params=None): self.params = params
    class _RecConn:
        def __init__(self, results): self._cur = _RecCur(results)
        def cursor(self): return self._cur

    d = datetime(2026, 6, 9, 0, 0)
    for win, days in (("7d", 6), ("30d", 29), ("90d", 89), ("365d", 364), ("bogus", 6)):
        conn = _RecConn([[(d, 2.0)]])
        out = S.effectiveness_daily(conn, win, 2000, grid_price=0.30, feed_in=0.08)
        assert conn._cur.params == (f"{days} days",)
        assert out == [{"day": "09.06", "runtime_h": 2.0, "kwh": 4.0, "eur": 0.88}]


def test_effectiveness_daily_tolerates_db_errors():
    class _Boom:
        def cursor(self): raise RuntimeError("db down")
    assert S.effectiveness_daily(_Boom(), "7d", 2000, 0.30, 0.08) == []


def test_wp_temps_maps_rows():
    t = datetime(2026, 6, 9, 12, 0)
    rows = [(t, 57.7, 26.4, 63.5, 14.6)]
    out = S._wp_temps(_Conn([rows]), "24 hours", "10 minutes")
    assert out == [{"t": t.isoformat(), "dhw": 57.7, "buffer": 26.4,
                    "supply": 63.5, "outside": 14.6}]


def test_wp_run_merges_surplus_and_onfraction():
    t = datetime(2026, 6, 9, 12, 0)
    conn = _Conn([[(t, 2200)], [(t, 0.5)]])     # surplus query, then on-fraction query
    out = S._wp_run(conn, "24 hours", "10 minutes")
    assert out == [{"t": t.isoformat(), "surplus": 2200.0, "on_frac": 0.5}]


def test_wp_comp_starts_is_per_bucket_delta_with_reset():
    t1, t2, t3 = (datetime(2026, 6, 9, h, 0) for h in (10, 11, 12))
    rows = [(t1, 40.0, 100), (t2, 42.0, 103), (t3, 41.0, 2)]   # t3: counter reset
    out = S._wp_comp(_Conn([rows]), "24 hours", "10 minutes")
    assert [o["starts"] for o in out] == [None, 3.0, 2.0]       # first None, then delta, reset->current
    assert [o["rps"] for o in out] == [40.0, 42.0, 41.0]


def test_wp_eff_estimates_kwh_from_runtime():
    d = datetime(2026, 6, 9, 0, 0)
    conn = _Conn([[(d, 2.0)], [(d, 5.2)]])      # runtime_h=2.0, scop=5.2
    out = S._wp_eff(conn, "7 days", nominal_w=2000)
    assert out == [{"day": "09.06", "kwh": 4.0, "scop": 5.2}]   # 2.0 h * 2.0 kW = 4.0 kWh


def test_wp_history_tolerates_db_errors():
    class _Boom:
        def cursor(self): raise RuntimeError("db down")
    r = S.wp_history(_Boom(), "24h")
    assert r == {"window": "24h", "temps": [], "run": [], "comp": [], "eff": [], "strings": []}


def test_wp_savings_computes_pv_grid_and_cumulative_eur():
    d1, d2 = datetime(2026, 6, 8, 0, 0), datetime(2026, 6, 9, 0, 0)
    rows = [(d1, 2.0, 1.0), (d2, 3.0, 0.5)]   # (day, pv_kwh, grid_kwh)
    out = S.wp_savings(_Conn([rows]), "7d", 2000, grid_price=0.30, feed_in=0.08)
    # saving = pv * (0.30-0.08) = pv*0.22 ; cum_eur runs
    assert out[0] == {"day": "08.06", "pv_kwh": 2.0, "grid_kwh": 1.0,
                      "saved_eur": 0.44, "cum_eur": 0.44}
    assert out[1] == {"day": "09.06", "pv_kwh": 3.0, "grid_kwh": 0.5,
                      "saved_eur": 0.66, "cum_eur": 1.10}


def test_wp_savings_tolerates_db_errors():
    class _Boom:
        def cursor(self): raise RuntimeError("db down")
    assert S.wp_savings(_Boom(), "24h", 2000, 0.30, 0.08) == []


def test_wp_timeline_today_maps_to_epoch_int_pairs():
    rows = [(1780900000, 1), (1780900300, 0)]
    out = S.wp_timeline_today(_Conn([rows]), 1780896000)
    assert out == [[1780900000, 1], [1780900300, 0]]

def test_wp_timeline_today_tolerates_db_errors():
    class _Boom:
        def cursor(self): raise RuntimeError("db down")
    assert S.wp_timeline_today(_Boom(), 0) == []
