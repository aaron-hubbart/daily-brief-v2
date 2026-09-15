# Deploying the hosted viewer

This deploys `viewer/webapp/` as a container on Kubernetes (GKE), mirroring the pattern already in use for the dashboard app at `dashboard.es-sandbox.com`: Cloud Build → GCR, nginx-ingress, cert-manager, one namespace per app. It uses Camunda's existing Azure AD tenant and the app registration you already created. Storage is a self-hosted Postgres (StatefulSet + PVC) in the same namespace — see `db/README.md` for the schema and why it's per-item rather than one file per day.

This app gets its own namespace (`daily-brief-v2`) and its own path (`/daily-brief-v2`) on the shared host — it does not touch the dashboard app's namespace, Ingress, or Secret.

**Assumption flagged for you to confirm**: the image tag below (`gcr.io/tam-aaron-hubbart/daily-brief-viewer:latest`) uses the same GCP project ID as the dashboard app's images, inferred from its `cloudbuild.yaml`. If that's not the right project, update the tag in `cloudbuild.yaml`, `k8s/deployment.yaml`, and `k8s/cronjob.yaml` before proceeding.

## 1. Finish the app registration

1. **Redirect URI**: Entra ID → App registrations → your app → **Authentication** → **Add a platform** → **Web** → add exactly:
   ```
   https://dashboard.es-sandbox.com/daily-brief-v2/auth/callback
   ```
2. **Client secret**: **Certificates & secrets** → **New client secret**, if you don't already have one saved. Copy the **value** immediately — it can't be retrieved again later.
3. **Supported account types**: should be single-tenant ("Accounts in this organizational directory only") — this is what makes "any Camunda user" work and also what keeps non-Camunda accounts out.
4. Note the **Application (client) ID** and **Directory (tenant) ID** from the Overview page — you'll need both in step 3 below.

## 2. Build and push the image

```powershell
gcloud builds submit --config=viewer/webapp/cloudbuild.yaml .
```

Run from the repo root. `cloudbuild.yaml`'s `dir: viewer` step points the actual Docker build context at `viewer/`, so the image can pick up both `webapp/` and the shared `daily-brief-viewer.html` one level up. This is also the image the archival CronJob runs (step 6) — one image, two different entry commands.

## 3. Namespace and secrets

```powershell
kubectl apply -f viewer/webapp/k8s/namespace.yaml

$postgresPassword = python3 -c "import secrets; print(secrets.token_urlsafe(24))"
kubectl create secret generic postgres-credentials --namespace daily-brief-v2 --from-literal=POSTGRES_USER=dailybrief --from-literal=POSTGRES_PASSWORD=$postgresPassword --from-literal=POSTGRES_DB=dailybrief

$flaskSecretKey = python3 -c "import secrets; print(secrets.token_hex(32))"
kubectl create secret generic daily-brief-secrets --namespace daily-brief-v2 --from-literal=FLASK_SECRET_KEY=$flaskSecretKey --from-literal=AZURE_CLIENT_ID="<from the app registration>" --from-literal=AZURE_CLIENT_SECRET="<from the app registration>" --from-literal=AZURE_TENANT_ID="<Camunda's tenant ID>"
```

Generating the password/key into a variable first, then using it in a one-line command, sidesteps PowerShell's line-continuation backtick entirely — one less thing to get wrong from a copy-paste. You can `echo $postgresPassword` first to sanity-check it before running the `kubectl create secret` line if you want to see it.

Never `kubectl apply -f k8s/*.template.yaml` directly — those are references for which keys exist, not something to fill in and apply.

`postgres-credentials` is the single source of truth for the DB connection — both the Postgres StatefulSet and the app Deployment read from it (the app builds `DATABASE_URL` from these three values via Kubernetes' `$(VAR)` env interpolation, so there's nothing to keep in sync by hand between the two).

There's no `UPLOAD_TOKENS` secret anymore — each person's API token now lives in Postgres and is assigned automatically the first time they sign in through the browser. See step 8.

## 4. Postgres

```powershell
kubectl create configmap postgres-schema --namespace daily-brief-v2 --from-file=viewer/webapp/db/schema.sql

kubectl apply -f viewer/webapp/k8s/postgres-statefulset.yaml
kubectl apply -f viewer/webapp/k8s/postgres-service.yaml

kubectl -n daily-brief-v2 rollout status statefulset/postgres
```

The `postgres-schema` ConfigMap is mounted at `/docker-entrypoint-initdb.d/` — the official Postgres image auto-runs any `.sql` files there, but **only the very first time it initializes an empty data directory**. If you change `schema.sql` later, re-creating this ConfigMap and restarting the pod won't re-apply it — that needs a real migration step (`kubectl exec` into the pod and run the new SQL by hand, or a proper migration tool, once there's a second schema change to make).

**If Postgres is already running from a previous deploy** (true for any cluster that predates migration 007): apply each new migration by hand once, against the running database — for example:

```powershell
Get-Content -Raw viewer/webapp/db/migrations/007_drop_api_token_and_account_projects.sql | kubectl exec -i -n daily-brief-v2 postgres-0 -- psql -U dailybrief -d dailybrief
```

Safe to run more than once.

Same deal for the `onboarding_completed_at` column added for the setup walkthrough — anyone upgrading from before that needs this too, also safe to run more than once:

```powershell
Get-Content -Raw viewer/webapp/db/migrations/002_add_onboarding_completed.sql | kubectl exec -i -n daily-brief-v2 postgres-0 -- psql -U dailybrief -d dailybrief
```

Existing users get `NULL` (walkthrough shows automatically next time they sign in) rather than a backfilled "completed" — a harmless one-time modal for people who already know the ropes, and they can dismiss it in a couple clicks.

Same again for the per-user `asana_pat` column and the `account_projects` mirror table added for the live Action Items pull (Overdue/Due Next 7 Days/No Due Date) — both safe to run more than once, and both leave existing users with the equivalent of "not connected yet" (no backfill needed, no live pull until each person adds their own token through the setup walkthrough or Account panel):

```powershell
Get-Content -Raw viewer/webapp/db/migrations/003_add_asana_pat.sql | kubectl exec -i -n daily-brief-v2 postgres-0 -- psql -U dailybrief -d dailybrief
Get-Content -Raw viewer/webapp/db/migrations/004_add_account_projects.sql | kubectl exec -i -n daily-brief-v2 postgres-0 -- psql -U dailybrief -d dailybrief
```

Same again for the `sso_sessions` table added for cross-app single sign-on (see "Shared SSO with the TAM Dashboard" below) — safe to run more than once, and a no-op for this app's own behavior until `SSO_COOKIE_DOMAIN` is actually set:

```powershell
Get-Content -Raw viewer/webapp/db/migrations/008_add_sso_sessions.sql | kubectl exec -i -n daily-brief-v2 postgres-0 -- psql -U dailybrief -d dailybrief
```


## 5. The app

```powershell
kubectl apply -f viewer/webapp/k8s/deployment.yaml
kubectl apply -f viewer/webapp/k8s/service.yaml
kubectl apply -f viewer/webapp/k8s/proxy-headers-configmap.yaml
kubectl apply -f viewer/webapp/k8s/ingress.yaml
```

## 6. The archival CronJob

```powershell
kubectl apply -f viewer/webapp/k8s/cronjob.yaml
```

Runs `archive_briefs.py` daily (09:00 UTC by default — edit the `schedule` in `cronjob.yaml` if you want a different time). See `db/README.md` for exactly what it does: brief days older than 14 days get marked `archived` (no longer shown to the end user, but still in the DB); brief days older than 30 days get permanently deleted. Both checks run every time the job fires, independent of each other.

To confirm it's wired up correctly without waiting for the schedule:
```powershell
kubectl create job --from=cronjob/daily-brief-archive daily-brief-archive-manual-test -n daily-brief-v2
kubectl -n daily-brief-v2 logs job/daily-brief-archive-manual-test
kubectl -n daily-brief-v2 delete job daily-brief-archive-manual-test
```

## 7. Verify

```powershell
kubectl -n daily-brief-v2 get pods,svc,ingress,statefulset
kubectl -n daily-brief-v2 get certificate          # watch cert-manager issue the TLS cert; wait for Ready: True
kubectl -n daily-brief-v2 logs deploy/daily-brief-viewer --tail=50
```

- `https://dashboard.es-sandbox.com/daily-brief-v2/healthz` → `ok` (process liveness, doesn't touch the DB).
- `https://dashboard.es-sandbox.com/daily-brief-v2/readyz` → `ok` once Postgres is reachable; `503` with a message if not — this is what the readiness probe actually checks, so a `503` here means the pod won't receive traffic yet, which is correct.
- `https://dashboard.es-sandbox.com/daily-brief-v2/` → redirects to a Microsoft sign-in page, then back to the viewer once you sign in with any `@camunda.com` account.
- Confirm the dashboard app at `/` and `/api`/`/auth` on the same host is completely unaffected — this Ingress only claims `/daily-brief-v2`.

## 8. Roll out to test users

This is fully self-service — no `kubectl` step per person:

1. **They sign in.** Visit the URL, sign in with any `@camunda.com` account. `db.get_or_create_user` creates their `users` row automatically — nothing for you to provision.
2. **They run `/daily-brief setup` in Claude** (see the in-app Setup walkthrough, or the skill repo's own `README.md`) — this writes their brief config directly to their own Google Drive.
3. **They connect Google Drive and (optionally) Asana** from the Account panel or the Setup walkthrough.
4. **Their skill starts writing briefs to Drive**, and their brief shows up next time they load the viewer (after connecting Drive).

Signing in and having reports show up are still two separate things — a person can sign in today and see an empty state until they've connected Google Drive and run the skill at least once.

## Shared SSO with the TAM Dashboard

Part of merging this viewer into the TAM Dashboard shell (`dashboard.es-sandbox.com/`) is single sign-on between the two apps, so a person doesn't have to log in twice on the same host. This app is the chosen identity authority (it already does a real MSAL sign-in with token refresh; the dashboard's Express proxy currently does its own hand-rolled OAuth and would otherwise need to be reconciled anyway) — off by default until the dashboard side is wired up to consume it:

1. **This app**, on every successful sign-in, creates a row in the `sso_sessions` table (see migration 008 above) and — only if `SSO_COOKIE_DOMAIN` is set — sets a `dashboard_sso` cookie scoped to the whole host (`Domain=dashboard.es-sandbox.com; Path=/`, unlike this app's own `daily_brief_session` cookie which stays scoped to `/daily-brief-v2`). `/logout` invalidates the row and clears the cookie.
2. **`GET /internal/sso/verify?token=...`** resolves that token to `{authenticated: true, user: {id, email, slug}}` (or `{authenticated: false}`) for any caller presenting the right `X-Internal-Auth: <INTERNAL_SSO_SECRET>` header. This is how the dashboard's Express proxy is meant to recognize a signed-in user — it already receives the shared cookie automatically (same domain), so it just needs to read `req.cookies.dashboard_sso` and forward it to this endpoint instead of running its own Azure AD callback.
3. **To turn this on**: generate a secret, put it in the live `daily-brief-secrets` Secret under `INTERNAL_SSO_SECRET` (see `k8s/secret.template.yaml`), configure the *same* value on the dashboard app, then set `SSO_COOKIE_DOMAIN=dashboard.es-sandbox.com` in `k8s/deployment.yaml` and roll out:
   ```powershell
   $internalSsoSecret = python3 -c "import secrets; print(secrets.token_hex(32))"
   kubectl -n daily-brief-v2 patch secret daily-brief-secrets --type merge -p "{\"stringData\":{\"INTERNAL_SSO_SECRET\":\"$internalSsoSecret\"}}"
   ```
   Until the dashboard app actually calls `/internal/sso/verify`, this is inert — the cookie gets set but nothing reads it, and the endpoint 404s for anyone without the secret.
4. **Not done yet**: the dashboard app's own side of this (reading the shared cookie, calling this endpoint, and retiring its own `/auth/login`, `/auth/callback`, `/auth/logout` in favor of redirecting here) lives in the `dashboard` repo, not this one — that's the other half of Phase 1.
5. **Expiry cleanup**: `sso_sessions` rows expire (`expires_at`, 8 hours from creation) but nothing deletes old rows yet — low volume for now, but worth folding into `archive_briefs.py`'s daily run if this sees real traffic.

## Updating the deployed image later

```powershell
gcloud builds submit --config=viewer/webapp/cloudbuild.yaml .
kubectl -n daily-brief-v2 rollout restart deployment/daily-brief-viewer
```

The image tag is `:latest`, so a plain re-apply of `deployment.yaml` won't pick up a new image. `rollout restart` forces a fresh pull. The CronJob (step 6) uses the same tag, so its next scheduled run also picks up whatever's newly pushed — no separate step needed for that. If you want each build independently addressable and roll-back-able, switch the tag to `$BUILD_ID` or a git SHA in `cloudbuild.yaml`, `deployment.yaml`, and `cronjob.yaml` — the dashboard app's own `cloudbuild.yaml` already does this for its proxy image via `--build-arg APP_VERSION=$BUILD_ID`, worth copying here too if this graduates past testing.

## Local development (without Kubernetes)

Needs a local Postgres in addition to `.env.example` → `.env`. On Windows this means either a native PostgreSQL install (the official installer puts `psql`/`createdb` on PATH) or a Postgres container (`docker run` / Podman) with the port published to `localhost`.

```powershell
# one-time local Postgres setup
createdb dailybrief
psql dailybrief -f viewer/webapp/db/schema.sql

cd viewer/webapp
python3 -m venv venv
venv\Scripts\pip install -r requirements.txt

# Load .env into this session's environment variables — PowerShell has no
# direct equivalent of bash's "source .env", so this parses key=value lines
# and sets each one for the current process only.
Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([^#=]+)=(.*)$') {
        [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), 'Process')
    }
}

venv\Scripts\python app.py
```

This runs the Flask dev server directly (not gunicorn, not a container) for quick local iteration. It still does the real MSAL/Azure AD flow, so `AZURE_REDIRECT_URI` needs to point at wherever you're actually running it (e.g. `http://localhost:8000/auth/callback`, registered as an additional Redirect URI on the app registration for local testing). Run `archive_briefs.py` the same way (`venv\Scripts\python archive_briefs.py`) to test the archival logic locally — the `.env` values loaded above stay set for the rest of that PowerShell session, so you don't need to reload them between the two.

## What this doesn't do yet

- **Checked-state sync.** Done. Checkbox toggles call `/api/items/<section>/<item_key>/checked`, which persists across devices and, for Action Items, mirrors onto the linked Asana task's completed state when the signed-in person has their own `asana_pat` configured (see the section above).
- **Multi-tenant automation.** This gets each test user a login and isolated data. It does not make the daily-brief *skill* itself multi-user — each person who wants their own automated briefs still needs their own Claude project and their own Drive/Slack/Asana connections. This is the viewer/hosting/storage layer only.
- **Group-based restriction.** `ALLOWED_GROUPS` is present in `app.py` but inactive, since this test rollout is open to any Camunda tenant user.
- **Admin panel.** `/admin` lists every real signed-in user (sign-up date, active brief count, last-active date) and lets an admin create/impersonate/delete throwaway test users for exercising the new-user experience safely (see the Admin Impersonation section below). Gated by `ADMIN_EMAILS` (comma-separated, case-insensitive) in `deployment.yaml`; empty/unset 404s the panel for everyone. Not a secret value, so it's a plain env var rather than a Kubernetes Secret — edit `deployment.yaml` directly and `kubectl -n daily-brief-v2 rollout restart deployment/daily-brief-viewer` to pick up a change.
- **Asana checkbox sync.** Checking or unchecking an Action Item in the viewer PATCHes `/api/items/action-items/{item_key}/checked`, which persists to Postgres (for New Items) and, when the signed-in person has their own Asana PAT configured (`users.asana_pat`, set via the setup walkthrough or Account panel — see `migrations/003_add_asana_pat.sql`), PUTs the same completed state to the linked Asana task (item_key is `action-{asana_gid}`, so no lookup is needed). No PAT configured and the checkbox still persists across devices for New Items, it just doesn't reach Asana; for the live-pulled Overdue/Due Next 7 Days/No Due Date items there's no Postgres row at all, so a checkbox toggle there only ever writes to Asana directly, and does nothing (no-ops with a 404) if the person somehow reaches one without a PAT configured, which the UI shouldn't allow since those subsections only render when a PAT exists. Check `users_with_asana_pat` on the admin panel's deployment status for an aggregate count without exposing any token value itself.
- **Live Action Items pull.** Overdue, Due Next 7 Days, and No Due Date are no longer synced by the skill at all — the webapp fetches them straight from Asana on every `/brief/<date>` page render (`app.py`'s `_fetch_live_action_items`), using `users.asana_pat` and the account→project-GID mapping read live from that user's Drive `account-config.json` (`gdrive_briefs.get_account_projects`). Only New Items — tasks the brief run itself just created — are ever written to Postgres for this section now.
- **In-app setup walkthrough.** First sign-in (`onboarding_completed_at IS NULL` on the `users` row) automatically opens a 4-step modal in the viewer: install the skill and run its First-Run Setup, connect data-source connectors, a couple of odds and ends (Claude Desktop, README pointer), and an optional step to connect a personal Asana PAT for the live Overdue/Due Next 7 Days/No Due Date pull (skippable — New Items keeps working either way). It calls `/api/onboarding/complete` on finishing so it doesn't reopen automatically, but anyone can reopen it any time via the "Setup" button in the topbar.
- **Account panel.** The "Account" button in the topbar shows the signed-in person's email, Google Drive connection status, and Asana connection status with save/disconnect controls for `asana_pat`, so connecting or removing Asana doesn't require replaying the whole setup walkthrough.
- **Admin impersonation.** `/admin` can create throwaway test users (synthetic `@daily-brief.local` emails, `is_test = TRUE`) and impersonate them to exercise the new-user onboarding flow without touching real data. A banner shows while impersonating, with a one-click return to the admin's own session. Impersonation can only ever target a test user — never a real one, even via a crafted user ID.
- **Image tag pinning.** Currently `:latest` for simplicity during testing.
- **Schema migrations.** `schema.sql` only runs once, on first Postgres init (see step 4). There's no migration tooling yet for changing the schema after that.
