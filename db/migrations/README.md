# Schema migrations

**init.sql is the fresh-install schema snapshot. Every schema change after the first tagged release lands ONLY as a numbered, idempotent migration here (`NNN-description.sql`) — never inline in init.sql.** The compose `db-migrate` one-shot applies them in order on startup (prod AND demo); services wait for it via `depends_on: db-migrate: service_completed_successfully`. On Kubernetes, apply them manually (see `deploy/k8s/README.md`). Migrations must be safe to re-run (use `IF NOT EXISTS` / `ALTER ... SET` / idempotent guards).

## Boundary rules

| Location | Purpose | When to touch |
|---|---|---|
| `db/init.sql` | Full schema snapshot for a fresh install | Never after the first tagged release |
| `db/migrations/NNN-description.sql` | Incremental, idempotent schema changes | Every post-release schema change |

## Naming convention

Files are applied in lexicographic order — zero-pad the number so ordering is stable:

```
001-hardening.sql
002-add-decision-log-cols.sql
```

## Idempotency requirements

Every migration must be safe to re-run without error:

- New tables: `CREATE TABLE IF NOT EXISTS`
- New columns: `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
- New indexes: `CREATE INDEX IF NOT EXISTS`
- Config upserts: `INSERT ... ON CONFLICT DO UPDATE` or `ALTER TABLE ... SET DEFAULT`

## Compose stack behaviour

The `db-migrate` one-shot service (present in both `docker-compose.yml` and
`docker-compose.demo.yml`) runs all `*.sql` files under this directory in sorted order
before any application service starts. If any migration fails the one-shot exits non-zero
and dependent services will not start.

## Kubernetes

The `deploy/k8s/` base ships a `db-migrate` **Job** that mounts these files (from a
`sunsteer-migrations` ConfigMap) and applies them on `kubectl apply -k .` — the cluster
equivalent of the Compose one-shot. For the create-the-ConfigMap step and the
upgrade/re-run procedure, follow **`deploy/k8s/README.md` → "Schema migrations"**; do not
hand-roll a `kubectl run` (it has no migrations mounted).

---

Current migrations: `001-hardening.sql` (server timeouts: idle-in-transaction + statement).
