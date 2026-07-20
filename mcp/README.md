# daily-brief-mcp-server

Remote MCP server wrapping the daily-brief webapp's item-sync API
(`/api/items/upsert`, `/api/items/batch-upsert`) as two MCP tools:

- `daily_brief_upsert_item` — single-item patch (post-meeting-patch, section-refresh)
- `daily_brief_batch_upsert_items` — full brief run, all items in one call

Built with the TypeScript MCP SDK on Streamable HTTP, per Anthropic's recommended
stack for remote servers (stateless JSON, no session state to manage).

## Why this exists

Claude's sandboxed bash tool only has network egress to a fixed allowlist, which
doesn't include arbitrary internal webapp domains. A custom MCP connector is a
different network path entirely: Anthropic's cloud infrastructure calls this
server directly, not the sandbox. That's what unblocks syncing brief items to
`dashboard.es-sandbox.com` (or wherever this ends up being hosted).

## Local development

```powershell
npm install
npm run build
$env:DAILY_BRIEF_API_BASE_URL = "https://dashboard.es-sandbox.com/daily-brief"
npm start
```

Test with the MCP inspector, supplying your own daily-brief API token (from
`$DAILY_BRIEF_API_BASE_URL/api/token`, after signing in) as the connector's
bearer token — the server no longer has a token or secret of its own to test
without:

```powershell
npx @modelcontextprotocol/inspector
```

Point it at `http://localhost:3000/mcp` and set the Authorization header to
`Bearer <your own token>` in the inspector's connection settings.

## Build and push the container image

### Locally, with Podman

```powershell
podman build -t daily-brief-mcp-server:latest -f Containerfile .
podman tag daily-brief-mcp-server:latest REPLACE_WITH_YOUR_REGISTRY/daily-brief-mcp-server:latest
podman push REPLACE_WITH_YOUR_REGISTRY/daily-brief-mcp-server:latest
```

### Via Google Cloud Build (no local daemon needed)

`cloudbuild.yaml` uses Kaniko rather than the default `gcr.io/cloud-builders/docker`
step — Cloud Build always runs steps as containers in Google's managed environment,
so there's no Podman option server-side, but Kaniko is the closest match to Podman's
philosophy (daemonless, rootless, no privileged socket).

One-time setup:

```powershell
gcloud services enable cloudbuild.googleapis.com artifactregistry.googleapis.com
gcloud artifacts repositories create daily-brief `
  --repository-format=docker --location=us-central1 `
  --description="daily-brief MCP server images"
```

Build and push (defaults already match the values above, so no `--substitutions` needed for a quick build):

```powershell
gcloud builds submit --config=cloudbuild.yaml .
```

This pushes `:latest` to
`us-central1-docker.pkg.dev/<your-project-id>/daily-brief/daily-brief-mcp-server`.
For a pinned, rollback-able tag instead of relying on `:latest` — worth doing
once this is more than a single-person test — pass `_TAG` explicitly with a
short git SHA computed locally:

```powershell
gcloud builds submit --config=cloudbuild.yaml `
  --substitutions=_TAG=$(git rev-parse --short HEAD) `
  .
```

Note this is `_TAG`, not Cloud Build's built-in `$SHORT_SHA` — that only
auto-populates for builds triggered from a connected Git source repo, not a
plain local-directory `gcloud builds submit` like this one, so it silently
resolves to empty and produces an invalid image tag if you try to use it
directly (see the comment in `cloudbuild.yaml`).

## Deploy to Kubernetes

1. Create the secret (just the base URL now — no per-user token or shared secret lives on this server):
   ```powershell
   kubectl create secret generic daily-brief-mcp-secrets `
     --from-literal=DAILY_BRIEF_API_BASE_URL=https://dashboard.es-sandbox.com/daily-brief `
     -n daily-brief --dry-run=client -o yaml | kubectl apply -f -
   ```
2. Update `image:` in `k8s/deployment.yaml` to your registry path, e.g.
   `us-central1-docker.pkg.dev/<project-id>/daily-brief/daily-brief-mcp-server:<the _TAG value you built with, or :latest if you didn't pass one>`
   if you built via Cloud Build. On GKE with the default node service account (or
   Workload Identity) granted `artifactregistry.reader`, no `imagePullSecrets` are
   needed. Off GKE, you'll need to create one from a service account key.
3. Update `host:` in `k8s/ingress.yaml` to your real domain.
4. Apply:
   ```powershell
   kubectl apply -f k8s/deployment.yaml
   kubectl apply -f k8s/ingress.yaml
   ```
5. Confirm the pod is healthy: `kubectl get pods -n daily-brief`

## Network requirements (important, read before deploying)

- The server must be reachable over the **public internet** — not behind a VPN,
  not on a private-only network. Anthropic's cloud calls it directly.
- Anthropic's outbound traffic to your server originates from `160.79.104.0/21`
  (per the Claude Platform docs — verify this is still current, ranges can expand).
  The ingress manifest here allowlists that range as defense in depth; it is not
  a substitute for TLS and per-user tokens.
- TLS is required. The ingress manifest assumes cert-manager with a
  `letsencrypt-prod` ClusterIssuer already configured in-cluster.

## Auth model

Per-user passthrough — this server holds no secret or token of its own. Each
person adds this connector under their own Claude account (Settings >
Connectors, `static_headers` auth type) and supplies their own personal
daily-brief API token as the fixed `Authorization: Bearer <token>` header,
the same token they'd get from `$DAILY_BRIEF_API_BASE_URL/api/token` after
signing in with their own Azure AD account.

`src/index.ts` requires that *some* bearer token is present on every `/mcp`
request, then forwards that exact value straight through to the webapp API
for that request (`src/requestContext.ts` threads it via `AsyncLocalStorage`
so concurrent requests from different people never cross). The webapp's
existing per-user token check (`db.get_user_by_token` in `viewer/webapp/db.py`)
is the real auth boundary — this server doesn't duplicate or second-guess it.
A wrong or expired token surfaces back to the person as the same
`Error: daily-brief API returned 401` the tool descriptions already document;
the fix is the same as always — sign in at `/api/token` and update the
connector's header with the fresh value.

This deliberately replaces the earlier single-`MCP_SHARED_SECRET` model, where
everyone shared one server-wide credential and every sync landed under
whichever one webapp account that credential's token belonged to. A leaked
token now only exposes the one person it belongs to.

If your org later needs to skip the manual "paste your token as a header"
step entirely (full OAuth consent, so adding the connector prompts an actual
Microsoft sign-in instead), that's the documented next step at
docs.claude.com/docs/connectors/building/authentication — a larger lift,
reusing the same Azure AD app registration the webapp already authenticates
against, not attempted in this pass.

## Adding the connector in Claude

Each person: Settings > Connectors > Add custom connector, paste
`https://mcp.REPLACE_WITH_YOUR_DOMAIN.com/mcp`, and supply their OWN
daily-brief API token (from `$DAILY_BRIEF_API_BASE_URL/api/token`, after
signing in) as the request header credential — never someone else's token,
and never a token shared across the team.
