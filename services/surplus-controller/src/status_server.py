"""Controller status + health endpoints.

/status  — latest loop state for the UI (always 200).
/healthz — liveness: 200 only while the MAIN LOOP is beating; 503 if the loop hung.
           This is the point of the file: /status is served by this daemon thread and would
           stay 200 even if the decision loop deadlocked, so liveness must key off a heartbeat
           the loop itself updates, not off "is the HTTP thread alive".
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_status = {}
_beat = None          # wall-clock of the last completed loop iteration
_beat_max = 60.0      # loop considered hung if no beat within this many seconds
_lock = threading.Lock()


def set_status(**kw):
    with _lock:
        _status.update(kw)


def beat(max_age_s=60.0):
    """Called once per loop iteration. max_age_s = how stale the heartbeat may get before
    /healthz reports the loop dead (set to a few loop intervals)."""
    global _beat, _beat_max
    with _lock:
        _beat = time.time()
        _beat_max = max_age_s


def heartbeat_age():
    with _lock:
        return None if _beat is None else time.time() - _beat


def _alive():
    age = heartbeat_age()
    with _lock:
        max_age = _beat_max
    return age is not None and age <= max_age


def _snapshot():
    with _lock:
        return dict(_status)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/status":
            self._json(200, _snapshot())
        elif self.path == "/healthz":
            alive = _alive()
            age = heartbeat_age()
            self._json(200 if alive else 503,
                       {"ok": alive, "heartbeat_age_s": None if age is None else round(age, 1)})
        else:
            self.send_response(404); self.end_headers()

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def serve(port):
    ThreadingHTTPServer(("", port), _Handler).serve_forever()
