"""energy-exporter: meter driver + Shelly poll -> Prometheus + TimescaleDB. READ-ONLY."""
import logging
import os
import threading
import time

from prometheus_client import start_http_server

from . import drivers, metrics, state_server, tsdb_writer
from .drivers.sma_modbus import read_inverter

log = logging.getLogger("energy_exporter")

def _pos_int(name, default, hi=3600):
    """Parse a sleep-/cadence-driving env into a safe positive int. A missing, non-numeric,
    zero/negative or absurd value falls back to the default — a bad value must never crash
    the exporter at import or spin a tight loop (sleep 0)."""
    try:
        v = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return v if 1 <= v <= hi else default


SHELLY_URL = os.environ.get("SHELLY_URL")          # optional in mock mode — validated in main()
METER_DRIVER = os.environ.get("METER_DRIVER", "sma_shm")
RELAY_DRIVER = os.environ.get("RELAY_DRIVER", "shelly")
INVERTER_HOST = os.environ.get("INVERTER_HOST", "")  # empty = inverter telemetry disabled
INVERTER_PORT = _pos_int("INVERTER_PORT", 502, hi=65535)
INVERTER_UNIT = _pos_int("INVERTER_UNIT_ID", 3, hi=255)
METRICS_PORT = _pos_int("METRICS_PORT", 9120, hi=65535)
STATE_PORT = _pos_int("STATE_PORT", 9121, hi=65535)
# Interface /state binds to. Default "" = all interfaces (the in-cluster controller reaches
# it via the node IP under hostNetwork). Set to a specific IP to restrict exposure.
STATE_BIND = os.environ.get("STATE_BIND", "")
SHELLY_POLL_S = _pos_int("SHELLY_POLL_SECONDS", 10)
INVERTER_POLL_S = _pos_int("INVERTER_POLL_SECONDS", 10)
FLUSH_S = _pos_int("TSDB_FLUSH_SECONDS", 60)

REQUIRED_ENV_BASE = ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASS")
REQUIRED_ENV_HARDWARE = ("SHM_HOST", "SHELLY_URL")   # required for hardware drivers; mock needs neither


def validate_env():
    """Fail fast with one clear message instead of half-starting against nothing."""
    driver = os.environ.get("METER_DRIVER", "sma_shm")
    if driver not in drivers.SUPPORTED_METERS:
        raise SystemExit(f"energy-exporter: unknown METER_DRIVER '{driver}' "
                         f"(supported: {', '.join(drivers.SUPPORTED_METERS)})")
    required = list(REQUIRED_ENV_BASE)
    if driver != "mock":
        required += REQUIRED_ENV_HARDWARE
    missing = [n for n in required if not os.environ.get(n)]
    if missing:
        raise SystemExit("energy-exporter: missing required environment variables: "
                         + ", ".join(missing))
    # Example k8s manifests ship CHANGE_ME placeholders; an unsubstituted one means the
    # secret/configmap was never filled in — fail fast instead of dialing CHANGE_ME forever.
    placeholders = [n for n in required if "CHANGE_ME" in os.environ.get(n, "")]
    if placeholders:
        raise SystemExit("energy-exporter: unsubstituted CHANGE_ME placeholder in required "
                         "environment variables: " + ", ".join(placeholders))


_buf = []
_buf_lock = threading.Lock()
_last_shelly = None
_last_inverter = None


def run_guarded(name, cycle_fn, sleep_s):
    """Run cycle_fn() forever; a thrown cycle is counted and survived (a dead daemon
    thread would otherwise leave the process alive but blind on this source)."""
    while True:
        try:
            cycle_fn()
        except Exception:
            metrics.POLL_ERRORS.labels(name).inc()
            log.warning("poll cycle failed for source %s", name, exc_info=True)
        time.sleep(sleep_s)


def run_meter_guarded(meter, retry_s=5):
    """Run the meter driver's blocking loop; if it ever throws or returns, count it and
    restart. The meter is the load-bearing source — a dead meter thread silently blinds
    the controller (which then fails the WP safe-off), so it must self-recover, not die."""
    while True:
        try:
            meter.run(on_meter_reading)
        except Exception:
            metrics.POLL_ERRORS.labels("meter").inc()
            log.warning("meter run loop failed; restarting", exc_info=True)
        time.sleep(retry_s)


def on_meter_reading(r):
    try:
        metrics.update_shm(r)
        # set_shm (not set_state) so /state carries a fresh shm_age_s — the controller
        # fails the WP safe-off when this stops updating (meter readings lost).
        state_server.set_shm(surplus_w=r["surplus_w"], import_w=r["import_w"],
                             export_w=r["export_w"])
        with _buf_lock:
            _buf.append(r)
    except Exception:
        metrics.POLL_ERRORS.labels("meter").inc()
        log.warning("meter reading update failed", exc_info=True)


def _shelly_cycle(relay):
    global _last_shelly
    _last_shelly = relay.get_state()
    metrics.update_shelly(_last_shelly)
    if _last_shelly:
        state_server.set_state(shelly_on=_last_shelly["relay_on"],
                               shelly_power_w=_last_shelly["power_w"], shelly_reachable=True)
    else:
        log.debug("shelly poll returned no state (unreachable)")
        state_server.set_state(shelly_reachable=False)


def _inverter_cycle():
    global _last_inverter
    _last_inverter = read_inverter(INVERTER_HOST, INVERTER_PORT, INVERTER_UNIT)
    metrics.update_inverter(_last_inverter)
    if _last_inverter:
        state_server.set_state(production_w=_last_inverter["production_w"])
    else:
        log.debug("inverter modbus read returned no data (unreachable)")


_tsdb_conn = None


def _flush_once(connect_fn):
    """One flush cycle, guarded as a whole (run via run_guarded) so a throw anywhere —
    not just in the DB block — is counted under POLL_ERRORS{tsdb} and survived. The _buf
    swap happens first, so a later failure deliberately drops this minute's aggregate
    rather than re-buffering it (history gaps don't affect safety; /state is the control
    path) and _buf cannot grow unbounded."""
    global _tsdb_conn
    with _buf_lock:
        samples, _buf[:] = list(_buf), []
    agg = tsdb_writer.aggregate_samples(samples)
    inv, she = _last_inverter, _last_shelly   # snapshot once (pollers may swap to None mid-cycle)
    _tsdb_conn = tsdb_writer.live_conn(_tsdb_conn, connect_fn)  # reconnect across DB restarts
    try:
        if agg:
            if inv:
                agg["production_w"] = inv["production_w"]
                agg["production_kwh_total"] = inv["total_yield_kwh"]
                agg["dc_power_a_w"] = inv.get("dc_power_a")
                agg["dc_power_b_w"] = inv.get("dc_power_b")
                agg["inverter_temp_c"] = inv.get("temp_c")
            tsdb_writer.write_meter(_tsdb_conn, agg)
        if she:
            tsdb_writer.write_heatpump(_tsdb_conn, she)
    except Exception:
        _tsdb_conn = None  # force reconnect next cycle; run_guarded counts + survives
        log.warning("tsdb flush/write failed; will reconnect next cycle", exc_info=True)
        raise


def tsdb_flusher(connect_fn):
    run_guarded("tsdb", lambda: _flush_once(connect_fn), FLUSH_S)


def main():
    import sys
    logging.basicConfig(
        level=logging.INFO, stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    validate_env()
    start_http_server(METRICS_PORT)
    def db_connect():
        return tsdb_writer.connect(
            os.environ["DB_HOST"], _pos_int("DB_PORT", 5432, hi=65535),
            os.environ["DB_NAME"], os.environ["DB_USER"], os.environ["DB_PASS"])
    threading.Thread(target=state_server.serve, args=(STATE_PORT, STATE_BIND), daemon=True).start()
    meter = drivers.get_meter(METER_DRIVER)
    threading.Thread(target=run_meter_guarded, args=(meter,), daemon=True).start()
    if SHELLY_URL:
        _relay = drivers.get_relay(RELAY_DRIVER)
        threading.Thread(target=run_guarded, args=("shelly", lambda: _shelly_cycle(_relay), SHELLY_POLL_S), daemon=True).start()
    if INVERTER_HOST:
        threading.Thread(target=run_guarded, args=("inverter", _inverter_cycle, INVERTER_POLL_S), daemon=True).start()
    threading.Thread(target=tsdb_flusher, args=(db_connect,), daemon=True).start()
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
