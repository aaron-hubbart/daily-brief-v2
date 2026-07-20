# daily-brief

A Claude skill that generates a personalized daily briefing. Pulls from Outlook calendar, Outlook email, Slack (DMs, account channels, tiger team channels, direct mentions), Zoom meeting summaries, and Asana tasks. Produces a structured, easy-to-read brief organized by customer account and internal initiative, and saves a standalone interactive HTML file to Google Drive.

## Structure

- `SKILL.md` — core skill: trigger phrases, timezone/timing logic, data source pulls, Sections 1/2 (recap and forward look), and pointers to the reference files below. Kept short deliberately, since it's read in full on every trigger.
- `references/html-output.md` — full HTML file spec: section wrappers, CSS, badges, link buttons, `data-id`/`data-section` conventions, sensitive-data rules. Read every run, but split out so `SKILL.md` doesn't carry it on every decision-making step.
- `references/status-updates.md` — Section 3 (Customer Updates) and Section 4 (Manager Update) generation, plus the per-account daily cache that gates them. Read only for the accounts (or manager entry) that actually need generating on a given run.
- `references/post-meeting-patch.md` — patches a single Yesterday's Meetings item into the latest brief file when meeting-manager finishes post-meeting processing. Read only when that trigger fires.
- `references/section-refresh.md` — patches a single Customer Update or Manager Update card into the latest brief file when its Refresh button is clicked. Read only when that trigger fires.

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
| Google Drive | Saving brief HTML files, the meeting run log sheet, and the status-update cache |

### Google Drive

- A folder to save brief files — copy its ID into `BRIEF_OUTPUT_FOLDER_ID` in your local `SKILL.md`
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
- **Meeting manager automation** — runs pre-meeting prep or post-meeting notes automatically for qualifying meetings, deduped via a Google Sheet run log; a completed post-meeting run patches the existing brief file in place (as a new timestamped file) rather than waiting for the next scheduled brief
- **Recurring task evaluation** — reads a TAM Recurring Activities Asana board and spawns due tasks on schedule
- **Status summary** — one editable, postable update per assigned account plus a manager rollup. Each generates once per day per entry (not once per brief run) and is cached; a Refresh button on each card forces an immediate single-entry regeneration that patches just that card into the latest file, without touching any other account or re-running a full brief

## Output

- **File name:** `Daily Brief_YYYY-MM-DD_hh-mm.html` (local date and 24-hour local time at generation)
- **Location:** Google Drive folder configured in `BRIEF_OUTPUT_FOLDER_ID`
- **Format:** Self-contained HTML with checkboxes, progress bar, and localStorage state persistence, keyed by date so multiple same-day files (regular runs, post-meeting patches, section refreshes) share checkbox progress
- **Multiple runs per day:** each run — full brief, post-meeting patch, or section refresh — writes a new timestamped file rather than overwriting the previous one, since Drive has no update-by-fileId path for this. The viewer lets you pick between same-day files.

## Viewer

The `viewer/` folder contains a standalone local viewer for browsing saved brief files:

- `daily-brief-viewer.html` — dropdown selector, timeline strip, dark/light mode, persistent checkboxes, Jira deep links, Claude Desktop meeting-manager and section-refresh buttons
- `server.py` — Python stdlib local HTTP server (no dependencies)
- `launch.bat` / `launch.command` — manual launchers for Windows and Mac
- `install-startup.bat` / `uninstall-startup.bat` — Windows Task Scheduler auto-start

## Configuration

Set these values in the `## Admin Config` block at the top of your local `SKILL.md` (this repo's copy keeps that block as placeholders, since the values are account-specific):

| Key | Description |
|-----|-------------|
| `BRIEF_OUTPUT_FOLDER_ID` | Google Drive folder ID where briefs are saved |
| `MEETING_RUN_LOG_SHEET_ID` | Google Sheet ID tracking meeting-manager runs |
| `RECURRING_ACTIVITIES_PROJECT_GID` | Asana project GID for the recurring task board |
| `STATUS_UPDATE_CACHE_FILE_ID` | Drive file ID of the Section 3/4 per-account daily cache — see `references/status-updates.md` |
| `SKILL_SOURCE_SHA` | Blob SHA of the last-synced `SKILL.md` on `main`, maintained automatically by the Skill Sync Check |
| `SYNC_CHECK_LAST_RUN` | Timestamp of the last time the Skill Sync Check actually hit the GitHub API, maintained automatically |

Update `viewer/daily-brief-viewer.html` with your Jira base URL if applicable (search for `JIRA_BASE`).

Update `viewer/install-startup.bat` with your local Python path if the auto-detection fails.
