"""One-shot ViCare feasibility probe. Run locally with creds in env:
  VICARE_USER=... VICARE_PASS=... VICARE_CLIENT_ID=... python tools/probe.py
Prints the device model + a presence-check of the fields we care about, and writes
the raw fetch_all_features() to tests/fixtures/features_real.json."""
import json
import os
import tempfile

from PyViCare.PyViCare import PyViCare

# (datapoint_key, feature_name) we hope to ingest — checked for presence below.
WANTED = [
    ("dhw_temp_c", "heating.dhw.sensors.temperature.dhwCylinder"),
    ("dhw_target_c", "heating.dhw.temperature.main"),
    ("dhw_charging", "heating.dhw.charging"),
    ("dhw_mode", "heating.dhw.operating.modes.active"),
    ("buffer_temp_c", "heating.bufferCylinder.sensors.temperature.main"),
    ("outside_temp_c", "heating.sensors.temperature.outside"),
    ("supply_temp_c", "heating.secondaryCircuit.sensors.temperature.supply"),
    ("return_temp_c", "heating.secondaryCircuit.sensors.temperature.return"),
    ("energy_heating_kwh", "heating.power.consumption.heating"),
    ("energy_dhw_kwh", "heating.power.consumption.dhw"),
    ("energy_total_kwh", "heating.power.consumption.total"),
    ("active_program", "heating.circuits.0.operating.programs.active"),
    ("cop_total", "heating.cop.total"),
]


def main():
    vicare = PyViCare()
    token_file = os.path.join(tempfile.gettempdir(), "vicare_probe_token.json")
    vicare.initWithCredentials(
        os.environ["VICARE_USER"], os.environ["VICARE_PASS"],
        os.environ["VICARE_CLIENT_ID"], token_file)

    print("devices:", [d.getModel() for d in vicare.devices])

    # pick the heat-pump device: prefer a model containing "Vitocal", else the one
    # returning the most features (the gateway/room-control return very few).
    def feats_of(dc):
        raw = dc.service.fetch_all_features()
        return raw, raw.get("data", raw if isinstance(raw, list) else [])

    counts = []
    for dc in vicare.devices:
        try:
            _, fl = feats_of(dc)
            counts.append((dc, len(fl)))
            print(f"  {dc.getModel():28s} -> {len(fl)} features")
        except Exception as e:
            print(f"  {dc.getModel():28s} -> ERROR {e}")
    vitocal = next((dc for dc in vicare.devices if "vitocal" in dc.getModel().lower()), None)
    device = vitocal or max(counts, key=lambda c: c[1])[0]
    print(f"\n--> using device: {device.getModel()}")

    raw, feats = feats_of(device)
    present = {f.get("feature") for f in feats}
    print(f"total features returned: {len(feats)}\n")

    print("PRESENCE CHECK (wanted fields):")
    for key, name in WANTED:
        mark = "OK " if name in present else "-- "
        print(f"  [{mark}] {key:20s} {name}")

    # also surface any energy/cop/compressor/buffer features actually present
    print("\nENERGY / COP / COMPRESSOR / BUFFER features actually present:")
    for f in sorted(present):
        if any(k in f for k in ("power.consumption", "cop", "compressor", "buffer", "spf",
                                "heat.production")):
            print("   ", f)

    out = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures", "features_real.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(raw, f, indent=2)
    print(f"\nwrote {os.path.relpath(out)}")


if __name__ == "__main__":
    main()
