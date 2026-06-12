import os
import subprocess
import sys

SERVICE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_validate_env_passes_with_conftest_env():
    from src import app
    app.validate_env()   # conftest seeds the required vars -> must not raise


def test_app_import_fails_fast_without_env():
    r = subprocess.run([sys.executable, "-c", "import src.app"],
                       capture_output=True, text=True, cwd=SERVICE_ROOT,
                       env={"PATH": os.environ["PATH"]})
    assert r.returncode == 1
    out = r.stderr + r.stdout
    for name in ("PV_LAT", "PV_LON", "DB_USER", "DB_PASS"):
        assert name in out
