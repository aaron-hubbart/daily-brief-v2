# Deploying to Kubernetes (GKE)

This mirrors the pattern already in use for the dashboard app at `dashboard.es-sandbox.com` (Cloud Build → GCR, nginx-ingress, cert-manager, a namespace per app) rather than the VM/systemd approach in `../DEPLOYMENT.md`. If you're on GKE with nginx-ingress and cert-manager already running (as the dashboard app implies), use this; `DEPLOYMENT.md` is still there if you ever need a non-Kubernetes target.

**Assumption flagged for you to confirm**: the image tag below (`gcr.io/tam-aaron-hubbart/daily-brief-viewer:latest`) uses the same GCP project ID as the dashboard app's images, inferred from its `cloudbuild.yaml`. If that's not the right project, update the tag in `cloudbuild.yaml` and `k8s/deployment.yaml` before proceeding.

This app gets its own namespace (`daily-brief`) and its own path (`/daily-brief`) on the shared host — it does not touch the dashboard app's namespace, Ingress, or Secret.

## 1. Build and push the image

```bash
gcloud builds submit --config=viewer/webapp/cloudbuild.yaml .
```

(Run from the repo root — `cloudbuild.yaml`'s `dir: viewer` step handles pointing the actual Docker build context at `viewer/` so it can pick up both `webapp/` and the shared `daily-brief-viewer.html` one level up.)

## 2. Create the namespace and secret

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

Never `kubectl apply -f k8s/secret.template.yaml` directly — it's a reference for which keys exist, not something to fill in and apply (the risk is committing real values by editing it in place and forgetting to gitignore the edit).

## 3. Finish the app registration redirect URI

Same app registration you already have — add this exact Redirect URI (Entra ID → App registrations → your app → Authentication → Web):

```
https://dashboard.es-sandbox.com/daily-brief/auth/callback
```

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
kubectl -n daily-brief logs deploy/daily-brief-viewer --tail=50
```

- `https://dashboard.es-sandbox.com/daily-brief/healthz` → `ok`, no cert warning once cert-manager finishes issuing (`kubectl -n daily-brief get certificate` to watch it go `Ready: True`), no sign-in prompt.
- `https://dashboard.es-sandbox.com/daily-brief/` → redirects to Microsoft sign-in, then back to the viewer.
- Confirm the dashboard app at `/` and `/api`/`/auth` on the same host is completely unaffected — this Ingress only claims `/daily-brief`.

## 6. Roll out to test users

Same as the VM version: any Camunda tenant account can sign in once this is live. Getting a test user's own reports in still needs an entry in `UPLOAD_TOKENS` (redeploy the secret with `kubectl create secret ... --dry-run=client -o yaml | kubectl apply -f -` to update it, or `kubectl edit secret`) mapped to their slug, plus their own copy of the daily-brief skill configured to push to this endpoint.

## Updating the deployed image later

```bash
gcloud builds submit --config=viewer/webapp/cloudbuild.yaml .
kubectl -n daily-brief rollout restart deployment/daily-brief-viewer
```

(The image tag is `:latest`, so a plain re-apply of `deployment.yaml` won't pick up a new image — Kubernetes doesn't re-pull an unchanged manifest. `rollout restart` forces a fresh pull. If you want each build to be independently addressable and roll back-able, switch the tag to `$BUILD_ID` or a git SHA in both `cloudbuild.yaml` and `deployment.yaml` — the dashboard app's own `cloudbuild.yaml` already does this for its proxy image via `--build-arg APP_VERSION=$BUILD_ID`, worth copying here too if this graduates past testing.)

## What this doesn't do yet

Same three items as the VM version, unchanged by moving to Kubernetes:

- The skill doesn't call `/api/upload` yet — wire it in once you've confirmed steps 5 and 6 above.
- This isn't multi-tenant automation — each additional person still needs their own Claude project and Drive/Slack/Asana connections.
- `ALLOWED_GROUPS` is present but unset (any Camunda user can sign in), per this rollout's requirements.
