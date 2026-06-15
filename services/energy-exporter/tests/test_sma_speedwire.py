"""run() loop of the SMA Speedwire driver: the load-bearing meter source.

The real loop is infinite and does blocking multicast I/O. These tests drive it through
a fake socket injected via _open_socket(); the fake's recvfrom scripts a sequence and
raises StopLoop to break out so assertions can run on the recorded on_reading calls.
"""
import src.drivers.sma_speedwire as sw


class StopLoop(Exception):
    pass


class FakeSock:
    """Scripts recvfrom: each item is either ("bytes", addr), the str "timeout"
    (raise TimeoutError, what socket.settimeout raises), or the str "stop" (raise StopLoop).
    An exhausted script raises StopLoop too, so the infinite run() always terminates."""

    def __init__(self, script):
        self._script = list(script)
        self.closed = False

    def recvfrom(self, _n):
        if not self._script:
            raise StopLoop()
        item = self._script.pop(0)
        if item == "timeout":
            raise TimeoutError()
        if item == "stop":
            raise StopLoop()
        return item

    def close(self):
        self.closed = True


def _drive(monkeypatch, scripts):
    """Run meter.run() with _open_socket returning the given fake sockets in order.
    Returns (readings, sockets) — what on_reading saw and the fakes that were opened."""
    sockets = [FakeSock(s) for s in scripts]
    opened = []

    def fake_open(_self):
        sock = sockets[len(opened)]
        opened.append(sock)
        return sock

    monkeypatch.setattr(sw.SmaSpeedwireMeter, "_open_socket", fake_open)
    meter = sw.SmaSpeedwireMeter("192.168.0.5")
    readings = []
    try:
        meter.run(readings.append)
    except StopLoop:
        pass
    return readings, opened


def test_dispatches_a_valid_telegram_from_the_configured_host(monkeypatch):
    monkeypatch.setattr(sw, "decode_em_telegram", lambda data: {"surplus_w": 42.0})
    data = b"x" * 120
    readings, _ = _drive(monkeypatch, [[(data, ("192.168.0.5", 9522)), "stop"]])
    assert readings == [{"surplus_w": 42.0}]


def test_ignores_telegrams_from_a_foreign_source(monkeypatch):
    # Source-IP filter: a telegram from anything other than the configured SHM host
    # must never reach the decoder / on_reading.
    monkeypatch.setattr(sw, "decode_em_telegram", lambda data: {"surplus_w": 1.0})
    data = b"x" * 120
    readings, _ = _drive(monkeypatch, [[(data, ("10.0.0.99", 9522)), "stop"]])
    assert readings == []


def test_drops_undersized_telegrams(monkeypatch):
    # A runt packet (<100 bytes) is not a valid EM telegram — dropped before decode.
    monkeypatch.setattr(sw, "decode_em_telegram", lambda data: {"surplus_w": 1.0})
    readings, _ = _drive(monkeypatch, [[(b"x" * 50, ("192.168.0.5", 9522)), "stop"]])
    assert readings == []


def test_rebuilds_socket_on_timeout_then_keeps_reading(monkeypatch):
    # The core fix: a silent meter (multicast lost / IGMP membership dropped) makes
    # recvfrom time out. run() must close + reopen the socket (re-join the group) and
    # keep going, NOT block forever on a dead membership.
    monkeypatch.setattr(sw, "decode_em_telegram", lambda data: {"surplus_w": 7.0})
    data = b"x" * 120
    readings, opened = _drive(monkeypatch, [
        ["timeout"],                                   # first socket goes silent
        [(data, ("192.168.0.5", 9522)), "stop"],       # rebuilt socket delivers a reading
    ])
    assert readings == [{"surplus_w": 7.0}]
    assert len(opened) == 2          # socket was rebuilt
    assert opened[0].closed is True  # the silent socket was closed


import socket as _sock
import struct as _struct


def test_membership_request_defaults_to_any_interface():
    # No interface configured -> join on the default-route NIC (INADDR_ANY), unchanged behaviour.
    meter = sw.SmaSpeedwireMeter("192.168.0.5")
    assert meter._membership_request() == _struct.pack(
        "4sl", _sock.inet_aton(sw.MCAST_GRP), _sock.INADDR_ANY)


def test_membership_request_pins_configured_interface():
    # On a multi-homed host (k8s hostNetwork) the default route may not be the PV LAN; an
    # explicit interface IP pins the multicast join to the right NIC.
    meter = sw.SmaSpeedwireMeter("192.168.0.5", iface_ip="192.168.1.50")
    assert meter._membership_request() == (
        _sock.inet_aton(sw.MCAST_GRP) + _sock.inet_aton("192.168.1.50"))
