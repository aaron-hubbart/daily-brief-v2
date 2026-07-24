# Single-Pointer Config File Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce the daily-brief-v2 skill's own configuration to a single value — a Drive file ID pointing at one `config.json` — and move every other setting into that file, written by a skill-driven interactive setup flow.

**Architecture:** `SKILL.md`'s `## Admin Config` block collapses from seven keys to one (`CONFIG_FILE_ID`). All other settings (the three remaining IDs, the auto-maintained sync SHAs, the Slack user ID, and the key-contacts list) move into `/config/config.json` inside the brief-data Drive folder, next to the existing `account-config.json` (which stays separate — the webapp reads it). The skill reads `config.json` at the start of every run, an interactive setup mode creates and populates it, and the Skill Sync Check reads/writes its SHA markers there instead of in `SKILL.md`. The webapp walkthrough changes only its wording.

**Tech Stack:** Markdown skill definition (`SKILL.md`, `references/*.md`, `README.md`), a static HTML/JS webapp view (`viewer-backend/daily-brief-viewer.html`), Python/Flask backend (unchanged) with a pytest suite used only as a regression guard for the HTML edit.

## Global Constraints

- The committed repo copy of `SKILL.md` keeps config values as generic placeholders — never commit real Drive/Asana IDs, Slack user IDs, or contact names. (Public-repo hygiene, per `references/item-sync.md`.)
- `account-config.json` is out of scope: do not change its shape, location, or how the skill/webapp read it.
- No Flask/backend changes: `app.py`, `drive_store.py`, and the webapp API surface are untouched. Only `daily-brief-viewer.html` text changes.
- The Section 3/4 status-update cache stays its own separate Drive file, referenced by `status_update_cache_file_id`; do not relocate it into `config.json`.
- `config.json` lives at `/config/config.json` inside the brief-data folder. Its shape: user settings at the top level, machine-maintained markers isolated under a `sync_state` sub-object.
- Do not add a `Co-Authored-By` trailer to commits (no `attribution.commit` in this project's settings).

---

## config.json canonical shape

Every task that references config keys uses exactly these names:

```json
{
  "brief_data_folder_id": "...",
  "meeting_run_log_sheet_id": "...",
  "recurring_activities_project_gid": "...",
  "status_update_cache_file_id": "...",
  "slack_user_id": "U0A0ZRB4JM8",
  "key_contacts": ["Rodrigo Scaldaferri", "Micah De Boer", "David Paroulek", "Colin Teubner"],
  "sync_state": {
    "skill_source_sha": "...",
    "references_source_sha": "...",
    "sync_check_last_run": "2026-07-23T00:00:00Z"
  }
}
```

---

### Task 1: Collapse Admin Config to `CONFIG_FILE_ID` and add the config-load step

Replace the seven-key Admin Config block with a single `CONFIG_FILE_ID`, and add a run-start step that loads `config.json` (and offers setup if the pointer is still a placeholder). This is the core mechanism every other SKILL.md change depends on.

**Files:**
- Modify: `SKILL.md` (the `## Admin Config` section, currently lines ~22–36)

**Interfaces:**
- Produces: `CONFIG_FILE_ID` (the single local skill value); the convention that all other settings are read from `config.json` by that ID at run start. Task 2 (sync check), Task 3 (setup flow), and Task 4 (Slack/contacts) all consume this.

- [ ] **Step 1: Replace the Admin Config block.** In `SKILL.md`, replace the entire current `## Admin Config` section — from the `## Admin Config` heading through the closing paragraph that begins "Item sync writes directly to Google Drive…" and its trailing `---` — with:

````markdown
## Admin Config

This skill keeps exactly one configuration value in your local copy of `SKILL.md` — a pointer to a single JSON config file on Google Drive that holds everything else. Set it here (this repo's committed copy keeps it as a placeholder, since the value is account-specific):

```
CONFIG_FILE_ID: <Drive file ID of your config.json — created for you by the setup flow below>
```

Everything else (the brief-data folder ID, the meeting run-log sheet ID, the recurring-activities Asana GID, the status-update cache file ID, your Slack user ID, your key contacts, and the auto-maintained sync markers) lives inside `config.json`, not here. If `CONFIG_FILE_ID` is still the placeholder, run the setup flow (see "First-Run Setup" below) — don't hand-edit values into this file.

### Loading config (do this at the start of every run, before the Skill Sync Check)

1. If `CONFIG_FILE_ID` is empty or still the placeholder text, do not attempt a brief. Offer to run First-Run Setup instead (see that section).
2. Otherwise, read `config.json` from Drive by that file ID (`Google Drive` connector — the same read path already used for `account-config.json` and the status-update cache). It provides, as top-level keys: `brief_data_folder_id`, `meeting_run_log_sheet_id`, `recurring_activities_project_gid`, `status_update_cache_file_id`, `slack_user_id`, `key_contacts`, and a `sync_state` object. Everywhere below that refers to one of the old Admin Config IDs (e.g. `BRIEF_DATA_FOLDER_ID`), use the corresponding value from `config.json`.

Item sync writes brief JSON directly to Google Drive via the "Google Drive: create_file" connector — the same connector used for the meeting-run-log sheet, the status-update cache, and `config.json` itself. There is no separate connector to add, no bearer token, and no custom MCP server: this skill never calls any webapp directly. See references/item-sync.md for the file layout and write mechanics.

---
````

- [ ] **Step 2: Verify the block reads correctly.**

Run: `sed -n '/^## Admin Config/,/^## Skill Sync Check/p' SKILL.md`
Expected: shows only `CONFIG_FILE_ID` as a configured value (no `BRIEF_DATA_FOLDER_ID`/`MEETING_RUN_LOG_SHEET_ID`/etc. as config lines), the "Loading config" numbered list, and the Item-sync paragraph, ending right before the Skill Sync Check heading.

- [ ] **Step 3: Confirm no orphaned references to the removed keys were left in the Admin Config area.**

Run: `grep -n "SKILL_SOURCE_SHA\|REFERENCES_SOURCE_SHA\|SYNC_CHECK_LAST_RUN" SKILL.md`
Expected: matches remain ONLY inside the Skill Sync Check section (they'll be rewritten in Task 2). No match should be a `## Admin Config` config line anymore.

- [ ] **Step 4: Commit.**

```bash
git add SKILL.md
git commit -m "Collapse Admin Config to single CONFIG_FILE_ID and add config-load step"
```

---

### Task 2: Rework the Skill Sync Check to use config.json's `sync_state`

The sync markers moved out of `SKILL.md`. The check now reads and writes them in `config.json` under `sync_state`, and the self-heal only has to preserve `CONFIG_FILE_ID` when overwriting the local copy.

**Files:**
- Modify: `SKILL.md` (the `## Skill Sync Check` section, currently lines ~40–52)

**Interfaces:**
- Consumes: `CONFIG_FILE_ID` and the loaded `config.json` from Task 1.
- Produces: the rule that `sync_state.skill_source_sha`, `sync_state.references_source_sha`, and `sync_state.sync_check_last_run` are persisted to `config.json`.

- [ ] **Step 1: Rewrite the numbered steps.** In `SKILL.md`'s `## Skill Sync Check` section, replace the numbered list (steps 1–5) and the closing sentence with the version below. Leave the two explanatory paragraphs above the list (about tracking two SHAs separately) intact except where they name where the markers live — update those to say `config.json`'s `sync_state` rather than "this local copy's Admin Config block".

````markdown
1. **Rate-limit gate:** compare the current time to `sync_state.sync_check_last_run` in `config.json`. If less than 4 hours have passed, skip straight to step 2's "Match" behavior without calling the GitHub API at all. If 4+ hours have passed (or the marker is missing), proceed to the actual check and update `sync_state.sync_check_last_run` to now (writing a new version of `config.json`) regardless of the check's outcome.
2. **Check:** fetch the current blob SHA for `SKILL.md` on `main` (`GET /repos/aaron-hubbart/daily-brief-v2/contents/SKILL.md`, or equivalent) and separately fetch the current tree SHA for the `references/` directory (`GET /repos/aaron-hubbart/daily-brief-v2/git/trees/main`, then read the `sha` of the entry whose `path` is `references`). Compare both against `sync_state.skill_source_sha` and `sync_state.references_source_sha` in `config.json`.
3. **Match:** both SHAs match their markers — proceed with the brief normally.
4. **Mismatch (either one):** the repo has moved ahead of the loaded copy — this applies even if only `references_source_sha` differs and `skill_source_sha` still matches. Self-heal: fetch `SKILL.md` and the full `references/` directory fresh from `main`, re-insert this local copy's real `CONFIG_FILE_ID` value into the fetched `SKILL.md`'s `## Admin Config` block (the repo file keeps it as a placeholder for public-repo hygiene; `CONFIG_FILE_ID` is now the only local-only value to preserve), overwrite the local copy, then update `sync_state.skill_source_sha` and `sync_state.references_source_sha` in `config.json` and write it back. Note briefly in the brief output that the skill definition was auto-synced.
5. **Fetch fails:** skip silently and proceed with the current local copy. Never block the brief on this check.

This makes drift self-correcting without paying for an API round trip on every single invocation, without a reference-only update silently going undetected, and — now that the markers live in `config.json` rather than `SKILL.md` — the self-heal only has to carry the one `CONFIG_FILE_ID` value across a re-fetch, and the markers survive even a full overwrite of the local copy.
````

- [ ] **Step 2: Update the explanatory paragraphs' marker names.** In the two paragraphs above that list, replace references to `SKILL_SOURCE_SHA`/`REFERENCES_SOURCE_SHA` with `sync_state.skill_source_sha`/`sync_state.references_source_sha`, and any phrase locating them "in this local copy's Admin Config block" with "in `config.json`'s `sync_state`".

Run: `grep -n "SKILL_SOURCE_SHA\|REFERENCES_SOURCE_SHA\|SYNC_CHECK_LAST_RUN\|Admin Config block" SKILL.md`
Expected: no remaining uppercase-marker names and no "Admin Config block" phrasing inside the Skill Sync Check section; only the new `sync_state.*` names appear.

- [ ] **Step 3: Commit.**

```bash
git add SKILL.md
git commit -m "Rework Skill Sync Check to read/write sync markers in config.json"
```

---

### Task 3: Add the First-Run Setup flow to SKILL.md

Document the skill-driven interactive setup: explicit trigger plus auto-offer, the config-file-location-first ordering, and the bootstrap where the skill creates `config.json` and reports its ID.

**Files:**
- Modify: `SKILL.md` (add a `## First-Run Setup` section; extend the trigger description in the frontmatter)

**Interfaces:**
- Consumes: `CONFIG_FILE_ID`, the config-load step (Task 1), the config.json shape.
- Produces: the `/daily-brief setup` trigger and the ordered setup steps.

- [ ] **Step 1: Add the setup trigger to the frontmatter description.** In the `description:` block at the top of `SKILL.md`, add a sentence after the existing trigger lines:

```
Also trigger the setup flow on "/daily-brief setup", "set up daily brief", "configure daily brief", or "daily brief setup" — see the First-Run Setup section.
```

- [ ] **Step 2: Add the `## First-Run Setup` section.** Insert it immediately after the `## Admin Config` section's closing `---` (before `## Skill Sync Check`):

````markdown
## First-Run Setup

Runs when the user explicitly asks (`/daily-brief setup`, "set up daily brief", etc.), and is auto-offered whenever a normal run finds `CONFIG_FILE_ID` still set to the placeholder (per the config-load step above — offer setup instead of erroring). Setup is interactive: the skill collects values and writes them into `config.json` on Drive via its Google Drive connector. The only thing the user ever hand-edits in `SKILL.md` is `CONFIG_FILE_ID`.

Run these steps in order:

1. **Establish the config file location (first step, always).** Ask the user for their brief-data Drive folder ID — the folder that holds `/briefs`, `/config`, and `/state` (see references/item-sync.md). If they don't have one yet, tell them to create an empty Drive folder and paste its ID from the URL (`drive.google.com/drive/folders/<this-part>`). Then create `/config/config.json` inside that folder via `Google Drive: create_file`, containing a starter document with `brief_data_folder_id` set to that folder and every other top-level key present but empty (`sync_state` as an empty object). Report the new file's Drive ID to the user and instruct them to paste it into `CONFIG_FILE_ID` at the top of their local `SKILL.md`. This paste is the only manual edit.
2. **Collect the remaining values.** Prompt for each, one at a time, and write them into `config.json` (read-modify-write a new version via the create connector):
   - `meeting_run_log_sheet_id` — the meeting-manager run-log Google Sheet ID
   - `recurring_activities_project_gid` — the Asana recurring-activities project GID
   - `status_update_cache_file_id` — the Drive file ID of the Section 3/4 daily cache JSON (offer to create an empty `{"customer_updates": {}, "manager_update": {}}` file if they don't have one, and use the resulting ID)
   - `slack_user_id` — their Slack user ID (format `UXXXXXXXXXX`), used to detect direct mentions
   - `key_contacts` — the list of named individuals to prioritize in email/Slack scanning
   Any value the user leaves blank stays empty; the skill degrades gracefully on empty config values the same way it does for an unavailable source.
3. **Point at the remaining prerequisites (reference only, don't re-collect).** Remind the user to: enable the MCP connectors they use (Microsoft 365, Slack, Zoom, Asana, Google Drive) under Claude's Settings → Connectors; and hand-maintain `/config/account-config.json` (account → Slack channel ID → Asana project GID mapping — see references/item-sync.md), which stays a separate file from `config.json`.

**Re-running setup** reads the existing `config.json` first and edits only the values the user chooses to change, rather than recreating the file from scratch.
````

- [ ] **Step 3: Verify placement and trigger.**

Run: `grep -n "## First-Run Setup\|/daily-brief setup\|Establish the config file location" SKILL.md`
Expected: the section heading, the trigger phrase in the description, and the step-1 heading all appear.

- [ ] **Step 4: Commit.**

```bash
git add SKILL.md
git commit -m "Add skill-driven First-Run Setup flow"
```

---

### Task 4: Move Slack user ID + key contacts to config.json; build the Slack channel list from account-config.json

Remove the last account-specific config baked into `SKILL.md` prose. The Slack user ID and key contacts now come from `config.json`; the hard-coded `in:<#…>` channel list is replaced with one built from `account-config.json`.

**Files:**
- Modify: `SKILL.md` (the "Outlook Email" key-contacts bullet ~line 107; the "Slack" data-source section ~lines 110–118)

**Interfaces:**
- Consumes: `config.json`'s `slack_user_id` and `key_contacts` (Task 1); `account-config.json`'s `accounts[].slack_channel_id`.

- [ ] **Step 1: Replace the hard-coded key-contacts line.** In the Outlook Email section, replace the line:

```
- Key contacts: Rodrigo Scaldaferri, Micah De Boer, David Paroulek, Colin Teubner, and any contact at BofA, JPMorgan Chase, Wells Fargo, Goldman Sachs, Optum, Blink Health
```

with:

```
- Key contacts: the names in `config.json`'s `key_contacts`, plus any contact at one of the accounts listed in `account-config.json` (matched by `account_name`)
```

- [ ] **Step 2: Replace the mentions/DMs query.** In the Slack section, replace the item that hard-codes the user ID:

```
1. **Mentions + DMs in one call.** `to:<@U0A0ZRB4JM8>` against `channel_types=public_channel,private_channel,mpim,im` covers both direct mentions and DM activity in a single query instead of two.
```

with:

```
1. **Mentions + DMs in one call.** `to:<@{slack_user_id}>` (from `config.json`) against `channel_types=public_channel,private_channel,mpim,im` covers both direct mentions and DM activity in a single query instead of two.
```

- [ ] **Step 3: Replace the hard-coded channel list.** Replace the item that lists literal channel IDs:

```
2. **Account channels in one call where possible.** Slack's search syntax accepts multiple `in:` modifiers in a single query (e.g. `in:<#C0395GFC4PR> in:<#C044Q1241GC> in:<#C04DXPZD2KF> in:<#C030JHUA7B6> in:<#C03LYGJJ47M> in:<#C04L8Q21277> in:<#C07BHQ26EBC> in:<#C057WEDQYUE>` for BofA, JPMC, Wells Fargo, Goldman, Optum, Blink, ICON, and Total System Services). I believe this returns results across all listed channels in one call rather than one call per account, but verify this against actual results the first few times — if it silently narrows to only the first channel or otherwise behaves unexpectedly, fall back to per-channel calls and note that in the run.
```

with:

```
2. **Account channels in one call where possible.** Build a single query with one `in:<#CHANNEL_ID>` modifier per account, using the `slack_channel_id` values from `account-config.json` (never a hard-coded list here). Slack's search syntax accepts multiple `in:` modifiers in one query, which should return results across all listed channels in a single call rather than one call per account — but verify this against actual results the first few times; if it silently narrows to only the first channel or otherwise behaves unexpectedly, fall back to per-channel calls and note that in the run.
```

- [ ] **Step 4: Verify no literal IDs or names remain in prose.**

Run: `grep -n "U0A0ZRB4JM8\|C0395GFC4PR\|Rodrigo Scaldaferri" SKILL.md`
Expected: no matches (all moved to config.json / account-config.json references).

- [ ] **Step 5: Commit.**

```bash
git add SKILL.md
git commit -m "Source Slack user ID, contacts, and channel list from config files"
```

---

### Task 5: Update README.md Configuration and prerequisites

Reduce the Configuration table to `CONFIG_FILE_ID`, and document the setup flow and config.json shape.

**Files:**
- Modify: `README.md` (the `## Configuration` section; the Google Drive / Slack prerequisite bullets that mention the old keys)

**Interfaces:**
- Consumes: the config.json shape and setup flow from Tasks 1 and 3.

- [ ] **Step 1: Replace the Configuration section.** Replace the entire `## Configuration` section (heading, intro sentence, and the seven-row table) with:

````markdown
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
  "key_contacts": ["First Last", "..."],
  "sync_state": { "skill_source_sha": "...", "references_source_sha": "...", "sync_check_last_run": "..." }
}
```

`sync_state` is maintained automatically by the Skill Sync Check. `account-config.json` (the account → Slack channel → Asana project mapping) remains a separate hand-maintained file in the same `/config` folder — see `references/item-sync.md`.
````

- [ ] **Step 2: Fix the prerequisite bullets that name old keys.** In the Prerequisites section, update the Google Drive, Asana, and Slack bullets that say "copy its ID into `BRIEF_DATA_FOLDER_ID`", "into `MEETING_RUN_LOG_SHEET_ID`", "into `STATUS_UPDATE_CACHE_FILE_ID`", "into `RECURRING_ACTIVITIES_PROJECT_GID`", and "set it in the Slack search section of `SKILL.md`" to instead say the value is collected by the setup flow and stored in `config.json` (naming the corresponding config key). Keep the descriptions of what each resource is.

Run: `grep -n "BRIEF_DATA_FOLDER_ID\|MEETING_RUN_LOG_SHEET_ID\|RECURRING_ACTIVITIES_PROJECT_GID\|STATUS_UPDATE_CACHE_FILE_ID\|Admin Config block" README.md`
Expected: no remaining instructions to paste these into `SKILL.md`'s Admin Config; any surviving mentions are only as `config.json` key names in the shape example.

- [ ] **Step 3: Commit.**

```bash
git add README.md
git commit -m "Document single CONFIG_FILE_ID and config.json in README"
```

---

### Task 6: Note config.json in the item-sync /config layout

`references/item-sync.md` describes the `/config` folder contents. Add `config.json` alongside `account-config.json` so the layout stays accurate.

**Files:**
- Modify: `references/item-sync.md` (the `## Account/Asana project config` section ~line 39, and any `/config` layout enumeration)

**Interfaces:**
- Consumes: config.json location convention (Task 1).

- [ ] **Step 1: Add a config.json note.** At the start of the `## Account/Asana project config` section (before the `account-config.json` paragraph), add:

```
The `/config` folder inside `BRIEF_DATA_FOLDER_ID` holds two hand-relevant files: `config.json` (the skill's own settings, created and written by the First-Run Setup flow — see `SKILL.md`) and `account-config.json` (below, hand-maintained). The skill reads `config.json` at the start of every run to resolve `BRIEF_DATA_FOLDER_ID` and its other settings.
```

- [ ] **Step 2: Verify.**

Run: `grep -n "config.json" references/item-sync.md`
Expected: the new note referencing `config.json` appears in the Account/Asana project config section, distinct from the `account-config.json` mentions.

- [ ] **Step 3: Commit.**

```bash
git add references/item-sync.md
git commit -m "Note config.json in item-sync /config layout"
```

---

### Task 7: Rewrite the webapp walkthrough step 2 (text only)

Update the setup walkthrough in the viewer HTML so step 2 points at `/daily-brief setup` and the single `CONFIG_FILE_ID`, instead of listing four Admin Config keys. Confirm the pytest suite still passes (regression guard — no backend change intended).

**Files:**
- Modify: `viewer-backend/daily-brief-viewer.html` (the `data-step="1"` and `data-step="2"` blocks, ~lines 188–210)
- Test: `viewer-backend/tests/` (existing suite, run as-is)

**Interfaces:**
- Consumes: the `CONFIG_FILE_ID` naming and setup trigger from Tasks 1 and 3.

- [ ] **Step 1: Update step 1's trailing line.** In the `data-step="1"` block, replace the sentence:

```html
        <p>Keep this same ID handy — you'll set it as <code>BRIEF_DATA_FOLDER_ID</code> in the next step.</p>
```

with:

```html
        <p>Keep this same ID handy — the skill's setup flow asks for it in the next step to create your config file.</p>
```

- [ ] **Step 2: Rewrite the step 2 block.** Replace the entire `data-step="2"` block (the `<h3>2. Install…</h3>` through its closing `</div>`, including the four-key `<ul>`) with:

```html
      <div class="setup-step" data-step="2">
        <h3>2. Install daily-brief-v2 and run setup</h3>
        <p>Add the skill to a Claude project from <a href="https://github.com/aaron-hubbart/daily-brief-v2" target="_blank" rel="noopener">github.com/aaron-hubbart/daily-brief-v2</a> — copy <code>SKILL.md</code> and the <code>references/</code> folder in.</p>
        <p>Then run <code>/daily-brief setup</code> in Claude. It creates a <code>config.json</code> in your Drive folder from step 1 and walks you through the rest of your settings, writing them there for you. When it reports the new config file's ID, paste that one value into <code>CONFIG_FILE_ID</code> at the top of your local <code>SKILL.md</code> — that's the only thing you hand-edit.</p>
        <p>There's no API token and nothing to paste into a connector — the skill writes brief JSON directly into your Drive folder using its own Google Drive connector.</p>
      </div>
```

- [ ] **Step 3: Verify the old keys are gone from the walkthrough.**

Run: `grep -n "Admin Config\|MEETING_RUN_LOG_SHEET_ID\|RECURRING_ACTIVITIES_PROJECT_GID\|STATUS_UPDATE_CACHE_FILE_ID" viewer-backend/daily-brief-viewer.html`
Expected: no matches in the setup-step blocks (the Account-panel note at ~line 266 references `BRIEF_DATA_FOLDER_ID`; leave that — it's about the webapp's own folder field, not the skill's Admin Config).

- [ ] **Step 4: Run the pytest suite as a regression guard.**

Run: `cd viewer-backend && python -m pytest -q`
Expected: all tests pass (the suite was 39 tests green; a text-only HTML edit must not change that).

- [ ] **Step 5: Commit.**

```bash
git add viewer-backend/daily-brief-viewer.html
git commit -m "Rewrite walkthrough step 2 for setup-driven config"
```

---

## Notes for the implementer

- Tasks 1–4 all edit `SKILL.md` and are ordered by dependency (Task 1 establishes the config-load mechanism the others reference). Do them in order.
- There are no unit tests for the skill markdown — verification for Tasks 1–6 is the `grep`/`sed` checks shown, plus reading the changed section to confirm it flows. Task 7 is the only one with an executable test (the existing pytest suite, used purely to confirm the HTML edit didn't break the app).
- When editing `SKILL.md`, match the existing prose voice (peer-level, direct) and keep the file short — it's read in full on every trigger.
