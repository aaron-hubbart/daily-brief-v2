# Deploying the hosted viewer

This deploys `viewer/webapp/` as a container on Kubernetes (GKE), mirroring the pattern already in use for the dashboard app at `dashboard.es-sandbox.com`: Cloud Build → GCR, nginx-ingress, cert-manager, one namespace per app. It uses Camunda's existing Azure AD tenant and the app registration you already created. Storage is a self-hosted Postgres (StatefulSet + PVC) in the same namespace — see `db/README.md` for the schema and why it's per-item rather than one file per day.

This app gets its own namespace (`daily-brief`) and its own path (`/daily-brief`) on the shared host — it does not touch the dashboard app's namespace, Ingress, or Secret.

**Assumption flagged for you to confirm**: the image tag below (`gcr.io/tam-aaron-hubbart/daily-brief-viewer:latest`) uses the same GCP project ID as the dashboard app's images, inferred from its `cloudbuild.yaml`. If that's not the right project, update the tag in `cloudbuild.yaml`, `k8s/deployment.yaml`, and `k8s/cronjob.yaml` before proceeding.

## 1. Finish the app registration

1. **Redirect URI**: Entra ID → App registrations → your app → **Authentication** → **Add a platform** → **Web** → add exactly:
   ```
   https://dashboard.es-sandbox.com/daily-brief/auth/callback
   ```
2. **Client secret**: **Certificates & secrets** → **New client secret**, if you don't already have one saved. Copy the **value** immediately — it can't be retrieved again later.
3. **Supported account types**: should be single-tenant ("Accounts in this organizational directory only") — this is what makes "any Camunda user" work and also what keeps non-Camunda accounts out.
4. Note the **Application (client) ID** and **Directory (tenant) ID** from the Overview page — you'll need both in step 3 below.

## 2. Build and push the image

```bash
gcloud builds submit --config=viewer/webapp/cloudbuild.yaml .
```

Run from the repo root. `cloudbuild.yaml`'s `dir: viewer` step points the actual Docker build context at `viewer/`, so the image can pick up both `webapp/` and the shared `daily-brief-viewer.html` one level up. This is also the image the archival CronJob runs (step 6) — one image, two different entry commands.

## 3. Namespace and secrets

```bash
kubectl apply -f viewer/webapp/k8s/namespace.yaml

kubectl create secret generic postgres-credentials \
  --namespace daily-brief \
  --from-literal=POSTGRES_USER="dailybrief" \
  --from-literal=POSTGRES_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')" \
  --from-literal=POSTGRES_DB="dailybrief"

kubectl create secret generic daily-brief-secrets \
  --namespace daily-brief \
  --from-literal=FLASK_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')" \
  --from-literal=AZURE_CLIENT_ID="<from the app registration>" \
  --from-literal=AZURE_CLIENT_SECRET="<from the app registration>" \
  --from-literal=AZURE_TENANT_ID="<Camunda's tenant ID>" \
  --from-literal=UPLOAD_TOKENS='{"<generate-a-token>":"aaron.hubbart@camunda.com"}'
```

Never `kubectl apply -f k8s/*.template.yaml` directly — those are references for which keys exist, not something to fill in and apply. Generate tokens the same way as the secret keys above (`python3 -c "import secrets; print(secrets.token_hex(32))"` or `token_urlsafe`).

`postgres-credentials` is the single source of truth for the DB connection — both the Postgres StatefulSet and the app Deployment read from it (the app builds `DATABASE_URL` from these three values via Kubernetes' `$(VAR)` env interpolation, so there's nothing to keep in sync by hand between the two).

## 4. Postgres

```bash
kubectl create configmap postgres-schema \
  --namespace daily-brief \
  --from-file=viewer/webapp/db/schema.sql

kubectl apply -f viewer/webapp/k8s/postgres-statefulset.yaml
kubectl apply -f viewer/webapp/k8s/postgres-service.yaml

kubectl -n daily-brief rollout status statefulset/postgres
```

The `postgres-schema` ConfigMap is mounted at `/docker-entrypoint-initdb.d/` — the official Postgres image auto-runs any `.sql` files there, but **only the very first time it initializes an empty data directory**. If you change `schema.sql` later, re-creating this ConfigMap and restarting the pod won't re-apply it — that needs a real migration step (`kubectl exec` into the pod and run the new SQL by hand, or a proper migration tool, once there's a second schema change to make).

## 5. The app

```bash
kubectl apply -f viewer/webapp/k8s/deployment.yaml
kubectl apply -f viewer/webapp/k8s/service.yaml
kubectl apply -f viewer/webapp/k8s/proxy-headers-configmap.yaml
kubectl apply -f viewer/webapp/k8s/ingress.yaml
```

## 6. The archival CronJob

```bash
kubectl apply -f viewer/webapp/k8s/cronjob.yaml
```

Runs `archive_briefs.py` daily (09:00 UTC by default — edit the `schedule` in `cronjob.yaml` if you want a different time). See `db/README.md` for exactly what it does: brief days older than 14 days get marked `archived` (no longer shown to the end user, but still in the DB); brief days older than 30 days get permanently deleted. Both checks run every time the job fires, independent of each other.

To confirm it's wired up correctly without waiting for the schedule:
```bash
kubectl create job --from=cronjob/daily-brief-archive daily-brief-archive-manual-test -n daily-brief
kubectl -n daily-brief logs job/daily-brief-archive-manual-test
kubectl -n daily-brief delete job daily-brief-archive-manual-test
```

## 7. Verify

```bash
kubectl -n daily-brief get pods,svc,ingress,statefulset
kubectl -n daily-brief get certificate          # watch cert-manager issue the TLS cert; wait for Ready: True
kubectl -n daily-brief logs deploy/daily-brief-viewer --tail=50
```

- `https://dashboard.es-sandbox.com/daily-brief/healthz` → `ok` (process liveness, doesn't touch the DB).
- `https://dashboard.es-sandbox.com/daily-brief/readyz` → `ok` once Postgres is reachable; `503` with a message if not — this is what the readiness probe actually checks, so a `503` here means the pod won't receive traffic yet, which is correct.
- `https://dashboard.es-sandbox.com/daily-brief/` → redirects to a Microsoft sign-in page, then back to the viewer once you sign in with any `@camunda.com` account.
- Confirm the dashboard app at `/` and `/api`/`/auth` on the same host is completely unaffected — this Ingress only claims `/daily-brief`.

## 8. Roll out to test users

Any Camunda tenant account can already sign in once the above is live — nothing extra to configure per person for viewing itself. Two things do need a per-person step:

- **Viewing**: nothing extra. They visit the URL and sign in; their `users` row is created automatically on first sign-in (or on the first item their own skill upserts, whichever happens first).
- **Getting their own reports in**: each person who wants their own daily-brief skill pushing items here needs an entry in `UPLOAD_TOKENS` (a token mapped to their email) and their own copy of the daily-brief skill configured with that token. To add one without wiping existing tokens:
  ```bash
  kubectl get secret daily-brief-secrets -n daily-brief -o jsonpath='{.data.UPLOAD_TOKENS}' | base64 -d
  # edit the JSON to add the new person, then:
  kubectl create secret generic daily-brief-secrets -n daily-brief \
    --from-literal=UPLOAD_TOKENS='<the edited JSON>' \
    --dry-run=client -o yaml | kubectl apply -f -
  kubectl -n daily-brief rollout restart deployment/daily-brief-viewer
  ```
  Signing in to view and having reports show up are two separate things — a test user can sign in today and see an empty state until either they get an upload token and their own skill upserts some items, or you manually insert a test row for a quick look (see `db/README.md`'s schema for the shape).

## Updating the deployed image later

```bash
gcloud builds submit --config=viewer/webapp/cloudbuild.yaml .
kubectl -n daily-brief rollout restart deployment/daily-brief-viewer
```

The image tag is `:latest`, so a plain re-apply of `deployment.yaml` won't pick up a new image. `rollout restart` forces a fresh pull. The CronJob (step 6) uses the same tag, so its next scheduled run also picks up whatever's newly pushed — no separate step needed for that. If you want each build independently addressable and roll-back-able, switch the tag to `$BUILD_ID` or a git SHA in `cloudbuild.yaml`, `deployment.yaml`, and `cronjob.yaml` — the dashboard app's own `cloudbuild.yaml` already does this for its proxy image via `--build-arg APP_VERSION=$BUILD_ID`, worth copying here too if this graduates past testing.

## Local development (without Kubernetes)

Needs a local Postgres in addition to `.env.example` → `.env`:

```bash
# one-time local Postgres setup (adjust to your OS's package manager)
createdb dailybrief
psql dailybrief -f viewer/webapp/db/schema.sql

cd viewer/webapp
python3 -m venv venv && venv/bin/pip install -r requirements.txt
set -a; source .env; set +a
venv/bin/python app.py
```

This runs the Flask dev server directly (not gunicorn, not a container) for quick local iteration. It still does the real MSAL/Azure AD flow, so `AZURE_REDIRECT_URI` needs to point at wherever you're actually running it (e.g. `http://localhost:8000/auth/callback`, registered as an additional Redirect URI on the app registration for local testing). Run `archive_briefs.py` the same way (`venv/bin/python archive_briefs.py`) to test the archival logic locally.

## What this doesn't do yet

- **The skill doesn't call `/api/items/upsert` or `/api/items/batch-upsert` yet.** These replace what would have been `/api/upload` in the old file-based design — the skill would call `batch-upsert` once per full brief generation, and `upsert` again later for a single item's refresh (no separate "patch a file" flow needed anymore, unlike the old `references/section-refresh.md` approach). Wiring this into the skill's actual generation logic (`references/html-output.md`, `references/status-updates.md` in the skill repo) is a substantial, separate change to that repo's instructions, not done here — say when you want to tackle it and I'll take that on as its own piece of work.
- **Checked-state sync.** `/api/items/<section>/<item_key>/checked` exists and works (tested), but the viewer's frontend still only tracks checked state in browser localStorage, same as the old file-based model. Wiring the frontend to call this endpoint (so checked state follows you across devices) is a deliberate follow-up, not done in this pass.
- **Multi-tenant automation.** This gets each test user a login and isolated data. It does not make the daily-brief *skill* itself multi-user — each person who wants their own automated briefs still needs their own Claude project and their own Drive/Slack/Asana connections. This is the viewer/hosting/storage layer only.
- **Group-based restriction.** `ALLOWED_GROUPS` is present in `app.py` but inactive, since this test rollout is open to any Camunda tenant user.
- **Image tag pinning.** Currently `:latest` for simplicity during testing.
- **Schema migrations.** `schema.sql` only runs once, on first Postgres init (see step 4). There's no migration tooling yet for changing the schema after that.
