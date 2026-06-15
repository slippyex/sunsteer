"""Rolling-window API call budget + poll-interval floor. Wall-clock injected; optionally
persisted so a restart does NOT grant a fresh daily quota against ViCare's server-side cap."""
import collections
import json
import logging
import os

log = logging.getLogger(__name__)


class RateBudget:
    def __init__(self, cap, window_s=86400, persist_path=None):
        self.cap = cap
        self.window_s = window_s
        self.persist_path = persist_path
        self._calls = collections.deque()
        if persist_path and os.path.exists(persist_path):
            try:
                with open(persist_path) as f:
                    raw = json.load(f)
            except Exception:
                raw = []
            # Coerce entries individually: a single bad element must not discard the
            # whole persisted window (which would silently grant a fresh daily quota).
            self._calls = collections.deque(self._coerce(raw))

    @staticmethod
    def _coerce(raw):
        for x in raw:
            try:
                yield float(x)
            except (TypeError, ValueError):
                continue

    def _evict(self, now):
        while self._calls and self._calls[0] <= now - self.window_s:
            self._calls.popleft()

    def _save(self):
        if not self.persist_path:
            return
        try:
            tmp = self.persist_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(list(self._calls), f)
            os.replace(tmp, self.persist_path)
        except Exception as e:
            # Persisting must never break the poll loop, but a silent failure means a restart
            # would grant a fresh daily quota against ViCare's server cap — make it visible.
            log.warning("rate budget persist to %s failed: %s — a restart may reset the daily "
                        "quota (check the volume is writable / not full)", self.persist_path, e)

    def allow(self, now):
        self._evict(now)
        return len(self._calls) < self.cap

    def record(self, now):
        self._calls.append(now)
        self._save()

    def count(self, now):
        self._evict(now)
        return len(self._calls)


def clamp_interval(seconds, floor=120, default=300):
    """Never poll faster than `floor` s; fall back to `default` on bad input."""
    try:
        return max(floor, int(seconds))
    except (TypeError, ValueError):
        return default
