# daily-brief v2 design: Google Drive-backed data layer

Date: 2026-07-21
Status: Approved (design phase) — implementation planning next
Repo: `aaron-hubbart/daily-brief-v2` (new, standalone — no shared git history with `aaron-hubbart/daily-brief`)

## Problem

The current `daily-brief` skill (in `aaron-hubbart/daily-brief`, `main` branch) syncs brief content
into a self-hosted Postgres database via a custom Node/TypeScript MCP server
(`daily-brief-mcp-server`), which Anthropic's cloud infrastructure calls on the skill's behalf
since Claude's sandboxed bash tool can't reach arbitrary internal domains directly.

Two things about that architecture are no longer acceptable:

1. **Data location**: brief content (customer names, meeting content, account status) lives in a
   self-hosted Postgres database, not an approved data location. It needs to live in Google Drive
   instead.
2. **The MCP server itself**: a custom, self-hosted MCP server is not an officially supported
   pattern and needs to be decommissioned entirely — not replaced with an equivalent custom
   server, retired.

The hosted viewer webapp (`viewer/webapp/` today) must keep working largely as-is: same GKE
hosting, same Flask app, same Entra ID (M365) sign-in, same templates, same look, feel, and
front-end behavior (dropdown selector, timeline strip, dark/light mode, persistent checkboxes,
Jira/Asana links, Claude Desktop deep links). This is a backend data-layer swap, not a front-end
redesign.

Multi-user support is preserved: any Camunda TAM should be able to sign in with their own M365
identity and see briefs sourced from their own Google Drive data.

## Non-goals

- Rewriting the webapp's UI, templates, or Entra ID auth flow — these are unchanged.
- Hosting on "Lamppost" — ruled out; the webapp stays on its current GKE hosting.
- Migrating historical brief data from Postgres to Drive — brief-days are daily/ephemeral by
  nature; this is a clean forward cutover, not a backfill.
- Preserving the legacy standalone local viewer (`viewer/daily-brief-viewer.html` + `server.py` +
  launch scripts) — it is optional and superseded by the hosted webapp; it is not carried into v2.
- Preserving the Claude Code `plugin/` wrapper — it exists only to connect to the MCP server being
  decommissioned, so it has no purpose in v2.

## Chosen approach

Of three approaches considered (full storage-layer swap keeping the existing Flask app; a full
rewrite on FastAPI with new templates; a dual-write Postgres+Drive migration period), this design
uses **a storage-layer swap on a fresh repo**: keep the existing Flask app's routes and templates,
replace `db.py`'s Postgres calls with a new Drive-backed data-access layer, and build all of this
in a brand-new `aaron-hubbart/daily-brief-v2` repository (not a branch of `daily-brief`) so it has
its own clean history as a standalone skill.

A full rewrite (FastAPI, new templates) was rejected: it would mean re-building and re-testing UI
behavior that already works today, for no functional gain, given the explicit requirement to
preserve front-end behavior as-is. A dual-write migration period was rejected as unnecessary
complexity given the actual user base is small (effectively single-digit TAMs today) — a clean
forward cutover after a bake-in period on a test deployment is sufficient.

## Repo structure

```
daily-brief-v2/
  SKILL.md                      — new skill, based on daily-brief's SKILL.md
  README.md
  references/
    item-sync.md                — rewritten: Drive file-write shape instead of API upsert calls
    status-updates.md           — same generation/cache logic; cache file lives in Drive as today
    post-meeting-patch.md       — rewritten: writes a new version of the affected JSON file
    section-refresh.md          — rewritten: writes a new version of the affected JSON file
  example/
    Daily Brief_EXAMPLE.html    — carried over unchanged (sanitized demo)
  viewer-backend/                (was viewer/webapp/)
    app.py                       — same routes/templates, storage calls swapped
    drive_store.py               — NEW: replaces db.py's Postgres queries with Drive reads
    google_oauth.py              — NEW: per-user Google OAuth consent + token refresh
    token_store.py               — NEW: SQLite-backed, one row per user, encrypted token columns
    asana_client.py               — mostly unchanged (still calls Asana directly)
    templates/                    — unchanged (brief_fragment.html, admin.html, etc.)
    k8s/                          — updated: no Postgres StatefulSet, no MCP server manifests;
                                     add a PVC for the SQLite token file, add the Google OAuth
                                     client secret
    DEPLOYMENT.md                 — rewritten for the new setup steps, including a full walkthrough
                                     for creating the Google Cloud OAuth client (consent screen,
                                     scopes, redirect URI, Internal user type)
```

Dropped entirely relative to `daily-brief` main: `mcp/` (the Node MCP server), `plugin/` (only
existed to wrap the MCP server), the Postgres schema/migrations, and the legacy local viewer.

The skill's "Skill Sync Check" is repointed at `aaron-hubbart/daily-brief-v2` as its own canonical
source, since this is a standalone skill, not a fork sharing history with `daily-brief`.

## Data layout in Google Drive

Per-user Drive folder, configured once via a new `BRIEF_DATA_FOLDER_ID` admin-config value in
`SKILL.md` (same pattern as today's `MEETING_RUN_LOG_SHEET_ID`):

```
/briefs/{date}/manifest.json          — date, brief_type, section list, item count, generated_at
/briefs/{date}/meetings.json          — Section 1 Part A (Yesterday's Meetings)
/briefs/{date}/accounts/{slug}.json   — Section 1 Part B, one file per account/initiative
/briefs/{date}/today.json             — Section 2
/briefs/{date}/action-items.json      — Section 2 action items (skill-sourced entries only)
/briefs/{date}/fyi.json
/briefs/{date}/updates/{slug}.json    — Section 3, one file per account
/briefs/{date}/manager-update.json    — Section 4
/config/account-config.json           — replaces Meeting Manager Config.xlsx's role for this
                                         skill: account name, Slack channel ID, Asana project GID
                                         per account. Hand-maintained, same as the .xlsx is today,
                                         just as JSON now.
/state/{date}.json                    — checkbox state, keyed by stable item ID. Written directly
                                         by the webapp via its own Drive OAuth (not the skill's
                                         create-only connector) — true in-place updates.
```

**Item IDs**: every checkable/card item gets a stable ID (a hash of account/initiative slug + item
type + title + date). This is what lets `/state/{date}.json` track a checkbox across same-day
regenerations, and what post-meeting-patch / section-refresh use to identify which single file to
write a new version of.

**Why files, not rows, for section content**: the skill's Drive connector is create-only — it
already only ever creates the meeting-run-log and status-cache files today, never edits them in
place. A full run or a patch always writes a *new* file version; the webapp always reads the
newest-by-`createdTime` file per path. Superseded versions are inert, cleaned up separately by
retention (see below), never deleted inline by the skill.

## Write paths: two independent actors, no direct connection between them

- **Skill** writes section JSON via its own native Google Drive connector (`Google Drive:
  create_file`) — the same connector already used today for the meeting-run-log sheet and status
  cache. Create-only, no network dependency on the webapp.
- **Webapp** reads that JSON, and separately owns checkbox state (`/state/{date}.json`) and
  retention cleanup — using its own per-user Google OAuth access (full `drive` scope, not the
  narrower `drive.file` scope, since it must read files created by a different OAuth client, the
  skill's own connector).

These two actors never talk to each other directly — Drive is the handoff point. This
deliberately avoids re-introducing a skill→webapp network dependency: that dependency is exactly
why the MCP server existed in today's architecture (Claude's sandboxed bash tool can't reach
arbitrary internal domains directly), and dropping the MCP server means giving up that path
entirely rather than rebuilding an equivalent of it. A Drive PAT or service-account key used for
direct API calls from the skill was considered and rejected: feasibility is unverified (unclear if
the skill's execution environment has network egress to `googleapis.com`), and even if feasible it
would mean a standing Drive credential living in the skill's own local config — a step backward
from "approved locations only," not forward — while providing no benefit the connector-based
design doesn't already get another way.

## Auth flow

1. User hits the webapp → redirected to Entra ID (M365) sign-in, exactly as today (`app.py`'s
   existing MSAL flow, unchanged). Identity lives in the same signed session cookie.
2. If this user has no stored Google OAuth token yet (or it's been revoked), redirect to a Google
   OAuth consent screen (new), requesting the broad `drive` scope. On success, store the resulting
   access + refresh token in the SQLite token store, keyed by the user's Entra object ID.
3. Every subsequent page load: pull the user's Google refresh token from SQLite, refresh if
   needed, use it for all Drive reads/writes for that request.

**`token_store.py`**: one SQLite file on a PVC (same volume-mount pattern the Postgres data used
today, just a file instead of a server). One row per user: `entra_object_id`, encrypted Google
refresh token, encrypted Asana PAT (reusing this store for both — no separate mechanism needed for
Asana). Encryption key comes from a k8s Secret, not stored in the SQLite file itself.

**What this deletes from today's stack**: the Postgres StatefulSet, its migrations, `db.py`'s SQL
layer, the `/api/token` and `/api/token/rotate` endpoints (no more bearer-token model for the
skill — the skill never calls the webapp at all now). The onboarding step that captures the Asana
PAT is unchanged from a UX standpoint; it now stores into SQLite instead of a Postgres column.

**Open dependency**: a Google Cloud OAuth client (Internal user type, scoped to `camunda.com`,
requesting the `drive` scope) must be registered before this works. The user (Aaron) can create
this but needs a documented walkthrough — to be included in the rewritten `DEPLOYMENT.md`.

## Live Asana action items

Unchanged in spirit: the webapp reads `/config/account-config.json` directly (via its own Drive
OAuth) for the account→project-GID mapping, calls Asana directly with the stored PAT, and merges
results with the skill-sourced `action-items.json` entries. The `/api/config/account-projects`
sync endpoint and its Postgres mirror table (`account_projects`) are removed entirely — nothing
needs to sync that mapping anymore, since the webapp can read it straight from Drive.

## Retention

The 14-day-soft-delete / 30-day-hard-delete pattern from today's k8s CronJob is preserved,
re-implemented against Drive: a scheduled job (per user, using their stored OAuth token) trims old
per-date brief folders on a similar cadence. This requires the broad `drive` scope already needed
for reads, so it adds no new scope requirement.

## Rollout

1. Build the v2 skill + webapp in the new repo; deploy the webapp to a separate test path/
   subdomain in the same GKE cluster — production (`dashboard.es-sandbox.com/daily-brief`) is
   untouched while this is in progress.
2. Run the v2 skill in parallel with v1 for a bake-in period: v1 keeps syncing to Postgres as
   today; v2 writes to a separate Drive folder. Compare output side-by-side with no risk to the
   live brief.
3. Once satisfied, point the actual Claude skill config at v2 and cut the webapp's production
   ingress over to the v2 deployment.
4. Retire v1: tear down the Postgres StatefulSet and the MCP server deployment/ingress. Archive
   (don't delete) the old `daily-brief` repo state in case anything needs cross-referencing later.

No live data migration is needed — brief-days are daily/ephemeral, so this is a clean forward
switch, not a backfill.

## Testing

- **Skill side** (manual/conversational, as today): verify a few full brief runs, a post-meeting
  patch, and a section refresh against the test Drive folder, checking the JSON shape matches
  what the rewritten `references/item-sync.md` documents.
- **Webapp side**: real unit/integration tests for the genuinely new pieces — `drive_store.py`
  (mock the Drive API), `google_oauth.py` (token refresh logic), `token_store.py` (SQLite read/
  write/encryption round-trip). Templates and routes are copied forward unchanged, so they don't
  need new test coverage beyond a manual pass.
- **Manual UI pass**: dropdown, timeline, checkboxes, dark/light mode, deep links — verified
  against the test deployment before cutover, to confirm front-end behavior is actually preserved
  in practice, not just in theory.

## Open items going into implementation planning

- Who/how the Google Cloud OAuth client gets created (Aaron will do this, needs a walkthrough in
  `DEPLOYMENT.md`).
- Exact hashing scheme for stable item IDs (needs to be specified precisely enough that
  post-meeting-patch and section-refresh can reliably regenerate the same ID for the same
  logical item).
- Whether `references/status-updates.md`'s per-account daily cache file moves into the new
  `/briefs/{date}/` layout or stays as its own separately-configured Drive file, as it is today.
