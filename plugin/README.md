# daily-brief-mcp plugin

Claude Code plugin that connects to the `daily-brief-mcp-server` GKE deployment
(namespace `daily-brief`, cluster `gk3-tam-ah-admin-cluster-pool-2`) as a remote
HTTP MCP server, exposing `daily_brief_upsert_item` and `daily_brief_batch_upsert_items`.

## Install

Copy or symlink the `plugin/` directory into your Claude Code plugin path, or
point a marketplace entry at this repo path. Claude Code loads MCP config from
`.mcp.json` inside the plugin.

## Required environment variables

Set these in your shell profile before starting Claude Code:

- `DAILY_BRIEF_MCP_TOKEN` — the bearer token checked by the app (matches the
  `MCP_SHARED_SECRET` k8s secret). Not stored in this repo.
- `DAILY_BRIEF_MCP_URL` — optional override; defaults to
  `https://mcp.dashboard.es-sandbox.com/mcp`.

## Ingress note

As of 2026-07-20, the `daily-brief-mcp-server` ingress restricted `/mcp` to
`160.79.104.0/21` (Anthropic's cloud connector egress range), which blocks
direct local connections from `mcp-remote`. To allow local/plugin-based
connections, remove the whitelist annotation:

```
kubectl annotate ingress daily-brief-mcp-server -n daily-brief nginx.ingress.kubernetes.io/whitelist-source-range- --overwrite
```

This makes `/mcp` reachable from any IP; the bearer token becomes the sole
auth gate. Rotate `MCP_SHARED_SECRET` if that tradeoff changes.
