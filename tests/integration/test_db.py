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
