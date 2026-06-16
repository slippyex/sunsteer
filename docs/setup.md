# Setup

From zero to a controlled heat pump. Time budget: ~30 minutes of software setup —
plus the electrician appointment for the wiring.

## 1. Prerequisites

- **Grid meter:** SMA Sunny Home Manager 2.0 on your LAN (its Speedwire multicast must
  be receivable by the Docker host — same L2 network, no router in between).
- **Relay:** Shelly Gen2 with a potential-free-capable output (e.g. **Shelly Pro 1PM**
  — it also has an Ethernet port, which beats basement WiFi), wired to the heat
  pump's SG-Ready input. Wiring notes and warnings: [hardware.md](hardware.md) and
  [DISCLAIMER.md](../DISCLAIMER.md). **Have the wiring done by an electrician.**
- **Host:** any Linux box with Docker + Compose v2 on the same network. A Raspberry
  Pi 4/5 is plenty — all images ship `linux/arm64`.
- Give the Shelly (and ideally the SHM) a fixed IP/DHCP reservation.

No hardware yet? Run the [zero-config demo](../README.md#try-it-in-two-minutes-no-hardware-needed) first.

## 2. Configure

```bash
git clone https://github.com/slippyex/sunsteer.git
cd sunsteer/deploy/compose
cp .env.example .env
```

Fill in everything marked **REQUIRED** in `.env`:

- `SHM_HOST` — IP or hostname of the Sunny Home Manager (sender filter for the multicast;
  a hostname is resolved to an IP at startup). On a multi-homed host you can also set the
  optional `SMA_IFACE_IP` to pin the multicast join to the NIC on the SHM's segment.
- `SHELLY_URL` — e.g. `http://192.168.1.50`.
- `PV_LAT`, `PV_LON`, `PV_TZ` — site location and timezone (forecast + day boundaries).
- `PV_PLANES` — your roof as `[[declination, azimuth, kWp], ...]`;
  azimuth 0 = south, −90 = east, +90 = west. An east/west roof has two entries.
- `DB_PASS`, `ADMIN_PASS` — database and web-UI credentials. The UI refuses to start
  open: no `ADMIN_PASS`, no UI.

Optional but recommended on first setup: leave `SHELLY_AUTOOFF_SECONDS` at its 60 s
default; only raise it if your relay sits on genuinely flaky WiFi (better: use the
Pro 1PM's Ethernet port).

## 3. Start

```bash
docker compose up -d            # pulls the released images from GHCR
# or, to build from source:
docker compose up -d --build
```

Health checks gate the startup order (DB → migrations → services). Verify:

```bash
docker compose ps                                  # everything Up (healthy)
curl -s http://localhost:9121/state | python3 -m json.tool   # live meter reading?
```

`shm_age_s` should be ~1–2 s and `surplus_w` plausible. If `shm_age_s` stays `null`,
the multicast isn't arriving — see [hardware.md](hardware.md#sma-sunny-home-manager-20).

## 4. First steps in the UI

Open `http://<host>:8080` and log in.

1. The controller starts in **paused** mode — nothing switches yet. Watch the live
   surplus and the "why" card first.
2. Open **Settings** and review the runtime tuning: ON/OFF thresholds, switch delays,
   minimum runtime/off-time, your grid price and feed-in tariff (used for the savings
   estimates), and the heat pump's nominal SG-Ready power draw (`wp_nominal_power_w`
   — used for own-load compensation; check your pump's data sheet, refine later
   against real measurements).
3. Switch mode to **manual** and toggle the relay once to prove the wiring end-to-end
   (you should hear/see the heat pump acknowledge the SG-Ready signal).
4. Switch mode to **auto**. From now on the decision log shows every action with its
   reason.

Settings changes apply on the next control cycle (≤ 15 s) — no restarts.

## 5. Optional add-ons

```bash
# Prometheus + Grafana (+ English alert rules):
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d
# Heat-pump telemetry via the vicare driver (set VICARE_* credentials in .env first;
# also set HEATPUMP_DRIVER=vicare and optionally HEATPUMP_LABEL in .env):
docker compose --profile vicare up -d
```

Grafana: `http://<host>:3000` · Prometheus: `http://localhost:9090` (loopback only).

## 6. Upgrades

```bash
git pull
# set SUNSTEER_VERSION in .env to the new release tag, then:
docker compose pull && docker compose up -d
```

Schema changes ship as numbered, idempotent scripts in `db/migrations/` and are
applied automatically on start by the `db-migrate` one-shot container — watch its
output with `docker compose logs db-migrate`.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Service exits immediately with `missing required environment variables: …` | `.env` incomplete — the message lists exactly what's missing |
| `shm_age_s` stays `null` | Multicast not reaching the host: not on the same L2 as the SHM, or `SHM_HOST` doesn't match the sender IP |
| UI answers 503 on everything | `ADMIN_PASS` not set — fail-closed by design |
| Decision log shows `external_change` entries | Something else switched the relay — often the auto-off watchdog firing because the relay was unreachable (check `shelly_reachable`, improve the network, prefer Ethernet) |
| Relay won't switch ON despite surplus | Check the "why" card — usually a delay/min-offtime counting down, or the adaptive threshold still above the current surplus |
