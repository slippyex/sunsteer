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


class ShellyRelayReader:
    """Read-only relay status reader for Shelly Gen2 (Switch.GetStatus)."""

    def __init__(self, base_url, switch_id=0):
        self.base_url = base_url
        self.switch_id = switch_id

    def get_state(self):
        return fetch_status(self.base_url, self.switch_id)


def parse_em_status(d: dict) -> dict:
    """Parse Shelly Pro 3EM EM.GetStatus (triphase) into total + per-phase active power (W).
    Missing fields read as 0.0 so a partial payload never crashes the poll cycle."""
    return {
        "power_w": float(d.get("total_act_power", 0.0)),
        "l1_w": float(d.get("a_act_power", 0.0)),
        "l2_w": float(d.get("b_act_power", 0.0)),
        "l3_w": float(d.get("c_act_power", 0.0)),
    }


def fetch_em_status(base_url: str, em_id: int = 0, timeout: float = 5.0):
    """GET http://<host>/rpc/EM.GetStatus?id=<id>. Returns parsed dict or None."""
    url = f"{base_url.rstrip('/')}/rpc/EM.GetStatus?id={em_id}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return parse_em_status(json.load(resp))
    except Exception:
        return None


class ShellyEMReader:
    """Read-only 3-phase power reader for Shelly Pro 3EM (EM.GetStatus).

    Used for the heat-pump CT clamp: real measured power, unlike the SG-Ready Shelly 1PM
    (a signal contact that always reads 0 W)."""

    def __init__(self, base_url, em_id=0):
        self.base_url = base_url
        self.em_id = em_id

    def get_power(self):
        return fetch_em_status(self.base_url, self.em_id)
