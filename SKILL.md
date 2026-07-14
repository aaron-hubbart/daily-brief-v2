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

Configure these in your local copy (not committed here, since they're account-specific):

```
BRIEF_OUTPUT_FOLDER_ID: <your Google Drive output folder ID>
MEETING_RUN_LOG_SHEET_ID: <your meeting-manager run log sheet ID>
RECURRING_ACTIVITIES_PROJECT_GID: <your Asana recurring-activities project GID>
SKILL_SOURCE_SHA: <maintained automatically by the Skill Sync Check below>
```

---

## Skill Sync Check (run this first, every time, before anything else)

This skill's canonical source of truth is this file on `main` in `aaron-hubbart/daily-brief`. Any environment that loads a local copy of this skill (e.g. a persistent runtime skill directory) can silently fall behind if `main` is updated without that local copy being refreshed. Check for that drift before doing anything else, every time this skill fires.

1. Fetch the current blob SHA for `SKILL.md` on `main` via the GitHub API and compare it against a `SKILL_SOURCE_SHA` marker tracked in the local copy's Admin Config block (this marker is local-only; it is not part of this repo file).
2. **Match:** proceed with the brief normally.
3. **Mismatch:** the repo has moved ahead of the loaded copy. Self-heal: fetch this file fresh from `main`, re-insert the local copy's real values into the `## Admin Config` block (this repo file keeps that block as generic placeholders for public-repo hygiene — the structure is version-controlled, only the literal IDs are local), update the `SKILL_SOURCE_SHA` marker, overwrite the local copy, and note briefly in the brief output that the skill definition was auto-synced. Note: `## HTML Output` (including the file-naming convention) is fully version-controlled here as of this update — it is not local-only. It was previously dropped from this repo file as an unintentional side effect of PR #6, not a deliberate exclusion; that has been corrected.
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
- Search for meetings completed in the recap window (last business day for the morning brief, today so far for midday/evening)
- Pull AI summary, transcript availability, recording availability, and next steps for each completed meeting via `get_meeting_assets`
- If no summary is available, note the meeting occurred and that recording/transcript status still needs checking
- For the Yesterday's Meetings status list (Section 1, Part A — see Output Format), this is the primary source for "recording/transcript found or not"
- Only surface meetings in the account/initiative recap (Part B) that produced meaningful content (skip 1:1 standups with no summary) — Part A still lists every meeting regardless of content, since its purpose is processing status, not narrative

### Asana (Asana: get_my_tasks / search_tasks)
- Pull incomplete tasks with due_on = today or overdue
- Group by: overdue, due today, due tomorrow (for evening brief)
- Omit tasks with no due date unless they appear high priority from the name
- For correlating action items to a specific call (Section 1, Part A): first check the Meeting Manager Run Log sheet (`MEETING_RUN_LOG_SHEET_ID`) for a row matching the meeting (by title and date). If no matching row exists there — which is expected right now, since post-meeting processing isn't yet writing to that log — fall back to searching the relevant account's Asana project for tasks created on or shortly after the meeting's date. Report whichever check found something; if neither does, say so plainly rather than guessing.

---

## Output Format

Start with a one-line header:

```
[Morning/Evening/Midday] Brief — [Day of week], [Month Date]
Estimated read time: X min
```

Then two sections:

---

### Section 1: Yesterday's Meetings, and Account/Initiative Recap

This section has two parts. Part A is meeting-centric (one entry per meeting); Part B is the existing account/initiative-centric recap. Both appear every run — Part A is not a replacement for Part B.

#### Part A: Yesterday's Meetings (call processing status)

List every meeting from the last business day (yesterday, or the prior Friday if today is Monday) in chronological order — this is meeting-by-meeting, not grouped by account. Personal calendar blocks and solo admin reminders (no attendees) are excluded; anything with attendees counts as a meeting for this list.

For each meeting, report:
- Title, time, attendees
- **Recording/transcript status** — checked via Zoom `get_meeting_assets`:
  - Found: link directly to the meeting summary doc (`summary_doc_url`) and/or recording, and note whether a transcript is available
  - Not found: flag it clearly (e.g. a `bwarn` badge reading "recording not found") — this is the trigger condition below
- **Asana action-item status** — checked per the Asana data-source note above (run log sheet first, Asana project search as fallback):
  - Found: note that items were logged, with a link to the task(s) or the account project
  - Not found: say so plainly — "no action items logged yet"

**If recording/transcript can't be found for a meeting:** don't silently note the gap and move on. Explicitly ask the user for a recording link or the full transcript text, so it can be run through the meeting-manager skill's post-meeting flow. Phrase this as a direct request in both the chat response and as a checkable item in the HTML (see HTML structure below) — e.g. "BFSI Industry Deep-Dive — no recording or transcript found. Reply with a link or paste the transcript to process this." Once the user supplies it, run the meeting-manager skill's post-meeting agent on it in the same conversation rather than waiting for the next brief.

#### Part B: Account / Initiative Recap

After pulling all data sources, consolidate everything by **customer account or internal initiative** — not by source. Each subsection covers one account or initiative and synthesizes across calendar, email, Slack, and Zoom for that topic. This grouping is mandatory — never output a source-by-source list (e.g. a "Calendar" section followed by a "Slack" section).

Order subsections by priority: customer accounts with active signals first (in rough order of urgency), then internal initiatives, then a mandatory catch-all "General / Admin" bucket for anything that doesn't fit elsewhere (personal calendar blocks, admin tasks, notifications with no clear account/initiative tie). Every item pulled from a data source must land in exactly one bucket — nothing gets silently dropped for lack of a clean category.

For each account or initiative subsection, include only what's relevant:
- Meetings that occurred (time, who attended, outcome or Zoom summary if available) — this can reference the same meetings as Part A, but focus here is narrative content, not processing status
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

For any meeting today that qualifies for meeting-prep (see "Today" in HTML structure below — customer meetings and substantive internal meetings, i.e. anything with attendees beyond the user), note whether prep exists yet or was just generated as part of this run.

End with a brief **Open Time** note if there are meaningful unblocked blocks in the day.

---

### Section 3: Customer Updates, and Section 4: Manager/Leadership Update — viewer-owned, do not embed statically

These two sections are **not** generated by this skill and must **not** be written into the static brief HTML during a run. They are owned entirely by the local viewer app (`viewer/daily-brief-viewer.html` + `viewer/server.py`), which injects them client-side every time a brief is opened:

- It reads the assigned account list fresh from `Meeting Manager Config.xlsx` (via `loadAccountChannels()`).
- For each account, it calls its own `/api/claude` endpoint on first load (or on "↺ Regenerate") with a prompt that has Claude search the account's Slack channel, email, and calendar directly, and writes a fresh draft into an editable textarea.
- It tracks per-account and manager-update state (draft text, last-posted timestamp) in the viewer's own `localStorage`, keyed by filename.
- "Post to Slack" / "DM Manager" buttons copy the formatted text and open the right Slack channel via `app_redirect`.

**Why this matters:** if this skill also writes its own Customer Updates / Manager Update sections directly into the generated HTML (as earlier runs of this skill did, mistakenly), the viewer's injection still fires unconditionally on top of it — producing two visually different copies of the same two sections stacked in the page. This happened in practice and was reported as a "duplicated section" bug; it was not a viewer bug, it was this skill overstepping its scope.

When generating the brief HTML, stop at the four sections in "HTML structure" above (Header, Schedule, Action Items, FYI). Leave Customer Updates and Manager/Leadership Update out of the static file entirely — the viewer supplies them at view-time.

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

The Slack channel ID mapping for Customer Updates is read by the viewer app from `Meeting Manager Config.xlsx` — see the note in Section 3/4 above. Update the config sheet as accounts are added or changed; this skill does not maintain that mapping directly.

---

## Error Handling

If a data source is unavailable (MCP auth issue, timeout), note it briefly at the bottom of the brief under "Unavailable Sources" and proceed with what's available. Do not fail the whole brief because one source errored.

If there is genuinely nothing to report in a section, omit it silently.

## HTML Output

Every brief run produces a standalone interactive HTML file in addition to the in-chat response. The file is self-contained (no external dependencies), works offline, and persists checkbox state in `localStorage` so it can be referenced throughout the day.

### When to generate

Generate the HTML file on every brief run. Name the file: `Daily Brief_YYYY-MM-DD_hh-mm.html` using the local date and 24-hour local time (zero-padded, hyphen-separated) at the moment the file is generated — e.g. `Daily Brief_2026-07-14_08-42.html`.

### HTML structure

The file has five sections, in order:

1. **Header** — date, brief type (Morning / Midday / Evening), timezone label, progress counter ("N of N done"), progress bar
2. **Yesterday's Meetings** — one checkable item per meeting from the last business day (Section 1, Part A). Each item shows title, time, attendees, a recording/transcript link if `get_meeting_assets` found one, and an Asana action-item status line (logged / not found, per the run-log-then-Asana-search check). If no recording/transcript was found, the item's subtitle asks directly for a link or transcript, and the item stays unchecked until that's resolved — this is a real to-do, not just informational, so it belongs here checkable rather than in FYI.
3. **Today** (renamed from "Schedule" — every meeting for the full current day, past or future, per the calendar-pull rule above) — checkable item per meeting with time, title, attendees, a Join link if a Zoom/Webex/Teams URL is present, and a meeting-prep output link. A meeting qualifies for a prep link if it has attendees beyond the user (personal reminders and solo admin blocks don't). For an upcoming qualifying meeting: check whether meeting-prep already exists (via the meeting-manager skill's routing table / per-account Drive folder); if it does, link to it; if not, run the meeting-manager skill's pre-meeting flow for that meeting as part of this brief, then link to the newly generated doc. For a qualifying meeting that has already occurred today by the time the brief runs, don't run pre-meeting prep after the fact — treat it like a Part A entry instead (recording/transcript + Asana status), since "prep" for a meeting that's already over doesn't make sense.
4. **Action Items** — every task that needs action today: overdue Asana tasks, email threads needing a reply, Slack items flagged for response, meeting manager runs needed. Each item is checkable and has a one-line subtitle. **Include a link button whenever a real URL exists for that item** — the Asana task permalink (`https://app.asana.com/0/0/{gid}/f`), the Slack message permalink (construct as `https://{workspace}.slack.com/archives/{channel_id}/p{ts_without_dot}` if not returned directly by the search/read call), the Zoom meeting summary doc URL, or a mailto/webLink for an email thread. This is not optional decoration — it's the difference between a checklist and something the user can actually act on with one click. Only omit the link button when no real URL exists for that item (never use a placeholder `#`).
5. **FYI** — non-actionable signals worth knowing: post-meeting summaries generated, recurring tasks spawned, informational Slack threads, status summary highlights. **Include a link button whenever a real URL exists**, same standard as Action Items — the Zoom meeting summary doc or recording URL, the Slack thread/message permalink (construct as `https://{workspace}.slack.com/archives/{channel_id}/p{ts_without_dot}` if not returned directly), a calendar event's `webLink`, or an Asana task permalink for a spawned recurring task. Nothing actionable is expected here, but "worth knowing" should still be one click from "worth reading in full" — don't make the user go dig for the source. Only omit the link when no real URL exists for that item.

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
body { font-family: var(--font); background: var(--bg); color: var(--t1); padding: 24px 16px 60px; max-width: 1400px; margin: 0 auto; }
```

This `body` rule (font, background, color, padding, max-width, centering) was previously undocumented here and left to per-run discretion, which is how it drifted — it now sets `max-width: 1400px` explicitly so every run is consistent.

### Badge types

| Class | Use |
|-------|-----|
| `bwarn` | Tentative, needs confirmation, time-sensitive |
| `bbad` | Overdue, blocking, critical |
| Custom inline style using `--accent-bg`/`--accent-t` | Informational label (e.g., "hiring", "prep run") |

### Link buttons

Use `class="lbtn primary"` for the primary CTA (Join Zoom, Open doc). Use `class="lbtn"` for secondary links (Asana task, Slack thread, email). All `href` values must be real URLs from the data — never placeholder `#` values in actual output. The example file uses `#` only because it is a sanitized demo.

### localStorage key

Use `brief:YYYY-MM-DD` as the key — the calendar date only, not the filename. Multiple runs in the same day now produce distinct timestamped files (see filename convention above), but they should still share checkbox progress, so the storage key intentionally does not include the time component. The `TOTAL` constant in the script must equal the actual number of checkable items (`.item[data-id]` elements) in that specific brief.

### Sensitive data rules

The HTML file produced during a live brief run will contain real names, meeting titles, and links. That is correct for personal use. However:

- **Never commit a real brief to the GitHub repo.** The `example/` folder in the repo is for sanitized demo files only.
- The example file must use fictional names, companies, and placeholder `#` links.
- No real email addresses, Slack user IDs, Asana GIDs, Zoom meeting IDs, or calendar event IDs may appear in any committed file.
- Customer names in examples must be fictional (e.g., "Acme Financial", "Pinnacle Health", "Meridian Bank") — never real account names.

### Delivering the file

Write the HTML to a local file first (needed anyway to present it as a downloadable artifact in chat), then upload that same content to Google Drive folder `BRIEF_OUTPUT_FOLDER_ID` (value configured in the local copy's Admin Config block, not committed here) using `Google Drive: create_file` with `contentMimeType: text/html` and `disableConversionToGoogleType: true`.

Use the `textContent` parameter, not `base64Content`. This file is plain text — base64-encoding it first only inflates the payload by roughly a third and adds an unnecessary encode/read-back pass before the upload call, which measurably slows the run for no benefit. Pass the HTML directly as `textContent`.

Name the file `Daily Brief_YYYY-MM-DD_hh-mm.html`. Because the filename includes the run time, multiple runs on the same day naturally coexist as separate files — there is no overwrite step, and no need for one.

Also present the file as a downloadable artifact in chat so it is immediately accessible without opening Drive.

---

## Tone

Peer-level, direct. No filler. No affirmations. Write like a prepared colleague who pulled the information for you before the call, not like a dashboard widget.
