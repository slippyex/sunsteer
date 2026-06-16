# Example Kubernetes manifests

Example manifests — **adapt them to your cluster. Not a turnkey deploy.** They are a
generic kustomize base (placeholders marked `CHANGE_ME`) mirroring the Compose stack in
`../compose/`. Images come from `ghcr.io/slippyex/sunsteer` (multi-arch, the reference
install runs on K3s).

## What's here

| File | Purpose |
|---|---|
| `namespace.yaml` | Namespace `sunsteer` |
| `timescaledb.yaml` | TimescaleDB Deployment + Service + 1Gi PVC |
| `energy-exporter.yaml` | Meter/relay reader — `hostNetwork: true` for Speedwire multicast |
| `surplus-controller.yaml` | The control loop |
| `control-ui.yaml` | Web UI |
| `heatpump-exporter.yaml` | Optional heat-pump telemetry — OFF by default; uncomment it in `kustomization.yaml` (and fill the VICARE_* secret keys for the `vicare` driver) to enable |
| `secret.example.yaml` | Secret template — copy to `secret.yaml` and fill in |
| `kustomization.yaml` | Ties it together |

## Deploy

```bash
cd deploy/k8s

# 1. Namespace (needed before the init.sql ConfigMap can be created in it).
kubectl apply -f namespace.yaml

# 2. init.sql as a ConfigMap (mounted into TimescaleDB's docker-entrypoint-initdb.d;
#    only runs on a first-time, empty data directory).
kubectl -n sunsteer create configmap timescaledb-init --from-file=init.sql=../../db/init.sql

# 3. Migrations as a ConfigMap (mounted into the db-migrate Job). The Job's
#    `find -name '*.sql'` ignores the dir's README.md.
kubectl -n sunsteer create configmap sunsteer-migrations --from-file=../../db/migrations/

# 4. Credentials: copy the template, fill in every CHANGE_ME, DO NOT commit secret.yaml.
cp secret.example.yaml secret.yaml
$EDITOR secret.yaml

# 5. Also replace the CHANGE_ME placeholders (SHM_HOST, SHELLY_URL, PV_LAT/PV_LON,
#    PV_PLANES, ...) in the Deployment manifests for your site. The services fail fast
#    on an un-edited CHANGE_ME, so this is not optional.

# 6. Apply everything. This also creates the db-migrate Job, which applies
#    db/migrations/*.sql automatically (parity with the Compose db-migrate one-shot) —
#    init.sql seeds a fresh DB only; the migrations carry post-release changes (e.g. the
#    server-timeout hardening in 001) and are NOT in init.sql. The app pods may briefly
#    crashloop until the Job completes.
kubectl apply -k .

# 7. (Optional) watch the migration Job finish.
kubectl -n sunsteer wait --for=condition=complete job/db-migrate --timeout=120s
```

## Schema migrations

`db/init.sql` only runs on a fresh database; every post-release schema change lands as a
numbered, idempotent file in `db/migrations/` (see `../../db/migrations/README.md`). The
`db-migrate` Job (created by `apply -k`) applies them automatically — this is the
Kubernetes equivalent of the Compose `db-migrate` one-shot, so a by-the-book install is
hardened without a manual step.

**Upgrade that adds a migration:** refresh the ConfigMap with the new file, then re-apply.
The Job auto-deletes 10 min after it succeeds (`ttlSecondsAfterFinished`), so once that
window has passed `apply -k` recreates it on its own; within the window (or to force it)
delete it explicitly — a completed Job's pod template is immutable:

```bash
kubectl -n sunsteer create configmap sunsteer-migrations \
  --from-file=../../db/migrations/ --dry-run=client -o yaml | kubectl apply -f -
kubectl -n sunsteer delete job db-migrate --ignore-not-found
kubectl apply -k .
```

Migrations are idempotent, so re-running the full set is always safe.

## Notes

- **No private cluster specifics here** — no node affinities, tolerations, priority
  classes or fixed IPs. Add those to fit your cluster.
- `energy-exporter` uses `hostNetwork: true` because SMA Speedwire multicast does not
  cross the pod-network NAT; schedule it on a node on the same L2 as the SHM.
- `control-ui` is `ClusterIP` by default — switch to `NodePort` or front it with an
  Ingress to reach the UI from outside the cluster.
