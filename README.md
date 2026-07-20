# daily-brief

A Claude skill that generates a personalized daily briefing. Pulls from Outlook calendar, Outlook email, Slack (DMs, account channels, tiger team channels, direct mentions), Zoom meeting summaries, and Asana tasks. Produces a structured, easy-to-read brief organized by customer account and internal initiative, and syncs it as structured items to the hosted daily-brief webapp's Postgres store.

## Structure

- `SKILL.md` — core skill: trigger phrases, timezone/timing logic, data source pulls, Sections 1/2 (recap and forward look), and pointers to the reference files below. Kept short deliberately, since it's read in full on every trigger.
- `references/item-sync.md` — item shape and API-sync spec: section/item_key conventions, badge/link/content shape, and the upsert calls into the hosted webapp. Read every run, but split out so `SKILL.md` doesn't carry it on every decision-making step.
- `references/status-updates.md` — Section 3 (Customer Updates) and Section 4 (Manager Update) generation, plus the per-account daily cache that gates them. Read only for the accounts (or manager entry) that actually need generating on a given run.
- `references/post-meeting-patch.md` — patches a single Yesterday's Meetings item via the API when meeting-manager finishes post-meeting processing. Read only when that trigger fires.
- `references/section-refresh.md` — patches a single Customer Update or Manager Update card via the API when its Refresh button is clicked. Read only when that trigger fires.

## Prerequisites

### Claude

- Claude.ai account with access to Projects and Skills
- Claude Desktop installed (required for meeting-manager and section-refresh deep links in the viewer)

### MCP Connectors

The following connectors must be enabled in your Claude workspace:

| Connector | Used for |
|-----------|----------|
| Microsoft 365 | Outlook calendar, email, and availability lookup |
| Slack | DMs, channel activity, direct mentions, and posting status updates |
| Zoom | AI meeting summaries (supplementary to calendar) |
| Asana | Task tracking and recurring activity board |
| Google Drive | The meeting run log sheet and the status-update cache |

### Daily Brief webapp

- The hosted webapp (`viewer/webapp/`) must be deployed and reachable — see `viewer/webapp/DEPLOYMENT.md`
- Sign in once at `DAILY_BRIEF_API_BASE_URL` with your `@camunda.com` account, then retrieve your token from `DAILY_BRIEF_API_BASE_URL/api/token` and copy both into your local `SKILL.md` Admin Config
- If the token is ever rotated (`/api/token/rotate`), update `DAILY_BRIEF_API_TOKEN` in your local `SKILL.md` — the old token stops working immediately

### Google Drive

- A Google Sheet for tracking meeting-manager runs — copy its ID into `MEETING_RUN_LOG_SHEET_ID`
- A small JSON file for the Section 3/4 daily cache — create an empty one (`{"customer_updates": {}, "manager_update": {}}` is a fine starting point) and copy its ID into `STATUS_UPDATE_CACHE_FILE_ID`. See `references/status-updates.md` for the schema.

### Asana

- A project for recurring task templates — copy its GID into `RECURRING_ACTIVITIES_PROJECT_GID` in your local `SKILL.md`
- Recommended custom fields on that project: `Frequency`, `Day of Week`, `Week of Month`, `Day of Month`, `Month`, `Month of Quarter`, `Due Offset Days`, `Customer`, `Active`, `Snooze Until`, `Last Run`

### Slack

- Your Slack user ID (format: `UXXXXXXXXXX`) — set it in the Slack search section of `SKILL.md` so direct mentions are correctly detected
- A DM or channel with your manager for Manager Update posts

### Viewer (optional)

- Python 3.10+ — required to run the local brief viewer server
- Windows: Task Scheduler access for auto-start via `install-startup.bat`
- Mac: Terminal access to run `launch.command`

## What it does

- **Recap** — summarizes yesterday's meetings, email threads, and Slack activity by account or initiative, plus a meeting-by-meeting processing status list (recording found, action items logged)
- **Forward look** — lists every meeting for the current day with prep status, due tasks, and flagged items
- **Meeting manager automation** — runs pre-meeting prep or post-meeting notes automatically for qualifying meetings, deduped via a Google Sheet run log; a completed post-meeting run patches the existing Yesterday's Meetings item via a single-item upsert rather than waiting for the next scheduled brief
- **Recurring task evaluation** — reads a TAM Recurring Activities Asana board and spawns due tasks on schedule
- **Status summary** — one editable, postable update per assigned account plus a manager rollup. Each generates once per day per entry (not once per brief run) and is cached; a Refresh button on each card forces an immediate single-entry regeneration that patches just that one item via the API, without touching any other account or re-running a full brief

## Output

- **Destination:** the hosted daily-brief webapp's Postgres store, via `/api/items/batch-upsert` (full runs) and `/api/items/upsert` (patches/refreshes) — see `references/item-sync.md` for the item shape and API calls
- **Format:** one row per item (a meeting, an account recap entry, a customer-update card, the manager update), keyed by `(brief_date, section, item_key)`. Rendering — CSS, layout, checkboxes, collapsible sections — is entirely the webapp's responsibility (`viewer/webapp/templates/brief_fragment.html`); the skill never builds or names an HTML file.
- **Multiple runs per day:** a full brief, post-meeting patch, or section refresh all upsert against the same `(brief_date, section, item_key)` rows, so later runs the same day update items in place rather than creating parallel copies. Refreshing the hosted viewer for that date shows the latest state.
- **Viewing:** sign in at `DAILY_BRIEF_API_BASE_URL` and open the date you want — see Hosted deployment below.

## Viewer (legacy, local, optional)

The `viewer/` folder (excluding `viewer/webapp/`, covered below) contains a standalone local viewer for browsing saved brief HTML files. It predates the Postgres-backed hosted webapp and is no longer where this skill delivers new content — the skill syncs items to Postgres via the API now, not HTML files to Drive — but it's kept for anyone with an existing archive of `Daily Brief_*.html` files, or who wants a fully local, single-user, no-deployment option:

- `daily-brief-viewer.html` — dropdown selector, timeline strip, dark/light mode, persistent checkboxes, Jira deep links, Claude Desktop meeting-manager and section-refresh buttons
- `server.py` — Python stdlib local HTTP server (no dependencies). Reads brief files from `viewer/data/`, not from its own folder — this keeps generated reports (real account names, meeting content) separate from app code. Creates `data/` automatically on first run if it doesn't exist.
- `data/` — where previously generated `Daily Brief_*.html` files land, if you have any from before this skill moved to the API. Gitignored.
- `launch.bat` / `launch.command` — manual launchers for Windows and Mac
- `install-startup.bat` / `uninstall-startup.bat` — Windows Task Scheduler auto-start

## Hosted deployment

`viewer/webapp/` is the primary viewer this skill syncs to — a small Flask app that does its own Azure AD (Entra ID) sign-in against Camunda's tenant, so more than one person can sign in and each only ever sees their own briefs. Deployed as a container on Kubernetes (GKE), mirroring the existing `dashboard.es-sandbox.com` app's pattern (Cloud Build → GCR, nginx-ingress, cert-manager), reachable at a sub-path of that same host (`/daily-brief/`) alongside it. Storage is Postgres (self-hosted in-cluster) rather than files — see `db/README.md` for the schema.

- `viewer/webapp/app.py` — MSAL-based OAuth 2.0 authorization code flow against Camunda's Azure AD tenant; identity lives in a signed session cookie, never a raw token. Brief content is rendered dynamically per request from Postgres rows (`db.py`, `templates/brief_fragment.html`), scoped to the signed-in user. Exposes `/api/items/upsert` and `/api/items/batch-upsert`, bearer-token-authenticated, for the skill to create or refresh individual items directly (the skill runs headless and can't complete an interactive sign-in). Each person's API token is assigned automatically in Postgres the first time they sign in — no admin step to add a new person, they just sign in and retrieve it themselves from `/api/token`.
- `viewer/webapp/db/schema.sql` + `db/README.md` — one row per user, one row per brief-day, one row per item (section/item_key), so a single item can be refreshed with one upsert instead of patching a whole file.
- `viewer/webapp/archive_briefs.py` — daily archival: brief-days older than 14 days get soft-deleted (marked archived, hidden from the user, still in the DB); older than 30 days get hard-deleted. Run via `k8s/cronjob.yaml`.
- `viewer/webapp/Dockerfile`, `cloudbuild.yaml`, `k8s/` — the container image and Kubernetes manifests (namespace, Postgres StatefulSet + Service, app Deployment, Service, Ingress, CronJob, secret templates).
- `viewer/webapp/DEPLOYMENT.md` — the full walkthrough: finishing the app registration, building and pushing the image, standing up Postgres, applying the manifests, verification, and rolling out to test users. Also covers running it locally without Kubernetes for quick iteration.
- `viewer/webapp/.env.example` — for local development only; the real deployment gets its config from Kubernetes Secrets instead (see `DEPLOYMENT.md`).

The skill's generation logic now calls the item-upsert endpoints directly (`references/item-sync.md`). See `DEPLOYMENT.md` for what's still a manual/follow-up step: checked-state sync from the frontend (checkbox state is still client-side/localStorage only — see the note in `app.py`'s `set_item_checked`), and true multi-tenant support for the underlying automation, not just the viewer login.

## Configuration

Set these values in the `## Admin Config` block at the top of your local `SKILL.md` (this repo's copy keeps that block as placeholders, since the values are account-specific):

| Key | Description |
|-----|-------------|
| `DAILY_BRIEF_API_BASE_URL` | Base URL of your deployed daily-brief webapp, e.g. `https://dashboard.es-sandbox.com/daily-brief` |
| `DAILY_BRIEF_API_TOKEN` | Your bearer token, retrieved from `DAILY_BRIEF_API_BASE_URL/api/token` while signed in |
| `MEETING_RUN_LOG_SHEET_ID` | Google Sheet ID tracking meeting-manager runs |
| `RECURRING_ACTIVITIES_PROJECT_GID` | Asana project GID for the recurring task board |
| `STATUS_UPDATE_CACHE_FILE_ID` | Drive file ID of the Section 3/4 per-account daily cache — see `references/status-updates.md` |
| `SKILL_SOURCE_SHA` | Blob SHA of the last-synced `SKILL.md` on `main`, maintained automatically by the Skill Sync Check |
| `SYNC_CHECK_LAST_RUN` | Timestamp of the last time the Skill Sync Check actually hit the GitHub API, maintained automatically |

Update `viewer/daily-brief-viewer.html` with your Jira base URL if applicable (search for `JIRA_BASE`) — only relevant if you're still using the legacy local viewer.

Update `viewer/install-startup.bat` with your local Python path if the auto-detection fails — only relevant if you're still using the legacy local viewer.
