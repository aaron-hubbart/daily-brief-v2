---
name: daily-brief
description: >
  Generates a personalized daily briefing for Aaron Hubbart, Senior TAM at Camunda.
  Pulls from all available data sources: Outlook calendar, Outlook email, Slack (DMs,
  account channels, tiger team channels, direct mentions), Zoom AI summaries,
  and Asana tasks. Produces a structured, easy-to-read summary covering the current
  day in review and the day ahead in plan. Automatically triggers meeting-manager
  pre-meeting and post-meeting for qualifying meetings. Evaluates the TAM Recurring
  Activities Asana board and spawns due tasks. Generates a boss-ready account
  status summary on the first run of each morning or when explicitly requested.

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
- Automated meeting manager pre/post runs for qualifying meetings
- Recurring task evaluation and Asana task creation
- A boss-ready status summary (morning first-run or on demand)

The brief is always split into two sections: **Yesterday / Today So Far** and **Today / Tomorrow Ahead**, followed by the **Status Summary** when applicable.

---

## Admin Config

```
MEETING_RUN_LOG_SHEET_ID: 1S36RADUN3O2xmywgvy-cK26yVtxUpwGecp1E7dXty60
RECURRING_ACTIVITIES_PROJECT_GID: 1216434461108524
```

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

Track whether this is the **first run of the morning** (before noon, first time today the brief has been run). The boss-ready status summary runs on first morning run or when explicitly requested.

---

## Data Sources and What to Pull

Run all data pulls in parallel where possible. Use the time windows below.

### Outlook Calendar (Microsoft 365: outlook_calendar_search) — Source of truth for all meetings
- Recap window: yesterday (or today so far if midday/evening)
- Ahead window: next 24 hours from current local time
- Pull all events in the window: title, time, attendees, location/link
- This is the authoritative meeting list. Do not add, remove, or infer meetings from Zoom or any other source.
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

### Zoom (Zoom for Claude: get_meeting_assets) — Supplementary AI summaries only
- Do not use Zoom to discover or enumerate meetings. The M365 calendar is the source of truth for what meetings occurred.
- For each meeting on the M365 calendar that has a Zoom link, attempt to fetch the AI summary and next steps via `get_meeting_assets` using the meeting ID from the calendar event.
- If a summary is available, surface it under the relevant account or initiative section.
- If no summary is available, do not note the absence — simply omit the Zoom enrichment for that meeting.
- Never surface a Zoom meeting that does not have a corresponding M365 calendar event.

### Asana (Asana: get_my_tasks)
- Pull incomplete tasks with due_on = today or overdue
- Group by: overdue, due today, due tomorrow (for evening brief)
- Omit tasks with no due date unless they appear high priority from the name

---

## Meeting Manager Integration

This is a core part of the brief. Run meeting manager for qualifying meetings automatically — do not ask for permission. The user has opted in by running the brief.

### Run Log Sheet

The run log is a Google Sheet (ID: `1S36RADUN3O2xmywgvy-cK26yVtxUpwGecp1E7dXty60`). Read it at the start of every brief run to know what has already been processed. It has the following columns:

| Column | Description |
|--------|-------------|
| meeting_id | M365 calendar event ID |
| meeting_subject | Human-readable title |
| meeting_start | ISO datetime of meeting start (local) |
| phase | `pre` or `post` |
| run_at | ISO datetime when meeting manager was run |
| status | `completed` or `error` |

Write a new row each time meeting manager runs successfully for a meeting+phase combination.

### Pre-Meeting Rules

For every meeting in the **next 24 hours** from the M365 calendar:
1. Skip personal/medication reminders (z-Personal category, no attendees, solo events).
2. Skip meetings with no attendees other than the user.
3. Check the run log: if a `pre` row exists for this meeting_id, skip — it has already been prepped.
4. Otherwise: invoke the meeting-manager skill in pre-meeting mode for this meeting. Log the result.
5. Summarize in the brief under the relevant account/initiative section: "Meeting prep run for [title] at [time]."

### Post-Meeting Rules

For every meeting in the **past 3 days** from the M365 calendar that has already ended:
1. Apply the same skip rules as pre-meeting (personal, no-attendee, solo).
2. Check the run log: if a `post` row exists for this meeting_id, skip — it has already been processed.
3. Otherwise: invoke the meeting-manager skill in post-meeting mode for this meeting. If a Zoom AI summary is available, pass it in as the transcript source. Log the result.
4. Summarize in the brief under the relevant account/initiative section: "Post-meeting notes generated for [title] from [date]."

### Ambiguity Handling

If meeting manager cannot determine mode (pre vs. post) or encounters an error for a specific meeting, note it once at the bottom of the brief under a "Meeting Manager — Needs Attention" subsection. Do not halt the rest of the brief.

---

## Recurring Activities Evaluation

At each brief run, read the TAM Recurring Activities Asana project (GID: `1216434461108524`) and evaluate every active task template against the current date.

### Reading the Board

Pull all tasks from the project. For each task, read:
- `name` and `notes` (the activity description)
- Custom fields: `Frequency`, `Day of Week`, `Week of Month`, `Day of Month`, `Month`, `Month of Quarter`, `Due Offset Days`, `Customer`, `Active`, `Snooze Until`, `Last Run`

Skip any task where `Active` = false.
Skip any task where `Snooze Until` is set and is in the future.

### Schedule Evaluation Logic

Determine whether today is a trigger date for each template using the following rules:

| Frequency | Trigger condition |
|-----------|------------------|
| daily | Every day |
| weekly | Current day of week matches `Day of Week` |
| bi-weekly | Current day of week matches `Day of Week`, and it has been ≥ 14 days since `Last Run` (or `Last Run` is unset) |
| monthly | Today's date matches `Day of Month`, OR today matches `Week of Month` + `Day of Week` (e.g., 2nd Monday) |
| quarterly | Monthly condition is met AND current month matches `Month of Quarter` within the current calendar quarter |
| annually | Monthly condition is met AND current month matches `Month` |

If `Day of Month`, `Week of Month`, `Day of Week`, `Month`, or `Month of Quarter` are set but create an ambiguous schedule, ask the user for clarification at brief time before spawning a task. Do not skip silently.

### Task Creation

When a template is triggered:
1. Create a new Asana task assigned to `me` with:
   - `name`: same as the template task name
   - `notes`: the template's notes/description
   - `due_on`: today + `Due Offset Days` (0 if unset)
   - Project: route to the customer's account project if `Customer` is set and the routing table in meeting-manager has a GID for that account; otherwise add to My Tasks
2. Update the template's `Last Run` custom field to today's date.
3. Surface the created task in the brief under the relevant account/initiative section.

---

## Output Format

Start with a one-line header:

```
[Morning/Evening/Midday] Brief — [Day of week], [Month Date]
Estimated read time: X min
```

Then the following sections in order:

---

### Section 1: Yesterday / Today So Far

After pulling all data sources, consolidate everything by **customer account or internal initiative** — not by source. Each subsection covers one account or initiative and synthesizes across calendar, email, Slack, Zoom summaries, meeting manager results, and Asana for that topic.

Order subsections by priority: customer accounts with active signals first (in rough order of urgency), then internal initiatives, then a catch-all "General / Admin" for anything that doesn't fit elsewhere.

For each account or initiative subsection, include only what's relevant:
- Meetings that occurred (time, who attended, outcome or Zoom AI summary if available)
- Post-meeting notes generated (with link to doc if meeting-manager produced one)
- Email threads needing attention or follow-up
- Slack signals: DMs, mentions, or key channel activity
- Overdue Asana tasks tied to that account
- Recurring tasks that were spawned today for that account

Skip any account or initiative with nothing to report.

---

### Section 2: Today / Tomorrow Ahead

Same structure: organize by **customer account or internal initiative**, not by source.

For each, include:
- Upcoming meetings in the next 24 hours (time, attendees, prep status — "prep run" or "prep needed")
- Meeting prep that was generated this run (with link to doc if produced)
- Asana tasks due today or tomorrow tied to that account
- Any flagged email or Slack threads requiring same-day action
- Recurring tasks spawned for today tied to that account

End with a brief **Open Time** note if there are meaningful unblocked blocks in the next 24 hours.

---

### Section 3: Status Summary (morning first-run or on demand only)

Produce a concise account-by-account status update suitable for a quick verbal or written update to your manager. This is not a deep dive — it is a one-paragraph-per-account snapshot of where things stand, what's moving, and what's at risk.

Format:

**[Account or Initiative]** — [1–3 sentences: current state, recent activity, next milestone or open risk. No bullet spray. Write as if briefing your boss verbally.]

Include all active accounts and internal initiatives with meaningful activity in the past 2 weeks. Omit accounts with no recent activity.

This section runs:
- On the first brief run before noon each day (morning first-run)
- Any time the user explicitly asks for the status summary, boss update, or similar

---

### Meeting Manager — Needs Attention (only if errors or ambiguity)

List any meetings where meeting manager could not complete pre or post processing, with a one-line reason. Prompt the user to resolve these manually or clarify.

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

If the meeting run log sheet is unavailable, proceed with the brief and skip meeting manager automation — note it under Unavailable Sources.

If the recurring activities project is unavailable, proceed with the brief and skip recurring task evaluation — note it under Unavailable Sources.

If there is genuinely nothing to report in a section, omit it silently.

---

## Regression Test Checklist

Before shipping changes to this skill, verify:

1. **Timezone**: `nowDateTime` from `outlook_find_available_time` is used, not Claude's clock. Brief header reflects correct local date.
2. **Meeting source of truth**: All meetings in Sections 1 and 2 come from M365 calendar only. No Zoom-only meetings appear.
3. **Pre-meeting dedup**: A meeting that already has a `pre` row in the run log does not trigger meeting manager again.
4. **Post-meeting dedup**: A meeting that already has a `post` row in the run log does not trigger meeting manager again.
5. **Post-meeting window**: Only meetings in the past 3 days are evaluated for post-meeting. Older meetings are skipped.
6. **Solo event skip**: Personal/medication/no-attendee events are not passed to meeting manager.
7. **Recurring task trigger**: A `weekly` task set for Friday fires on Friday, not other days.
8. **Recurring task dedup**: `Last Run` = today means the task does not spawn again on a second brief run the same day.
9. **Snooze**: A task with `Snooze Until` in the future is skipped without note.
10. **Ambiguous schedule**: An ambiguous recurring schedule produces a clarifying question, not a silent skip.
11. **Status summary timing**: Status summary appears on morning first-run; does not appear on a second morning run unless explicitly requested.
12. **Run log write**: After meeting manager runs, a new row is written to the Google Sheet with correct phase, meeting_id, and run_at.
13. **Error isolation**: A meeting manager failure for one meeting does not prevent the rest of the brief from completing.
14. **Output structure**: Sections are organized by account/initiative, not by data source.

---

## Suggested Improvements

The following are worth considering for future iterations:

1. **Slack DM drafting**: After post-meeting notes are generated for a customer meeting, auto-draft a Slack message to the AE (Rodrigo for AcmeFin/Zebra Financial) with the key next steps, staged for review.
2. **Recurring task completion detection**: Before spawning a new task, check if an identical task was created and completed recently — avoid re-spawning tasks the user already closed.
3. **Boss summary delivery**: Option to send the status summary directly to a specified Slack DM or email on a schedule.
4. **Meeting prep quality gate**: Flag meetings with no Asana project, no recent email thread, and no Slack channel — these are likely under-documented accounts that need attention.
5. **Brief run log**: Track brief runs (not just meeting manager runs) so the skill can reliably distinguish "first run of the morning" across sessions without relying on conversation state.

---

## Tone

Peer-level, direct. No filler. No affirmations. Write like a prepared colleague who pulled the information for you before the call, not like a dashboard widget.
