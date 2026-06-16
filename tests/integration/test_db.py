"""Integration smoke: real SQL against a real TimescaleDB with init.sql + migrations applied.
Catches schema/column drift that mocked unit tests miss. Runs only when PGHOST is set (CI/local docker)."""
import os
import sys

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("PGHOST"), reason="needs a live Postgres")

# repo root is three levels up: tests/integration/test_db.py -> tests/integration -> tests -> <repo>
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _conn():
    import psycopg2
    c = psycopg2.connect(host=os.environ["PGHOST"], port=int(os.environ.get("PGPORT", "5432")),
                         dbname=os.environ["PGDATABASE"], user=os.environ["PGUSER"],
                         password=os.environ["PGPASSWORD"])
    c.autocommit = True
    return c


def _drop_src_modules():
    """Both services ship a top-level `src` package, so the second import would resolve to
    the first service's already-cached `src`. Evict any cached `src`/`src.*` so the next
    `import src.<mod>` re-resolves against the sys.path entry we just inserted."""
    for name in [m for m in sys.modules if m == "src" or m.startswith("src.")]:
        del sys.modules[name]


def test_control_ui_sources_against_real_schema():
    _drop_src_modules()
    sys.path.insert(0, os.path.join(ROOT, "services", "control-ui"))
    import importlib
    src = importlib.import_module("src.sources")
    c = _conn()
    assert isinstance(src.load_config(c), dict)
    assert isinstance(src.recent_decisions(c), list)
    for w in ("24h", "7d", "30d", "90d", "365d"):
        assert "window" in src.wp_history(c, w)
    src.save_settings(c, {"threshold_base_w": 2600})
    assert src.load_config(c)["threshold_base_w"] == 2600
    # Whitelist + sql.Identifier: a non-column key is ignored (never reaches SQL), the
    # whitelisted value still persists, and nothing raises.
    src.save_settings(c, {"threshold_base_w": 2601, "not_a_column": 5})
    assert src.load_config(c)["threshold_base_w"] == 2601
    c.close()


def test_controller_dblog_against_real_schema():
    _drop_src_modules()
    sys.path.insert(0, os.path.join(ROOT, "services", "surplus-controller"))
    from src import dblog  # type: ignore
    c = _conn()
    dblog.write_decision(c, mode="auto", surplus_w=100.0, eff_threshold=2000.0,
                         forecast_remaining=5.0, relay_target=True, action="switched_on",
                         reason="surplus_threshold_met", available_w=100.0, relay_on_before=False,
                         state_age_s=0.5, shelly_reachable=True)
    a_on, a_off = dblog.last_switch_ages(c)
    assert a_on is not None
    c.close()


def test_today_summary_survives_a_counter_reset():
    # The UI's today_summary computes today's production the same way daily_production does and
    # must be equally reset-proof: max-min would report the whole lifetime span as "today".
    _drop_src_modules()
    sys.path.insert(0, os.path.join(ROOT, "services", "control-ui"))
    import importlib
    src = importlib.import_module("src.sources")
    c = _conn()
    with c.cursor() as cur:
        cur.execute("DELETE FROM energy_meter")
        # Today: counter climbs 10->14 (4 kWh), RESETS to 0, then 0->2 (2 kWh). Real = 6 kWh.
        for k, val in enumerate([10.0, 12.0, 14.0, 0.0, 1.0, 2.0]):
            cur.execute(
                "INSERT INTO energy_meter (time, production_kwh_total) VALUES "
                "(date_trunc('day', now()) + interval '6 hours' + (%s * interval '1 minute'), %s)",
                (k, val))
    prod = src.today_summary(c)["prod_kwh"]
    c.close()
    assert abs(prod - 6.0) < 0.01            # real production, not the ~14 lifetime span


def test_heatpump_telemetry_table_exists_and_vicare_is_gone():
    # The generic contract table replaces the vendor-named one; data is preserved by a RENAME.
    c = _conn()
    with c.cursor() as cur:
        cur.execute("SELECT to_regclass('public.heatpump_telemetry'), "
                    "to_regclass('public.heatpump_vicare')")
        new, old = cur.fetchone()
    c.close()
    assert new is not None        # heatpump_telemetry exists
    assert old is None            # heatpump_vicare no longer exists


def test_heatpump_writer_against_real_schema():
    _drop_src_modules()
    sys.path.insert(0, os.path.join(ROOT, "services", "heatpump-exporter"))
    from src import tsdb_writer as w  # type: ignore
    c = _conn()
    w.write(c, {"dhw_temp_c": 51.0, "compressor_starts": 5})
    with c.cursor() as cur:
        cur.execute("SELECT dhw_temp_c, compressor_starts FROM heatpump_telemetry ORDER BY time DESC LIMIT 1")
        row = cur.fetchone()
    c.close()
    assert row == (51.0, 5.0)


def test_daily_production_survives_a_midday_counter_reset():
    # production_kwh_total is a monotonic lifetime counter. If the inverter resets it mid-day,
    # max(total)-min(total) reports a wildly wrong figure (the whole lifetime span). The real
    # day's production is the sum of POSITIVE deltas across the day -> reset-proof.
    _drop_src_modules()
    sys.path.insert(0, os.path.join(ROOT, "services", "surplus-controller"))
    from src import dblog  # type: ignore
    c = _conn()
    with c.cursor() as cur:
        cur.execute("DELETE FROM energy_meter")        # isolate: exactly one past day below
        # Yesterday, solidly mid-day: counter climbs 1000->1004 (4 kWh), RESETS to 0, then 0->2
        # (2 kWh). True production = 6 kWh; max-min would report ~1004.
        for k, val in enumerate([1000.0, 1002.0, 1004.0, 0.0, 1.0, 2.0]):
            cur.execute(
                "INSERT INTO energy_meter (time, production_kwh_total) VALUES "
                "(date_trunc('day', now()) - interval '1 day' + interval '10 hours' "
                "+ (%s * interval '1 minute'), %s)", (k, val))
    produced = list(dblog.daily_production(c).values())
    c.close()
    assert len(produced) == 1
    assert abs(produced[0] - 6.0) < 0.01            # real production, not the ~1004 lifetime span


def test_harvest_summary_self_and_wasted():
    import importlib
    _drop_src_modules()
    sys.path.insert(0, os.path.join(ROOT, "services", "control-ui"))
    sources = importlib.import_module("src.sources")
    c = _conn()
    with c.cursor() as cur:
        cur.execute("DELETE FROM energy_meter; DELETE FROM heatpump;")
        # 10 minutes today: WP ON, surplus +3000 (full PV covers the 2000 W WP) -> self-consumed.
        cur.execute("""INSERT INTO energy_meter (time, surplus_w, export_w)
                       SELECT now() - (g||' min')::interval, 3000, 3000 FROM generate_series(1,10) g""")
        cur.execute("""INSERT INTO heatpump (time, relay_on)
                       SELECT now() - (g||' min')::interval, true FROM generate_series(1,10) g""")
        # 10 minutes today: WP OFF, exporting 1500 W -> wasted (could have driven the WP).
        cur.execute("""INSERT INTO energy_meter (time, surplus_w, export_w)
                       SELECT now() - (g||' min')::interval, 1500, 1500 FROM generate_series(11,20) g""")
        cur.execute("""INSERT INTO heatpump (time, relay_on)
                       SELECT now() - (g||' min')::interval, false FROM generate_series(11,20) g""")
    h = sources.harvest_summary(c, "today", nominal_w=2000, grid_price=0.30, feed_in=0.08)
    # self-consumed ~ 2000 W × 10 min = 0.333 kWh; wasted ~ 1500 W × 10 min = 0.25 kWh
    assert 0.28 < h["self_kwh"] < 0.38
    assert 0.20 < h["wasted_kwh"] < 0.30
    # € = kWh × (grid − feed). Each field is independently rounded to 2 decimals, so compare
    # within a sub-cent tolerance rather than for exact equality (rounding-order would otherwise
    # make the 2-decimal € differ from the full-precision product).
    assert abs(h["self_eur"] - h["self_kwh"] * (0.30 - 0.08)) < 0.01
    assert abs(h["wasted_eur"] - h["wasted_kwh"] * (0.30 - 0.08)) < 0.01


def test_harvest_summary_tolerant_on_bad_conn():
    import importlib
    _drop_src_modules()
    sys.path.insert(0, os.path.join(ROOT, "services", "control-ui"))
    sources = importlib.import_module("src.sources")

    class Dead:
        def cursor(self): raise RuntimeError("db down")
    h = sources.harvest_summary(Dead(), "today", 2000, 0.30, 0.08)
    assert h == {"self_kwh": None, "self_eur": None, "wasted_kwh": None,
                 "wasted_eur": None, "cop": None}
