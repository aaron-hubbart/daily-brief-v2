# daily-brief

A Claude skill that generates a personalized daily briefing. Pulls from Outlook calendar, Outlook email, Slack (DMs, account channels, tiger team channels, direct mentions), Zoom meeting summaries, and Asana tasks. Produces a structured, easy-to-read brief organized by customer account and internal initiative, and saves a standalone interactive HTML file to Google Drive.

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

### Requirements

- Python 3.8+ on PATH (or locatable via `where python`)
- Claude Desktop (for meeting-manager deep links)
- Microsoft 365, Slack, Zoom, and Asana MCP connectors configured in Claude

## Configuration

Set these values in the `## Admin Config` block at the top of `SKILL.md`:

| Key | Description |
|-----|-------------|
| `BRIEF_OUTPUT_FOLDER_ID` | Google Drive folder ID where briefs are saved |
| `MEETING_RUN_LOG_SHEET_ID` | Google Sheet ID tracking meeting-manager runs |
| `RECURRING_ACTIVITIES_PROJECT_GID` | Asana project GID for the recurring task board |

Update `viewer/daily-brief-viewer.html` with your Jira base URL if applicable (search for `JIRA_BASE`).

Update `viewer/install-startup.bat` with your local Python path if the auto-detection fails.
