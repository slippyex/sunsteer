"""Shelly Gen2 RPC client — READ-ONLY (Switch.GetStatus). No Switch.Set."""
import json
import urllib.request


def parse_switch_status(d: dict) -> dict:
    temp = d.get("temperature") or {}
    return {
        "relay_on": bool(d.get("output", False)),
        "power_w": float(d.get("apower", 0.0)),
        "energy_wh_total": float((d.get("aenergy") or {}).get("total", 0.0)),
        "voltage": d.get("voltage"),
        "temperature_c": temp.get("tC"),
    }


def fetch_status(base_url: str, switch_id: int = 0, timeout: float = 5.0):
    """GET http://<host>/rpc/Switch.GetStatus?id=<id>. Returns parsed dict or None."""
    url = f"{base_url.rstrip('/')}/rpc/Switch.GetStatus?id={switch_id}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return parse_switch_status(json.load(resp))
    except Exception:
        return None
