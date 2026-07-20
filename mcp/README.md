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
$env:DAILY_BRIEF_API_TOKEN = "<token from the Drive JSON file>"
$env:MCP_SHARED_SECRET = "<any long random string, optional but recommended>"
npm start
```

Test with the MCP inspector:

```powershell
npx @modelcontextprotocol/inspector
```

Point it at `http://localhost:3000/mcp`.

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

Build and push:

```powershell
gcloud builds submit --config=cloudbuild.yaml `
  --substitutions=_REGION=us-central1,_REPO=daily-brief,_IMAGE=daily-brief-mcp-server `
  .
```

This pushes both `:latest` and `:$SHORT_SHA` tags to
`us-central1-docker.pkg.dev/<your-project-id>/daily-brief/daily-brief-mcp-server`.
Use the `$SHORT_SHA` tag in `k8s/deployment.yaml` for anything beyond local testing —
pinning to `latest` in a cluster makes rollbacks harder to reason about.

## Deploy to Kubernetes

1. Fill in the secret values (don't commit the filled-in file):
   ```powershell
   kubectl create secret generic daily-brief-mcp-secrets `
     --from-literal=DAILY_BRIEF_API_BASE_URL=https://dashboard.es-sandbox.com/daily-brief `
     --from-literal=DAILY_BRIEF_API_TOKEN=<token> `
     --from-literal=MCP_SHARED_SECRET=<random string> `
     -n daily-brief --dry-run=client -o yaml | kubectl apply -f -
   ```
2. Update `image:` in `k8s/deployment.yaml` to your registry path, e.g.
   `us-central1-docker.pkg.dev/<project-id>/daily-brief/daily-brief-mcp-server:<SHORT_SHA>`
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
  a substitute for TLS and the shared-secret check.
- TLS is required. The ingress manifest assumes cert-manager with a
  `letsencrypt-prod` ClusterIssuer already configured in-cluster.

## Auth model

This uses the `static_headers` auth type (currently in beta) rather than full
OAuth: your organization's Claude admin pastes `MCP_SHARED_SECRET` as a fixed
`Authorization: Bearer <secret>` header when adding the connector, and Claude
sends it on every request. The server checks it in `src/index.ts`.

If `static_headers` isn't available on your plan, or you want per-user consent
instead of one shared secret across the org, you'll need to implement the OAuth
2.0 flow described at docs.claude.com/docs/connectors/building/authentication
(Dynamic Client Registration or a Client ID Metadata Document) instead of the
shared-secret check here. That's a larger lift — worth doing only if more than
one person will use this connector.

## Adding the connector in Claude

Settings > Connectors > Add custom connector, paste
`https://mcp.REPLACE_WITH_YOUR_DOMAIN.com/mcp`, and supply `MCP_SHARED_SECRET`
as the request header credential when prompted (or as the OAuth client secret,
if you went the OAuth route instead).
