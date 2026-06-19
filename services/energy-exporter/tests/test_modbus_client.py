import sys
import types

import src.drivers.sma_modbus as mb
from src.drivers.sma_modbus import parse_s32, parse_u32, parse_u64


def test_read_holding_registers_kwargs_match_installed_pymodbus():
    # Guard against the API drift that broke 0.3.2: pymodbus renamed the unit-id kwarg
    # slave= -> device_id=. The hand-written fakes below can't catch an upstream change,
    # so bind this to the REAL installed signature — a future breaking bump fails loudly here.
    import inspect

    from pymodbus.client import ModbusTcpClient
    params = inspect.signature(ModbusTcpClient.read_holding_registers).parameters
    assert "device_id" in params, "read_inverter passes device_id=; pymodbus no longer accepts it"
    assert "count" in params
    assert "slave" not in params, "pymodbus still has slave=; revisit the read_inverter call"


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
    def read_holding_registers(self, addr, count=2, device_id=3):
        return _Resp(_REGMAP[addr])


def test_read_inverter_maps_all_fields(monkeypatch):
    # read_inverter lazy-imports pymodbus.client -> inject a fake module
    monkeypatch.setitem(sys.modules, "pymodbus.client",
                        types.SimpleNamespace(ModbusTcpClient=_FakeClient))
    r = mb.read_inverter("1.2.3.4")
    assert r["production_w"] == 5000.0 and r["total_yield_kwh"] == 100.0
    assert r["strings"] == [
        {"idx": 1, "power": 4000.0, "voltage": 400.0, "current": 10.0},
        {"idx": 2, "power": 400.0, "voltage": 360.0, "current": 1.0},
    ]
    assert "dc_power_a" not in r and "dc_power_b" not in r   # flat keys removed in 0.6.0
    assert r["temp_c"] == 43.3 and r["operating_state"] == 307 and r["riso_ohm"] == 740287
    assert r["ac_v_l1"] == 230.0 and r["grid_freq"] == 50.0


def test_read_inverter_nan_total_yield_is_none_not_zero(monkeypatch):
    # A NaN lifetime-yield register must map to None (-> NULL in TSDB), never 0.0: writing a 0
    # into the monotonic production_kwh_total counter is a spurious reset that corrupts any
    # delta/increase query (and the controller's daily_production calibration).
    regmap = dict(_REGMAP)
    regmap[30513] = [0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF]   # U64 NaN sentinel (register read OK)

    class _FakeNanTotal(_FakeClient):
        def read_holding_registers(self, addr, count=2, device_id=3):
            return _Resp(regmap[addr])

    monkeypatch.setitem(sys.modules, "pymodbus.client",
                        types.SimpleNamespace(ModbusTcpClient=_FakeNanTotal))
    r = mb.read_inverter("1.2.3.4")
    assert r is not None                   # registers readable -> inverter still reachable
    assert r["total_yield_kwh"] is None    # NOT 0.0
    assert r["production_w"] == 5000.0     # unrelated fields unaffected


def test_read_inverter_logs_on_failure(monkeypatch, caplog):
    # A failing inverter read must be logged (with cause), not swallowed into an indistinct
    # None — else a code bug looks identical to "inverter off at night".
    import logging

    class _Boom(_FakeClient):
        def read_holding_registers(self, addr, count=2, device_id=3):
            raise RuntimeError("modbus exploded")

    monkeypatch.setitem(sys.modules, "pymodbus.client",
                        types.SimpleNamespace(ModbusTcpClient=_Boom))
    with caplog.at_level(logging.WARNING):
        r = mb.read_inverter("1.2.3.4")
    assert r is None
    assert any("modbus exploded" in rec.message or rec.exc_info for rec in caplog.records)
