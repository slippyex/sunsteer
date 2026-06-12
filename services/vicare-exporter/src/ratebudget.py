"""Rolling-window API call budget + poll-interval floor. Pure, wall-clock injected."""
import collections


class RateBudget:
    """Allows at most `cap` calls within any trailing `window_s` seconds."""

    def __init__(self, cap, window_s=86400):
        self.cap = cap
        self.window_s = window_s
        self._calls = collections.deque()

    def _evict(self, now):
        while self._calls and self._calls[0] <= now - self.window_s:
            self._calls.popleft()

    def allow(self, now):
        self._evict(now)
        return len(self._calls) < self.cap

    def record(self, now):
        self._calls.append(now)

    def count(self, now):
        self._evict(now)
        return len(self._calls)


def clamp_interval(seconds, floor=120, default=300):
    """Never poll faster than `floor` s; fall back to `default` on bad input."""
    try:
        return max(floor, int(seconds))
    except (TypeError, ValueError):
        return default
