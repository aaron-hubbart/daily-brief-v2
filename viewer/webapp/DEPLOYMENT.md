# Deploying the hosted viewer

This deploys `viewer/webapp/` as a container on Kubernetes (GKE), mirroring the pattern already in use for the dashboard app at `dashboard.es-sandbox.com`: Cloud Build → GCR, nginx-ingress, cert-manager, one namespace per app. It uses Camunda's existing Azure AD tenant and the app registration you already created.

This app gets its own namespace (`daily-brief`) and its own path (`/daily-brief`) on the shared host — it does not touch the dashboard app's namespace, Ingress, or Secret.

**Assumption flagged for you to confirm**: the image tag below (`gcr.io/tam-aaron-hubbart/daily-brief-viewer:latest`) uses the same GCP project ID as the dashboard app's images, inferred from its `cloudbuild.yaml`. If that's not the right project, update the tag in `cloudbuild.yaml` and `k8s/deployment.yaml` before proceeding.

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

Run from the repo root. `cloudbuild.yaml`'s `dir: viewer` step points the actual Docker build context at `viewer/`, so the image can pick up both `webapp/` and the shared `daily-brief-viewer.html` one level up.

## 3. Create the namespace and secret

```bash
kubectl apply -f viewer/webapp/k8s/namespace.yaml

kubectl create secret generic daily-brief-secrets \
  --namespace daily-brief \
  --from-literal=FLASK_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')" \
  --from-literal=AZURE_CLIENT_ID="<from the app registration>" \
  --from-literal=AZURE_CLIENT_SECRET="<from the app registration>" \
  --from-literal=AZURE_TENANT_ID="<Camunda's tenant ID>" \
  --from-literal=UPLOAD_TOKENS='{"<generate-a-token>":"aaron-hubbart"}'
```

Never `kubectl apply -f k8s/secret.template.yaml` directly — it's a reference for which keys exist, not something to fill in and apply. Generate the upload token the same way as the secret key (`python3 -c "import secrets; print(secrets.token_hex(32))"`).

## 4. Apply the rest

```bash
kubectl apply -f viewer/webapp/k8s/pvc.yaml
kubectl apply -f viewer/webapp/k8s/deployment.yaml
kubectl apply -f viewer/webapp/k8s/service.yaml
kubectl apply -f viewer/webapp/k8s/ingress.yaml
```

## 5. Verify

```bash
kubectl -n daily-brief get pods,svc,ingress
kubectl -n daily-brief get certificate          # watch cert-manager issue the TLS cert; wait for Ready: True
kubectl -n daily-brief logs deploy/daily-brief-viewer --tail=50
```

- `https://dashboard.es-sandbox.com/daily-brief/healthz` → `ok`, no sign-in prompt (intentionally unauthenticated), no cert warning once the certificate above is `Ready`.
- `https://dashboard.es-sandbox.com/daily-brief/` → redirects to a Microsoft sign-in page, then back to the viewer once you sign in with any `@camunda.com` account.
- Confirm the dashboard app at `/` and `/api`/`/auth` on the same host is completely unaffected — this Ingress only claims `/daily-brief`.
- Sign in as two different test users and confirm each only ever sees their own (empty, at first) brief list — `/api/briefs` is scoped per-session, never client-supplied.

## 6. Roll out to test users

Any Camunda tenant account can already sign in once the above is live — nothing extra to configure per person for viewing itself. Two things do need a per-person step:

- **Viewing**: nothing extra. They visit the URL and sign in; their `data/{slug}/` folder is created automatically on first request.
- **Getting their own reports in**: each person who wants their own daily-brief skill pushing reports here needs an entry in `UPLOAD_TOKENS` (a token mapped to their slug) and their own copy of the daily-brief skill configured with that token. To add one without wiping existing tokens:
  ```bash
  kubectl get secret daily-brief-secrets -n daily-brief -o jsonpath='{.data.UPLOAD_TOKENS}' | base64 -d
  # edit the JSON to add the new person, then:
  kubectl create secret generic daily-brief-secrets -n daily-brief \
    --from-literal=UPLOAD_TOKENS='<the edited JSON>' \
    --dry-run=client -o yaml | kubectl apply -f -
  kubectl -n daily-brief rollout restart deployment/daily-brief-viewer
  ```
  Signing in to view and having reports show up are two separate things — a test user can sign in today and see an empty state until either they get an upload token and run their own skill, or you manually drop a sample file into their `data/{slug}/` folder for a quick look.

## Updating the deployed image later

```bash
gcloud builds submit --config=viewer/webapp/cloudbuild.yaml .
kubectl -n daily-brief rollout restart deployment/daily-brief-viewer
```

The image tag is `:latest`, so a plain re-apply of `deployment.yaml` won't pick up a new image — Kubernetes doesn't re-pull an unchanged manifest. `rollout restart` forces a fresh pull. If you want each build independently addressable and roll-back-able, switch the tag to `$BUILD_ID` or a git SHA in both `cloudbuild.yaml` and `deployment.yaml` — the dashboard app's own `cloudbuild.yaml` already does this for its proxy image via `--build-arg APP_VERSION=$BUILD_ID`, worth copying here too if this graduates past testing.

## Local development (without Kubernetes)

`.env.example` is for this — copy it to `.env`, fill in real values, and run:

```bash
cd viewer/webapp
python3 -m venv venv && venv/bin/pip install -r requirements.txt
set -a; source .env; set +a
venv/bin/python app.py
```

This runs the Flask dev server directly (not gunicorn, not a container) for quick local iteration. It still does the real MSAL/Azure AD flow, so `AZURE_REDIRECT_URI` needs to point at wherever you're actually running it (e.g. `http://localhost:8000/auth/callback`, registered as an additional Redirect URI on the app registration for local testing).

## What this doesn't do yet

- **The skill doesn't call `/api/upload` yet.** Once you've confirmed steps 5 and 6 above, say so and I'll wire it into `references/html-output.md`'s delivery step (alongside the existing Google Drive upload, not instead of it) and set up the Admin Config values for whichever user(s) need it.
- **Multi-tenant automation.** This gets each test user a login and an isolated folder. It does not make the daily-brief *skill* itself multi-user — each person who wants their own automated briefs still needs their own Claude project and their own Drive/Slack/Asana connections. This is the viewer/hosting layer only.
- **Group-based restriction.** `ALLOWED_GROUPS` is present in `app.py` but inactive, since this test rollout is open to any Camunda tenant user. Restricting later is an app-registration token-configuration change plus one env var, not a code change.
- **Image tag pinning.** Currently `:latest` for simplicity during testing — see "Updating the deployed image later" above for switching to per-build tags once this is more than a test.
