"""Shelly Gen2 RPC relay driver: read state + Switch.Set with toggle_after auto-off watchdog."""
import json
import logging
import urllib.request

_log = logging.getLogger(__name__)


def build_set_url(base_url: str, on: bool, switch_id: int, auto_off_s: int | None) -> str:
    """Switch.Set URL. When turning ON, 'toggle_after' arms the Shelly auto-off watchdog."""
    b = base_url.rstrip("/")
    q = f"id={switch_id}&on={'true' if on else 'false'}"
    if on and auto_off_s:
        q += f"&toggle_after={auto_off_s}"
    return f"{b}/rpc/Switch.Set?{q}"


class ShellyRelayActuator:
    """Relay actuator for Shelly Gen2 RPC (read + Switch.Set with toggle_after watchdog)."""

    def __init__(self, base_url: str, switch_id: int = 0, timeout: float = 5.0):
        self.base_url = base_url
        self.switch_id = switch_id
        self.timeout = timeout

    def get_state(self) -> bool | None:
        url = f"{self.base_url.rstrip('/')}/rpc/Switch.GetStatus?id={self.switch_id}"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                return bool(json.load(resp).get("output"))
        except Exception:
            # Every-cycle poll -> debug only (no log spam), but the cause is captured so a
            # flapping/unreachable relay is diagnosable. Return value/behaviour unchanged.
            _log.debug("Shelly get_state failed (GET %s)", url, exc_info=True)
            return None

    def set(self, on: bool, auto_off_s: int | None) -> bool:
        """True only on HTTP 200 AND a non-error RPC body. Gen2 can return 200 with
        {"error": ...} — that must count as a failed switch."""
        # SAFETY: never emit an ON without an armed hardware auto-off watchdog. A
        # watchdog-less ON latches the relay forever if the controller dies, so a falsy
        # auto_off_s on an ON command is a hard failure — refuse it, send nothing.
        if on and not auto_off_s:
            _log.error("refusing ON without auto-off watchdog (auto_off_s=%r): a watchdog-less "
                       "ON would latch the relay forever if the controller dies", auto_off_s)
            return False
        url = build_set_url(self.base_url, on, self.switch_id, auto_off_s)
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                if resp.status != 200:
                    return False
                body = json.load(resp)
                return not (isinstance(body, dict) and "error" in body)
        except Exception:
            return False
