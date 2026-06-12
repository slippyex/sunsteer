"""Tiny JSON /state endpoint exposing the latest live values for the controller."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_latest = {}
_shm_ts = None          # wall-clock of the last SHM telegram -> freshness for the controller
_lock = threading.Lock()


def set_state(**kw):
    """Update slow/secondary values (Shelly, inverter) WITHOUT touching SHM freshness."""
    with _lock:
        _latest.update(kw)


def set_shm(**kw):
    """Update the SHM-derived live values and stamp freshness. The controller treats a
    missing/old stamp as 'blind' and fails the WP safe-off, so only the real SHM telegram
    path may call this — never the Shelly/inverter pollers."""
    global _shm_ts
    with _lock:
        _latest.update(kw)
        _shm_ts = time.time()


def _snapshot():
    with _lock:
        snap = dict(_latest)
        snap["shm_age_s"] = round(time.time() - _shm_ts, 1) if _shm_ts is not None else None
    return snap


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/state":
            self.send_response(404); self.end_headers(); return
        body = json.dumps(_snapshot()).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # silence access logging
        pass


def serve(port):
    ThreadingHTTPServer(("", port), _Handler).serve_forever()
