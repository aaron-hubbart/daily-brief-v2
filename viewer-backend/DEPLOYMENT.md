# Deploying the Drive-backed viewer

This deploys `viewer-backend/` as a container on the same GKE cluster v1
(`aaron-hubbart/daily-brief`'s `viewer/webapp/`) already runs on, in its own
namespace (`daily-brief-v2`) and its own path (`/daily-brief-v2`) on the
shared `dashboard.es-sandbox.com` host. It does not touch v1's namespace,
Ingress, Secret, or Postgres StatefulSet — the two coexist during the bake-in
period described in the design spec's Rollout section
(`docs/superpowers/specs/2026-07-21-daily-brief-v2-design.md`).

Storage is Google Drive, per-user, via two separate OAuth grants: the
existing Entra ID (M365) sign-in (unchanged from v1 — reuses the same Azure
AD app registration) and a **new** Google OAuth consent step this app adds.
There is no Postgres, no MCP server, and no per-user API token for a skill to
authenticate with — the skill writes directly to Drive via its own native
connector, so this webapp only ever talks to Drive using each signed-in
person's own consent.

**Assumption flagged for you to confirm**: the image tag below
(`gcr.io/tam-aaron-hubbart/daily-brief-viewer-v2:latest`) reuses the same GCP
project as v1's images. If that's not right, update it in the `gcloud builds
submit` command and `k8s/deployment.yaml` before proceeding.

## 1. Reuse the existing Azure AD app registration (add a second redirect URI)

v2 signs in against the **same** Camunda Azure AD tenant and app registration
v1 already uses — no new Azure app registration needed, just one more
allowed redirect URI on the existing one:

1. Entra ID → App registrations → your existing daily-brief app → **Authentication** → **Add a platform** (or add another URI under the existing Web platform) → add exactly:
   ```
   https://dashboard.es-sandbox.com/daily-brief-v2/auth/callback
   ```
   This is *in addition to* v1's `.../daily-brief/auth/callback` — both coexist on the same app registration.
2. You already have `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, and `AZURE_TENANT_ID` from v1's setup — reuse those same three values for v2's secret in step 4. There is no reason to rotate the client secret just for this; it's shared between both deployments.

## 2. Register the Google Cloud OAuth client (new — v1 never needed this)

This is the actual new dependency v2 introduces. The webapp needs its own
Google OAuth client (separate from the daily-brief skill's own Google Drive
connector inside Claude — that's a different OAuth client entirely, already
set up, not touched here) so it can read/write each signed-in user's Drive on
their behalf.

### 2a. Pick or create a Google Cloud project

Use the same GCP project as everything else here (`tam-aaron-hubbart`, or
whatever your GKE/GCR project actually is) unless you have a reason to
isolate this into its own project. Confirm you're pointed at the right one:

```powershell
gcloud config get-value project
```

### 2b. Enable the Drive API

```powershell
gcloud services enable drive.googleapis.com
```

### 2c. Configure the OAuth consent screen — User Type must be "Internal"

Google Cloud Console → **APIs & Services** → **OAuth consent screen**:

1. **User Type: Internal.** This is the single most important setting here.
   Internal apps are restricted to users in your own Google Workspace
   organization (`camunda.com`) and are **exempt from Google's app
   verification process** — including the CASA security assessment that
   would otherwise be required for the `drive` scope specifically, since
   it's a Google-classified "restricted" scope. Requesting the same scope
   as an **External** app would require submitting for that verification,
   which can take weeks and isn't warranted for an internal tool used by a
   handful of TAMs. "Internal" only shows up as an option if your Google
   account is part of a Google Workspace organization (it is, for
   `@camunda.com`) — a personal Gmail account can't create Internal apps.
2. Fill in app name (e.g. "Daily Brief Viewer"), user support email, developer
   contact email. These are shown on the consent screen users see when
   linking their Google account.
3. **Scopes**: add `https://www.googleapis.com/auth/drive` (the full,
   non-`.file` scope — see the design spec for why the narrower `drive.file`
   scope doesn't work here: this app needs to read files the *skill's*
   separate Drive connector created, and `drive.file` only grants access to
   files the requesting app itself created).
4. No test users list to manage — Internal apps skip that step entirely,
   unlike External apps in testing mode.

### 2d. Create the OAuth client ID

Google Cloud Console → **APIs & Services** → **Credentials** → **Create
Credentials** → **OAuth client ID**:

1. **Application type: Web application**
2. **Name**: e.g. "daily-brief-v2-viewer"
3. **Authorized redirect URIs** — add both of these (production and local dev):
   ```
   https://dashboard.es-sandbox.com/daily-brief-v2/auth/google/callback
   http://localhost:8000/auth/google/callback
   ```
4. Click **Create**. Copy the **Client ID** and **Client secret** shown —
   the secret is retrievable again later from the Credentials page (unlike
   Azure AD's, which is one-time-only), but copy both now while you're here.

## 3. Generate the token encryption key

```powershell
$tokenEncryptionKey = python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

This encrypts the Google refresh token and Asana PAT at rest in the SQLite
token store (`token_store.py`) — see the design spec's Auth flow section for
why this exists instead of a database.

## 4. Namespace and secrets

```powershell
kubectl apply -f viewer-backend/k8s/namespace.yaml

$flaskSecretKey = python -c "import secrets; print(secrets.token_hex(32))"
kubectl create secret generic daily-brief-secrets --namespace daily-brief-v2 `
  --from-literal=FLASK_SECRET_KEY=$flaskSecretKey `
  --from-literal=AZURE_CLIENT_ID="<same value v1 uses>" `
  --from-literal=AZURE_CLIENT_SECRET="<same value v1 uses>" `
  --from-literal=AZURE_TENANT_ID="<same value v1 uses>" `
  --from-literal=GOOGLE_CLIENT_ID="<from step 2d>" `
  --from-literal=GOOGLE_CLIENT_SECRET="<from step 2d>" `
  --from-literal=TOKEN_ENCRYPTION_KEY=$tokenEncryptionKey
```

This is a **separate Secret in a separate namespace** from v1's
`daily-brief-secrets` (which lives in the `daily-brief` namespace) — same
name, different namespace, so there's no collision and no risk of
overwriting v1's live credentials. Never `kubectl apply -f
k8s/secret.template.yaml` directly — it's a reference for which keys exist,
not something to fill in and apply.

## 5. Build and push the image

```powershell
gcloud builds submit --tag gcr.io/tam-aaron-hubbart/daily-brief-viewer-v2:latest viewer-backend/
```

Run from the repo root. This uses `gcloud`'s single-command image build
(no separate `cloudbuild.yaml` needed for a straightforward Dockerfile
build like this one) — if you want a proper Cloud Build config with a
pinned, roll-back-able tag later (matching v1's own noted follow-up), that's
a reasonable thing to add once this graduates past testing, not required
for the initial rollout.

## 6. The app

```powershell
kubectl apply -f viewer-backend/k8s/pvc.yaml
kubectl apply -f viewer-backend/k8s/deployment.yaml
kubectl apply -f viewer-backend/k8s/service.yaml
kubectl apply -f viewer-backend/k8s/ingress.yaml

kubectl -n daily-brief-v2 rollout status deployment/daily-brief-viewer
```

## 7. Verify

```powershell
kubectl -n daily-brief-v2 get pods,svc,ingress,pvc
kubectl -n daily-brief-v2 get certificate          # watch cert-manager issue the TLS cert; wait for Ready: True
kubectl -n daily-brief-v2 logs deploy/daily-brief-viewer --tail=50
```

- `https://dashboard.es-sandbox.com/daily-brief-v2/healthz` → `ok` (process liveness, doesn't touch the token store).
- `https://dashboard.es-sandbox.com/daily-brief-v2/readyz` → `ok` once the token store SQLite file is reachable; `503` with a message if not.
- `https://dashboard.es-sandbox.com/daily-brief-v2/` → redirects to Microsoft sign-in, then (first time) to Google's consent screen requesting Drive access, then to the viewer.
- Confirm v1 at `/daily-brief` and the dashboard app on the same host are completely unaffected — this is a separate Ingress in a separate namespace, claiming only `/daily-brief-v2`.

## 8. Link a Drive folder (one-time, per user, self-service)

Unlike v1, there's no automatic API token to fetch — the equivalent
one-time step here is linking a Google Drive folder:

1. **Create a Drive folder** to hold your brief data (any name, e.g. "Daily
   Brief Data"). Copy its folder ID from the URL
   (`drive.google.com/drive/folders/<this-part>`).
2. **Put that same folder ID in your local `SKILL.md`'s Admin Config** as
   `BRIEF_DATA_FOLDER_ID` (see the skill repo's own setup docs) — this is
   what the skill writes brief JSON into via its native Drive connector.
3. **Sign in to the webapp and link Google.** First sign-in redirects
   through Google consent automatically. Then confirm the same folder ID in
   the webapp itself, via the Account panel's Drive-folder field
   (`/api/drive-folder`) — this is the one manual linkage step, matching
   the same folder ID from step 2 so both the skill and the webapp agree
   on where your data lives.
4. **Run the skill.** Your next brief writes JSON into that folder; the
   webapp reads it back.

## Local development (without Kubernetes)

```powershell
cd viewer-backend
python -m venv venv
venv\Scripts\pip install -r requirements.txt

$env:FLASK_SECRET_KEY = python -c "import secrets; print(secrets.token_hex(32))"
$env:TOKEN_ENCRYPTION_KEY = python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
$env:TOKEN_DB_PATH = "$PWD\tokens.db"
$env:AZURE_TENANT_ID = "<from step 1>"
$env:AZURE_CLIENT_ID = "<from step 1>"
$env:AZURE_CLIENT_SECRET = "<from step 1>"
$env:AZURE_REDIRECT_URI = "http://localhost:8000/auth/callback"
$env:GOOGLE_CLIENT_ID = "<from step 2d>"
$env:GOOGLE_CLIENT_SECRET = "<from step 2d>"
$env:GOOGLE_REDIRECT_URI = "http://localhost:8000/auth/google/callback"

venv\Scripts\python app.py
```

This runs the Flask dev server directly (not gunicorn, not a container) for
quick local iteration, and does the real MSAL/Azure AD and Google OAuth
flows — both `http://localhost:8000/...` redirect URIs need to already be
registered (Azure AD as an additional Redirect URI on the app registration;
Google as one of the two URIs added in step 2d above, which already covers
this). This is the fastest path to running the manual end-to-end
verification checklist (Task 11 in
`docs/superpowers/plans/2026-07-21-webapp-drive-backend.md`) without
needing the Ingress/TLS cert to be live first.

## Updating the deployed image later

```powershell
gcloud builds submit --tag gcr.io/tam-aaron-hubbart/daily-brief-viewer-v2:latest viewer-backend/
kubectl -n daily-brief-v2 rollout restart deployment/daily-brief-viewer
```

The image tag is `:latest`, so a plain re-apply of `deployment.yaml` won't
pick up a new image — `rollout restart` forces a fresh pull.

## What this doesn't do yet

- **Retention cleanup isn't wired up.** `drive_store.run_retention_cleanup`
  exists and is tested, but nothing calls it yet (no k8s CronJob, no admin
  route) — see the implementation plan's Open Items section. Old brief-date
  folders in Drive will accumulate until this is built.
- **`ALLOWED_GROUPS` is present but inactive**, same as v1 — this rollout is
  open to any Camunda tenant user who links Google and configures a folder.
- **Image tag pinning.** Currently `:latest`, same caveat as v1.
- **No automated migration from v1.** Per the design spec, this is a clean
  forward cutover, not a data migration — brief-days are daily/ephemeral, so
  there's nothing to backfill from v1's Postgres into Drive.
