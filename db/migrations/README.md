# Schema migrations

`../init.sql` creates the full schema for a fresh install.

Once Sunsteer has tagged releases, schema changes land here as numbered, idempotent
scripts (`001-<description>.sql`, `002-...`), applied in order on upgrade. Scripts must
be safe to re-run (`IF NOT EXISTS` / `IF EXISTS` guards). A future compose deployment
will apply them automatically on startup; until then — and on Kubernetes — apply them
manually before rolling out a new version.

No migrations yet — the directory exists so the upgrade path is part of the repo layout
from day one.
