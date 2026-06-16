# Self-consumption report (#2, 0.5.1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.
>
> **Git:** Do NOT commit. The user commits manually. Agents stage with `git add` at most.

**Goal:** A read-only "PV harvest" card in the control-ui showing, per range (today/week/month/quarter/year): money saved by the heat pump, surplus wasted (exported while the pump was off), and the COP/SPF trend.

**Architecture:** A tolerant SQL summary in `control-ui/src/sources.py` over `energy_meter` + `heatpump` + `heatpump_telemetry`, served by a new htmx partial `/partials/harvest?range=…` rendering a dedicated Ops-Center card (range tabs, € headline, green/amber stacked bar). No control-path impact.

**Tech Stack:** FastAPI + Jinja2 + HTMX, psycopg2/TimescaleDB, pytest (Dockerfile `test` stage + the repo-root `tests/integration` real-DB suite). Spec: `docs/superpowers/specs/2026-06-16-self-consumption-accuracy-design.md` (Component #2).

---

## File Structure

- **Modify** `services/control-ui/src/sources.py` — `harvest_summary(conn, range_key, nominal_w, grid_price, feed_in)` tolerant reader.
- **Modify** `services/control-ui/src/app.py` — `/partials/harvest` endpoint.
- **Create** `services/control-ui/templates/partials/harvest.html` — the card.
- **Modify** `services/control-ui/templates/index.html` — include the card (htmx).
- **Modify** `services/control-ui/static/sunsteer.css` — range tabs + stacked bar.
- **Modify** `services/control-ui/src/i18n.py` — EN/DE keys.
- **Test** `tests/integration/test_db.py` (real-DB harvest SQL) and `services/control-ui/tests/test_app.py` (partial render).
- **Docs/version:** `README.md`, `CHANGELOG.md`, `deploy/compose/*`, `deploy/k8s/*`.

---

## Task 1: `harvest_summary` SQL + tolerant reader

**Files:** Modify `services/control-ui/src/sources.py`; Test `tests/integration/test_db.py`.

- [ ] **Step 1: Write the failing integration test** — append to `tests/integration/test_db.py` (PGHOST-gated; it imports the control-ui `src`):

```python
def test_harvest_summary_self_and_wasted():
    import importlib
    _drop_src_modules()
    sys.path.insert(0, os.path.join(ROOT, "services", "control-ui"))
    sources = importlib.import_module("src.sources")
    c = _conn()
    with c.cursor() as cur:
        cur.execute("DELETE FROM energy_meter; DELETE FROM heatpump;")
        # 10 minutes today: WP ON, surplus +3000 (full PV covers the 2000 W WP) -> self-consumed.
        cur.execute("""INSERT INTO energy_meter (time, surplus_w, export_w)
                       SELECT now() - (g||' min')::interval, 3000, 3000 FROM generate_series(1,10) g""")
        cur.execute("""INSERT INTO heatpump (time, relay_on)
                       SELECT now() - (g||' min')::interval, true FROM generate_series(1,10) g""")
        # 10 minutes today: WP OFF, exporting 1500 W -> wasted (could have driven the WP).
        cur.execute("""INSERT INTO energy_meter (time, surplus_w, export_w)
                       SELECT now() - (g||' min')::interval, 1500, 1500 FROM generate_series(11,20) g""")
        cur.execute("""INSERT INTO heatpump (time, relay_on)
                       SELECT now() - (g||' min')::interval, false FROM generate_series(11,20) g""")
    h = sources.harvest_summary(c, "today", nominal_w=2000, grid_price=0.30, feed_in=0.08)
    # self-consumed ~ 2000 W × 10 min = 0.333 kWh; wasted ~ 1500 W × 10 min = 0.25 kWh
    assert 0.28 < h["self_kwh"] < 0.38
    assert 0.20 < h["wasted_kwh"] < 0.30
    assert round(h["self_eur"], 4) == round(h["self_kwh"] * (0.30 - 0.08), 4)
    assert round(h["wasted_eur"], 4) == round(h["wasted_kwh"] * (0.30 - 0.08), 4)


def test_harvest_summary_tolerant_on_bad_conn():
    import importlib
    _drop_src_modules()
    sys.path.insert(0, os.path.join(ROOT, "services", "control-ui"))
    sources = importlib.import_module("src.sources")

    class Dead:
        def cursor(self): raise RuntimeError("db down")
    h = sources.harvest_summary(Dead(), "today", 2000, 0.30, 0.08)
    assert h == {"self_kwh": None, "self_eur": None, "wasted_kwh": None,
                 "wasted_eur": None, "cop": None}
```

- [ ] **Step 2: Run it — FAIL** (`AttributeError: harvest_summary`). The integration suite runs in CI / locally with a Postgres; see `tests/integration` and the `db-integration` CI job. (If no local Postgres, this test is skipped — it WILL run in CI.)

- [ ] **Step 3: Implement** in `services/control-ui/src/sources.py`. Add the range map near `_WP_WINDOWS` and the reader:

```python
# Calendar-aligned ranges for the harvest report -> the date_trunc unit for "since start of".
_HARVEST_RANGES = ("today", "week", "month", "quarter", "year")
_HARVEST_UNIT = {"today": "day", "week": "week", "month": "month",
                 "quarter": "quarter", "year": "year"}


def harvest_summary(conn, range_key, nominal_w, grid_price, feed_in):
    """Self-consumption vs wasted-surplus for a calendar range. All-tolerant -> None values
    on any error. self_kwh: PV the WP self-consumed (surplus reconstructed to surplus+nominal,
    clamped to [0, nominal], over minutes the relay was ON). wasted_kwh: PV exported while the
    relay was OFF, capped at the WP's nominal draw (what it could have absorbed). € = kWh ×
    (grid_price - feed_in). cop: representative SCOP over the range (telemetry lags ~3 days)."""
    none = {"self_kwh": None, "self_eur": None, "wasted_kwh": None, "wasted_eur": None, "cop": None}
    unit = _HARVEST_UNIT.get(range_key)
    if unit is None:
        return none
    n = nominal_w or 0
    spread = (grid_price or 0) - (feed_in or 0)
    try:
        with conn.cursor() as cur:
            cur.execute(
                # 1-minute buckets first -> the outer sums are watt-MINUTES -> /60000.0 = kWh,
                # cadence-independent (same idiom as wp_savings).
                "WITH wp AS (SELECT time_bucket('1 minute'::interval, time) m, bool_or(relay_on) on_ "
                "  FROM heatpump WHERE time >= date_trunc(%s, now()) GROUP BY m), "
                "sm AS (SELECT time_bucket('1 minute'::interval, time) m, avg(surplus_w) surplus, "
                "  avg(export_w) exp FROM energy_meter WHERE time >= date_trunc(%s, now()) GROUP BY m) "
                "SELECT "
                "  coalesce(sum(CASE WHEN wp.on_ THEN least(greatest(sm.surplus + %s, 0), %s) END), 0)/60000.0, "
                "  coalesce(sum(CASE WHEN NOT wp.on_ THEN least(greatest(sm.exp, 0), %s) END), 0)/60000.0 "
                "FROM wp JOIN sm USING (m)",
                (unit, unit, n, n, n))
            self_kwh, wasted_kwh = cur.fetchone()
            cur.execute("SELECT round(avg(scop_total)::numeric, 2) FROM heatpump_telemetry "
                        "WHERE time >= date_trunc(%s, now())", (unit,))
            cop = cur.fetchone()[0]
        self_kwh = float(self_kwh)
        wasted_kwh = float(wasted_kwh)
        return {"self_kwh": round(self_kwh, 2), "self_eur": round(self_kwh * spread, 2),
                "wasted_kwh": round(wasted_kwh, 2), "wasted_eur": round(wasted_kwh * spread, 2),
                "cop": float(cop) if cop is not None else None}
    except Exception as e:
        log.warning("harvest_summary: %s", e)
        return none
```

- [ ] **Step 4: Run — PASS** (where Postgres is available; else skipped + verified in CI). Local quick check if you have docker Postgres: set PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD and run `python -m pytest tests/integration -k harvest -q`.

- [ ] **Step 5: Stage** — `git add services/control-ui/src/sources.py tests/integration/test_db.py`

---

## Task 2: partial endpoint + Ops-Center card

**Files:** Modify `services/control-ui/src/app.py`, `templates/index.html`, `static/sunsteer.css`, `src/i18n.py`; Create `templates/partials/harvest.html`; Test `tests/test_app.py`.

- [ ] **Step 1: Write the failing render test** — append to `services/control-ui/tests/test_app.py`:

```python
def test_partials_harvest_renders(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(appmod, "_db", lambda: type("C", (), {"close": lambda self: None})())
    monkeypatch.setattr(appmod.sources, "load_config",
                        lambda conn: {"grid_price_eur_kwh": 0.30, "feed_in_tariff_eur_kwh": 0.08,
                                      "wp_nominal_power_w": 2000})
    monkeypatch.setattr(appmod.sources, "harvest_summary",
                        lambda *a, **k: {"self_kwh": 3.5, "self_eur": 0.77, "wasted_kwh": 1.2,
                                         "wasted_eur": 0.26, "cop": 4.1})
    c = TestClient(appmod.app)
    r = c.get("/partials/harvest?range=week")
    assert r.status_code == 200
    assert "0.77" in r.text and "week" in r.text.lower()


def test_partials_harvest_defaults_and_tolerates_none(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(appmod, "_db", lambda: type("C", (), {"close": lambda self: None})())
    monkeypatch.setattr(appmod.sources, "load_config", lambda conn: {})
    monkeypatch.setattr(appmod.sources, "harvest_summary",
                        lambda *a, **k: {"self_kwh": None, "self_eur": None, "wasted_kwh": None,
                                         "wasted_eur": None, "cop": None})
    c = TestClient(appmod.app)
    r = c.get("/partials/harvest")           # no range -> defaults to today
    assert r.status_code == 200              # renders, no 500
```

- [ ] **Step 2: Run — FAIL** (`404` / template missing).

Run: `docker build --target test services/control-ui`

- [ ] **Step 3: Add the endpoint** in `services/control-ui/src/app.py` (mirror the `balance` handler's config pattern; read the range from the query string, default "today", validate against the allowed set):

```python
@app.get("/partials/harvest", response_class=HTMLResponse)
def harvest(request: Request):
    rng = request.query_params.get("range", "today")
    if rng not in sources._HARVEST_RANGES:
        rng = "today"
    with _db_optional() as conn:
        cfg = sources.load_config(conn)
        grid = float(cfg.get("grid_price_eur_kwh") or 0.30)
        feed = float(cfg.get("feed_in_tariff_eur_kwh") or 0.08)
        nominal = float(cfg.get("wp_nominal_power_w") or 2000)
        h = sources.harvest_summary(conn, rng, nominal, grid, feed)
    total = (h.get("self_kwh") or 0) + (h.get("wasted_kwh") or 0)
    h["self_pct"] = round(100 * (h.get("self_kwh") or 0) / total) if total else 0
    h["wasted_pct"] = 100 - h["self_pct"] if total else 0
    return render(request, "partials/harvest.html", h=h, rng=rng, ranges=sources._HARVEST_RANGES)
```

> Note: `_db_optional()` yields `None` on a DB outage; `load_config(None)` / `harvest_summary(None, ...)` are already tolerant (return `{}` / all-None), so the card degrades to dashes — never 500.

- [ ] **Step 4: Create the card** `services/control-ui/templates/partials/harvest.html`. Read `templates/partials/balance.html` and `static/sunsteer.css` first to match the exact classes/colour variables. Structure (adapt class names to the existing palette — `.c` cyan, `.g` green, `.a` amber, `.num` big value):

```html
{# Range tabs — htmx swaps this whole card #}
<div class="rtabs">
  {% for r in ranges %}
  <button class="{{ 'on' if r == rng else '' }}"
          hx-get="/partials/harvest?range={{ r }}" hx-target="#harvest" hx-swap="innerHTML">
    {{ t('range_' ~ r) }}
  </button>
  {% endfor %}
</div>

{# € saved — headline #}
<div class="num c">{{ "%.2f"|format(h.self_eur) if h.self_eur is not none else '–' }}<small> €</small></div>
<div class="lbl">{{ t('harvest_saved') }}</div>

{# Stacked bar: self-consumed (green) vs wasted (amber) #}
<div class="stack" title="{{ t('self_consumption') }} / {{ t('harvest_wasted') }}">
  <i class="self" style="width: {{ h.self_pct }}%"></i>
  <i class="waste" style="width: {{ h.wasted_pct }}%"></i>
</div>
<div class="row2">
  <span class="g">{{ h.self_kwh if h.self_kwh is not none else '–' }} kWh {{ t('self_consumption') }}</span>
  <span class="a">{{ h.wasted_kwh if h.wasted_kwh is not none else '–' }} kWh {{ t('harvest_wasted') }}</span>
</div>

<div class="kv" style="margin-top:8px;">
  {{ t('harvest_wasted_eur') }} <b class="a">{{ "%.2f"|format(h.wasted_eur) if h.wasted_eur is not none else '–' }} €</b><br>
  {{ t('cop') }} <b>{{ h.cop if h.cop is not none else '–' }}</b> <small>{{ t('cop_lag_note') }}</small>
</div>
```

- [ ] **Step 5: Add the CSS** to `services/control-ui/static/sunsteer.css` (match the existing colour variables — find the green/amber/cyan custom properties in the file and reuse them):

```css
/* harvest report: range tabs + self-vs-wasted stacked bar */
.rtabs{display:flex;gap:4px;margin-bottom:10px;flex-wrap:wrap}
.rtabs button{background:transparent;border:1px solid var(--line,#2a3138);color:var(--muted,#7d8893);
  font:inherit;font-size:.8rem;padding:3px 8px;border-radius:3px;cursor:pointer}
.rtabs button.on{border-color:var(--cyan,#36d6e7);color:var(--cyan,#36d6e7)}
.stack{display:flex;height:10px;border-radius:2px;overflow:hidden;background:var(--line,#2a3138);margin:6px 0}
.stack i{display:block;height:100%}
.stack .self{background:var(--green,#37c871)}
.stack .waste{background:var(--amber,#e0a23a)}
```

> Use the real custom-property names from `sunsteer.css` (the fallbacks above are only defaults). Match the existing `.num`/`.lbl`/`.row2` look.

- [ ] **Step 6: Add i18n** to `services/control-ui/src/i18n.py` (DE, EN tuples):

```python
    "range_today":   ("Heute", "Today"),
    "range_week":    ("Woche", "Week"),
    "range_month":   ("Monat", "Month"),
    "range_quarter": ("Quartal", "Quarter"),
    "range_year":    ("Jahr", "Year"),
    "harvest_title": ("PV-Ernte", "PV harvest"),
    "harvest_saved": ("gespart durch PV-Eigenverbrauch", "saved via PV self-consumption"),
    "harvest_wasted": ("verschenkt", "wasted"),
    "harvest_wasted_eur": ("verschenkt", "left on the table"),
    "cop_lag_note":  ("(Telemetrie ~3 Tage Verzug)", "(telemetry lags ~3 days)"),
```

(Reuse the existing `self_consumption` and `cop` keys; add `cop` if absent: `"cop": ("COP/SPF", "COP/SPF")`.)

- [ ] **Step 7: Wire into the page** — in `services/control-ui/templates/index.html`, add the card next to the existing `balance` panel (find the `id="balance"` htmx div and add a sibling, with a heading using `t('harvest_title')`):

```html
        <div class="panel"><h3>{{ t('harvest_title') }}</h3>
          <div id="harvest" hx-get="/partials/harvest" hx-trigger="load, every 300s" hx-swap="innerHTML"></div>
        </div>
```

> Match the surrounding panel markup exactly (read the neighbours first — class names/heading style may differ).

- [ ] **Step 8: Run — PASS**

Run: `docker build --target test services/control-ui` → all green.

- [ ] **Step 9: Stage** — `git add services/control-ui/`

---

## Task 3: Surface the 0.5.0 PV-headroom basis in the live cockpit

**Why:** 0.5.0 introduced `available = production − base_load` (the real PV headroom for the WP) but it lives only in two Prometheus gauges — invisible in the UI. Surface it in the ÜBERSCHUSS status panel: the headroom value, the household base load, and which basis the controller is on right now (the production path vs the warm-up/no-inverter nominal fallback). Read-only, reuses the existing `_live()` Prometheus pattern.

**Files:** Modify `services/control-ui/src/app.py` (`_LIVE`, `_live()`), `templates/partials/status.html`, `src/i18n.py`; Test `tests/test_app.py`.

- [ ] **Step 1: Write the failing render test** — append to `services/control-ui/tests/test_app.py` (mirror the existing `_patch` + `TestClient` idiom in that file; `status()` calls `appmod._live()`, so stub that):

```python
def test_partials_status_shows_headroom_basis(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(appmod, "_live", lambda: {
        "surplus": 1500, "threshold": 2000, "production": 4000, "consumption": 500,
        "wp_power": 2000, "relay": 1, "self_consumption": 0.5, "autarky": 0.5,
        "sun_elevation": 40, "sun_in_window": True, "sun_rise": "06:00", "sun_set": "21:00",
        "available": 3450, "base_load": 550, "basis_production": True,
        "health": {"shm": True, "shelly": True, "wr": True, "controller": True}})
    c = TestClient(appmod.app)
    r = c.get("/partials/status")
    assert r.status_code == 200
    assert "3450" in r.text and "550" in r.text   # headroom + base-load rendered
```

- [ ] **Step 2: Run — FAIL** (`3450` not in output).

Run: `docker build --target test services/control-ui`

- [ ] **Step 3: Add the three queries** to the `_LIVE` dict in `services/control-ui/src/app.py` (next to the other `surplus_control_*` entries):

```python
    "available": "surplus_control_available_watts",
    "base_load": "surplus_control_base_load_watts",
    "basis": "surplus_control_available_basis",
```

- [ ] **Step 4: Derive the basis flag** in `_live()` (after the `mode` line, before the return):

```python
    # 0.5.0: available_basis == 1 -> controller is on the production−base_load path; else the
    # nominal/sun-gated fallback (estimator warming up, or no fresh inverter production).
    v["basis_production"] = v.get("basis") == 1
```

- [ ] **Step 5: Render it** in `services/control-ui/templates/partials/status.html` — add a block after the secondary kv (after the `sun` row's closing `</div>` on line ~20, before the health block):

```html
{# ── Real PV headroom: production − base_load (0.5.0) ──────────────── #}
<div class="kv" style="margin-top:6px;">
  {{ t('kpi_headroom') }} <b class="c">{{ (L.available|round|int) if L.available is not none else '–' }} W</b><br>
  {{ t('headroom_basis') }}
  {% if L.basis_production %}<b class="g">{{ t('basis_production') }}</b>
    <span class="txt-a">({{ t('kpi_base_load') }} {{ (L.base_load|round|int) if L.base_load is not none else '–' }} W)</span>
  {% else %}<b class="a">{{ t('basis_nominal') }}</b>{% endif %}
</div>
```

- [ ] **Step 6: Add i18n** to `services/control-ui/src/i18n.py` (DE, EN tuples):

```python
    "kpi_headroom":    ("PV-Headroom (WP)", "PV headroom (HP)"),
    "headroom_basis":  ("Basis", "Basis"),
    "basis_production": ("Produktion − Grundlast", "production − base load"),
    "basis_nominal":   ("Schätzung (Aufwärmphase / kein WR)", "estimate (warm-up / no inverter)"),
    "kpi_base_load":   ("Grundlast", "base load"),
```

- [ ] **Step 7: Run — PASS**

Run: `docker build --target test services/control-ui` → all green.

- [ ] **Step 8: Stage** — `git add services/control-ui/`

---

## Task 4: Show the running version in the control-ui header

**Why:** There is currently no way to tell from the UI which image version is running, which made a silent 0.5.0 rollout look like "nothing changed". Inject `SUNSTEER_VERSION` (deploy-time env, bumped together with the image tag) and render it in the topbar brand.

**Files:** Modify `services/control-ui/src/app.py`, `templates/index.html`, `static/sunsteer.css`, `deploy/compose/docker-compose.yml`, `deploy/k8s/control-ui.yaml`; Test `tests/test_app.py`.

- [ ] **Step 1: Write the failing render test** — append to `services/control-ui/tests/test_app.py`:

```python
def test_index_shows_version(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(appmod, "VERSION", "9.9.9")
    monkeypatch.setattr(appmod, "_db", lambda: type("C", (), {"close": lambda self: None})())
    c = TestClient(appmod.app)
    r = c.get("/")
    assert r.status_code == 200
    assert "9.9.9" in r.text
```

> Match the existing `_patch` helper / `_db` monkeypatch idiom already used by the other `test_app.py` tests (read them first). The index route hits the DB for `cfg`/`decisions`; mirror how the neighbouring index test stubs that.

- [ ] **Step 2: Run — FAIL** (`9.9.9` not in output).

Run: `docker build --target test services/control-ui`

- [ ] **Step 3: Read the controller's version env** in `services/control-ui/src/app.py`. Add a module-level constant next to the other `os.environ.get(...)` constants (e.g. near `GRAFANA`):

```python
VERSION = os.environ.get("SUNSTEER_VERSION", "dev")
```

Inject it into every template via the single `render()` helper (so includes can use it too) — add `version=VERSION` to the `ctx.update(...)` call:

```python
    ctx.update(request=request, lang=lang, version=VERSION,
               t=lambda key, default=None, **fmt: i18n.t(lang, key, default=default, **fmt))
```

- [ ] **Step 4: Render it in the header** — in `services/control-ui/templates/index.html`, add a version chip to the brand (line ~18):

```html
    <div class="brand">SUNSTEER<span class="sub">{{ t('subtitle') }}</span><span class="ver">v{{ version }}</span></div>
```

- [ ] **Step 5: Style the chip** — add to `services/control-ui/static/sunsteer.css` (match the existing muted/line custom-property names — read the `.brand .sub` rule first and mirror it):

```css
.brand .ver{font-size:.62rem;font-weight:600;letter-spacing:.04em;color:var(--muted,#7d8893);
  border:1px solid var(--line,#2a3138);border-radius:3px;padding:1px 5px;margin-left:8px;vertical-align:middle}
```

- [ ] **Step 6: Pass the env at deploy time.** In `services/control-ui/Dockerfile` — no change needed (env comes from the runtime). In `deploy/compose/docker-compose.yml`, add to the `control-ui` service an `environment:` entry (mirror its existing env block; create one if absent):

```yaml
      SUNSTEER_VERSION: ${SUNSTEER_VERSION:-0.5.1}
```

In `deploy/k8s/control-ui.yaml`, add to the container `env:` list:

```yaml
        - name: SUNSTEER_VERSION
          value: "0.5.1"
```

- [ ] **Step 7: Run — PASS**

Run: `docker build --target test services/control-ui` → all green.

- [ ] **Step 8: Stage** — `git add services/control-ui/ deploy/compose/docker-compose.yml deploy/k8s/control-ui.yaml`

> **Downstream note (handled by the controller, not this subagent):** the homelab-k3s repo's `apps/control-ui/deployment.yaml` also needs `SUNSTEER_VERSION: "0.5.1"` so the live cluster shows it. That edit happens in the other repo during the version bump.

---

## Task 5: Docs + version 0.5.1

**Files:** `README.md`, `CHANGELOG.md`, `deploy/compose/docker-compose.yml`, `deploy/compose/docker-compose.demo.yml`, `deploy/compose/.env.example`, `deploy/k8s/kustomization.yaml`, `deploy/k8s/{energy-exporter,surplus-controller,control-ui,heatpump-exporter}.yaml`.

- [ ] **Step 1: README** — under Features add: "**PV harvest report** — a UI card shows, per range, the € saved by self-consuming PV in the heat pump and the surplus left on the table (exported while the pump was off)." In the Observable/UI bullet, note the live cockpit now shows the **PV headroom basis** (production − base load vs the warm-up fallback) and the running **version** in the header.

- [ ] **Step 2: CHANGELOG** — new section above 0.5.0:

```markdown
## [0.5.1] - 2026-06-16

### Added
- A **PV harvest** card in the web UI: per range (today / week / month / quarter / year), the
  € saved by self-consuming PV in the heat pump, the surplus wasted (exported while the pump
  was off), as a green/amber split, plus the COP/SPF trend.
- The live cockpit now surfaces the **0.5.0 PV-headroom basis**: the real headroom
  (production − base load), the household base load, and whether the controller is on the
  production path or the warm-up/no-inverter nominal fallback.
- The running **version** is shown in the web-UI header (`SUNSTEER_VERSION`), so a rollout is
  visible at a glance.
```

Update compare links: `[Unreleased]: …/compare/v0.5.1...HEAD`, add `[0.5.1]: …/compare/v0.5.0...v0.5.1`.

- [ ] **Step 3: Version bump**:

```bash
cd ~/workspaces/private/sunsteer
sed -i '' 's/SUNSTEER_VERSION:-0.5.0/SUNSTEER_VERSION:-0.5.1/g' deploy/compose/docker-compose.yml deploy/compose/docker-compose.demo.yml
sed -i '' 's/^#SUNSTEER_VERSION=0.5.0/#SUNSTEER_VERSION=0.5.1/; s/(default: 0.5.0)/(default: 0.5.1)/' deploy/compose/.env.example
sed -i '' 's#\(sunsteer/[a-z-]*\):0.5.0#\1:0.5.1#' deploy/k8s/energy-exporter.yaml deploy/k8s/surplus-controller.yaml deploy/k8s/control-ui.yaml deploy/k8s/heatpump-exporter.yaml
sed -i '' 's/newTag: "0.5.0"/newTag: "0.5.1"/g; s/already pin :0.5.0/already pin :0.5.1/' deploy/k8s/kustomization.yaml
```

Verify: `grep -rn "0.5.0" deploy/ | grep -v sha256` → nothing.

- [ ] **Step 4: Stage** — `git add README.md CHANGELOG.md deploy/`

---

## Final verification

- [ ] All four Dockerfile test stages pass.
- [ ] The real-DB `tests/integration` suite passes (a throwaway TimescaleDB with init.sql applied; harvest tests green).
- [ ] `ruff check .` clean.
- [ ] `docker compose -f deploy/compose/docker-compose.yml config -q` OK; kustomize shows `:0.5.1`.
- [ ] (Optional) demo smoke with the monitoring profile to eyeball the card; otherwise verify on the cluster post-rollout.
- [ ] Hand the uncommitted tree to the user to commit + tag `v0.5.1`.

---

## Self-review (author)

- **Spec coverage:** three KPIs (T1: self_kwh/wasted_kwh/cop SQL + €), five ranges (calendar-aligned via date_trunc), Ops-Center card with tabs + stacked bar (T2), docs + 0.5.1 (T3). Wasted = relay-off + export proxy capped at nominal (per spec). Read-only, tolerant (T1 returns all-None on error; T2 degrades to dashes).
- **Type consistency:** `harvest_summary(conn, range_key, nominal_w, grid_price, feed_in) -> {self_kwh, self_eur, wasted_kwh, wasted_eur, cop}` (floats or None); `_HARVEST_RANGES` tuple used by both the handler and the template; i18n keys `range_*`, `harvest_*`, `cop_lag_note`.
- **Caveats for the implementer:** read `balance.html`, the neighbouring `index.html` panel, and `sunsteer.css` colour variables FIRST and match them — the template/CSS snippets use placeholder var names. The integration test needs a live Postgres (CI provides it); locally it skips unless PGHOST is set.
