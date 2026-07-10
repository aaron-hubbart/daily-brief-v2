---
name: daily-brief
description: >
  Generates a personalized daily briefing for Aaron Hubbart, Senior TAM at Camunda.
  Pulls from all available data sources: Outlook calendar, Outlook email, Slack (DMs,
  account channels, tiger team channels, direct mentions), Zoom meeting summaries,
  and Asana tasks. Produces a structured, easy-to-read summary covering the current
  day in review and the day ahead in plan.

  Trigger on any of these phrases or clear variations: "daily brief", "morning brief",
  "evening brief", "brief me", "what's my day look like", "catch me up", "day ahead",
  "what happened today", "end of day summary", "start of day", "eod brief", "sod brief",
  "what do I have today", "what's on my plate", "run my brief", "give me my brief".
  Also trigger when the user says something like "brief" with no other context, or
  asks to be caught up on the day, communications, or schedule.

  Do NOT require the user to specify morning vs. evening — infer from context or current
  time. Always run the brief without asking for confirmation first.
---

# Daily Brief Skill

## Admin Config

```
BRIEF_OUTPUT_FOLDER_ID: 1h6AGEIHGLTAFM_6OB17_K4zl3HoLJ1uT
MEETING_RUN_LOG_SHEET_ID: 1S36RADUN3O2xmywgvy-cK26yVtxUpwGecp1E7dXty60
RECURRING_ACTIVITIES_PROJECT_GID: 1216434461108524
```

---

## Purpose

Produce a structured daily briefing that covers:
- A recap of the current or previous day (what happened, what came in)
- A forward look at the upcoming day or remainder of today

The brief is always split into two sections: **Yesterday / Today So Far** and **Today / Tomorrow**.

---

## Timezone Resolution

Before applying any timing logic, determine the user's current local time. Do not rely on Claude's assumed UTC clock.

Use `Microsoft 365: outlook_find_available_time` with a short near-future window (e.g., next 15 minutes from Claude's approximate now). The response includes a `nowDateTime` field with an authoritative current timestamp in the user's Outlook mailbox timezone. Use that timestamp and timezone for all time-of-day decisions below.

If `outlook_find_available_time` is unavailable or errors, fall back to the `nowDateTime` field from any recent `outlook_calendar_search` result, or ask the user for their current local time as a last resort.

Do not use Claude's internal clock as the source of truth for the user's local time.

---

## Timing Logic

Infer the user's intent from the user's current local time (resolved above) and any contextual cues:

- Before noon: assume **morning brief** — recap yesterday, plan today
- After noon but before 5pm: assume **midday check-in** — recap today so far, plan remainder + tomorrow
- After 5pm: assume **evening brief** — recap today, plan tomorrow
- If the user specifies morning/evening explicitly, honor that regardless of time
- If the conversation already has context (e.g., "what happened in my meetings today"), use that

State the timing assumption briefly at the top of the brief (e.g., "Morning brief for Thursday, June 19").

---

## Data Sources and What to Pull

Run all data pulls in parallel where possible. Use the time windows below.

### Outlook Calendar (Microsoft 365: outlook_calendar_search)
- Recap window: yesterday (or today so far if midday/evening)
- Ahead window: today (morning) or tomorrow (evening)
- Pull all events in the window: title, time, attendees, location/link
- Flag any conflicts, back-to-back blocks, or meetings with key accounts

### Outlook Email (Microsoft 365: outlook_email_search)
- Recap window: emails received since EOD yesterday (or past 24 hours)
- Ahead window: not applicable — omit from forward section unless there's a scheduled send or thread requiring same-day action
- Focus on: unread, flagged, or emails from key contacts
- Key contacts: Rodrigo Scaldaferri, Micah De Boer, David Paroulek, Colin Teubner, and any contact at AcmeFin, Zebra Financial, Umbrella Financial, Initech Financial, Acme Health, Zebra Health
- Summarize threads, not individual messages — group by sender/topic

### Slack (Slack: slack_search_public_and_private)
Run multiple targeted searches:
1. Direct mentions: `to:<@U0A0ZRB4JM8>` or `<@U0A0ZRB4JM8>`
2. DMs: channel_types=im, recent messages
3. Account channels: search for channels related to AcmeFin, Zebra Financial, Umbrella Financial, Initech Financial, Acme Health, Zebra Health
4. Tiger team / AI-First CS: search for tiger team, AI-first, CS tiger
5. Time-scope all searches to the recap window

Consolidate into a single Slack section. Surface only items that need attention or are informational — skip noise, bot messages, and automated notifications.

### Zoom (Zoom for Claude: search_meetings + get_meeting_assets)
- Search for meetings completed in the recap window
- Pull AI summary and next steps for each completed meeting
- If no summary is available, note the meeting occurred
- Only surface meetings that produced meaningful content (skip 1:1 standups with no summary)

### Asana (Asana: get_my_tasks)
- Pull incomplete tasks with due_on = today or overdue
- Group by: overdue, due today, due tomorrow (for evening brief)
- Omit tasks with no due date unless they appear high priority from the name

---

## Output Format

Start with a one-line header:

```
[Morning/Evening/Midday] Brief — [Day of week], [Month Date]
Estimated read time: X min
```

Then two sections:

---

### Section 1: Yesterday / Today So Far

After pulling all data sources, consolidate everything by **customer account or internal initiative** — not by source. Each subsection covers one account or initiative and synthesizes across calendar, email, Slack, and Zoom for that topic.

Order subsections by priority: customer accounts with active signals first (in rough order of urgency), then internal initiatives, then a catch-all "General / Admin" for anything that doesn't fit elsewhere.

For each account or initiative subsection, include only what's relevant:
- Meetings that occurred (time, who attended, outcome or Zoom summary if available)
- Email threads needing attention or follow-up
- Slack signals: DMs, mentions, or key channel activity
- Overdue Asana tasks tied to that account

Skip any account or initiative with nothing to report. Do not create a section just to say nothing happened.

Example structure (only include sections with content):

**Acme Financial** — Upgrade testing thread from Alex Rivera shows the 8.6→8.9 migration failed. Triage session ran this morning. Two overdue tasks.

**Zebra Financial** — Bi-Weekly Sync occurred, ended early at 10 minutes. No summary available.

**AI-First CS Tiger Team** — Alana tagged you in #prj-cs-ai-first on actora PR #74.

**Internal / Admin** — Required training block at 2:30 PM. Submit Timesheet overdue.

---

### Section 2: Today / Tomorrow Ahead

Same structure: organize by **customer account or internal initiative**, not by source.

For each, include:
- Upcoming meetings (time, attendees, prep needed)
- Asana tasks due today or tomorrow tied to that account
- Any flagged email or Slack threads requiring same-day action

End with a brief **Open Time** note if there are meaningful unblocked blocks in the day.

---

## Formatting Rules

- Prose for summaries, not bullet spray
- Use a simple list only when enumerating meetings or tasks within a section
- No bold text mid-sentence; section headers only
- Keep each item concise — this is a brief, not a report
- If an account or initiative has nothing to report, omit it entirely
- Estimated read time: count ~200 words per minute, round up to nearest half minute

---

## Account and People Context

Aaron's primary accounts: Acme Financial, Zebra Financial, Umbrella Financial, Initech Financial, Acme Health, Zebra Health.
Key Camunda colleagues: Rodrigo Scaldaferri (AE), Micah De Boer, David Paroulek (Senior SA), Colin Teubner.
Tiger team: Norman, Rashid, Tanya, Liz (AI-First CS Tiger Team).

Use this context to prioritize and flag items. A Slack DM from Rodrigo about AcmeFin matters more than a general #announcements post.

---

## Error Handling

If a data source is unavailable (MCP auth issue, timeout), note it briefly at the bottom of the brief under "Unavailable Sources" and proceed with what's available. Do not fail the whole brief because one source errored.

If there is genuinely nothing to report in a section, omit it silently.

---

## Tone

Peer-level, direct. No filler. No affirmations. Write like a prepared colleague who pulled the information for you before the call, not like a dashboard widget.

---

## HTML Output

Every brief run produces a standalone interactive HTML file in addition to the in-chat response. The file is self-contained (no external dependencies), works offline, and persists checkbox state in `localStorage` so it can be referenced throughout the day.

### When to generate

Generate the HTML file on every brief run. Name the file: `Daily Brief_YYYY-MM-DD.html` using the local date.

### HTML structure

The file has four sections, in order:

1. **Header** — date, brief type (Morning / Midday / Evening), timezone label, progress counter ("N of N done"), progress bar
2. **Schedule** — every meeting in the next 24 hours as a checkable item with time, title, attendees, and a Join link if a Zoom/Webex URL is present
3. **Action Items** — every task that needs action today: overdue Asana tasks, email threads needing a reply, Slack items flagged for response, meeting manager runs needed. Each item is checkable, has a one-line subtitle, and optional link buttons.
4. **FYI** — non-actionable signals worth knowing: post-meeting summaries generated, recurring tasks spawned, informational Slack threads, status summary highlights

### CSS design system

Use exactly the CSS from the existing example (reproduced below). Do not deviate from the design tokens, class names, or layout. The only dynamic changes are content and the `data-id` / `TOTAL` values in the script.

```css
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg:#f5f4f1; --surface:#fff; --border:#e2e0d8; --border-strong:#c8c6bc;
  --t1:#1a1916; --t2:#5a5850; --t3:#9a9890;
  --accent:#1a5ca0; --accent-bg:#eef3fb; --accent-t:#1a5ca0;
  --warn-bg:#fdf5e6; --warn-t:#7a5000;
  --bad-bg:#fef1f0; --bad-t:#b02520;
  --done:.35; --font:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
  --mono:ui-monospace,"SF Mono","Cascadia Code",monospace; --r:5px;
}
@media(prefers-color-scheme:dark){:root{
  --bg:#18181b; --surface:#1e1e22; --border:#2c2c32; --border-strong:#3c3c44;
  --t1:#e6e4de; --t2:#9a9890; --t3:#5a5850;
  --accent:#5a9de0; --accent-bg:#0f2140; --accent-t:#6aade8;
  --warn-bg:#28200a; --warn-t:#e8a020; --bad-bg:#280e0e; --bad-t:#e06868;
}}
```

### Badge types

| Class | Use |
|-------|-----|
| `bwarn` | Tentative, needs confirmation, time-sensitive |
| `bbad` | Overdue, blocking, critical |
| Custom inline style using `--accent-bg`/`--accent-t` | Informational label (e.g., "hiring", "prep run") |

### Link buttons

Use `class="lbtn primary"` for the primary CTA (Join Zoom, Open doc). Use `class="lbtn"` for secondary links (Asana task, Slack thread, email). All `href` values must be real URLs from the data — never placeholder `#` values in actual output. The example file uses `#` only because it is a sanitized demo.

### localStorage key

Use `brief:YYYY-MM-DD` as the key (matching the file date). The `TOTAL` constant in the script must equal the actual number of checkable items (`.item[data-id]` elements) in that specific brief.

### Sensitive data rules

The HTML file produced during a live brief run will contain real names, meeting titles, and links. That is correct for personal use. However:

- **Never commit a real brief to the GitHub repo.** The `example/` folder in the repo is for sanitized demo files only.
- The example file must use fictional names, companies, and placeholder `#` links.
- No real email addresses, Slack user IDs, Asana GIDs, Zoom meeting IDs, or calendar event IDs may appear in any committed file.
- Customer names in examples must be fictional (e.g., "Acme Financial", "Pinnacle Health", "Meridian Bank") — never real account names.

### Delivering the file

After generating the HTML, upload it to Google Drive folder `BRIEF_OUTPUT_FOLDER_ID` (`1h6AGEIHGLTAFM_6OB17_K4zl3HoLJ1uT`) using `Google Drive: create_file` with `contentMimeType: text/html` and `disableConversionToGoogleType: true`. Name the file `Daily Brief_YYYY-MM-DD.html`. If a file with that name already exists for today (e.g., a second brief run), overwrite it by updating the existing file rather than creating a duplicate.

Also present the file as a downloadable artifact in chat so it is immediately accessible without opening Drive.

