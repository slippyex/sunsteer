import struct
from src.sma_decoder import decode_em_telegram

def build_telegram(actuals, counters, serial=1234567):
    # 28-byte header: "SMA\0" + filler to offset 20, serial at 20..24, filler to 28
    head = b"SMA\x00" + b"\x00" * 16
    head += struct.pack(">I", serial)        # offset 20..24
    head += b"\x00" * 4                       # offset 24..28
    body = b""
    for index, val in actuals:                # type 4 = 4-byte actual (0.1 W)
        body += bytes([0, index, 4, 0]) + struct.pack(">I", val)
    for index, val in counters:               # type 8 = 8-byte counter (Ws)
        body += bytes([0, index, 8, 0]) + struct.pack(">Q", val)
    return head + body

def test_decode_extracts_power_and_counters():
    tg = build_telegram(
        actuals=[(1, 3000), (2, 0), (21, 3000), (41, 0), (61, 0)],   # import 300.0 W via L1
        counters=[(1, 3_600_000), (2, 7_200_000)],                   # 1 kWh import, 2 kWh export
    )
    r = decode_em_telegram(tg)
    assert r["serial"] == 1234567
    assert round(r["import_w"], 1) == 300.0
    assert round(r["export_w"], 1) == 0.0
    assert round(r["surplus_w"], 1) == -300.0          # export - import
    assert round(r["l1_w"], 1) == -300.0               # l1 import positive -> consumption negative surplus
    assert round(r["import_kwh_total"], 3) == 1.0
    assert round(r["export_kwh_total"], 3) == 2.0

def test_decode_rejects_non_sma():
    assert decode_em_telegram(b"XXXX" + b"\x00" * 40) is None
