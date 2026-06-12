"""SMA Energy-Meter (Speedwire) telegram decoder. Pure, no I/O."""
import struct

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


def decode_em_telegram(data: bytes):
    if len(data) < 28 or data[0:3] != b"SMA":
        return None
    serial = struct.unpack(">I", data[20:24])[0]
    raw = {}
    pos, n = 28, len(data)
    while pos + 4 <= n:
        index = data[pos + 1]
        typ = data[pos + 2]
        if typ == 4 and pos + 8 <= n:
            val = struct.unpack(">I", data[pos + 4:pos + 8])[0]
            if index in _ACTUAL:
                field, fac = _ACTUAL[index]
                raw[field] = val * fac
            pos += 8
        elif typ == 8 and pos + 12 <= n:
            val = struct.unpack(">Q", data[pos + 4:pos + 12])[0]
            if index in _COUNTER:
                raw[_COUNTER[index]] = val * _WS_TO_KWH
            pos += 12
        else:
            pos += 4

    import_w = raw.get("import_w", 0.0)
    export_w = raw.get("export_w", 0.0)
    out = {
        "serial": serial,
        "import_w": import_w,
        "export_w": export_w,
        "surplus_w": export_w - import_w,
        "import_kwh_total": raw.get("import_kwh_total", 0.0),
        "export_kwh_total": raw.get("export_kwh_total", 0.0),
    }
    for ph in ("l1", "l2", "l3"):
        out[f"{ph}_w"] = raw.get(f"{ph}_export", 0.0) - raw.get(f"{ph}_import", 0.0)
    return out
