import json

from src.ratebudget import RateBudget, clamp_interval


def test_allows_until_cap_then_blocks():
    b = RateBudget(cap=3, window_s=100)
    for i in range(3):
        assert b.allow(now=i) is True
        b.record(now=i)
    assert b.allow(now=3) is False


def test_window_slides_and_frees_budget():
    b = RateBudget(cap=2, window_s=100)
    b.record(now=0)
    b.record(now=10)
    assert b.allow(now=50) is False
    assert b.allow(now=111) is True   # now=0 evicted (>100s old), one slot free


def test_count_evicts_old():
    b = RateBudget(cap=10, window_s=100)
    b.record(now=0)
    b.record(now=200)
    assert b.count(now=200) == 1


def test_clamp_interval_floor():
    assert clamp_interval(30) == 120
    assert clamp_interval(300) == 300
    assert clamp_interval("bad", default=300) == 300


def test_budget_persists_and_survives_restart(tmp_path):
    p = tmp_path / "budget.json"
    b1 = RateBudget(cap=5, window_s=86400, persist_path=str(p))
    b1.record(1000.0); b1.record(1000.0); b1.record(1000.0)
    b2 = RateBudget(cap=5, window_s=86400, persist_path=str(p))   # simulated restart
    assert b2.count(1000.0) == 3            # NOT reset to 0
    assert b2.allow(1000.0) is True


def test_persisted_entries_outside_window_are_dropped_on_load(tmp_path):
    p = tmp_path / "budget.json"
    b1 = RateBudget(cap=5, window_s=100, persist_path=str(p))
    b1.record(1000.0)
    b2 = RateBudget(cap=5, window_s=100, persist_path=str(p))
    assert b2.count(2000.0) == 0            # 1000 is >100s before 2000 -> evicted


def test_partially_corrupt_persist_file_keeps_valid_entries(tmp_path):
    # A single non-coercible entry must NOT nuke the whole window (which would
    # silently grant a fresh daily quota against ViCare's server-side cap).
    p = tmp_path / "budget.json"
    p.write_text(json.dumps([1000.0, "foo", 1001.0]))
    b = RateBudget(cap=5, window_s=86400, persist_path=str(p))
    assert b.count(1001.0) == 2             # two valid timestamps retained, not reset to empty


def test_save_failure_is_logged_not_silent(tmp_path, caplog):
    # Persisting to an unwritable path must warn (else a restart silently grants fresh quota).
    import logging
    bad = tmp_path / "nope" / "budget.json"   # parent dir does not exist -> open() fails
    b = RateBudget(cap=5, window_s=86400, persist_path=str(bad))
    with caplog.at_level(logging.WARNING):
        b.record(now=1.0)                      # triggers _save()
    assert any("persist" in r.message for r in caplog.records)
