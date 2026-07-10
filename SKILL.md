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

Subsections (only include if there's content):

**Calendar** — List meetings with time, title, and a one-line note on what it was or who attended. Flag anything that ran long, was cancelled, or had a notable outcome from Zoom summary.

**Email** — Summarize by thread/topic, not message count. Call out anything needing a response or follow-up.

**Slack** — Surface DMs needing a reply, key discussion threads in account or tiger team channels, and any direct mentions. One line per item unless it warrants more detail.

**Asana** — List overdue tasks by name and original due date.

---

### Section 2: Today / Tomorrow Ahead

Subsections:

**Calendar** — Full schedule with time, title, attendees. Flag prep needed (e.g., customer call with no notes pulled yet). Flag open time blocks if the day looks light.

**Asana** — Tasks due today or tomorrow. Group: due today, due tomorrow.

**Email / Slack** — Only include if there are flagged threads or known time-sensitive items to address.

---

## Formatting Rules

- Prose for summaries, not bullet spray
- Use a simple list only when enumerating meetings or tasks
- No bold text mid-sentence; section headers only
- Keep each item concise — this is a brief, not a report
- If a section is empty, omit it entirely (don't say "No emails today")
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
