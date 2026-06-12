import sys
import types

import src.drivers.sma_modbus as mb
from src.drivers.sma_modbus import parse_s32, parse_u32, parse_u64


def test_parse_s32_positive():
    assert parse_s32([0x0001, 0x86A0]) == 100000          # 0x000186A0 = 100000 W

def test_parse_s32_negative():
    assert parse_s32([0xFFFF, 0xFFFF]) == -1

def test_parse_s32_nan():
    assert parse_s32([0x8000, 0x0000]) is None            # SMA "no value" (e.g. night)

def test_parse_u32_value():
    assert parse_u32([0x0000, 0x96BB]) == 38587           # ×0.01 -> 385.87 V

def test_parse_u32_nan():
    assert parse_u32([0xFFFF, 0xFFFF]) is None

def test_parse_u64_value():
    assert parse_u64([0x0000, 0x0000, 0x0001, 0x86A0]) == 100000

def test_parse_u64_nan():
    assert parse_u64([0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF]) is None


# ── read_inverter mapping (fake Modbus client, no pymodbus needed) ──────────
class _Resp:
    def __init__(self, regs): self.registers = regs
    def isError(self): return False


_REGMAP = {
    30775: [0x0000, 0x1388],              # AC power S32 = 5000 W
    30513: [0, 0, 0x0001, 0x86A0],        # total yield U64 = 100000 Wh -> 100.0 kWh
    30773: [0x0000, 0x0FA0], 30771: [0x0000, 0x9C40], 30769: [0x0000, 0x2710],  # A: 4000 W / 400 V / 10 A
    30961: [0x0000, 0x0190], 30959: [0x0000, 0x8CA0], 30957: [0x0000, 0x03E8],  # B: 400 W / 360 V / 1 A
    30953: [0x0000, 0x01B1],              # temp S32 = 433 -> 43.3 °C
    30201: [0x0000, 0x0133],              # operating state = 307 (Ok)
    30225: [0x000B, 0x4BBF],              # riso = 740287 ohm
    30783: [0x0000, 0x59D8], 30785: [0x0000, 0x59D8], 30787: [0x0000, 0x59D8],  # AC V = 230 V
    30803: [0x0000, 0x1388],              # grid freq = 5000 -> 50.00 Hz
}


class _FakeClient:
    def __init__(self, *a, **k): pass
    def connect(self): return True
    def close(self): pass
    def read_holding_registers(self, addr, count=2, slave=3):
        return _Resp(_REGMAP[addr])


def test_read_inverter_maps_all_fields(monkeypatch):
    # read_inverter lazy-imports pymodbus.client -> inject a fake module
    monkeypatch.setitem(sys.modules, "pymodbus.client",
                        types.SimpleNamespace(ModbusTcpClient=_FakeClient))
    r = mb.read_inverter("1.2.3.4")
    assert r["production_w"] == 5000.0 and r["total_yield_kwh"] == 100.0
    assert r["dc_power_a"] == 4000.0 and r["dc_voltage_a"] == 400.0 and r["dc_current_a"] == 10.0
    assert r["dc_power_b"] == 400.0 and r["dc_voltage_b"] == 360.0 and r["dc_current_b"] == 1.0
    assert r["temp_c"] == 43.3 and r["operating_state"] == 307 and r["riso_ohm"] == 740287
    assert r["ac_v_l1"] == 230.0 and r["grid_freq"] == 50.0
