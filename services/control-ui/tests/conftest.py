"""Required env for importing src.app in tests — dummy values, no real services."""
import os

for _k, _v in {"PV_LAT": "50.0", "PV_LON": "8.0",
               "DB_USER": "x", "DB_PASS": "x"}.items():
    os.environ.setdefault(_k, _v)
