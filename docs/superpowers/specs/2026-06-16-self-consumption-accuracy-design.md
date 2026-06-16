# Accurate & visible self-consumption — design

**Goal:** Make the controller's surplus signal reflect *real* PV headroom (not a fixed
nominal WP estimate), and make the resulting self-consumption — and what was left on the
table — visible in the UI.

**Status:** approved (brainstorm 2026-06-16). Two components, shipped in sequence:
**#1 control-core accuracy (0.5.0)**, then **#2 self-consumption report (0.5.1)**.

## Motivation

Today `available_surplus = surplus + (wp_nominal if relay_on else 0)` — a fixed-nominal
load-compensation. Live data showed its failure mode (2026-06-14, relay ON at 23:57 while
the WP drew ~0): the +nominal becomes a phantom surplus. The 0.4.1 sun-gate fixed the
night case; this fixes the *general* case (the WP modulates; nominal over-/under-states it),
and then surfaces the real economic value of the system.

---

## Component #1 — `available = production − base_load` (0.5.0)

**Insight:** the surplus genuinely free for the WP is `production − base_load` (household
consumption excluding the WP), because `surplus + WP_draw = production − base_load`. So we
never need to measure the WP draw directly — only the household baseline.

### Data flow

`/state` already carries `surplus_w` and (when the inverter is configured + reachable)
`production_w`. Then `consumption = production_w − surplus_w`.

### Base-load estimator

- Keep a rolling window of `consumption` samples (default **60 min**) — long enough to
  contain the WP's off-troughs (heat pumps cycle).
- `base_load` = the **20th percentile** of the window (robust to cooking/transient spikes;
  tracks the household baseline, not the WP peaks).
- Warm-up: until the window holds enough span (e.g. ≥ 20 min of samples), use the fallback.

### Available surplus

- When `production_w` is **present and fresh**: `available = production_w − base_load`.
- Else (no inverter / stale production): **fallback** to today's
  `surplus + (wp_nominal if relay_on and sun_up else 0)` — no loss of function without an
  inverter.
- The value feeds the **unchanged** hysteresis (ON when `available > eff` for
  `on_delay_cycles`, OFF when `available < threshold_off` for `off_delay_cycles`,
  min-runtime/off-time intact).

### Why this is safe

- It does not oscillate: `base_load` is the WP-free baseline (a low percentile), so it does
  not move when the WP turns on → `available` is stable across the WP's own switching.
- Errors are bounded and conservative: an over-high `base_load` releases the WP slightly
  early (no grid waste); the configured thresholds bound an over-low one.
- The fail-safe chain is untouched: the production-based path runs only when the meter state
  is fresh; the blind/stale path still forces OFF.
- The **sun-gate stays** as an independent guard — production telemetry can fail; solar
  elevation is always computable.

### Exporter change (small, backward-compatible)

`production_w` must only appear in `/state` when the inverter reading is **fresh** (drop it
when the inverter is unreachable/stale), so the controller never computes on a frozen value.
Absent `production_w` → controller falls back. No `/state` schema bump (absent = fallback).

### Observability

- `surplus_control_base_load_watts` (estimated baseline).
- `surplus_control_available_basis` (1 = production-based, 0 = nominal-fallback) — see at a
  glance which mode is active.
- `surplus_control_available_watts` already exists; now more accurate.

---

## Component #2 — self-consumption report, visually integrated (0.5.1)

Read-only. Uses the now-accurate numbers. Three KPIs over **today / week / month / quarter /
year** (the TimescaleDB 365-day retention bounds the longest range):

1. **Wasted surplus** — PV exported while the heat pump was off and could have taken it:
   `∫ min(export_w, wp_nominal_power_w)` over intervals where the relay was OFF (the
   controller wasn't running the WP). This proxy is computable straight from stored
   `energy_meter.export_w` + `heatpump.relay_on` — no need to recompute a historical
   base-load. In € = `kWh × (grid_price − feed_in)` — money left on the table.
2. **Achieved savings** — WP-self-consumed PV `kWh × (grid_price − feed_in)` (extends the
   existing `effectiveness_eur` to longer horizons).
3. **COP / SPF trend** — from `heatpump_telemetry`, shown as a weekly trend with a note about
   the ~3-day telemetry lag (not a reliable daily value).

Computed with SQL over `energy_meter` + `decision_log` + `heatpump_telemetry`. Optional
Prometheus recording rule for Grafana.

### Visual integration (control-ui) — first-class, not an afterthought

A dedicated **"PV-Ernte" / self-consumption card** in the Ops-Center design language
(`static/sunsteer.css`: `.num` big value, `.c` cyan glow, `.g` green, `.a` amber):

- **Range tabs** (Heute · Woche · Monat · Quartal · Jahr) via htmx, like the existing
  partials; the selected range is passed as a query param to the partial endpoint.
- **Headline:** the € saved for the range — big, cyan, glowing.
- **Stacked horizontal bar:** PV self-consumed by the WP (green) vs wasted/exported-while-
  available (amber) — the split is the story, shown visually.
- **Secondary row:** self-consumed kWh, wasted kWh, and the COP/SPF trend (small).
- New htmx partial endpoint + template `partials/harvest.html`; EN/DE i18n; tolerant readers
  (degrade to `–` on a DB hiccup, never 500).

---

## Testing

- Base-load estimator: synthetic consumption series (WP cycling + a cooking spike) →
  expected `base_load`; warm-up fallback.
- `available`: production-present path vs no-production fallback vs stale-production fallback;
  the 2026-06-14 scenario stays released.
- Exporter: `production_w` omitted from `/state` when the inverter is stale/unreachable.
- #2: query correctness against the integration TimescaleDB (wasted-surplus and savings on a
  seeded fixture); UI partial renders the three KPIs + the stacked bar; tolerant on DB error.
- All existing fail-safe / sun-gate / config-consistency tests stay green.

## Sequencing & docs

- **0.5.0** = #1 (behaviour change → minor). **0.5.1** = #2.
- Docs updated with each: `architecture.md` (the new `available` formula + base-load
  estimator), `README` features, `.env.example`/`setup` for any new knob, `CHANGELOG`. The
  base-load window / percentile are fixed sensible constants (**60 min / 20th percentile**);
  promote to env vars only if real use shows a need.

## Out of scope

- CT-clamp / direct WP metering (hardware). The base-load approach is the software answer.
- Dynamic tariffs and multi-load dispatch (separate ideas #3/#4).
