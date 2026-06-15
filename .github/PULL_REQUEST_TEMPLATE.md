<!-- Thanks for contributing to Sunsteer! Keep PRs focused — one concern per PR. -->

## What and why

<!-- What does this change do, and why? Link any related issue: "Closes #123". -->

## How it was tested

<!-- Commands you ran and what you observed. CI runs each service's Dockerfile `test`
     stage; for a quick local loop see CONTRIBUTING.md. -->

```
# e.g. docker build --target test services/<service>
```

## Checklist

- [ ] PR is focused on a single concern.
- [ ] New behaviour has tests; bug fixes have a regression test.
- [ ] All four service test stages pass (`.github/workflows/ci.yml`), and `ruff` is clean.
- [ ] No hardcoded private values (IPs, coordinates, credentials) — env vars with neutral
      defaults, and RFC-5737 (`192.0.2.x`) addresses in tests.
- [ ] User-facing UI strings go through the i18n table (`services/control-ui/src/i18n.py`)
      with **English and German** entries.
- [ ] Schema changes are a numbered idempotent migration in `db/migrations/` (not an edit
      to `init.sql`).

## Safety-relevant changes

<!-- Required if this touches the fail-safe chain: stale-data handling, the relay auto-off
     watchdog, minimum runtimes, or the fail-closed UI auth. Otherwise write "n/a". -->

- [ ] This PR does **not** touch the fail-safe chain, **or** the behaviour change and its
      failure modes are explained below.

<!-- Explanation: -->
