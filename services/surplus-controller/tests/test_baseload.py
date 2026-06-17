from src.baseload import BaseLoad


def test_none_until_min_samples():
    b = BaseLoad(window_s=3600, min_samples=20, max_stale_s=21600)
    for t in range(0, 10 * 15, 15):      # only 10 samples (< 20)
        b.update(t, 400)
    assert b.estimate(150, percentile=50) is None


def test_median_of_household_samples():
    b = BaseLoad(window_s=3600, min_samples=20, max_stale_s=21600)
    now = 0
    for _ in range(60):                  # 60 household samples around ~500 W
        b.update(now, 400 if now % 2 == 0 else 600)
        now += 15
    base = b.estimate(now, percentile=50)
    assert 400 <= base <= 600


def test_percentile_parameter_respected():
    b = BaseLoad(window_s=3600, min_samples=5, max_stale_s=21600)
    now = 0
    for v in [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]:
        b.update(now, v); now += 15
    low = b.estimate(now, percentile=10)
    high = b.estimate(now, percentile=90)
    assert low < high
    assert low <= 200 and high >= 900


def test_holds_last_value_when_window_drains():
    b = BaseLoad(window_s=3600, min_samples=20, max_stale_s=21600)
    now = 0
    for _ in range(40):
        b.update(now, 500); now += 15      # warm up, last sample ~ t=585
    held = b.estimate(now, percentile=50)
    assert held == 500
    # Jump 2 h ahead with NO new samples: window drains -> hold last value.
    later = now + 7200
    assert b.estimate(later, percentile=50) == 500


def test_returns_none_after_max_stale():
    b = BaseLoad(window_s=3600, min_samples=20, max_stale_s=21600)
    now = 0
    for _ in range(40):
        b.update(now, 500); now += 15
    assert b.estimate(now, percentile=50) == 500
    # 7 h later (> window 1h + max_stale 6h since the window drained) -> None.
    assert b.estimate(now + 7 * 3600 + 100, percentile=50) is None


def test_window_evicts_old_samples():
    b = BaseLoad(window_s=3600, min_samples=5, max_stale_s=21600)
    b.update(0, 5000)                      # stale outlier
    now = 3700
    for _ in range(20):
        b.update(now, 400); now += 15
    assert b.estimate(now, percentile=50) < 600   # outlier evicted
