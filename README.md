# daily-brief-v2

A Claude skill that generates a personalized daily briefing. Pulls from Outlook calendar, Outlook email, Slack (DMs, account channels, tiger team channels, direct mentions), Zoom meeting summaries, and Asana tasks. Produces a structured, easy-to-read brief organized by customer account and internal initiative, and syncs it as JSON files directly to Google Drive.

## Structure

- `SKILL.md` — core skill: trigger phrases, timezone/timing logic, data source pulls, Sections 1/2 (recap and forward look), and pointers to the reference files below. Kept short deliberately, since it's read in full on every trigger.
- `references/item-sync.md` — item shape and Drive-sync spec: section/item_key conventions, badge/link/content shape, and the `Google Drive: create_file` calls that write a run's content into `BRIEF_DATA_FOLDER_ID`. Read every run, but split out so `SKILL.md` doesn't carry it on every decision-making step.
- `references/status-updates.md` — Section 3 (Customer Updates) and Section 4 (Manager Update) generation, plus the per-account daily cache that gates them. Read only for the accounts (or manager entry) that actually need generating on a given run.
- `references/post-meeting-patch.md` — writes a new version of the affected Yesterday's Meetings item to Drive when meeting-manager finishes post-meeting processing. Read only when that trigger fires.
- `references/section-refresh.md` — writes a new version of a single Customer Update or Manager Update card, or a full section (Yesterday's Meetings, Account/Initiative Recap, Today, Action Items, FYI), to Drive when its Refresh button is clicked. Read only when that trigger fires.

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
| Google Drive | The meeting run log sheet, the status-update cache, and the brief-data JSON output written into `BRIEF_DATA_FOLDER_ID` |

### Daily Brief webapp

See `viewer-backend/DEPLOYMENT.md` in this repo for deploying and linking the hosted webapp; there is no API token to retrieve, since the skill never calls the webapp directly.

### Google Drive

- A Google Sheet for tracking meeting-manager runs — copy its ID into `MEETING_RUN_LOG_SHEET_ID`
- A small JSON file for the Section 3/4 daily cache — create an empty one (`{"customer_updates": {}, "manager_update": {}}` is a fine starting point) and copy its ID into `STATUS_UPDATE_CACHE_FILE_ID`. See `references/status-updates.md` for the schema.
- A folder to hold this skill's brief-data output (`/briefs`, `/config`, `/state`) — copy its ID into `BRIEF_DATA_FOLDER_ID`. See `references/item-sync.md` for the layout.

### Asana

- A project for recurring task templates — copy its GID into `RECURRING_ACTIVITIES_PROJECT_GID` in your local `SKILL.md`
- Recommended custom fields on that project: `Frequency`, `Day of Week`, `Week of Month`, `Day of Month`, `Month`, `Month of Quarter`, `Due Offset Days`, `Customer`, `Active`, `Snooze Until`, `Last Run`

### Slack

- Your Slack user ID (format: `UXXXXXXXXXX`) — set it in the Slack search section of `SKILL.md` so direct mentions are correctly detected
- A DM or channel with your manager for Manager Update posts

## What it does

- **Recap** — summarizes yesterday's meetings, email threads, and Slack activity by account or initiative, plus a meeting-by-meeting processing status list (recording found, action items logged)
- **Forward look** — lists every meeting for the current day with prep status, due tasks, and flagged items
- **Meeting manager automation** — runs pre-meeting prep or post-meeting notes automatically for qualifying meetings, deduped via a Google Sheet run log; a completed post-meeting run patches the existing Yesterday's Meetings item by writing a new version to Drive rather than waiting for the next scheduled brief
- **Recurring task evaluation** — reads a TAM Recurring Activities Asana board and spawns due tasks on schedule
- **Status summary** — one editable, postable update per assigned account plus a manager rollup. Each generates once per day per entry (not once per brief run) and is cached; a Refresh button on each card forces an immediate single-entry regeneration that writes just that one item to Drive, without touching any other account or re-running a full brief

## Output

- **Destination:** JSON files written directly to Google Drive, into `BRIEF_DATA_FOLDER_ID` — see `references/item-sync.md` for the authoritative file layout, section/item_key conventions, and write mechanics; this file stays an overview rather than duplicating that spec.
- **Multiple runs per day:** a full brief, post-meeting patch, or section refresh all write against the same `(brief_date, section, item_key)` identity, so later runs the same day update items in place rather than creating parallel copies. Refreshing the hosted viewer for that date shows the latest state.
- **Viewing:** sign in at the hosted webapp and open the date you want — see Hosted deployment below.

## Hosted deployment

The hosted viewer is `viewer-backend/` in this same repo — a Flask app that uses MSAL for Entra ID sign-in (unchanged from before) plus its own per-user Google OAuth so it can read each signed-in person's Drive on their behalf. See `viewer-backend/DEPLOYMENT.md` for the full walkthrough: app registration, Google OAuth client setup, building and pushing the image, standing up the deployment, verification, and linking a Drive folder per user.

## Configuration

Set these values in the `## Admin Config` block at the top of your local `SKILL.md` (this repo's copy keeps that block as placeholders, since the values are account-specific):

| Key | Description |
|-----|-------------|
| `BRIEF_DATA_FOLDER_ID` | Drive folder ID that holds `/briefs`, `/config`, and `/state` for this skill's output — see `references/item-sync.md` for the layout. Create it once, then link the same folder ID in the webapp's Account panel |
| `MEETING_RUN_LOG_SHEET_ID` | Google Sheet ID tracking meeting-manager runs |
| `RECURRING_ACTIVITIES_PROJECT_GID` | Asana project GID for the recurring task board |
| `STATUS_UPDATE_CACHE_FILE_ID` | Drive file ID of the Section 3/4 per-account daily cache — unchanged from before, still its own separate file, not inside `BRIEF_DATA_FOLDER_ID` — see `references/status-updates.md` |
| `SKILL_SOURCE_SHA` | Blob SHA of the last-synced `SKILL.md` on `main`, maintained automatically by the Skill Sync Check |
| `REFERENCES_SOURCE_SHA` | Tree SHA of the last-synced `references/` directory on `main`, maintained automatically by the Skill Sync Check — catches drift in reference files even when `SKILL.md` itself hasn't changed |
| `SYNC_CHECK_LAST_RUN` | Timestamp of the last time the Skill Sync Check actually hit the GitHub API, maintained automatically |
