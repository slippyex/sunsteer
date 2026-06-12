# Schema migrations

`../init.sql` creates the full schema for a fresh install.

Once Sunsteer has tagged releases, schema changes land here as numbered, idempotent
scripts (`001-<description>.sql`, `002-...`), applied in order on upgrade. Scripts must
be safe to re-run (`IF NOT EXISTS` / `IF EXISTS` guards). The compose stack applies
them automatically on startup (`db-migrate` service in `deploy/compose/docker-compose.yml`);
on Kubernetes, apply them manually before rolling out a new version.

No migrations yet — the directory exists so the upgrade path is part of the repo layout
from day one.
