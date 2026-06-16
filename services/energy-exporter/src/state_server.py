"""Tiny JSON /state endpoint exposing the latest live values for the controller."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_latest = {}
_shm_ts = None          # wall-clock of the last SHM telegram -> freshness for the controller
_production_ts = None   # wall-clock of the last good inverter read -> freshness for production_w
_lock = threading.Lock()

PRODUCTION_FRESH_S = 90  # inverter polls ~10s; tolerate a few misses before dropping production_w


def set_state(**kw):
    """Update slow/secondary values (Shelly, inverter) WITHOUT touching SHM freshness."""
    with _lock:
        _latest.update(kw)


def set_production(production_w):
    """Inverter production + its own freshness stamp. Kept separate from set_state so a stale
    inverter (frozen last value) is DROPPED from /state, not served as if live — the
    controller computes consumption = production - surplus and must not trust a frozen value."""
    global _production_ts
    with _lock:
        _latest["production_w"] = production_w
        _production_ts = time.time()


def set_shm(**kw):
    """Update the SHM-derived live values and stamp freshness. The controller treats a
    missing/old stamp as 'blind' and fails the WP safe-off, so only the real SHM telegram
    path may call this — never the Shelly/inverter pollers."""
    global _shm_ts
    with _lock:
        _latest.update(kw)
        _shm_ts = time.time()


SCHEMA_VERSION = 1   # bump on breaking /state changes; contract: docs/state-interface.md


def _snapshot():
    with _lock:
        snap = dict(_latest)
        snap["schema"] = SCHEMA_VERSION
        snap["shm_age_s"] = round(time.time() - _shm_ts, 1) if _shm_ts is not None else None
        if _production_ts is None or (time.time() - _production_ts) > PRODUCTION_FRESH_S:
            snap.pop("production_w", None)
    return snap


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/state":
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(_snapshot()).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # silence access logging
        pass


def serve(port, bind=""):
    # bind "" = all interfaces (default); pass a specific IP to restrict /state exposure.
    ThreadingHTTPServer((bind, port), _Handler).serve_forever()
