"""SMA inverter reader via Modbus TCP — READ-ONLY (SMA register profile)."""
import logging

_log = logging.getLogger(__name__)

# SMA Modbus holding registers (SMA device profile, Sunny Tripower X — verified live 2026-06)
REG_AC_POWER = 30775      # S32, W  — current AC active power = production
REG_TOTAL_YIELD = 30513   # U64, Wh — lifetime yield (today's yield is derived in SQL from this)
# Per-MPPT DC registers (power S32 W, voltage U32 ×0.01 V, current U32 ×0.001 A), 1-based idx.
# Add a tuple here to read another MPPT once its registers are confirmed for the model.
_MPPTS = [
    (1, 30773, 30771, 30769),   # MPPT 1
    (2, 30961, 30959, 30957),   # MPPT 2
]
REG_TEMP = 30953          # S32, ×0.1 °C  — device/heatsink temperature
REG_OP_STATE = 30201      # U32 enum      — operating state (307 = Ok)
REG_RISO = 30225          # U32, ohm      — DC insulation resistance
REG_AC_V_L1, REG_AC_V_L2, REG_AC_V_L3 = 30783, 30785, 30787   # U32, ×0.01 V
REG_GRID_FREQ = 30803     # U32, ×0.01 Hz

_S32_NAN = 0x80000000              # SMA "no value" sentinel for S32 (e.g. night)
_U32_NAN = 0xFFFFFFFF              # SMA "no value" sentinel for U32
_U64_NAN = 0xFFFFFFFFFFFFFFFF      # SMA "no value" sentinel for U64


def parse_s32(regs):
    """Two big-endian 16-bit registers -> signed 32-bit int; SMA NaN -> None."""
    raw = (regs[0] << 16) | regs[1]
    if raw == _S32_NAN:
        return None
    return raw - 0x100000000 if raw >= 0x80000000 else raw


def parse_u32(regs):
    """Two big-endian 16-bit registers -> unsigned 32-bit int; SMA NaN -> None."""
    raw = (regs[0] << 16) | regs[1]
    return None if raw == _U32_NAN else raw


def parse_u64(regs):
    """Four big-endian 16-bit registers -> unsigned 64-bit int; SMA NaN -> None."""
    raw = 0
    for r in regs:
        raw = (raw << 16) | r
    return None if raw == _U64_NAN else raw


def build_strings(readings):
    """Keep only MPPTs whose power register read a real value (NaN/None -> array drops it)."""
    return [r for r in readings if r["power"] is not None]


def read_inverter(host, port=502, unit_id=3, timeout=5.0):
    """Read the inverter (READ-ONLY). production_w + total_yield_kwh gate reachability (None ->
    unreachable); the richer per-string/health fields are read tolerantly (a NaN/failed register
    -> None for that field only). Returns dict or None."""
    from pymodbus.client import ModbusTcpClient  # lazy import so unit tests need no pymodbus
    client = ModbusTcpClient(host, port=port, timeout=timeout)
    try:
        if not client.connect():
            return None

        def regs(addr, count):
            r = client.read_holding_registers(addr, count=count, device_id=unit_id)
            return None if r.isError() else r.registers

        def s32(addr):
            rs = regs(addr, 2)
            return parse_s32(rs) if rs else None

        def u32(addr):
            rs = regs(addr, 2)
            return parse_u32(rs) if rs else None

        def scaled(v, factor):
            return round(v * factor, 3) if v is not None else None

        p = regs(REG_AC_POWER, 2)
        ty = regs(REG_TOTAL_YIELD, 4)
        if p is None or ty is None:               # core registers unreadable -> unreachable
            return None
        power, total = parse_s32(p), parse_u64(ty)
        readings = [
            {"idx": i, "power": float(pw) if (pw := s32(rp)) is not None else None,
             "voltage": scaled(u32(rv), 0.01), "current": scaled(u32(ri), 0.001)}
            for i, rp, rv, ri in _MPPTS
        ]
        return {
            "production_w": float(power) if power is not None else 0.0,
            # NaN lifetime counter -> None (NULL in TSDB), never 0.0: a 0 in the monotonic
            # production_kwh_total reads as a counter reset and corrupts delta/increase queries.
            "total_yield_kwh": (total / 1000.0) if total is not None else None,
            "strings": build_strings(readings),
            "temp_c": scaled(s32(REG_TEMP), 0.1),
            "operating_state": u32(REG_OP_STATE),
            "riso_ohm": u32(REG_RISO),
            "ac_v_l1": scaled(u32(REG_AC_V_L1), 0.01),
            "ac_v_l2": scaled(u32(REG_AC_V_L2), 0.01),
            "ac_v_l3": scaled(u32(REG_AC_V_L3), 0.01),
            "grid_freq": scaled(u32(REG_GRID_FREQ), 0.01),
        }
    except Exception:
        # Log the cause so a code/register bug is distinguishable from "inverter unreachable"
        # (both return None -> INV_REACHABLE=0). Non-safety telemetry, so still degrade to None.
        _log.warning("inverter modbus read failed", exc_info=True)
        return None
    finally:
        client.close()
