"""energy-exporter: SHM multicast + Shelly poll -> Prometheus + TimescaleDB. READ-ONLY."""
import os
import socket
import struct
import threading
import time

from prometheus_client import start_http_server

from . import metrics
from . import state_server
from .sma_decoder import decode_em_telegram
from .shelly_client import fetch_status
from .modbus_client import read_inverter
from . import tsdb_writer

MCAST_GRP = "239.12.255.254"
MCAST_PORT = 9522

SHM_FILTER = os.environ.get("SHM_HOST", "192.168.2.44")
SHELLY_URL = os.environ.get("SHELLY_URL", "http://192.168.2.90")
INVERTER_HOST = os.environ.get("INVERTER_HOST", "192.168.2.68")
INVERTER_PORT = int(os.environ.get("INVERTER_PORT", "502"))
INVERTER_UNIT = int(os.environ.get("INVERTER_UNIT_ID", "3"))
METRICS_PORT = int(os.environ.get("METRICS_PORT", "9120"))
STATE_PORT = int(os.environ.get("STATE_PORT", "9121"))
SHELLY_POLL_S = int(os.environ.get("SHELLY_POLL_SECONDS", "10"))
INVERTER_POLL_S = int(os.environ.get("INVERTER_POLL_SECONDS", "10"))
FLUSH_S = int(os.environ.get("TSDB_FLUSH_SECONDS", "60"))

_buf = []
_buf_lock = threading.Lock()
_last_shelly = None
_last_inverter = None


def shm_listener():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("", MCAST_PORT))
    mreq = struct.pack("4sl", socket.inet_aton(MCAST_GRP), socket.INADDR_ANY)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    while True:
        data, addr = s.recvfrom(2048)
        if addr[0] != SHM_FILTER or len(data) < 100:
            continue
        r = decode_em_telegram(data)
        if not r:
            continue
        metrics.update_shm(r)
        # set_shm (not set_state) so /state carries a fresh shm_age_s — the controller
        # fails the WP safe-off when this stops updating (SHM multicast lost).
        state_server.set_shm(surplus_w=r["surplus_w"], import_w=r["import_w"],
                             export_w=r["export_w"])
        with _buf_lock:
            _buf.append(r)


def shelly_poller():
    global _last_shelly
    while True:
        _last_shelly = fetch_status(SHELLY_URL)
        metrics.update_shelly(_last_shelly)
        if _last_shelly:
            state_server.set_state(shelly_on=_last_shelly["relay_on"],
                                   shelly_power_w=_last_shelly["power_w"], shelly_reachable=True)
        else:
            state_server.set_state(shelly_reachable=False)
        time.sleep(SHELLY_POLL_S)


def inverter_poller():
    global _last_inverter
    while True:
        _last_inverter = read_inverter(INVERTER_HOST, INVERTER_PORT, INVERTER_UNIT)
        metrics.update_inverter(_last_inverter)
        if _last_inverter:
            state_server.set_state(production_w=_last_inverter["production_w"])
        time.sleep(INVERTER_POLL_S)


def tsdb_flusher(connect_fn):
    conn = None
    while True:
        time.sleep(FLUSH_S)
        with _buf_lock:
            samples, _buf[:] = list(_buf), []
        agg = tsdb_writer.aggregate_samples(samples)
        try:
            conn = tsdb_writer.live_conn(conn, connect_fn)  # reconnect across DB restarts
            if agg:
                if _last_inverter:
                    agg["production_w"] = _last_inverter["production_w"]
                    agg["production_kwh_total"] = _last_inverter["total_yield_kwh"]
                    agg["dc_power_a_w"] = _last_inverter.get("dc_power_a")
                    agg["dc_power_b_w"] = _last_inverter.get("dc_power_b")
                    agg["inverter_temp_c"] = _last_inverter.get("temp_c")
                tsdb_writer.write_meter(conn, agg)
            if _last_shelly:
                tsdb_writer.write_heatpump(conn, _last_shelly)
        except Exception:
            metrics.POLL_ERRORS.labels("tsdb").inc()
            conn = None  # force reconnect next cycle


def main():
    start_http_server(METRICS_PORT)
    def db_connect():
        return tsdb_writer.connect(
            os.environ["DB_HOST"], int(os.environ.get("DB_PORT", "5432")),
            os.environ["DB_NAME"], os.environ["DB_USER"], os.environ["DB_PASS"])
    threading.Thread(target=state_server.serve, args=(STATE_PORT,), daemon=True).start()
    threading.Thread(target=shm_listener, daemon=True).start()
    threading.Thread(target=shelly_poller, daemon=True).start()
    threading.Thread(target=inverter_poller, daemon=True).start()
    threading.Thread(target=tsdb_flusher, args=(db_connect,), daemon=True).start()
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
