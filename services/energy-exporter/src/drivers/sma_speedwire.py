"""SMA Speedwire (SHM 2.0) grid-meter driver: multicast join + telegram decode."""
import socket
import struct

from ..sma_decoder import decode_em_telegram

MCAST_GRP = "239.12.255.254"   # fixed by the Speedwire protocol
MCAST_PORT = 9522
# The SHM 2.0 transmits every ~1-2 s. If recvfrom blocks longer than this the multicast
# is silent (meter off / IGMP membership dropped by a switch); we rebuild the socket to
# re-join rather than block forever on a dead membership. Generous vs the cadence so a
# brief blip doesn't churn sockets, well under the controller's stale fail-safe window.
RECV_TIMEOUT_S = 10.0


class SmaSpeedwireMeter:
    """GridMeter protocol for the SMA Sunny Home Manager 2.0."""

    def __init__(self, shm_host, recv_timeout_s=RECV_TIMEOUT_S, iface_ip=None):
        self.shm_host = shm_host           # source filter: only telegrams from this sender
        self.recv_timeout_s = recv_timeout_s
        self.iface_ip = iface_ip           # local NIC to join on; None = default-route interface

    def _membership_request(self):
        """Build the IP_ADD_MEMBERSHIP mreq. Default (no iface_ip) joins on the default-route
        interface (INADDR_ANY); a configured interface IP pins the join to one NIC — needed on
        multi-homed hosts (k8s hostNetwork) where the default route isn't the PV LAN."""
        grp = socket.inet_aton(MCAST_GRP)
        if self.iface_ip:
            return grp + socket.inet_aton(self.iface_ip)
        return struct.pack("4sl", grp, socket.INADDR_ANY)

    def _open_socket(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("", MCAST_PORT))
        s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, self._membership_request())
        s.settimeout(self.recv_timeout_s)   # detect silence instead of blocking forever
        return s

    def run(self, on_reading):
        sock = self._open_socket()
        try:
            while True:
                try:
                    data, addr = sock.recvfrom(2048)
                except TimeoutError:   # socket.settimeout fired: meter silent
                    # Meter went silent (multicast/IGMP membership lost). Rebuild the socket to
                    # re-join the group; shm_age_s keeps growing meanwhile so the controller
                    # fails the WP safe-off. Never leaves the thread alive-but-blind on a dead
                    # membership, which the rest of the fail-safe chain is built to rely on.
                    sock.close()
                    sock = self._open_socket()
                    continue
                if addr[0] != self.shm_host or len(data) < 100:
                    continue
                r = decode_em_telegram(data)
                if r:
                    on_reading(r)
        finally:
            sock.close()
