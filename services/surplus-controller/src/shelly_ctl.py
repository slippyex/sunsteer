"""Shelly Gen2 RPC write path (Switch.Set) with auto-off watchdog."""
import json
import urllib.request


def get_switch(base_url, switch_id=0, timeout=5.0):
    """Read the Shelly's actual relay state (Switch.GetStatus -> output).
    Returns True/False, or None if unreachable. Used at startup to seed the
    commanded state from hardware so a controller restart doesn't re-log a
    spurious 'switched_on' while the relay is already on."""
    url = f"{base_url.rstrip('/')}/rpc/Switch.GetStatus?id={switch_id}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return bool(json.load(resp).get("output"))
    except Exception:
        return None


def build_set_url(base_url: str, on: bool, switch_id: int, auto_off_s: int) -> str:
    """Switch.Set URL. When turning ON, 'toggle_after' arms the Shelly auto-off watchdog:
    if the controller stops re-arming, the relay flips back OFF after auto_off_s."""
    b = base_url.rstrip("/")
    q = f"id={switch_id}&on={'true' if on else 'false'}"
    if on and auto_off_s:
        q += f"&toggle_after={auto_off_s}"
    return f"{b}/rpc/Switch.Set?{q}"


def set_switch(base_url, on, switch_id=0, auto_off_s=60, timeout=5.0) -> bool:
    """Returns True on success, False on any error."""
    url = build_set_url(base_url, on, switch_id, auto_off_s)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False
