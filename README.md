# Sunsteer

**Local SG-Ready heat-pump control from PV surplus.**

Sunsteer reads your grid meter, decides when genuine PV surplus is available, and
switches your heat pump's SG-Ready input through a local relay — no cloud, fully
observable, with a web UI that explains every decision.

> ⚠️ **Status: extraction in progress.** This repository is being extracted from a
> private homelab setup. It is not yet ready for general use — configuration still
> contains environment-specific defaults. Watch the releases for `v0.1.0`.

## Services

| Service | Purpose |
|---|---|
| `services/energy-exporter` | Reads SMA Sunny Home Manager 2.0 (Speedwire multicast), Shelly relay state, and optional SMA inverter telemetry (Modbus); serves `/state` and Prometheus `/metrics`; writes to TimescaleDB |
| `services/surplus-controller` | The control loop: adaptive threshold from PV forecast, hysteresis, min-runtime/offtime, fail-safe OFF on stale data; switches the Shelly |
| `services/control-ui` | FastAPI web UI (EN/DE): live status, decision log with explanations, history charts, settings |
| `services/vicare-exporter` | Optional: Viessmann ViCare telemetry (temperatures, compressor, energy counters) |

## License

[MIT](LICENSE)
