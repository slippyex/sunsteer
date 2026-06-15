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


# --- M5: robustness of the OBIS record walk (length-driven, desync-proof) ---

def _header(serial=1234567):
    return b"SMA\x00" + b"\x00" * 16 + struct.pack(">I", serial) + b"\x00" * 4


def _actual_rec(index, val):
    return bytes([0, index, 4, 0]) + struct.pack(">I", val)


def test_unknown_record_between_known_ones_does_not_desync():
    # An OBIS record of an unexpected type carries its length in the header (4 + type bytes).
    # The walk must skip it by that length, not a fixed 4 — otherwise every record AFTER it is
    # misaligned and silently misread. Here index 2 (export) sits after a type-2 mystery record.
    unknown = bytes([0, 99, 2, 0]) + b"\xAA\xBB"        # type-2 record: 4 header + 2 data
    tg = _header() + _actual_rec(1, 3000) + unknown + _actual_rec(2, 5000)
    out = decode_em_telegram(tg)
    assert out["import_w"] == 300.0                      # 3000 * 0.1
    assert out["export_w"] == 500.0                      # only correct if alignment survived


def test_truncated_trailing_record_is_dropped_not_crashed():
    # A record header that claims 8 data bytes but the telegram is cut short must not over-read
    # or crash — the good records already decoded are kept.
    tg = _header() + _actual_rec(1, 3000) + bytes([0, 2, 8, 0]) + b"\x00\x00\x00"
    out = decode_em_telegram(tg)
    assert out is not None
    assert out["import_w"] == 300.0


def test_decoder_output_matches_the_meter_reading_contract():
    # The reading dict flowing decoder -> metrics -> writer is a TypedDict contract. Lock the
    # decoder's emitted keys to it so a renamed/added field can't silently drift from the spec.
    from src.drivers import MeterReading
    out = decode_em_telegram(build_telegram(actuals=[(1, 3000)], counters=[(1, 0)]))
    assert set(out.keys()) == set(MeterReading.__annotations__.keys())
