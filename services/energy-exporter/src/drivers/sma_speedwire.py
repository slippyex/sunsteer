"""SMA Speedwire (SHM 2.0) grid-meter driver: multicast join + telegram decode."""
import socket
import struct

from ..sma_decoder import decode_em_telegram

MCAST_GRP = "239.12.255.254"   # fixed by the Speedwire protocol
MCAST_PORT = 9522


class SmaSpeedwireMeter:
    """GridMeter protocol for the SMA Sunny Home Manager 2.0."""

    def __init__(self, shm_host):
        self.shm_host = shm_host   # source filter: only telegrams from this sender

    def run(self, on_reading):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("", MCAST_PORT))
        mreq = struct.pack("4sl", socket.inet_aton(MCAST_GRP), socket.INADDR_ANY)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        while True:
            data, addr = s.recvfrom(2048)
            if addr[0] != self.shm_host or len(data) < 100:
                continue
            r = decode_em_telegram(data)
            if r:
                on_reading(r)
