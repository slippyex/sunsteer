"""Rolling household base-load estimate (consumption excluding the heat pump).

available = production - base_load is the real PV headroom for the WP. base_load is the
low-percentile of recent consumption: the heat pump cycles, so the window holds WP-off
troughs, and a low percentile picks them out while ignoring cooking/load spikes."""
import collections


class BaseLoad:
    def __init__(self, window_s=3600, percentile=20, min_warmup_s=1200):
        self.window_s = window_s
        self.percentile = percentile
        self.min_warmup_s = min_warmup_s
        self._samples = collections.deque()

    def update(self, now, consumption_w):
        if consumption_w is None:
            return
        self._samples.append((now, float(consumption_w)))
        cutoff = now - self.window_s
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def estimate(self):
        """Base-load watts, or None until the window spans at least min_warmup_s."""
        if not self._samples:
            return None
        span = self._samples[-1][0] - self._samples[0][0]
        if span < self.min_warmup_s:
            return None
        vals = sorted(v for _, v in self._samples)
        k = max(0, min(len(vals) - 1, int(round((self.percentile / 100.0) * (len(vals) - 1)))))
        return vals[k]
