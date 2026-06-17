"""Rolling household base-load estimate (consumption excluding the heat pump).

available = production - base_load is the real PV headroom for the WP. base_load is a low
percentile of recent HOUSEHOLD consumption, sampled ONLY while the heat-pump relay is OFF so the
WP's own draw can never contaminate the baseline. During a long continuous run (no fresh OFF
samples) the last good estimate is held for up to max_stale_s; after that estimate() returns None
and the controller falls back to the nominal path."""
import collections


class BaseLoad:
    def __init__(self, window_s=3600, min_samples=20, max_stale_s=21600):
        self.window_s = window_s
        self.min_samples = min_samples
        self.max_stale_s = max_stale_s
        self._samples = collections.deque()
        self._last_value = None
        self._last_ts = None

    def _evict(self, now):
        cutoff = now - self.window_s
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def update(self, now, consumption_w):
        """Append a HOUSEHOLD consumption sample. The caller guarantees the relay is OFF, so this
        is the house load with the WP excluded. Evicts samples older than window_s."""
        if consumption_w is None:
            return
        self._samples.append((now, float(consumption_w)))
        self._evict(now)

    def estimate(self, now, percentile):
        """base-load watts at `percentile` of the window's household samples. Holds the last good
        value while no fresh samples remain (up to max_stale_s), else None. Evicts here too so a
        long run with no updates drains the window and triggers the hold-last path."""
        self._evict(now)
        if len(self._samples) >= self.min_samples:
            vals = sorted(v for _, v in self._samples)
            k = max(0, min(len(vals) - 1, int(round((percentile / 100.0) * (len(vals) - 1)))))
            self._last_value = vals[k]
            self._last_ts = now
            return self._last_value
        if (self._last_value is not None and self._last_ts is not None
                and (now - self._last_ts) <= self.max_stale_s):
            return self._last_value
        return None
