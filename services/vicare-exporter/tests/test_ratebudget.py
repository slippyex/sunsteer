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
