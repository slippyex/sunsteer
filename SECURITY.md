# Security Policy

Sunsteer switches a relay wired to a heat pump's SG-Ready input, so we take security
and safety reports seriously. Thank you for helping keep users and their hardware safe.

## Supported versions

Sunsteer is pre-1.0; security fixes land on the latest released minor only.

| Version | Supported |
|---|---|
| 0.3.x | ✅ |
| < 0.3 | ❌ (please upgrade) |

## Reporting a vulnerability

**Please do not open a public issue for security vulnerabilities.**

Report privately through one of:

1. **GitHub private vulnerability reporting** (preferred) — on the repository's
   **Security** tab, click **Report a vulnerability**. This opens a private advisory only
   the maintainers can see.
2. **Email** — `mvelten773@gmail.com` with the subject `[sunsteer security]`.

Please include:

- the affected service(s) (`energy-exporter`, `surplus-controller`, `control-ui`,
  `vicare-exporter`) and version / image tag,
- how it's deployed (Docker Compose, Kubernetes, demo),
- a description, impact, and reproduction steps (a proof of concept helps),
- any relevant logs or configuration (with secrets redacted).

## What to expect

- **Acknowledgement** within about 5 days.
- An assessment and, for confirmed issues, a fix on the supported release, credited to you
  unless you prefer to stay anonymous.
- Coordinated disclosure: we'll agree on a timeline before any public write-up, and publish
  a GitHub Security Advisory once a fix is available.

## Network trust boundaries (by design)

Sunsteer assumes a **trusted private network** between its services. The following are
deliberate, documented trade-offs, not vulnerabilities:

- **Unauthenticated internal endpoints.** `energy-exporter` `/state` and `/metrics`, and
  `surplus-controller` `/status`, `/healthz` and `/metrics`, are served without auth and
  bind to all interfaces by default. They carry read-only telemetry for the in-cluster
  controller and Prometheus. Restrict exposure with `STATE_BIND` (exporter) / `STATUS_BIND`
  (controller), and/or apply the optional `deploy/k8s/networkpolicy.yaml`. Under
  `network_mode: host` / `hostNetwork` they are reachable on the node network (and a
  NetworkPolicy cannot restrict a host-network pod), so keep that network trusted.
- **The control UI is the one authenticated surface.** It is fail-closed behind HTTP Basic
  auth (503 without `ADMIN_PASS`) and binds to loopback by default — put it behind a TLS
  reverse proxy before exposing it.
- **CSRF with no Origin/Referer is allowed.** The UI's CSRF guard permits requests that send
  neither header (non-browser clients like `curl`/scripts), since the real threat — a browser
  silently replaying cached Basic credentials cross-site — always sends one of them.
- **SMA Speedwire source-IP filtering is spoofable** on a flat L2 multicast segment; the worst
  case is bad gauge values (pure parsing, no code execution), never remote control.

## Scope and safety note

Especially relevant are issues in the **fail-safe chain** — anything that could keep the
heat pump switched **on** when it should be off (stale-data handling, the relay auto-off
watchdog, minimum runtimes), or that bypasses the fail-closed web UI auth.

Sunsteer is provided under the MIT License with no warranty; see
[DISCLAIMER.md](DISCLAIMER.md). Wiring to a heating system is the user's responsibility.
