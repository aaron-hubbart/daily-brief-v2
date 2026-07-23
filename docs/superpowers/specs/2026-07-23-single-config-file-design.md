# Design: single-pointer config for daily-brief-v2

Date: 2026-07-23
Status: Approved (pending spec review)

## Problem

Setting up the skill today requires editing several values directly in a local
copy of `SKILL.md`. The `## Admin Config` block holds seven keys
(`BRIEF_DATA_FOLDER_ID`, `MEETING_RUN_LOG_SHEET_ID`,
`RECURRING_ACTIVITIES_PROJECT_GID`, `STATUS_UPDATE_CACHE_FILE_ID`, plus the
auto-maintained `SKILL_SOURCE_SHA`, `REFERENCES_SOURCE_SHA`,
`SYNC_CHECK_LAST_RUN`), and additional config is scattered through `SKILL.md`
prose (the user's Slack user ID, key contacts, a hard-coded Slack channel-ID
list). Every value that must be edited in `SKILL.md` is a value that the Skill
Sync Check has to carefully preserve when it self-heals by overwriting the local
copy, and it means the skill's configuration is entangled with its logic.

## Goal

Reduce the skill's own configuration to a **single value** — a pointer to one
JSON config file — and move every other setting into that file. Keep the
existing setup flow intact in shape; only change *where* the details land.

## Decisions (from brainstorming)

- **Config pointer:** the single skill value is the **Drive file ID of
  `config.json`**. The skill reads that file directly; everything else,
  including `BRIEF_DATA_FOLDER_ID`, lives inside it.
- **Scope of config.json:** it absorbs the four Admin Config IDs, the sync SHAs,
  the Slack user ID, and the key-contacts list. `account-config.json` stays a
  **separate** file — the webapp reads it, so leaving it in place avoids
  touching the webapp's read path.
- **Who writes config.json:** the **skill**, via an interactive setup mode,
  using its Drive connector.
- **Setup trigger:** explicit (`/daily-brief setup`) **and** auto-offered on a
  normal run when the config pointer is still a placeholder.
- **Slack channel-list cleanup:** **included** — the hard-coded channel-ID list
  in `SKILL.md`'s Slack section is replaced with a list built from
  `account-config.json`'s channel IDs.

## Design

### 1. The one skill value

`SKILL.md`'s `## Admin Config` block collapses from seven keys to one:

```
CONFIG_FILE_ID: <Drive file ID of your config.json — created for you by the setup flow>
```

Every other key is removed from `SKILL.md`. This repo's committed copy keeps
`CONFIG_FILE_ID` as a generic placeholder, same public-repo hygiene as the
existing block. `README.md`'s Configuration table is reduced to this one key,
with a pointer to the setup flow for everything else.

### 2. config.json

Location: `/config/config.json` inside the brief-data Drive folder, alongside
the existing `/config/account-config.json`.

Shape — user-chosen settings at the top level, machine-maintained sync state
isolated in its own `sync_state` sub-object:

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

Notes:
- `key_contacts` holds the named individuals. Account affiliation (a contact at
  BofA, JPMC, etc.) continues to be derived from the account names in
  `account-config.json`, not duplicated here.
- `sync_state` is the only part of the file the skill writes during normal runs
  (see section 4). The rest is written only during setup.

### 3. Interactive setup flow (skill-driven)

Triggered by `/daily-brief setup` or a natural-language "set up daily brief",
**and** auto-offered whenever a normal run finds `CONFIG_FILE_ID` still set to
the placeholder (so a fresh install offers setup instead of erroring). Steps, in
order:

1. **Establish the config file location** (the first item in the flow). Ask for
   the brief-data Drive folder ID (or note one the user will create). The skill
   creates `/config/config.json` in that folder with a starter document, reports
   the new file's Drive ID, and instructs the user to paste it into
   `CONFIG_FILE_ID` in their local `SKILL.md`. This paste is the only manual
   edit to `SKILL.md`.
2. **Collect the remaining values.** Prompt for each remaining setting
   (`meeting_run_log_sheet_id`, `recurring_activities_project_gid`,
   `status_update_cache_file_id`, `slack_user_id`, `key_contacts`) and write them
   into `config.json` via the Drive connector. `brief_data_folder_id` is set
   from the folder used in step 1. Re-running setup reads the existing
   `config.json` and edits it in place (updating only the values the user
   changes) rather than recreating it.
3. **Point at the remaining prerequisites** that already exist and are unchanged:
   enabling the MCP connectors (Microsoft 365, Slack, Zoom, Asana, Google Drive)
   and hand-maintaining `account-config.json`. These are referenced, not
   re-collected.

The setup flow is documented in the skill so it can run without the webapp.

### 4. Runtime changes

- **Config load at run start.** Every run begins by reading `config.json` (by
  `CONFIG_FILE_ID`) to load all settings and the sync markers. If
  `CONFIG_FILE_ID` is the placeholder, the run offers setup (section 3) instead
  of proceeding.
- **Skill Sync Check reworked.** The check reads `sync_state.skill_source_sha`,
  `sync_state.references_source_sha`, and `sync_state.sync_check_last_run` from
  `config.json` instead of from the `SKILL.md` Admin Config block, and writes the
  updated values back into `config.json`. The self-heal path (overwrite the
  local `SKILL.md` from `main` on drift) then only has to preserve the single
  `CONFIG_FILE_ID` value, since the SHAs no longer live in `SKILL.md`. This is
  strictly simpler than today's re-insertion of multiple markers, and the
  markers now survive even a full re-fetch of the local copy because they live on
  Drive.
- **Slack channel list built from account-config.json.** The hard-coded
  `in:<#...>` channel-ID list in `SKILL.md`'s Slack data-source section is
  replaced with instruction to build the multi-`in:` query from the
  `slack_channel_id` values in `account-config.json` (already the authoritative
  source for the account→channel mapping). This removes the last piece of
  account-specific config baked into `SKILL.md` prose without expanding
  `config.json`'s scope.

### 5. Webapp walkthrough

The 5-step walkthrough in `viewer-backend/daily-brief-viewer.html` changes only
its text:
- **Step 2** ("Install the daily-brief-v2 skill" / "fill in your local copy's
  Admin Config block" with four keys) is rewritten to: install the skill, run
  `/daily-brief setup` in Claude, and paste the resulting config file ID into
  `CONFIG_FILE_ID` in `SKILL.md`.
- **Step 1** (link a Google Drive folder to the *webapp's* own state, via
  `/api/drive-folder`) is unchanged — that is the viewer's own concern, separate
  from the skill's `config.json`. The existing note that this folder must match
  the skill's brief-data folder still holds.
- Steps 3–5 (connectors, other prerequisites, optional Asana PAT) are unchanged
  except for wording that referenced the old Admin Config keys.

No Flask/backend changes. `/api/drive-folder` and the rest of the webapp API are
untouched.

## Out of scope

- Any change to `account-config.json`'s shape, location, or the webapp's reading
  of it.
- Any change to the webapp backend (`app.py`, `drive_store.py`, etc.) or its API
  surface.
- Migrating the Section 3/4 status-update cache file's location (it remains its
  own separate Drive file, referenced by `status_update_cache_file_id`).

## Files touched

- `SKILL.md` — collapse Admin Config to `CONFIG_FILE_ID`; add the setup flow;
  rework the Skill Sync Check to use `config.json`; add the config-load step at
  run start; replace the hard-coded Slack channel list; move Slack user ID and
  key contacts out of prose.
- `README.md` — reduce the Configuration table to `CONFIG_FILE_ID` and document
  the setup flow / config.json shape.
- `references/item-sync.md` — note `config.json` alongside `account-config.json`
  in the `/config` layout description if it enumerates that folder's contents.
- `viewer-backend/daily-brief-viewer.html` — rewrite walkthrough step 2 text and
  any wording referencing the old Admin Config keys.
