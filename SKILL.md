---
name: daily-brief-v2
description: >
  Generates a personalized daily briefing for Aaron Hubbart, Senior TAM at Camunda, pulling from Outlook calendar/email, Slack (DMs, account channels, tiger team, mentions), Zoom summaries, and Asana tasks. Produces a structured recap of the day so far and a plan ahead.

  Trigger on: "daily brief", "morning brief", "evening brief", "brief me", "catch me up", "what's my day look like", "what happened today", "eod brief", "sod brief", or "brief" alone. Also trigger when asked to catch up on the day, communications, or schedule.

  Also trigger on "refresh the [account] update", "regenerate manager update", "refresh section:[slug]", or any message starting with "/daily-brief Refresh" — these patch a single card/section, not a full brief.

  Also trigger the setup flow on "/daily-brief setup", "set up daily brief", or "configure daily brief" — see the First-Run Setup section.

  Also trigger the on-demand account-discovery flow on "find new accounts", "scan for customers", or "find more accounts" — see the "On-Demand: Find New Accounts" section of references/first-run-setup.md.

  Don't require morning vs. evening — infer from context or current time. Always run without asking for confirmation first.
---

# Daily Brief Skill

This file is the core: trigger, timing, and what to pull. Three things are deliberately kept in separate reference files in this same skill directory so they don't get read on every run when they don't apply:

- `references/item-sync.md` — **MANDATORY ON EVERY RUN; read before generating content.** Item shape, section/item_key conventions, folder hierarchy, and the Google Drive writes that sync a run's content into this skill's `BRIEF_DATA_FOLDER_ID`. This is Step 1 of the Mandatory Sync Flow (see "MANDATORY SYNC FLOW" section below). You must read this file BEFORE generating Sections 1–4, not after.
- `references/status-updates.md` — Section 3/4 (Customer Updates, Manager Update) generation. **Read this file on every single brief run, with no exceptions** — including the first "brief me" of the day, which is exactly the case where every account and the manager entry are cache misses and need full generation. The per-account gate that decides reuse-vs-regenerate lives inside that file, not here; you cannot correctly skip Sections 3/4 without having read it first. Treating these sections as optional, or assuming a cache hit without checking, is the single most common failure mode of this skill — do not extrapolate "most runs reuse the cache" into "check is skippable."
- `references/post-meeting-patch.md` — the post-meeting patch flow. Only read when that specific, infrequent trigger fires.
- `references/section-refresh.md` — patches a single Customer Update or Manager Update card, or regenerates one of the other five sections in full, when a Refresh button is clicked. Only read when that trigger fires.
- `references/first-run-setup.md` — the First-Run Setup flow (minimal config, automated discovery, confirmation, write) and the on-demand "find new accounts" flow. Only read when one of those two triggers fires.

## Admin Config

This skill keeps exactly one configuration value in your local copy of `SKILL.md` — a pointer to a single JSON config file on Google Drive that holds everything else. Set it here (this repo's committed copy keeps it as a placeholder, since the value is account-specific):

```
CONFIG_FILE_ID: <Drive file ID of your config.json — created for you by the setup flow below>
```

Everything else (the brief-data folder ID, the meeting run-log sheet ID, the recurring-activities Asana GID, the status-update cache file ID, your Slack user ID, and your key contacts) lives inside `config.json`, not here. If `CONFIG_FILE_ID` is still the placeholder, run the setup flow (see "First-Run Setup" below) — don't hand-edit values into this file. In a multi-user install, leave this line a placeholder and put each user's `CONFIG_FILE_ID` in their own project instructions instead (see the resolution rule below) — that keeps this shared skill definition free of any one user's data.

### Loading config (do this at the start of every run)

1. **Resolve `CONFIG_FILE_ID`.** If your project instructions (project-folder instructions / Claude Project custom instructions) define a `CONFIG_FILE_ID`, use that value — it takes precedence. The `CONFIG_FILE_ID` line in the Admin Config block above is only a fallback for a single-user local copy.
2. If the resolved `CONFIG_FILE_ID` is empty or still the placeholder text, do not attempt a brief. Offer to run First-Run Setup instead (see that section).
3. Otherwise, read `config.json` from Drive by that file ID (`Google Drive` connector — the same read path already used for `account-config.json` and the status-update cache). It provides, as top-level keys: `brief_data_folder_id`, `meeting_run_log_sheet_id`, `recurring_activities_project_gid`, `status_update_cache_file_id`, `slack_user_id`, `key_contacts`, and optionally a `google_drive_pat_file_id`. Everywhere below that refers to one of the old Admin Config IDs (e.g. `BRIEF_DATA_FOLDER_ID`), use the corresponding value from `config.json`.

### Google Drive write mechanics

This skill uses two distinct write paths depending on whether the target file needs to be **created** or **updated in place**:

1. **New files** (brief section JSON, new folders): use the `Google Drive: create_file` connector as before. This is correct for section files in `/briefs/{date}/` since those are always new per-date.

2. **Existing files that must be updated in place** (`config.json` and the status-update cache file referenced by `status_update_cache_file_id`): use the **Google Drive REST API v3** via `bash_tool` with a Google Cloud OAuth2 access token. The `Google Drive: create_file` connector cannot update an existing file — it always creates a new file, which changes the file ID and breaks any pointer to the old one. For these two files, the file ID is the stable reference that other parts of the system depend on, so in-place update is required.

**How to update an existing Drive file via the API:**

```bash
# 1. Read the PAT from Drive (stored base64-encoded with BOM)
#    google_drive_pat_file_id is in config.json, or passed via project instructions
PAT=$(Google Drive: download_file_content → base64 -d | sed 's/^\xef\xbb\xbf//')

# 2. PATCH the file content
curl -s -X PATCH \
  "https://www.googleapis.com/upload/drive/v3/files/{FILE_ID}?uploadType=media" \
  -H "Authorization: Bearer $PAT" \
  -H "Content-Type: application/json" \
  --data-binary @updated_file.json
```

In practice, since `bash_tool` has network egress restrictions, the PAT-based update must go through a helper that has access to `googleapis.com`. If the bash egress allowlist does not include `googleapis.com`, fall back to writing a new file via the connector and note that the file ID has changed — the caller's project instructions or config will need the new ID.

**When this matters:** Step 5 of the Mandatory Sync Flow (Update Status Cache) and any run that writes back to `config.json`. Both files are referenced by stable file IDs that must not change between runs.

See references/item-sync.md for the file layout and folder hierarchy.

---

## First-Run Setup

Runs when the user explicitly asks (`/daily-brief setup`, "set up daily brief", etc.), and is auto-offered whenever a normal run finds `CONFIG_FILE_ID` still set to the placeholder (per the config-load step above — offer setup instead of erroring).

Read `references/first-run-setup.md` in full before running this flow — it documents the minimal-configuration phase, the automated discovery pass (email, Slack, Asana, and internal-board detection), the confirmation-and-edit step, and the final write-and-hand-off step. It also documents the on-demand "find new accounts" flow used outside of full setup.

**Re-running setup** loads both existing config files first, uses them as the Phase 1/2 starting point, re-confirms, and writes a fresh version of each file once — never a per-key incremental write.

---

---

## Purpose

Produce a structured daily briefing that covers:
- A recap of the current or previous day (what happened, what came in)
- A forward look at the upcoming day or remainder of today

The brief is always split into two sections: **Yesterday / Today So Far** and **Today / Tomorrow**.

---

## MANDATORY SYNC FLOW — Every Run Without Exception

**This skill does not complete until all sync steps below are finished. The in-chat response alone does not constitute a complete brief.** Sync is not optional, conditional, or deferred — it is the write operation that persists the brief to Google Drive; skipping any step leaves the brief incomplete.

**BEFORE generating any content, read `references/item-sync.md` in full.** This reference file documents the authoritative file layout, folder specifications, item shapes, and all Google Drive write operations. You cannot correctly structure the brief output without having read this file first. Do not wait until the end of the run to read it.

### PROHIBITED Output Formats — Read Before Anything Else

The Google Drive deliverable for this skill is EIGHT separate JSON files per date, listed in Step 4 and specified in full in `references/item-sync.md`. Every one of the following is a violation and must not happen — not as a fallback, not "just this once," not because a section is empty, not because "one file reads better":

- **A single consolidated `brief.json`** (or any file that packs multiple sections into one JSON blob). The section split is load-bearing — the hosted viewer reads one file per section, and post-meeting-patch / section-refresh flows rewrite a single section's file. A consolidated file breaks both. If you catch yourself building a top-level `sections: { ... }` object, stop; that is the prohibited shape.
- **A Google Doc (`application/vnd.google-apps.document`)**, a Word doc, a plain-text file, a Markdown file, or any non-`application/json` mime type for the scheduled-run deliverable. Do not fall back to `create_file` with `content_mime_type: text/markdown` because "the JSON schema is complex" — the schema is in `references/item-sync.md`, use it. Do not set `disable_conversion_to_google_type: false`; always pass `true` so JSON stays JSON.
- **Files saved loose in the parent, in `BRIEF_DATA_FOLDER_ID` root, in "My Drive", or in a legacy folder** (`Daily Briefs`, `Daily Briefs New`, `daily-brief`, etc.). The date subfolder MUST live under `/briefs/{date}/`; nothing else is a valid location for a scheduled run.
- **Omitting a section file because it's empty.** Empty sections still get their file, with `[]` for the array-shaped sections or `{}`-shape for `manager-update.json` — the viewer treats a missing file as "brief never ran," not "nothing to report."
- **A chat-only response with no Drive writes.** Interactive `brief me` conversations may include a prose summary in chat, but scheduled runs without a human present MUST still produce the eight files. A pretty in-chat brief that skipped Step 4 is a failed run, not a completed one.

Explicit list of the eight files that must be written on every scheduled run:

```
/briefs/{date}/manifest.json
/briefs/{date}/meetings.json
/briefs/{date}/accounts/{slug}.json   (one file per account/initiative with content — Section 1 Part B is split)
/briefs/{date}/today.json
/briefs/{date}/action-items.json
/briefs/{date}/updates/{slug}.json    (one file per in-scope account — Section 3 is split)
/briefs/{date}/manager-update.json
/briefs/{date}/fyi.json
```

`accounts/` and `updates/` are folders containing per-account JSON files. Everything else in the list is a single JSON file with a fixed name. See `references/item-sync.md` for the exact shape of each.

**Historic failure to correct against:** on 2026-08-19, a scheduled run produced a single Google Doc, then later a single consolidated `brief.json`, in the wrong parent folder, with no per-account split at all. Both are prohibited by the rules above. If in doubt, re-read this section before writing anything.

### Mandatory Sync Flow (Five Sequential Steps)

**Step 1: Read `references/item-sync.md`** — Understand the file layout, folder hierarchy, item schema (item_key conventions, field shapes, badges, links, content), and Google Drive connector mechanics. This is a prerequisite for understanding Steps 2–5. This reference also documents the Folder Existence Check requirements (Step 2 below).

**Step 2: Run Folder Existence Check** — Before writing any files, query `BRIEF_DATA_FOLDER_ID` to check whether `/briefs`, `/config`, `/{date}`, `/accounts`, and `/updates` folders already exist. Use existing folder IDs; create new ones only if they don't exist. Capture the resolved IDs for Step 4.

**Step 3: Generate Brief Content** — Pull all data sources (Outlook, Slack, Zoom, Asana) and synthesize Sections 1–4. See "Data Sources and What to Pull" below for specifics.

**Step 4: Write ALL Section JSON Files to Google Drive** — Using the folder IDs from Step 2, write the complete section JSON files via `Google Drive: create_file`. Each of the paths below is its OWN file — do not merge them into a single consolidated `brief.json`, and do not create any of them as a Google Doc, Markdown, or plain text (see the PROHIBITED Output Formats block above for the full list). All files use `content_mime_type: application/json` and `disable_conversion_to_google_type: true`:
- `/briefs/{date}/manifest.json`
- `/briefs/{date}/meetings.json`
- `/briefs/{date}/accounts/{slug}.json` (one per account/initiative with content)
- `/briefs/{date}/today.json`
- `/briefs/{date}/action-items.json` (read-merge-rewrite; see `references/item-sync.md`)
- `/briefs/{date}/updates/{slug}.json` (one per in-scope account)
- `/briefs/{date}/manager-update.json`
- `/briefs/{date}/fyi.json`

See `references/item-sync.md` for the exact item shape, field requirements, and all write mechanics.

**Step 5: Update Status Cache In Place** — Update `STATUS_UPDATE_CACHE_FILE_ID` with new `generated_at` timestamps for each account and the manager entry generated this run. **This must be an in-place update of the existing file, not a new file creation**, because the file ID is a stable reference stored in `config.json`. Use the Google Drive REST API v3 PATCH method described in "Google Drive write mechanics" above. If the API update fails (e.g. network egress restriction), fall back to writing via the connector's `create_file` and note in the brief output that the status cache file ID has changed and `config.json` needs updating.

**All five steps are mandatory on every run.** A brief run that completes steps 1–3 but skips 4–5 has produced an in-chat response but NO persistent brief — the webapp has no files to read. Always finish all five steps before ending the run. If a Drive write fails, note it in the brief output and do not move on as though sync succeeded.

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

## Resolve In-Scope Accounts

Before pulling data, read `/config/account-config.json` and compute which accounts this run processes. Today's weekday and the start of the current week are in the user's local timezone (from Timezone Resolution above); the week starts Monday 00:00 local.

- Every `primary` account is in scope.
- A `secondary` account is in scope if its `run_day` equals today's weekday, OR (catch-up) its `run_day` falls on-or-before today within the current week AND it has not run this week. "Has not run this week" means its `customer_updates[account_name].generated_at` in the status-update cache (`STATUS_UPDATE_CACHE_FILE_ID`) is missing or earlier than this week's Monday 00:00 local.
- A `secondary` account that is not in scope is omitted entirely from this run — no recap entry, no Customer Update card, no Slack pull.

Carry two groups forward: **primary in-scope** and **secondary in-scope**. Every later step that iterates accounts (the account/initiative recap, the Slack pull, Sections 3/4) uses these groups, not the raw file. If reading `account-config.json` fails, note it under Unavailable Sources and treat the account list as empty rather than blocking the brief.

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
- Key contacts: the names in `config.json`'s `key_contacts`, plus any contact at one of the accounts listed in `account-config.json` (matched by `account_name`)
- Summarize threads, not individual messages — group by sender/topic

### Slack (Slack: slack_search_public_and_private)
Consolidate what used to be five separate searches into fewer calls:

1. **Mentions + DMs in one call.** `to:<@{slack_user_id}>` (from `config.json`) against `channel_types=public_channel,private_channel,mpim,im` covers both direct mentions and DM activity in a single query instead of two.
2. **Account channels in one call where possible.** Build a single query with one `in:<#CHANNEL_ID>` modifier per in-scope account (primary + in-scope secondary from Resolve In-Scope Accounts), including each account's `slack_channel_id` plus every ID in its `supporting_slack_channel_ids`. Never hard-code a channel list here. Slack's search syntax accepts multiple `in:` modifiers in one query, which should return results across all listed channels in a single call rather than one call per account — but verify this against actual results the first few times; if it silently narrows to only the first channel or otherwise behaves unexpectedly, fall back to per-channel calls and note that in the run.
3. **Tiger team / AI-First CS**: one query for tiger team / AI-first / CS tiger.
4. Time-scope every query to the recap window via `after`/`before`.

Consolidate into a single Slack section. Surface only items that need attention or are informational — skip noise, bot messages, and automated notifications.

### Zoom (Zoom for Claude: search_meetings + get_meeting_assets)
- Search for meetings completed in the recap window (last business day for the morning brief, today so far for midday/evening)
- Pull AI summary, transcript availability, recording availability, and next steps for each completed meeting via `get_meeting_assets`. This is a per-meeting call today (search_meetings, then one get_meeting_assets call per meeting) — if the Zoom MCP server later exposes a batched or multi-meeting assets lookup, switch to that; until then this N+1 pattern is accepted as a known cost on days with several completed meetings.
- If no summary is available, note the meeting occurred and that recording/transcript status still needs checking
- For the Yesterday's Meetings status list (Section 1, Part A — see Output Format), this is the primary source for "recording/transcript found or not"
- Only surface meetings in the account/initiative recap (Part B) that produced meaningful content (skip 1:1 standups with no summary) — Part A still lists every meeting regardless of content, since its purpose is processing status, not narrative

### Asana (Asana: get_my_tasks / search_tasks)
- Pull incomplete tasks with due_on = today or overdue
- Group by: overdue, due today, due tomorrow (for evening brief)
- Omit tasks with no due date unless they appear high priority from the name
- For correlating action items to a specific call (Section 1, Part A): first check the Meeting Manager Run Log sheet (`MEETING_RUN_LOG_SHEET_ID`) for a row matching the meeting (by title and date). If no matching row exists there — which is expected right now, since post-meeting processing isn't yet writing to that log — fall back to searching the relevant account's Asana project for tasks created on or shortly after the meeting's date. Report whichever check found something; if neither does, say so plainly rather than guessing.
- **Action item creation is mandatory on every run, never deferred.** After generating all sections, collect every actionable item surfaced by the brief (from Zoom meeting next steps, "recording not found" follow-ups, overdue items needing attention, email threads requiring response, and any other item that warrants tracking). Search Asana first for each one to avoid duplicates, then batch-create all missing tasks in a single `Asana:create_tasks` call (accepts 1-50 tasks per call). Do not skip this step, do not defer it to a follow-up message, and do not ask the user whether to create them. See `references/item-sync.md`, Action Items, for the full task-creation and project-routing rules.

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

List every meeting from the last business day (yesterday, or the prior Friday if today is Monday) in chronological order — this is meeting-by-meeting, not grouped by account. Personal calendar blocks and solo admin reminders (no attendees) are excluded; anything with attendees counts as a meeting for this list. This applies regardless of platform — Zoom, Webex, Teams, or anything else the calendar shows; the recording/transcript check below is what determines whether one was found, not which platform hosted the meeting.

**Every meeting in this list gets a recording/transcript check, with no exceptions.** This is not conditional on the meeting looking important, on the person not having mentioned it, or on a prior run having already covered it — check every single time, every meeting, every run. Skipping this check (or checking it but not following through on the "not found" path below) is a known failure mode of this skill; treat "I already noted it was missing" as not having actually done this step; noting a gap without asking is exactly the silent-and-move-on behavior this rule exists to prevent.

For each meeting, report:
- Title, time, attendees
- **Recording/transcript status** — checked via Zoom `get_meeting_assets`:
  - Found: link directly to the meeting summary doc (`summary_doc_url`) and/or recording, and note whether a transcript is available
  - Not found: flag it with a `bbad` badge reading "not found — needs input" (matches the badge shape in `references/item-sync.md`) — this is the trigger condition below, and it applies whether or not the meeting was ever on Zoom to begin with (a Webex/Teams meeting with no Zoom presence at all is still "not found", not exempt from the check)
- **Asana action-item status** — checked per the Asana data-source note above (run log sheet first, Asana project search as fallback):
  - Found: note that items were logged, with a link to the task(s) or the account project
  - Not found: say so plainly — "no action items logged yet"

**If recording/transcript can't be found for a meeting, all of the following are required, not optional — this is the complete checklist, and every item on it must actually happen, not just the first one:**
1. Explicitly ask the user for a recording link or the full transcript text, so it can be run through the meeting-manager skill's post-meeting flow. Phrase this as a direct request in the chat response — e.g. "BFSI Industry Deep-Dive — no recording or transcript found. Reply with a link or paste the transcript to process this."
2. Give the corresponding synced item the `bbad` badge and this same ask as its `subtitle` (see `references/item-sync.md` for the exact item shape).
3. Include a `claude://claude.ai/new?q=` deep-link button on that item so the person can click straight into a Claude Desktop conversation pre-filled with `/meeting-manager Run post-meeting notes for: [meeting] ([date])` and paste the transcript there.
4. Create the corresponding Asana task per the Action Items rule below — the "provide transcript" ask must itself be a real, linked Asana item, not just prose in this section.

Once the user supplies the recording/transcript, run the meeting-manager skill's post-meeting agent on it in the same conversation rather than waiting for the next brief.

#### Part B: Account / Initiative Recap

After pulling all data sources, consolidate everything by **customer account or internal initiative** — not by source. Each subsection covers one account or initiative and synthesizes across calendar, email, Slack, and Zoom for that topic. This grouping is mandatory — never output a source-by-source list (e.g. a "Calendar" section followed by a "Slack" section).

Order subsections by priority: customer accounts with active signals first (in rough order of urgency), then internal initiatives, then a mandatory catch-all "General / Admin" bucket for anything that doesn't fit elsewhere (personal calendar blocks, admin tasks, notifications with no clear account/initiative tie). Every item pulled from a data source must land in exactly one bucket — nothing gets silently dropped for lack of a clean category.

In-scope secondary accounts (see Resolve In-Scope Accounts) are grouped into a dedicated "Secondary Accounts" subsection placed after the primary customer-account and internal-initiative subsections and before the General / Admin bucket. Secondary accounts that are not in scope this run do not appear at all. Primary accounts are grouped as usual above.

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

Only in-scope accounts appear (all primary, plus secondary accounts scheduled or caught-up for today per Resolve In-Scope Accounts); in-scope secondary accounts go in the same "Secondary Accounts" subsection used in Section 1.

For each, include:
- Upcoming meetings (time, attendees, prep needed)
- Asana tasks due today or tomorrow tied to that account
- Any flagged email or Slack threads requiring same-day action

**Every meeting in Today gets both a pre-meeting-prep deep-link and a post-meeting deep-link, with no exceptions and no qualifying criteria.** This used to be gated on the meeting "qualifying" (customer meetings and substantive internal meetings, i.e. anything with attendees beyond the user) — that gate is gone. Every meeting gets both links regardless of type, size, or whether meeting-prep already exists for it: a personal solo block has no attendees and isn't a meeting at all for this purpose (same exclusion as Yesterday's Meetings), but anything with attendees gets both links, full stop. See `references/item-sync.md` for the exact link shape and the `claude://` deep-link targets for each (pre-meeting prep before the meeting concludes, post-meeting notes after).

End with a brief **Open Time** note if there are meaningful unblocked blocks in the day.

---

### Section 3: Customer Updates & Section 4: Manager/Leadership Update

**Sections 3 and 4 are mandatory parts of every brief run — they are never silently omitted.** What varies per run is only whether each entry's content comes from cache or gets freshly generated, not whether the section appears at all. Both sections are gated by a per-account daily cache to avoid re-synthesizing the same status updates on every brief run of the day. Full generation logic, the cache schema, and the gate live in `references/status-updates.md` — **read that file on every run, before considering the brief complete**, then generate for any account or the manager entry the gate says needs it, and reuse cached content for entries the gate says to reuse.

Quick summary of the gate: each account (and the manager update) generates fresh the first time it's needed that day, then every later run that day reuses its cached content — evaluated per entry, so a run can reuse six accounts and regenerate two in the same pass. On the first "brief me" of a given day, expect every entry to be a cache miss — that means a full generate-and-synthesize pass for all eight accounts plus the manager update, not a quick skip. Each card also has a Refresh button (see `references/item-sync.md`) that forces an immediate, single-card regeneration outside the normal brief flow — see `references/section-refresh.md` for that flow.

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

Configure your accounts in `/config/account-config.json` and your key colleagues in `config.json`'s `key_contacts` (see the First-Run Setup section).

Use this context to prioritize and flag items — a Slack DM from your AE about a strategic account matters more than a general announcement channel.

The Slack channel ID mapping for Customer Updates is read from `/config/account-config.json` — see `references/item-sync.md` for its Drive location and shape, and the note in Section 3/4 above. The First-Run Setup flow builds and updates this file (discover → confirm — see the First-Run Setup section); this skill reads it on every run but never writes it during a normal brief.

---

## Error Handling

If a data source is unavailable (connector auth issue, timeout), note it briefly at the bottom of the brief under "Unavailable Sources" and proceed with what's available. Do not fail the whole brief because one source errored.

If there is genuinely nothing to report in a section, omit it silently.

---

## Folder Existence Check Details

This is Step 2 of the Mandatory Sync Flow (see above). Before writing any files to `BRIEF_DATA_FOLDER_ID`, check whether the necessary folder hierarchy already exists. This prevents duplicate folder creation on subsequent brief runs.

**Process:**

1. **Query for `/briefs` folder** — Use `Google Drive: list_files` (or equivalent) to search for a folder named "briefs" inside `BRIEF_DATA_FOLDER_ID`. If found, use its ID; if not, create it.
2. **Query for `/config` folder** — Use `Google Drive: list_files` to search for a folder named "config" inside `BRIEF_DATA_FOLDER_ID`. If found, use its ID; if not, create it. This folder holds `config.json` and `account-config.json`.
3. **Query for `/{date}` folder** — Inside the `/briefs` folder (using the ID from step 1), search for a folder matching today's date in `YYYY-MM-DD` format. If found, use its ID; if not, create it.
4. **Query for `/accounts` subfolder** — Inside the `/{date}` folder (using the ID from step 3), search for a folder named "accounts". If found, use its ID; if not, create it.
5. **Query for `/updates` subfolder** — Inside the `/{date}` folder (using the ID from step 3), search for a folder named "updates". If found, use its ID; if not, create it.

**Capture and use folder IDs for all writes** — Once this check is complete, use the resolved folder IDs (whether newly created or existing) for all subsequent `Google Drive: create_file` calls in Steps 4–5. This ensures files go to the correct locations without re-creating folders that already exist.

## Post-Meeting Patch Runs

Not part of the normal brief trigger. When meeting-manager's post-meeting agent finishes processing a meeting flagged in today's brief as missing a recording/transcript, read `references/post-meeting-patch.md` and follow that flow to write a new version of the affected file(s) to Drive instead of waiting for the next scheduled run.

## Section Refresh Runs

Not part of the normal brief trigger. When a Customer Update or Manager Update card's Refresh button is clicked, a section's Refresh button is clicked (`refresh section:[slug]`), or the user asks directly to refresh/regenerate one of these, read `references/section-refresh.md` and follow that flow to write a new version of the affected file(s) to Drive.

---

## Tone

Peer-level, direct. No filler. No affirmations. Write like a prepared colleague who pulled the information for you before the call, not like a dashboard widget.
