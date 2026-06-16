# Hardware notes

What Sunsteer is tested with, what each device actually provides, and the traps we ran
into so you don't have to.

## SMA Sunny Home Manager 2.0

The grid meter and the system's single source of truth for surplus.

- It broadcasts Speedwire telegrams (~1/s) to the multicast group
  `239.12.255.254:9522`. The exporter joins that group and filters by sender IP
  (`SHM_HOST`).
- **Multicast does not cross Docker's bridge NAT** — the exporter container runs with
  `network_mode: host`. It also rarely crosses routers/VLANs without extra work
  (IGMP snooping/querier settings); easiest is putting the Docker host on the same L2
  segment as the SHM.
- Sunsteer only *listens*. It does not talk to the SHM, does not touch its
  configuration, and coexists with whatever the SMA ecosystem does.

## Shelly relay at the SG-Ready input

- Tested with the **Shelly Pro 1PM** (Gen2 RPC API). Any Gen2 relay with a
  potential-free-capable output should work — the controller uses
  `Switch.Set`/`Switch.GetStatus` with `toggle_after` as the auto-off watchdog.
- **The relay is a signal contact here, not a power switch.** It closes the SG-Ready
  input of the heat pump; the pump's own controller decides what to do with that
  recommendation. Consequence: the Shelly's power measurement reads **0 W** — that is
  correct and expected in this wiring, not a bug.
- Want real heat-pump power consumption? Add a CT-clamp meter (e.g. **Shelly EM /
  Pro 3EM**) on the heat pump's supply line. Until then, Sunsteer estimates energy
  as `runtime × wp_nominal_power_w` — clearly labelled as an estimate in the UI.
- **Wire it via Ethernet if you can** (the Pro 1PM has RJ45). A relay on weak
  basement WiFi drops off the network, the auto-off watchdog fires, and your decision
  log fills with `external_change` entries. We measured −87 dBm in a basement: ~1-min
  dropouts several times per hour. A mesh repeater (−67 dBm) or a cable ends that.
- The auto-off watchdog (`SHELLY_AUTOOFF_SECONDS`, default 60 s) is a **feature**:
  if the controller dies, the relay releases SG-Ready on its own. Only raise it if
  dropouts force you to — and fix the network instead.

## SMA inverter via Modbus TCP (optional)

Per-string DC power, device temperature, insulation resistance, lifetime yield —
nice-to-have telemetry for the UI and Grafana, not used by the control loop.

- Tested with a **Sunny Tripower X**: enable Modbus TCP in the inverter's web UI
  (port `502`), unit ID is typically `3` (`INVERTER_UNIT_ID`).
- Register layout is the SMA device profile; the implementation is in
  `services/energy-exporter/src/drivers/sma_modbus.py`. Other SMA models likely work
  but are unverified.
- Leave `INVERTER_HOST` empty to disable entirely.

## Heat-pump telemetry — `vicare` driver

The `heatpump-exporter` service provides optional heat-pump telemetry (temperatures,
compressor speed/starts, energy counters). Select the driver with `HEATPUMP_DRIVER`
(default `vicare`). The `mock` driver produces synthetic telemetry for the demo — no
credentials or vendor hardware required.

**`vicare` driver** — Viessmann ViCare cloud API quirks (driver-specific):

- The API provides **no instantaneous power** (only cumulative, estimated kWh counters),
  and those counters lag — **thermal posts before electrical, sometimes days**. Sunsteer's
  UI labels affected figures accordingly (e.g. COP shown as "–" until both sides reported).
- Polling is rate-budgeted (`VICARE_DAILY_CAP`) to stay inside Viessmann's API limits.
- Strictly informative: the control loop never depends on it. Set `HEATPUMP_DRIVER=mock`
  (or omit the service entirely) if you don't use the ViCare API — surplus control works
  the same.

For the full contract (DB table, Prometheus metrics, "bring your own driver"):
[docs/heatpump-interface.md](heatpump-interface.md).

## The heat pump itself

Sunsteer talks to the pump exclusively through the **SG-Ready contact**. What the
closed contact means (raise DHW/buffer setpoints, run now, …) is configured **in the
heat pump**, per its manufacturer's documentation. Set that up first and test it
manually — Sunsteer can only be as useful as the response your pump is configured to
give. See [DISCLAIMER.md](../DISCLAIMER.md) for the safety notes.

## Other meters?

The meter interface is pluggable — see the two extension paths in
[CONTRIBUTING.md](../CONTRIBUTING.md) and the [`/state` contract](state-interface.md).
Roadmap candidates: Shelly Pro 3EM at the feed-in point, Tibber Pulse, P1/DSMR.
