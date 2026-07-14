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

---

## Skill Sync Check (run this first, every time, before anything else)

This skill's canonical source of truth is this file on `main` in `aaron-hubbart/daily-brief`. Any environment that loads a local copy of this skill (e.g. a persistent runtime skill directory) can silently fall behind if `main` is updated without that local copy being refreshed. Check for that drift before doing anything else, every time this skill fires.

1. Fetch the current blob SHA for `SKILL.md` on `main` via the GitHub API and compare it against a `SKILL_SOURCE_SHA` marker tracked in the local copy's Admin Config block (this marker is local-only; it is not part of this repo file).
2. **Match:** proceed with the brief normally.
3. **Mismatch:** the repo has moved ahead of the loaded copy. Self-heal: fetch this file fresh from `main`, re-insert the local copy's `## Admin Config` block and `## HTML Output` section (both intentionally local-only — Admin Config holds real account/folder/sheet IDs, and this repo file keeps that block generic for public-repo hygiene), update the `SKILL_SOURCE_SHA` marker, overwrite the local copy, and note briefly in the brief output that the skill definition was auto-synced.
4. **Fetch fails:** skip silently and proceed with the current local copy. Never block the brief on this check.

This makes drift self-correcting on every run, since the loaded copy is only ever read during a brief.

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
- For the morning brief specifically, always pull the FULL current calendar day in a single query (midnight to midnight, local time) regardless of the current time — this includes meetings earlier in the day that have already started or finished by the time the brief runs. Do not scope the "today" pull to only meetings still upcoming relative to now; a morning brief run at 8am still needs to show a 7am meeting that already happened.
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

After pulling all data sources, consolidate everything by **customer account or internal initiative** — not by source. Each subsection covers one account or initiative and synthesizes across calendar, email, Slack, and Zoom for that topic. This grouping is mandatory for both Section 1 and Section 2 — never output a source-by-source list (e.g. a "Calendar" section followed by a "Slack" section).

Order subsections by priority: customer accounts with active signals first (in rough order of urgency), then internal initiatives, then a mandatory catch-all "General / Admin" bucket for anything that doesn't fit elsewhere (personal calendar blocks, admin tasks, notifications with no clear account/initiative tie). Every item pulled from a data source must land in exactly one bucket — nothing gets silently dropped for lack of a clean category.

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

### Section 3: Customer Updates

One collapsible card per customer account on your assigned list — every account listed in the Accounts sheet of `Meeting Manager Config.xlsx` (root of your Google Drive, file ID stored in Claude memory as `meeting_manager_config_id`), not just accounts with signals in the current pull. Read the account list fresh from the config file each time this section is generated — do not rely on a previously-known or hardcoded list, since accounts can be added or removed in the config independent of this skill. The entire section is also collapsed by default.

If an account has no new activity in the update window, still generate its card — state plainly that there's nothing new to report since the last update rather than omitting the account. Order cards with active-signal accounts first, then quiet ones.

For each account, generate a plain-text update summarizing recent activity suitable for posting to the account's internal Slack channel. The update should be factual, professional, and peer-level — written as a TAM status post, not a brief excerpt.

**Finding the last update window:**
1. Search the account's Slack channel for posts containing `[TAM-UPDATE] #claude-brief-skill`. Use `slack_search_public_and_private` with that query scoped to the channel.
2. If a matching post exists within the last 7 days, use its timestamp as the start of the summary window.
3. If no matching post exists, or the most recent one is older than 7 days, default to a 7-day lookback from today.

**Update content:** Summarize what has happened across the account in that window — meetings, email threads, support tickets, Slack activity, decisions made, next steps. Do not copy verbatim from sources; synthesize into a coherent narrative.

**Format of each update post:**
```
[TAM-UPDATE] #claude-brief-skill

*[Account Name] — TAM Update*
[Date range covered]

[Narrative summary — 2–5 sentences or short bullets]

Next steps:
• [item]
• [item]
```

**Slack channel mapping** — read at runtime from the Meeting Manager Config.xlsx file (file ID stored in Claude memory as `meeting_manager_config_id`). The Accounts sheet contains a `Slack Channel ID` column. Load the file using the same routing table logic in the meeting-manager skill (Step 1 of routing-table.md). Index accounts by Account Name and all aliases. The channel ID for each account is used to pre-populate the post destination.

Do not hardcode channel IDs here. Always read from the config file so additions and changes made to the xlsx are automatically reflected.

Add new accounts to the Meeting Manager Config.xlsx Accounts sheet (including their Slack Channel ID) as they are onboarded.

The HTML brief presents each account card with:
- An editable text area pre-populated with the generated update
- A channel field showing the channel name, editable
- A "Post to Slack" button that opens `https://slack.com/app_redirect?channel={channel_id}` — the user pastes and sends from Slack
- A timestamp showing when the last `[TAM-UPDATE] #claude-brief-skill` post was made (or "No previous update found")

---

### Section 4: Manager/Leadership Update

A single collapsed section (collapsed by default) containing one editable text area with a synthesized update across all active accounts and initiatives. Suitable for a quick verbal or written update to your manager.

**Format:**
```
[TAM-UPDATE] #claude-brief-skill

*TAM Weekly Update — [Your Name]*
[Date]

[Account]: [1–2 sentence status]
[Account]: [1–2 sentence status]
...

Key risks: [brief list]
Focus this week: [brief list]
```

**Finding the last manager update:**
Search the manager DM channel (`D0A25TNDGJJ`) for `[TAM-UPDATE] #claude-brief-skill`. Use the same 7-day lookback logic as customer updates.

**Posting:** The HTML brief presents a "Post to Manager" button that opens `https://slack.com/app_redirect?channel=D0A25TNDGJJ`. The user pastes and sends from Slack.

The section shows when the last manager update was posted (or "No previous update found").

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

Configure your primary accounts, key colleagues, and team members in the Admin Config block.

Use this context to prioritize and flag items — a Slack DM from your AE about a strategic account matters more than a general announcement channel.

The Slack channel ID mapping for Customer Updates lives in Section 3 of the Output Format above. Update it as accounts are added or changed.

---

## Error Handling

If a data source is unavailable (MCP auth issue, timeout), note it briefly at the bottom of the brief under "Unavailable Sources" and proceed with what's available. Do not fail the whole brief because one source errored.

If there is genuinely nothing to report in a section, omit it silently.

---

## HTML Output — File Naming Convention

Every brief run also produces a companion interactive HTML file. The full spec for that file — CSS design system, structure, badge types, and delivery details — is intentionally local-only (see the loaded skill copy's `## HTML Output` section) and is not duplicated here. The file naming convention itself is tracked in this repo so it can't drift out of sync with the local copy:

Name the file `Daily Brief_YYYY-MM-DD_hh-mm.html`, using the local date and 24-hour local time (zero-padded, hyphen-separated) at the moment the file is generated — e.g. `Daily Brief_2026-07-14_08-42.html`. Because the filename includes the run time, multiple runs on the same day naturally coexist as separate files; there is no overwrite step.

The `localStorage` key used for checkbox persistence in that file is scoped to the calendar date only (`brief:YYYY-MM-DD`), not the timestamp, so checkbox progress carries over across same-day runs even though each run produces a distinct file.

---

## Tone

Peer-level, direct. No filler. No affirmations. Write like a prepared colleague who pulled the information for you before the call, not like a dashboard widget.
