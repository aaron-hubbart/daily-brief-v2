---
name: daily-brief-v2
description: >
  Generates a personalized daily briefing for Aaron Hubbart, Senior TAM at Camunda, pulling from Outlook calendar/email, Slack (DMs, account channels, tiger team, mentions), Zoom summaries, and Asana tasks. Produces a structured recap of the day so far and a plan ahead.

  Trigger on: "daily brief", "morning brief", "evening brief", "brief me", "catch me up", "what's my day look like", "what happened today", "eod brief", "sod brief", or "brief" alone. Also trigger when asked to catch up on the day, communications, or schedule.

  Also trigger on "refresh the [account] update", "regenerate manager update", "refresh section:[slug]", or any message starting with "/daily-brief Refresh" — these patch a single card/section, not a full brief.

  Also trigger the setup flow on "/daily-brief setup", "set up daily brief", or "configure daily brief" — see the First-Run Setup section.

  Don't require morning vs. evening — infer from context or current time. Always run without asking for confirmation first.
---

# Daily Brief Skill

This file is the core: trigger, timing, and what to pull. Three things are deliberately kept in separate reference files in this same skill directory so they don't get read on every run when they don't apply:

- `references/item-sync.md` — item shape, section/item_key conventions, and the Google Drive writes that sync a run's content into this skill's `BRIEF_DATA_FOLDER_ID`. Used every run, but pulled out so this core file stays short for the earlier decision-making steps.
- `references/status-updates.md` — Section 3/4 (Customer Updates, Manager Update) generation. **Read this file on every single brief run, with no exceptions** — including the first "brief me" of the day, which is exactly the case where every account and the manager entry are cache misses and need full generation. The per-account gate that decides reuse-vs-regenerate lives inside that file, not here; you cannot correctly skip Sections 3/4 without having read it first. Treating these sections as optional, or assuming a cache hit without checking, is the single most common failure mode of this skill — do not extrapolate "most runs reuse the cache" into "check is skippable."
- `references/post-meeting-patch.md` — the post-meeting patch flow. Only read when that specific, infrequent trigger fires.
- `references/section-refresh.md` — patches a single Customer Update or Manager Update card, or regenerates one of the other five sections in full, when a Refresh button is clicked. Only read when that trigger fires.

## Admin Config

This skill keeps exactly one configuration value in your local copy of `SKILL.md` — a pointer to a single JSON config file on Google Drive that holds everything else. Set it here (this repo's committed copy keeps it as a placeholder, since the value is account-specific):

```
CONFIG_FILE_ID: <Drive file ID of your config.json — created for you by the setup flow below>
```

Everything else (the brief-data folder ID, the meeting run-log sheet ID, the recurring-activities Asana GID, the status-update cache file ID, your Slack user ID, your key contacts, and the auto-maintained sync markers) lives inside `config.json`, not here. If `CONFIG_FILE_ID` is still the placeholder, run the setup flow (see "First-Run Setup" below) — don't hand-edit values into this file. In a multi-user install, leave this line a placeholder and put each user's `CONFIG_FILE_ID` in their own project instructions instead (see the resolution rule below) — that keeps this shared skill definition free of any one user's data.

### Loading config (do this at the start of every run, before the Skill Sync Check)

1. **Resolve `CONFIG_FILE_ID`.** If your project instructions (project-folder instructions / Claude Project custom instructions) define a `CONFIG_FILE_ID`, use that value — it takes precedence. The `CONFIG_FILE_ID` line in the Admin Config block above is only a fallback for a single-user local copy.
2. If the resolved `CONFIG_FILE_ID` is empty or still the placeholder text, do not attempt a brief. Offer to run First-Run Setup instead (see that section).
3. Otherwise, read `config.json` from Drive by that file ID (`Google Drive` connector — the same read path already used for `account-config.json` and the status-update cache). It provides, as top-level keys: `brief_data_folder_id`, `meeting_run_log_sheet_id`, `recurring_activities_project_gid`, `status_update_cache_file_id`, `slack_user_id`, `key_contacts`, and a `sync_state` object. Everywhere below that refers to one of the old Admin Config IDs (e.g. `BRIEF_DATA_FOLDER_ID`), use the corresponding value from `config.json`.

Item sync writes brief JSON directly to Google Drive via the "Google Drive: create_file" connector — the same connector used for the meeting-run-log sheet, the status-update cache, and `config.json` itself. There is no separate connector to add, no bearer token, and no custom MCP server: this skill never calls any webapp directly. See references/item-sync.md for the file layout and write mechanics.

---

## First-Run Setup

Runs when the user explicitly asks (`/daily-brief setup`, "set up daily brief", etc.), and is auto-offered whenever a normal run finds `CONFIG_FILE_ID` still set to the placeholder (per the config-load step above — offer setup instead of erroring). Setup is interactive and **gathers everything before writing anything**: collect all values, confirm them with the user, then write each config file once. The only thing the user ever hand-edits in `SKILL.md` is `CONFIG_FILE_ID`.

### Phase A — Gather global settings

Ask for these and hold them in the conversation (do not write yet). Ask for the brief-data Drive folder ID first, since both config files live inside it — if the user doesn't have one, tell them to create an empty Drive folder and paste its ID from the URL (`drive.google.com/drive/folders/<this-part>`).

- brief-data Drive folder ID → `brief_data_folder_id`
- meeting-manager run-log Google Sheet ID → `meeting_run_log_sheet_id`
- Asana recurring-activities project GID → `recurring_activities_project_gid`
- status-update cache file ID → `status_update_cache_file_id` (offer to create an empty `{"customer_updates": {}, "manager_update": {}}` file and use its ID)
- Slack user ID (`UXXXXXXXXXX`) → `slack_user_id`
- key contacts (named individuals) → `key_contacts`

### Phase B — Build the account list (discover → confirm)

Produce the full account list before writing. Do not write to Drive during this phase.

1. **Seed** from the existing `/config/account-config.json` if one exists in the folder (read it); otherwise start empty.
2. **Propose additions** by scanning the user's Slack account channels and Asana projects for customer-account names not already in the list.
3. **Draft each account's details by name-search:** the Slack channel(s) whose name matches the account (main + any supporting), the Asana board matching the name — resolved to its `project_gid` — and a Drive folder matching the name for `gdrive_folder_id`. Leave any detail you can't resolve blank.
4. **Confirm with the user.** Present the whole draft and have them correct, fill gaps, add, or remove accounts. Always confirm `tier` (primary/secondary) and, for each secondary account, its `run_day` weekday — these are not discoverable. The result is the complete account list in the shape documented in `references/item-sync.md` (`account_name`, `tier`, `run_day`, `slack_channel_id`, `supporting_slack_channel_ids`, `project_gid`, `asana_board_name`, `gdrive_folder_id`), plus the top-level `internal_project_gid`.

(Future: a per-person account-assignment CSV will become the seed in step 1 — the rest of the flow is unchanged when that lands.)

### Phase C — Write once, then hand off the ID

After the user confirms everything:

1. Create `/config/config.json` in the folder via one `Google Drive: create_file`, containing all Phase A values and `sync_state: {}`.
2. Create `/config/account-config.json` in the folder via one `Google Drive: create_file`, containing the full confirmed account list and `internal_project_gid`.
3. Report the new `config.json` Drive file ID and instruct the user to paste it into `CONFIG_FILE_ID` at the top of their local `SKILL.md`. This paste is the only manual edit.
4. Point at the remaining prerequisites (reference only): enable the MCP connectors they use (Microsoft 365, Slack, Zoom, Asana, Google Drive) under Claude's Settings → Connectors.

**Re-running setup** loads both existing files first, uses them as the Phase A/B starting point, re-confirms, and writes a fresh version of each file once — never a per-key incremental write.

---

## Skill Sync Check (run this right after loading config, before any brief work)

This skill's canonical source of truth is this file and the `references/` directory on `main` in `aaron-hubbart/daily-brief-v2`. Any environment that loads a local copy of this skill (e.g. a persistent runtime skill directory) can silently fall behind if `main` is updated without that local copy being refreshed. Check for that drift before any brief work, every time this skill fires (right after loading config) — but rate-limit the check itself, since hitting the GitHub API on every single brief run is pure overhead for a condition that's only ever true right after a PR merges.

Two things are tracked separately, since a PR can change one without the other (most reference-only changes never touch this file's own content): `sync_state.skill_source_sha` (this file's own blob SHA) and `sync_state.references_source_sha` (the `references/` directory's tree SHA — a single value that changes whenever any file inside that directory changes, anywhere in it, without needing to check each reference file individually). Checking `SKILL.md` alone is not sufficient: several past changes touched only `references/item-sync.md` and left this file's own content untouched, which a `SKILL.md`-only check would have reported as "Match" while the loaded reference files quietly went stale.

1. **Rate-limit gate:** compare the current time to `sync_state.sync_check_last_run` in `config.json`. If less than 4 hours have passed, skip straight to step 2's "Match" behavior without calling the GitHub API at all. If 4+ hours have passed (or the marker is missing), proceed to the actual check and update `sync_state.sync_check_last_run` to now (writing a new version of `config.json`) regardless of the check's outcome.
2. **Check:** fetch the current blob SHA for `SKILL.md` on `main` (`GET /repos/aaron-hubbart/daily-brief-v2/contents/SKILL.md`, or equivalent) and separately fetch the current tree SHA for the `references/` directory (`GET /repos/aaron-hubbart/daily-brief-v2/git/trees/main`, then read the `sha` of the entry whose `path` is `references`). Compare both against `sync_state.skill_source_sha` and `sync_state.references_source_sha` in `config.json`.
3. **Match:** both SHAs match their markers — proceed with the brief normally.
4. **Mismatch (either one):** the repo has moved ahead of the loaded copy — this applies even if only `references_source_sha` differs and `skill_source_sha` still matches. Self-heal: fetch `SKILL.md` and the full `references/` directory fresh from `main`, re-insert this local copy's real `CONFIG_FILE_ID` value into the fetched `SKILL.md`'s `## Admin Config` block (the repo file keeps it as a placeholder for public-repo hygiene; `CONFIG_FILE_ID` is now the only local-only value to preserve), overwrite the local copy, then update `sync_state.skill_source_sha` and `sync_state.references_source_sha` in `config.json` and write it back. Note briefly in the brief output that the skill definition was auto-synced.
5. **Fetch fails:** skip silently and proceed with the current local copy. Never block the brief on this check.

This makes drift self-correcting without paying for an API round trip on every single invocation, without a reference-only update silently going undetected, and — now that the markers live in `config.json` rather than `SKILL.md` — the self-heal only has to carry the one `CONFIG_FILE_ID` value across a re-fetch, and the markers survive even a full overwrite of the local copy.

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
- When new action-item tasks need creating (see `references/item-sync.md`, Action Items), batch them into one `Asana:create_tasks` call rather than creating one at a time — it accepts up to 50 tasks per call.

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


## Folder Existence Check

Before writing files to `BRIEF_DATA_FOLDER_ID`, check whether the necessary folder hierarchy already exists. This prevents duplicate folder creation on subsequent brief runs.

**Process:**

1. **Query for `/briefs` folder** — Use `Google Drive: list_files` (or equivalent) to search for a folder named "briefs" inside `BRIEF_DATA_FOLDER_ID`. If found, use its ID; if not, create it.
2. **Query for `/config` folder** — Use `Google Drive: list_files` to search for a folder named "config" inside `BRIEF_DATA_FOLDER_ID`. If found, use its ID; if not, create it. This folder holds `config.json` and `account-config.json`.
3. **Query for `/{date}` folder** — Inside the `/briefs` folder (using the ID from step 1), search for a folder matching today's date in `YYYY-MM-DD` format. If found, use its ID; if not, create it.
4. **Query for `/accounts` subfolder** — Inside the `/{date}` folder (using the ID from step 3), search for a folder named "accounts". If found, use its ID; if not, create it.
5. **Query for `/updates` subfolder** — Inside the `/{date}` folder (using the ID from step 3), search for a folder named "updates". If found, use its ID; if not, create it.

**Use existing folder IDs for all file writes** — Once this check is complete, use the resolved folder IDs (whether newly created or existing) for all subsequent `Google Drive: create_file` calls to write section JSON files. This ensures files go to the correct locations without re-creating folders that already exist.

---

## Brief Completion Checklist — sync is mandatory

**BEFORE COMPLETING ANY BRIEF RUN:**

1. ✓ Generate brief content (Sections 1–4).
2. ✓ Read `references/item-sync.md` for the file layout, item shape, and Google Drive write specs.
3. ✓ Run the Folder Existence Check (per `references/item-sync.md`) to resolve or create the `/briefs/{date}` hierarchy and its `accounts/` and `updates/` subfolders, and capture their folder IDs.
4. ✓ Write ALL section JSON files to Google Drive via `create_file` calls:
   - One file per section, using the exact paths in `references/item-sync.md` — `manifest.json`, `meetings.json`, `today.json`, `action-items.json`, `fyi.json`, `accounts/{slug}.json`, `updates/{slug}.json`.
   - Use the resolved folder IDs from step 3.
   - Include all item shapes, badges, links, and content per the `item-sync.md` spec (and honor the `action-items.json` read-merge-rewrite rule).
5. ✓ Update `STATUS_UPDATE_CACHE_FILE_ID` with new `generated_at` timestamps for each account/manager entry generated this run.

**IF ANY SYNC STEP IS SKIPPED, THE BRIEF IS INCOMPLETE.** Sync is not optional — it is the single write operation that persists the brief to the persistent store; the in-chat response alone does not.

## Data Sync

Every brief run writes its content as JSON files into `BRIEF_DATA_FOLDER_ID` on Google Drive, in addition to the in-chat response, per the full spec in `references/item-sync.md`. Read that file when you reach the sync step in a run — it covers the file layout, section/item_key conventions, badge/link/content shape, and the exact `Google Drive: create_file` calls to make.

**Before writing any files, complete the Folder Existence Check above to resolve or create the necessary folder hierarchy and obtain their IDs.** Then use those folder IDs for all subsequent file writes.

## Post-Meeting Patch Runs

Not part of the normal brief trigger. When meeting-manager's post-meeting agent finishes processing a meeting flagged in today's brief as missing a recording/transcript, read `references/post-meeting-patch.md` and follow that flow to write a new version of the affected file(s) to Drive instead of waiting for the next scheduled run.

## Section Refresh Runs

Not part of the normal brief trigger. When a Customer Update or Manager Update card's Refresh button is clicked, a section's Refresh button is clicked (`refresh section:[slug]`), or the user asks directly to refresh/regenerate one of these, read `references/section-refresh.md` and follow that flow to write a new version of the affected file(s) to Drive.

---

## Tone

Peer-level, direct. No filler. No affirmations. Write like a prepared colleague who pulled the information for you before the call, not like a dashboard widget.
