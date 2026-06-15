# Sunsteer — Findings-Abarbeitung (hoch → mittel → niedrig)

Ziel: alle Review-Findings beheben; operative Robustheit und Code-Stil auf 4–5 Sterne.
Methode: TDD pro Verhaltensänderung. Tests laufen pro Service via `python3 -m pytest tests/`
(control-ui über `.venv/bin/python`, vicare über eigenen venv mit PyViCare).
Kein commit/push — macht der User selbst.

## HIGH

- [x] **H1 — SMA Speedwire: blockierendes `recvfrom` ohne Timeout** ✅ `settimeout` + Socket-Rebuild
  bei `TimeoutError`; `_open_socket()` gekapselt. 4 neue Tests (Source-IP-Filter, runt-drop,
  dispatch, Timeout→Reconnect). 44 passed, ruff clean.
- [x] **H2 — Forecast-Retry: fixe 3-h-Wartezeit auch nach Fehler** ✅ `FORECAST_FAIL_BACKOFF_S =
  min(FORECAST_S,300)`; bei Exception kurzer Backoff. 2 neue Tests. 85 passed.
- [x] **H3 — verdächtige FastAPI/Starlette-Pins** → **erledigt/verifiziert**: beide Releases existieren
  auf PyPI, `fastapi 0.137.0` verlangt `starlette>=0.46.0`, `1.0.1` erfüllt das. Kein Eingriff.

## MEDIUM — alle erledigt ✅

- [x] **M1 — Thread-Race auf `_forecast_remaining`** ✅ `fc`-Snapshot pro Zyklus. Test mit Mid-Cycle-Mutation.
- [x] **M2 — Watchdog-Re-Arm vs. Status-Reporting** ✅ Reporting in eigenem `try`, Fehler als `reporting` kategorisiert.
- [x] **M3 — Vicare Endlos-Loop bei falschen Creds** ✅ `max_invalid_attempts` → `SystemExit` (CrashLoopBackOff). 2 Tests.
- [x] **M4 — Prometheus `isfinite`-Guard** ✅ `parse_prom_value` lehnt NaN/±Inf ab. 2 Tests.
- [x] **M5 — SMA-OBIS-Decoder desync** ✅ längengesteuerter Walk (`4+typ`, bounds-checked). 2 Tests.
- [x] **M6 — SQL Spalten-Interpolation** ✅ `psycopg2.sql.Identifier` (injektionssicher by construction). Integration-Guard.
- [x] **M7 — Multicast-Interface** ✅ `SMA_IFACE_IP` env, `_membership_request()`. 2 Tests.
- [x] **M8 — `daily_production` Counter-Reset** ✅ Summe positiver Deltas via `lag()`. Integrationstest.
- [x] **M9 — `TypedDict` Reading-Contract** ✅ `MeterReading`, Contract-Lock-Test.
- [x] **M10 — `read_state` Typ-Validierung** ✅ `_num()`-Coercion → blind statt Crash. Test.
- [x] **M11 — Compose Resource-Limits** ✅ `deploy.resources.limits` in prod + demo, spiegelt k8s.
- [x] **M12 — `prometheus_client` Drift** ✅ vicare 0.20 → 0.21.

Regression nach MEDIUM: energy 49 · surplus 88 · control-ui 118 · vicare 30 · integration 6 · ruff clean.

## LOW

- [x] **L1 — Type-Hints** ✅ `statemachine.decide` voll typisiert (safety core), `config` bereits typisiert.
- [~] **L2 — Monolithische `main()`-Loop → `process_cycle`** — **bewusst deferred.** Begründung: die Loop
  verschränkt reine Logik mit I/O (External-Reconcile mutiert `relay_on`/`last_on` per DB-Write zwischen
  den Streak-Berechnungen), ist sicherheitskritisch und stark getestet/kommentiert. Vollständige Extraktion
  = echtes Regressionsrisiko für LOW-Style-Gewinn; Teil-Extraktion = kosmetisch. Empfehlung: separater,
  einzeln reviewter PR, falls gewünscht.
- [x] **L3 — Magic Numbers** ✅ `STARTUP_LONG_AGO_S`, `HEARTBEAT_BUDGET_S`, `_OFF_THRESHOLD_GAP_W`.
- [x] **L4 — `_basic_ok` bare `except` verengt** ✅ `(binascii.Error, UnicodeDecodeError, ValueError)`.
- [x] **L5 — Vicare `_next_backoff`-Helfer** ✅ Dedup beider Loops, 2 Tests. (Jitter bewusst weggelassen: Singleton.)
- [x] **L6 — vicare `set_from` `float()`-Guard** ✅ nicht-numerischer Wert skippt statt Crash. Test.
- [x] **L7 — `.ruff_cache/` in `.gitignore`** ✅.
- [x] **L8 — `.dockerignore` pro Service** ✅ (4 Services).
- [x] **L9 — Image-CVE-Scan (Trivy) in CI** ✅ `image-scan`-Job, HIGH/CRITICAL, `--ignore-unfixed`.
  ⚠️ Braucht einen Live-CI-Lauf zur Bestätigung (Trivy-Tag `0.58.1`, neuer Job) — lokal nicht ausführbar.
- [x] **L10 — k8s Probes** ✅ TimescaleDB readiness+liveness (`pg_isready`), vicare readiness.
- [x] **L11 — Trust-Boundaries dokumentiert** ✅ neuer SECURITY.md-Abschnitt (Binds, CSRF-no-Origin, IP-Spoof).
- [x] **L12 — Substring-Matching kommentiert** ✅ (vicare, last-resort).

## Review

**Ergebnis:** Alle HIGH (2 + 1 verifiziert), alle MEDIUM (12), alle LOW (11 erledigt, L2 bewusst deferred).
Streng nach TDD gearbeitet: jede Verhaltensänderung Test-rot → minimal-grün → refactor. Verhaltenserhaltende
Härtungen (sql.Identifier, narrow excepts, Konstanten, Type-Hints) mit grüner Suite verifiziert.

**Neue Tests:** energy +5 (Speedwire run/timeout/iface, Decoder-desync/truncated, MeterReading-Contract),
surplus +4 (Forecast-Backoff, fc-Snapshot, Reporting-Isolation, non-numeric-blind), control-ui +2 (NaN/Inf),
vicare +4 (invalid-creds-exit, transient-recovery, next_backoff, set_from-guard), integration +1 (Counter-Reset).

**Testbilanz:** energy 49 · surplus 88 · control-ui 118 · vicare 33 · integration 6 · config 3 = **297, alle grün; ruff clean.**

**Sterne-Ziele:** operative Robustheit (Socket-Timeout/Reconnect, Forecast-Backoff, fc-Snapshot,
Reporting-Isolation, Decoder-Robustheit, Counter-Reset-Guard, invalid-creds-Exit, non-numeric-Coercion,
Compose-Limits) und Code-Stil (Type-Hints am safety core, benannte Konstanten, TypedDict-Contract,
`_next_backoff`-Dedup, narrow excepts, injektionssicheres SQL) deutlich gehoben → Ziel 4–5★ erreicht,
mit Ausnahme der bewusst deferierten Loop-Extraktion (L2).

**Verifikation ausstehend (nicht lokal ausführbar):** der neue CI-`image-scan`-Job (L9) braucht einen
echten CI-Lauf; die Compose-`deploy.resources.limits` und k8s-Probes wurden YAML-validiert + `docker compose
config`, aber nicht live deployt.

## Phase 2 — Residuen aus Re-Assessment (+ Docs + Final Review)

### Code (TDD) — alle erledigt ✅
- [x] **A1 — sma_modbus NaN-Zähler → `None`** ✅ + `_setg`-Guard in update_inverter. 2 Tests.
- [x] **A2 — control-ui `today_summary` reset-fest** ✅ positive-Delta-Summen. Integrationstest.
- [x] **A3 — `SHM_HOST` Hostname-Auflösung** ✅ `gethostbyname` + fail-fast. 2 Tests.
- [x] **A4 — `_basic_ok` constant-time** ✅ beide Digests, dann `&`. Test.
- [x] **A5 — vicare `validate_env()`** ✅ + Aufruf in main(). 3 Tests.
- [x] **A6 — config.py Safety-Bound-Konstanten** ✅.
- [x] **A7 — Type-Hints** ✅ shelly + dblog public functions.
- [x] **A8 — cross-thread `control_config`-Write dokumentiert** ✅ (update_pr docstring).

### Infra/DB — alle erledigt ✅
- [x] **B1 — migration 002 (Query-Indizes)** ✅ idempotent (2× gegen Live-DB verifiziert).
- [x] **B2 — compose timescaledb/db-migrate hardening** ✅ (no-new-privileges; db-migrate cap_drop ALL — Container-Start live verifiziert).
- [x] **B3 — vicare k8s readOnlyRootFilesystem** ✅ (+ /tmp emptyDir + PYTHONDONTWRITEBYTECODE).
- [x] **B4 — Dependabot-Config** ✅ (actions + pip×4). SARIF-Upload bewusst geskippt.

### Docs — erledigt ✅
- [x] **C1 — CHANGELOG `[Unreleased]`** ✅ Added/Changed/Fixed/Security.
- [x] **C2 — `.env.example` + setup.md** für `SMA_IFACE_IP` + SHM_HOST-Hostname ✅. README ohne Drift.

Regression nach Phase 2: energy 53 · surplus 88 · control-ui 119 · vicare 36 · integration 7 · ruff clean = **303 grün**.

### Final
- [x] **D — unabhängiger Review** (3 Agenten) ✅ → Code-Qualität **4/5**, Architektur **4/5**, Sicherheit **4.5/5**.

### Phase 3 — neue HIGH aus dem Review (sofort gefixt, TDD)
- [x] **R1 — threshold Division durch 0** bei degeneriertem `full_sun_ref_kwh` → Guard. Test.
- [x] **R2 — control-ui balance 500 bei NULL-Config-Spalte** → `or default` coalesce. Test.
- [x] **R3 — read_inverter still geschluckte Exception** → `log.warning(exc_info)`. Test.

Schluss-Regression: energy 54 · surplus 89 · control-ui 120 · vicare 36 · integration 7 · ruff clean = **306 grün**.

## Phase 4 — Architektur (erledigt ✅)
- [x] **Arch H1 — `/status` versioniert** ✅ Producer stempelt `schema:1`, Consumer warnt bei Mismatch; `docs/status-interface.md`. 2 Tests.
- [x] **Arch H2 — `connect`/`live_conn` Drift** ✅ auf logging-reiche Variante konvergiert (behebt zugleich Silent-Swallow in energy/vicare) + 2 Konsistenz-Guard-Tests. *(Reviewer-Behauptung „byte-identical" war falsch — sie waren bereits gedriftet.)*
- [x] **Arch H3 — vicare „positional schema"** ✅ **war bereits korrekt** (INSERT benennt Spalten); irreführenden init.sql-Kommentar korrigiert + Namens-Konsistenztest ergänzt.
- [x] **Arch M1 — Forecast nicht pluggable** ✅ als bewusste Scoping-Entscheidung dokumentiert (YAGNI; PR-Self-Calibration statt Source-Swap). Kein Code.

## Phase 5 — Security-in-Depth (erledigt ✅)
- [x] **Sec M1 — Token-File chmod 0600** ✅ `secure_token_file()` + umask 0077. 2 Tests.
- [x] **Sec M2 — `STATUS_BIND`** ✅ (Test) + **opt-in NetworkPolicy** (`deploy/k8s/networkpolicy.yaml`, ehrlicher hostNetwork-Vorbehalt).
- [x] **Sec L6 — timescaledb securityContext** ✅ sicherer Teilumfang (`allowPrivilegeEscalation:false` + seccomp; runAsNonRoot/readOnly/capDrop bewusst weggelassen — Postgres braucht root zum Init).

Docs: CHANGELOG (Added/Fixed/Security), `status-interface.md`, `architecture.md` (Forecast-Scoping + /status-Link), `.env.example` (STATUS_BIND), SECURITY.md (Mitigations). 

Schluss-Regression: energy 54 · surplus 91 · control-ui 121 · vicare 38 · integration 10 · ruff clean = **314 grün**.

## Phase 6 — Offene Items + Release 0.3.1 (erledigt ✅)
- [x] **L2 (Teilmenge) — Entscheidungskern extrahiert** ✅ pure `decide_action()` (Load-Komp + Streaks + decide), 3 direkte Unit-Tests; Loop schlanker, Verhalten via run_loop-Tests bestätigt (94 surplus grün).
- [x] **mypy-Gate (scoped, passing)** ✅ `mypy.ini` + CI-Schritt über 14 typisierte Kern-/Boundary-Module (gepinnt `mypy==1.14.1`); 2 Fixes (sma_decoder MeterReading-Literal, validation-Annotation) zum Verbreitern.
- [x] **Release 0.3.1 vorbereitet** ✅ CHANGELOG `[0.3.1] - 2026-06-15` (Added/Changed/Fixed/Security) + frisches `[Unreleased]` + Links; alle Image-Tags / `SUNSTEER_VERSION` / kustomization newTag / `.env.example` auf 0.3.1; compose prod+demo valide.

Schluss-Regression: energy 54 · surplus 94 · control-ui 121 · vicare 38 · integration 10 = **317 grün**; ruff clean; mypy-Gate clean (14 Dateien).

### Weiterhin bewusst offen (brauchen Repo-Root-Build-Context-Umbau → eigener PR)
- `_pos_int`-Dedup und H2-Vollausbau (echte geteilte DB-Lib statt Drift-Guard) — beide blockiert durch die pro-Service Build-Contexts; unverhältnismäßig für einen Patch-Release.

### Release-Handgriffe für den User (manuell, da kein git durch mich)
- `git tag v0.3.1` + push → der release.yml-Workflow baut/published Images, SBOM + Provenance.
- Vorbehalt: CI-`image-scan` (Trivy) und die k8s-Manifeste sind lokal nicht voll ausführbar — erster CI-/Cluster-Lauf bestätigt sie.

## Vorgehen
1. HIGH zuerst (H1, H2), je TDD: Test rot → minimal grün → refactor.
2. Nach jeder Severity-Stufe: volle Suite des betroffenen Service grün + kurzer Status.
3. MEDIUM, dann LOW.
4. Abschluss: Review-Sektion unten + Gesamttest aller Services.

## Review
(wird am Ende gefüllt)
