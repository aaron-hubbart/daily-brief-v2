# daily-brief

Claude skill that generates a personalized daily briefing for Aaron Hubbart, Senior TAM at Camunda.

## What it does

Pulls from Outlook calendar, Outlook email, Slack (DMs, account channels, #prj-cs-ai-first), Zoom meeting summaries, and Asana tasks. Produces a standalone interactive HTML file saved to Google Drive.

## Output

- **File name:** `Daily Brief_YYYY-MM-DD.html`
- **Location:** Google Drive → Claude Outputs → Daily Briefs
- **Format:** Self-contained HTML with localStorage checkboxes, Zoom join links, dark mode, progress tracking — no external dependencies

## Usage

Run in a Claude chat that has M365, Slack, Zoom, Asana, and Google Drive MCP connectors active:

```
/daily-brief
```

Or any natural-language variation: "morning brief", "brief me", "what's on my plate today", etc.

## Configuration

The Google Drive folder ID is stored in the `## Configuration` block at the top of `SKILL.md`.  
To change it, tell Claude: *"Update my daily brief folder to [new folder name or Drive URL]."*

## Files

| File | Purpose |
|------|---------|
| `SKILL.md` | Skill definition — trigger phrases, data sources, HTML template, Drive upload process |
