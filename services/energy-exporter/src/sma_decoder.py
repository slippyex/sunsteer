"""SMA Energy-Meter (Speedwire) telegram decoder. Pure, no I/O."""
from __future__ import annotations

import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:                       # avoid coupling the pure decoder to drivers at runtime
    from .drivers import MeterReading

# OBIS index -> (field, factor) for type-4 actual power (unit 0.1 W).
_ACTUAL = {
    1:  ("import_w", 0.1),
    2:  ("export_w", 0.1),
    21: ("l1_import", 0.1), 22: ("l1_export", 0.1),
    41: ("l2_import", 0.1), 42: ("l2_export", 0.1),
    61: ("l3_import", 0.1), 62: ("l3_export", 0.1),
}
# type-8 counters (Ws) -> kWh field
_COUNTER = {1: "import_kwh_total", 2: "export_kwh_total"}
_WS_TO_KWH = 1.0 / 3_600_000.0


def decode_em_telegram(data: bytes) -> MeterReading | None:
    if len(data) < 28 or data[0:3] != b"SMA":
        return None
    serial = struct.unpack(">I", data[20:24])[0]
    raw = {}
    pos, n = 28, len(data)
    while pos + 4 <= n:
        index = data[pos + 1]
        typ = data[pos + 2]
        # Each OBIS record is self-describing: 4-byte header + `typ` data bytes. Advance by that
        # full length (not a fixed 4) so an unknown/future record type can't misalign everything
        # after it. typ >= 0 keeps the stride >= 4, so the walk always terminates.
        step = 4 + typ
        if pos + step > n:
            break                       # truncated trailing record -> keep what we decoded
        if typ == 4:
            val = struct.unpack(">I", data[pos + 4:pos + 8])[0]
            if index in _ACTUAL:
                field, fac = _ACTUAL[index]
                raw[field] = val * fac
        elif typ == 8:
            val = struct.unpack(">Q", data[pos + 4:pos + 12])[0]
            if index in _COUNTER:
                raw[_COUNTER[index]] = val * _WS_TO_KWH
        pos += step

    import_w = raw.get("import_w", 0.0)
    export_w = raw.get("export_w", 0.0)
    # One MeterReading literal (per-phase nets computed inline) so the typed contract is
    # statically checkable — a dynamic-key loop would erase it back to a plain dict.
    return {
        "serial": serial,
        "import_w": import_w,
        "export_w": export_w,
        "surplus_w": export_w - import_w,
        "import_kwh_total": raw.get("import_kwh_total", 0.0),
        "export_kwh_total": raw.get("export_kwh_total", 0.0),
        "l1_w": raw.get("l1_export", 0.0) - raw.get("l1_import", 0.0),
        "l2_w": raw.get("l2_export", 0.0) - raw.get("l2_import", 0.0),
        "l3_w": raw.get("l3_export", 0.0) - raw.get("l3_import", 0.0),
    }
