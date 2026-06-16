from src.baseload import BaseLoad


def test_warmup_returns_none_until_enough_span():
    b = BaseLoad(window_s=3600, percentile=20, min_warmup_s=1200)
    b.update(0, 400)
    b.update(600, 450)
    assert b.estimate() is None


def test_percentile_tracks_baseline_not_wp_peaks():
    b = BaseLoad(window_s=3600, percentile=20, min_warmup_s=1200)
    t = 0
    for _ in range(30):
        b.update(t, 400);  t += 60
        b.update(t, 2400); t += 60
    base = b.estimate()
    assert 350 < base < 700


def test_window_evicts_old_samples():
    b = BaseLoad(window_s=3600, percentile=20, min_warmup_s=0)
    b.update(0, 5000)
    for t in range(3700, 5000, 60):
        b.update(t, 400)
    assert b.estimate() < 600
