# daily-brief-v2

A Claude skill that generates a personalized daily briefing. Pulls from Outlook calendar, Outlook email, Slack (DMs, account channels, tiger team channels, direct mentions), Zoom meeting summaries, and Asana tasks. Produces a structured, easy-to-read brief organized by customer account and internal initiative, and syncs it as JSON files directly to Google Drive.

## Structure

- `SKILL.md` — core skill: trigger phrases, timezone/timing logic, data source pulls, Sections 1/2 (recap and forward look), and pointers to the reference files below. Kept short deliberately, since it's read in full on every trigger.
- `references/item-sync.md` — item shape and Drive-sync spec: section/item_key conventions, badge/link/content shape, and the `Google Drive: create_file` calls that write a run's content into `BRIEF_DATA_FOLDER_ID`. Read every run, but split out so `SKILL.md` doesn't carry it on every decision-making step.
- `references/status-updates.md` — Section 3 (Customer Updates) and Section 4 (Manager Update) generation, plus the per-account daily cache that gates them. Read only for the accounts (or manager entry) that actually need generating on a given run.
- `references/post-meeting-patch.md` — writes a new version of the affected Yesterday's Meetings item to Drive when meeting-manager finishes post-meeting processing. Read only when that trigger fires.
- `references/section-refresh.md` — writes a new version of a single Customer Update or Manager Update card, or a full section (Yesterday's Meetings, Account/Initiative Recap, Today, Action Items, FYI), to Drive when its Refresh button is clicked. Read only when that trigger fires.
- `references/first-run-setup.md` — the First-Run Setup flow (minimal Drive-folder/Slack-ID collection, automated email/Slack/Asana discovery, user confirmation, write) and the on-demand "find new accounts" flow. Read only when setup or account-discovery triggers.

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

- A Google Sheet for tracking meeting-manager runs — its ID is left blank by setup for you to fill in afterward, in the `meeting_run_log_sheet_id` field of `config.json`
- A small JSON file for the Section 3/4 daily cache — create an empty one (`{"customer_updates": {}, "manager_update": {}}` is a fine starting point); its ID is left blank by setup for you to fill in afterward, in the `status_update_cache_file_id` field of `config.json`. See `references/status-updates.md` for the schema.
- A folder to hold `/briefs` (this skill's own output), `/config` (hand-maintained by you), and `/state` (written by the hosted webapp, not this skill) — its ID is collected by the setup flow and stored in the `brief_data_folder_id` field of `config.json`. See `references/item-sync.md` for the layout.

Setup itself now only asks for this folder ID and your Slack user ID up front — it discovers your customer accounts, their Slack channels, and their Asana projects automatically, then has you review and confirm before writing anything. See `references/first-run-setup.md` for the full flow. You can also run account discovery anytime after setup ("find new accounts"), or use the "Scan for Accounts" button on the hosted webapp's Customers tab (Asana-only there, since the webapp has no Slack access).

### Asana

- A project for recurring task templates — its GID is left blank by setup for you to fill in afterward, in the `recurring_activities_project_gid` field of `config.json`
- Recommended custom fields on that project: `Frequency`, `Day of Week`, `Week of Month`, `Day of Month`, `Month`, `Month of Quarter`, `Due Offset Days`, `Customer`, `Active`, `Snooze Until`, `Last Run`

### Slack

- Your Slack user ID (format: `UXXXXXXXXXX`) — it is collected by the setup flow and stored in the `slack_user_id` field of `config.json` so direct mentions are correctly detected
- A DM or channel with your manager for Manager Update posts

## What it does

- **Recap** — summarizes yesterday's meetings, email threads, and Slack activity by account or initiative, plus a meeting-by-meeting processing status list (recording found, action items logged)
- **Forward look** — lists every meeting for the current day with prep status, due tasks, and flagged items
- **Meeting manager deep-links** — every meeting gets pre-meeting-prep and post-meeting-notes `claude://` deep-links, no qualifying filter; when a recording/transcript is missing, the person is asked directly and can paste a transcript to trigger post-meeting processing in that same conversation, which patches the existing Yesterday's Meetings item by writing a new version to Drive rather than waiting for the next scheduled brief
- **Recurring task evaluation** — reads a TAM Recurring Activities Asana board and spawns due tasks on schedule
- **Status summary** — one editable, postable update per in-scope account (all primary accounts, plus secondary accounts on their weekly run day) plus a manager rollup. Each generates once per day per entry (not once per brief run) and is cached; a Refresh button on each card forces an immediate single-entry regeneration that writes just that one item to Drive, without touching any other account or re-running a full brief

## Output

- **Destination:** JSON files written directly to Google Drive, into `BRIEF_DATA_FOLDER_ID` — see `references/item-sync.md` for the authoritative file layout, section/item_key conventions, and write mechanics; this file stays an overview rather than duplicating that spec.
- **Multiple runs per day:** a full brief, post-meeting patch, or section refresh all write against the same `(brief_date, section, item_key)` identity, so later runs the same day update items in place rather than creating parallel copies. Refreshing the hosted viewer for that date shows the latest state.
- **Viewing:** sign in at the hosted webapp and open the date you want — see Hosted deployment below.

## Hosted deployment

The hosted viewer is `viewer-backend/` in this same repo — a Flask app that uses MSAL for Entra ID sign-in (unchanged from before) plus its own per-user Google OAuth so it can read each signed-in person's Drive on their behalf. See `viewer-backend/DEPLOYMENT.md` for the full walkthrough: app registration, Google OAuth client setup, building and pushing the image, standing up the deployment, verification, and linking a Drive folder per user.

## Configuration

The skill keeps a single value in your local `SKILL.md` — a pointer to one JSON config file on Google Drive that holds everything else (this repo's copy keeps it as a placeholder, since the value is account-specific):

| Key | Description |
|-----|-------------|
| `CONFIG_FILE_ID` | Drive file ID of your `config.json`. Created for you by the setup flow — run `/daily-brief setup` in Claude, then paste the reported ID here. |

Everything else lives in `/config/config.json` inside your brief-data Drive folder, written by the setup flow (you don't hand-edit it for first-run setup):

```json
{
  "brief_data_folder_id": "...",
  "meeting_run_log_sheet_id": "...",
  "recurring_activities_project_gid": "...",
  "status_update_cache_file_id": "...",
  "slack_user_id": "UXXXXXXXXXX",
  "key_contacts": ["First Last", "..."]
}
```

`sync_state` is maintained automatically by the Skill Sync Check. `account-config.json` is a separate file in the same `/config` folder holding the per-account mapping (name, tier, run day, main + supporting Slack channels, Asana board, docs folder); the First-Run Setup flow builds and updates it for you (discover → confirm) — see `references/item-sync.md`. Accounts are tiered: primary accounts run every day; secondary accounts run one configured weekday per week (with catch-up if a run day is missed) and appear in their own brief subsection, hidden on other days.
