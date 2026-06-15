# Changelog

All notable changes to Sunsteer are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

_Nothing yet._

## [0.3.1] - 2026-06-15

A robustness, data-integrity and hardening pass. No breaking changes to the `/state`
contract (`schema` stays `1`); existing deployments upgrade by pulling the new images.

### Added
- The controller's `/status` endpoint is now a **versioned contract** (`schema: 1`),
  documented in [docs/status-interface.md](docs/status-interface.md); the UI warns and
  degrades on a version mismatch instead of silently mis-rendering.
- `SMA_IFACE_IP` to pin the Speedwire multicast join to a specific network interface on
  multi-homed / `hostNetwork` hosts.
- Container-image CVE scanning (Trivy, HIGH/CRITICAL) in CI, alongside the existing
  `pip-audit` dependency audit.
- Dependabot for weekly updates of the SHA-pinned GitHub Actions and the pinned Python
  dependencies.
- A scoped **mypy type-check gate** in CI over the typed cores (decision/threshold/config,
  decoder, extract, rate budget, and the DB/relay/driver boundaries).
- Database query-path indexes (migration `002-query-indexes.sql`) so the hot read paths
  stay off full hypertable scans under the 365-day retention.
- A documented **"Network trust boundaries"** section in [SECURITY.md](SECURITY.md).

### Changed
- Compose services now declare **memory/CPU resource limits** (mirroring the Kubernetes
  manifests) so a leak or runaway can't OOM the whole host and take down the control loop.
- `SHM_HOST` may now be a **hostname** — it is resolved to an IP at startup. Previously a
  hostname silently dropped every telegram (the source filter compares against an IP).
- Hardened the Compose `timescaledb` and `db-migrate` services (`no-new-privileges`;
  `db-migrate` also drops all Linux capabilities); the Kubernetes `vicare-exporter` pod now
  runs with a **read-only root filesystem**.

### Fixed
- The SMA Speedwire meter now **recovers from a silently-dead meter / dropped multicast**
  (socket read timeout → re-join) instead of blocking forever "alive but blind".
- The PV forecast **retries quickly after a transient failure** instead of leaving the
  adaptive threshold stuck on its base value for up to the full 3-hour refresh interval.
- The SMA telegram decoder is resilient to unknown / truncated records (length-driven walk,
  no desync that silently corrupts later values).
- Daily production (controller PR calibration **and** the UI's today balance) now **survives
  an inverter/meter counter reset** — summed from positive deltas instead of `max − min`,
  which would otherwise report the whole lifetime span as one day.
- A NaN inverter lifetime-yield register no longer writes a spurious `0` (a phantom counter
  reset) into the time series — it stores `NULL`.
- The controller coerces a non-numeric `/state` field to **"blind" (fail-safe OFF)** instead
  of crashing the control cycle.
- Non-finite (`NaN`/`±Inf`) Prometheus values no longer crash UI partials.
- The ViCare exporter **exits visibly (CrashLoopBackOff) after repeated invalid-credential
  rejections** instead of silently burning the API rate budget, and fails fast with a clear
  message when a required environment variable is missing.
- The control loop keeps telemetry (metrics/status) failures from being mis-counted as
  control-cycle errors, and snapshots the forecast once per cycle so the decision log can't
  disagree with the decision it records.
- The UI savings/balance card degrades instead of returning HTTP 500 when a price or
  nominal-power config column is NULL.
- The adaptive threshold can no longer divide by zero on a degenerate `full_sun_ref_kwh`.
- A failed inverter Modbus read is now logged with its cause (so a code/register bug is
  distinguishable from a genuinely unreachable inverter) instead of being swallowed silently.
- All services now log the cause when a database connection drops and is re-established,
  instead of two of the three reconnecting silently (the resilience primitives were
  converged and are guarded against drift by a cross-service consistency test).

### Security
- The web UI's HTTP Basic-auth check is **constant-time** with respect to the username (no
  early-out that would leak username validity through response timing).
- Configuration writes use `psycopg2.sql.Identifier` — injection-proof by construction, not
  only by the column whitelist.
- The cached ViCare OAuth token is now written **owner-only (0600)** (restrictive umask plus
  an explicit `chmod`), so anything sharing the PVC/UID can't read the long-lived refresh grant.
- New `STATUS_BIND` to restrict the controller's `/status` + `/healthz` server to a single
  interface (mirrors `STATE_BIND`).
- An **optional NetworkPolicy** (`deploy/k8s/networkpolicy.yaml`) restricts ingress to the
  namespace, and the TimescaleDB pod gained `allowPrivilegeEscalation: false` +
  `seccompProfile: RuntimeDefault` (the subset safe for the database).

## [0.3.0] - 2026-06-15

A hardening and portability release. No breaking changes to the `/state` contract
(`schema` stays `1`). Existing Compose deployments upgrade by pulling the new images.

### Added
- **Pluggable relay drivers** via `RELAY_DRIVER`, mirroring the existing meter-driver
  pattern: a `RelayActuator` (controller, write + hardware auto-off watchdog) and a
  `RelayReader` (exporter, read-only). See [docs/relay-interface.md](docs/relay-interface.md).
- **Kubernetes example manifests** under [`deploy/k8s/`](deploy/k8s/): a generic kustomize
  base with non-root `securityContext`, a `db-migrate` Job (Compose-parity migrations),
  and pinned image tags.
- **CSRF protection** on state-changing UI routes (Origin/Referer check); `ALLOWED_ORIGIN`
  for reverse-proxy setups.
- **Numbered, idempotent database migrations** in [`db/migrations/`](db/migrations/),
  applied automatically by a `db-migrate` one-shot (Compose) / Job (Kubernetes).
- New Prometheus alerts: relay write failures, controller loop errors, exporter poll
  errors, and ViCare staleness.
- `STATE_BIND` to restrict the `/state` server to a single interface.
- CI quality gates: `ruff` lint, `pip-audit` dependency audit, a real-TimescaleDB
  integration smoke, and a config-column consistency guard.
- Released images now carry an **SBOM and SLSA build provenance**.

### Changed
- The web UI and the optional Grafana add-on **bind to loopback by default**
  (`UI_BIND` / `GRAFANA_BIND`) — HTTP Basic auth has no TLS, so front it with a TLS
  reverse proxy to expose it.
- All container images run as a **non-root user** (uid 10001).
- **Reproducible images**: TimescaleDB and the monitoring images are digest-pinned,
  GitHub Actions are SHA-pinned.
- **Robust environment parsing** across every service: an invalid, zero or absurd port /
  cadence / cap value falls back to its default instead of crashing at start or spinning a
  tight loop.
- The ViCare exporter is **opt-in on Kubernetes** (commented out in the kustomize base).
- The ViCare API rate budget is now wall-clock based and **persisted across restarts**, so
  a restart no longer grants a fresh daily quota.

### Fixed
- The forecast now uses `PV_TZ` instead of a hardcoded timezone.
- Exporter background threads no longer die silently — loops are guarded and failures are
  counted (`energy_exporter_poll_errors_total`).
- The control UI degrades gracefully on a database outage instead of returning HTTP 500,
  and now shows a visible "not saved" warning when a write can't be persisted.
- A relay switch is only treated as successful on HTTP 200 **and** a non-error RPC body;
  a Gen2 `200 + {"error": ...}` now counts as a failed switch.
- The relay hardware auto-off watchdog is **enforced** — an ON command without an armed
  watchdog is refused (defence in depth against a wedged controller latching the relay on).
- The controller now warns when the `/state` schema version is unrecognized.

### Security
- Updated `fastapi`, `starlette` (→ 1.0.x), `jinja2` and `python-multipart` to clear
  known CVEs.
- `ADMIN_PASS` / `ADMIN_USER` left at the `CHANGE_ME` placeholder now keep the UI
  **fail-closed** (HTTP 503) instead of being accepted as valid credentials.
- All services reject unsubstituted `CHANGE_ME` placeholders in required environment
  variables and fail fast.

## [0.2.2] - 2026-06-13

### Added
- `WEATHER_LOCATION` to label the weather panel with a place name.

## [0.2.1] - 2026-06-13

### Fixed
- The EN/DE language switch is visible on desktop again.
- Weather chart renders as a proper sparkline; inverter tile no longer over-stretches.
- The decision log moved below the history and is collapsible, with its own scroll area.

## [0.2.0] - 2026-06-13

### Changed
- Redesigned web UI — a dark, industrial "control room" theme with an at-a-glance cockpit
  layout and a settings modal, plus a responsive mobile layout.
- Removed all CDN dependencies: CSS, fonts, htmx and Chart.js are now self-hosted, so the
  UI works fully offline.

## [0.1.1] - 2026-06-12

### Added
- A `schema` version field (`schema: 1`) on the `/state` contract, so consumers can detect
  breaking changes.

## [0.1.0] - 2026-06-12

Initial public release.

### Added
- Local SG-Ready heat-pump control from PV surplus: reads an **SMA Sunny Home Manager 2.0**
  grid meter, decides when genuine surplus is available, and switches a **Shelly Gen2**
  relay — no cloud.
- **Adaptive threshold** driven by the remaining PV forecast (Open-Meteo GTI, forecast.solar
  fallback), self-calibrating from actual production.
- **Hysteresis and compressor protection**: ON/OFF streaks, minimum runtimes and off-times.
- **Fail-safe by design**: stale meter data switches the heat pump OFF; a hardware auto-off
  watchdog on the relay catches a dead controller; the web UI is fail-closed behind HTTP
  Basic auth.
- **Explainable** decision log with an EN/DE "why" card.
- Runtime tuning (thresholds, delays, runtimes, prices) lives in the database and
  hot-reloads each cycle.
- Prometheus metrics from every service, an optional Grafana add-on, and English alert
  rules.
- A bring-your-own-meter seam: implement the `GridMeter` driver protocol, or serve the
  documented `/state` JSON contract from any process.
- Docker Compose stack, a zero-config demo (`docker-compose.demo.yml`), and multi-arch
  (`amd64` + `arm64`) images on GHCR.

[Unreleased]: https://github.com/slippyex/sunsteer/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/slippyex/sunsteer/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/slippyex/sunsteer/compare/v0.2.2...v0.3.0
[0.2.2]: https://github.com/slippyex/sunsteer/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/slippyex/sunsteer/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/slippyex/sunsteer/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/slippyex/sunsteer/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/slippyex/sunsteer/releases/tag/v0.1.0
