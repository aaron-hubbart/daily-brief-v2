# daily-brief

A Claude skill that generates a personalized daily briefing. Pulls from Outlook calendar, Outlook email, Slack (DMs, account channels, tiger team channels, direct mentions), Zoom meeting summaries, and Asana tasks. Produces a structured, easy-to-read brief organized by customer account and internal initiative, and saves a standalone interactive HTML file to Google Drive.

## Prerequisites

### Claude

- Claude.ai account with access to Projects and Skills
- Claude Desktop installed (required for meeting-manager deep links in the viewer)

### MCP Connectors

The following connectors must be enabled in your Claude workspace:

| Connector | Used for |
|-----------|----------|
| Microsoft 365 | Outlook calendar, email, and availability lookup |
| Slack | DMs, channel activity, and direct mentions |
| Zoom | AI meeting summaries (supplementary to calendar) |
| Asana | Task tracking and recurring activity board |
| Google Drive | Saving brief HTML files and the meeting run log sheet |

### Google Drive

- A folder in Google Drive to save brief files — copy its ID into `BRIEF_OUTPUT_FOLDER_ID` in `SKILL.md`
- A Google Sheet for tracking meeting-manager runs — copy its ID into `MEETING_RUN_LOG_SHEET_ID` in `SKILL.md`

### Asana

- A project for recurring task templates — copy its GID into `RECURRING_ACTIVITIES_PROJECT_GID` in `SKILL.md`
- Recommended custom fields on that project: `Frequency`, `Day of Week`, `Week of Month`, `Day of Month`, `Month`, `Month of Quarter`, `Due Offset Days`, `Customer`, `Active`, `Snooze Until`, `Last Run`

### Slack

- Your Slack user ID (format: `UXXXXXXXXXX`) — set it in the Slack search section of `SKILL.md` so direct mentions are correctly detected

### Viewer (optional)

- Python 3.10+ — required to run the local brief viewer server
- Windows: Task Scheduler access for auto-start via `install-startup.bat`
- Mac: Terminal access to run `launch.command`

## What it does

- **Recap** — summarizes yesterday's meetings, email threads, and Slack activity by account or initiative
- **Forward look** — lists upcoming meetings with prep status, due tasks, and flagged items for the next 24 hours
- **Meeting manager automation** — runs pre-meeting prep or post-meeting notes automatically for qualifying meetings, deduped via a Google Sheet run log
- **Recurring task evaluation** — reads a TAM Recurring Activities Asana board and spawns due tasks on schedule
- **Status summary** — generates a boss-ready one-paragraph-per-account snapshot on the first morning run or on demand

## Output

- **File name:** `Daily Brief_YYYY-MM-DD_HHmm.html`
- **Location:** Google Drive folder configured in `BRIEF_OUTPUT_FOLDER_ID`
- **Format:** Self-contained HTML with checkboxes, progress bar, and localStorage state persistence

## Viewer

The `viewer/` folder contains a standalone local viewer for browsing saved brief files:

- `daily-brief-viewer.html` — dropdown selector, timeline strip, dark/light mode, persistent checkboxes, Jira deep links, Claude Desktop meeting-manager buttons
- `server.py` — Python stdlib local HTTP server (no dependencies)
- `launch.bat` / `launch.command` — manual launchers for Windows and Mac
- `install-startup.bat` / `uninstall-startup.bat` — Windows Task Scheduler auto-start

## Configuration

Set these values in the `## Admin Config` block at the top of `SKILL.md`:

| Key | Description |
|-----|-------------|
| `BRIEF_OUTPUT_FOLDER_ID` | Google Drive folder ID where briefs are saved |
| `MEETING_RUN_LOG_SHEET_ID` | Google Sheet ID tracking meeting-manager runs |
| `RECURRING_ACTIVITIES_PROJECT_GID` | Asana project GID for the recurring task board |

Update `viewer/daily-brief-viewer.html` with your Jira base URL if applicable (search for `JIRA_BASE`).

Update `viewer/install-startup.bat` with your local Python path if the auto-detection fails.
