# The relay interface — actuator contract

The surplus-controller drives the heat pump through a `RelayActuator` (the write side,
`services/surplus-controller/src/relays/`). The energy-exporter separately reads relay
status through a `RelayReader` (read-only, `services/energy-exporter/src/drivers/`) — the
two are deliberately distinct: only the controller may actuate.

## RelayActuator (controller, safety-critical)

```python
def get_state(self) -> bool | None:   # actual relay state, None if unreachable
def set(self, on: bool, auto_off_s: int) -> bool:   # command; True only on confirmed success
```

### The hardware auto-off watchdog is a REQUIRED capability

`set(on=True, auto_off_s)` MUST arm a **hardware** auto-off timer of `auto_off_s` seconds on
the relay device. The controller re-arms it every cycle; if the controller dies or wedges,
the relay releases on its own — this is the last layer of the fail-safe chain (see
docs/architecture.md). A relay that cannot self-release after a timeout is **not supported**:
there is no software-watchdog fallback. Conformance:

- `set(True, N)` arms the device watchdog for N seconds (Shelly: `Switch.Set?...&toggle_after=N`).
- `set(...)` returns `True` ONLY on confirmed success — a transport error OR an application-level
  error response (e.g. Shelly Gen2 returns HTTP 200 with `{"error": ...}`) MUST return `False`,
  so the controller does not record an unconfirmed switch as done.
- `get_state()` returns the device's real state, or `None` when unreachable (the controller
  treats `None`/unreachable as a reason to fail safe).

Select the driver with `RELAY_DRIVER` (default `shelly`). Add one by implementing the protocol
in `src/relays/`, adding its key to `SUPPORTED_RELAYS`, and a branch in `get_relay()`.

## RelayReader (exporter, read-only)

```python
def get_state(self) -> dict | None:   # {relay_on, power_w, voltage, temperature_c, ...} or None
```

Read-only status for the `/state` JSON and Prometheus. It MUST NOT actuate (no Switch.Set).
