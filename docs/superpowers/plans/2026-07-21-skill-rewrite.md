# daily-brief-v2 Skill Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the daily-brief skill (`SKILL.md`, `README.md`, and the four `references/*.md` files) as a new, standalone skill in `aaron-hubbart/daily-brief-v2` that writes brief content directly to Google Drive via the skill's native Drive connector, with no Postgres, no MCP server, and no bearer-token API calls anywhere in the skill's own logic — matching the already-built and merged `viewer-backend/` (this same repo), which reads exactly this Drive layout.

**Architecture:** This is a content/prose rewrite of five Markdown files, not code — there is no compiler or test runner to prove correctness. Instead, each task's "verification" is a concrete, checkable consistency pass: does the file's Admin Config match the webapp's actual expectations, do all item_key/section-slug conventions match `viewer-backend`'s `drive_store.py`, are there zero remaining references to Postgres, the MCP server, or API upsert calls anywhere in the rewritten files. The base content for every file already exists (read in full during the design/brainstorming phase) at `C:\Users\AaronHubbart\Documents\Camunda-Software\utils\daily-brief\{SKILL.md,README.md,references/*.md}` — this is a real, working skill definition to adapt, not a blank page.

**Tech Stack:** Markdown only. No code, no dependencies, no test framework.

## Global Constraints

- Every rewritten file lives in `aaron-hubbart/daily-brief-v2` (this repo), at the repo root (`SKILL.md`, `README.md`) or under `references/` — mirroring the source repo's layout exactly, since that's a proven, working structure.
- The skill writes brief content via `Google Drive: create_file` only — the same native connector already used today for the meeting-run-log sheet and status-update cache. No custom MCP server, no bearer token, no direct HTTP call to any webapp.
- The Drive data layout is exactly what `viewer-backend/drive_store.py` (already built, merged via PR #1) reads: `/briefs/{date}/manifest.json`, `meetings.json`, `accounts/{slug}.json`, `today.json`, `action-items.json`, `fyi.json`, `updates/{slug}.json`, `manager-update.json`, and `/config/account-config.json`. Read `drive_store.py`'s `SECTION_FILES`/`SECTION_SUBFOLDERS` constants and `get_account_projects` directly (`viewer-backend/drive_store.py` in this repo) before writing any task's content, to keep the two sides of this contract in lockstep — the plan text below describes the shapes, but the actual merged code is the source of truth if anything drifts.
- `(section, item_key)` is the stable per-item key — unchanged from the source skill's existing conventions (`ym-{HHmm}-{slug(title)}`, `recap-{slug(account)}`, `today-{HHmm}-{slug(title)}`, `action-{asana_gid}`, `fyi-{n}`, `cust-update-{slug(account)}`, `mgr-update`). No new hashing scheme — this was an open item in the design spec, resolved during the webapp build: the existing item_key convention already serves as the stable per-item identifier the Drive `/state/{date}.json` file keys on.
- Section content files are one JSON file per section (an array of item objects, each shaped `{item_key, item_type, title, subtitle, badge, links, content, checked, display_order, generated_at}` — matching what `drive_store.get_items_for_day` reads), except `accounts/{slug}.json` and `updates/{slug}.json`, which are one file per account (a single item object, not an array) inside their respective subfolders, and `manager-update.json`, which is a single item object (not an array, not a subfolder).
- **A single-item patch (post-meeting-patch, a section-level or single-item refresh) means writing a new version of the WHOLE section file it belongs to** (re-reading the current version, changing just the one item, writing the result as a new file via `create_file`) — except for the one-file-per-account sections (`accounts/{slug}.json`, `updates/{slug}.json`), where the "whole file" already is the one item, so a patch there is a direct single-file rewrite with nothing else to merge. This is a fundamentally different mechanic from the source skill's Postgres-based per-row upsert, and every rewritten reference file must describe it accurately — this is the single most important behavioral change in this rewrite.
- `/config/account-config.json` replaces `Meeting Manager Config.xlsx`'s role for this skill specifically (account name, Slack channel ID, Asana project GID) — hand-maintained by the user, read by both the skill and the webapp. It does not replace `Meeting Manager Config.xlsx` for the separate meeting-manager skill, which is out of scope here.
- The Section 3/4 per-account daily cache (`STATUS_UPDATE_CACHE_FILE_ID`) stays exactly as it is today — its own separately-configured Drive file, not moved into `/briefs/{date}/`. Resolved design-spec open item: this cache tracks "was this account's update already generated today, across however many brief runs happen that day," which is a different lifetime than a single brief's per-date content, so it doesn't belong inside a dated folder.
- The Skill Sync Check's canonical source repo changes from `aaron-hubbart/daily-brief` to `aaron-hubbart/daily-brief-v2` (this is a new, standalone skill, not a fork sharing history).
- No real account names, Slack channel IDs, Asana GIDs, or other real data anywhere in the rewritten files — same repo-hygiene rule the source skill already documents, carried forward unchanged.

---

### Task 1: `SKILL.md` rewrite

**Files:**
- Create: `SKILL.md` (repo root)

**Interfaces:**
- Consumes: the source `SKILL.md` at `C:\Users\AaronHubbart\Documents\Camunda-Software\utils\daily-brief\SKILL.md` (already read in full during design — see the design spec's Explore Project Context notes) as the base to adapt.
- Produces: the Admin Config keys every other task's references assume exist: `BRIEF_DATA_FOLDER_ID`, `MEETING_RUN_LOG_SHEET_ID`, `RECURRING_ACTIVITIES_PROJECT_GID`, `STATUS_UPDATE_CACHE_FILE_ID`, `SKILL_SOURCE_SHA`, `REFERENCES_SOURCE_SHA`, `SYNC_CHECK_LAST_RUN`.

- [ ] **Step 1: Copy the source file forward as a starting point**

Read `C:\Users\AaronHubbart\Documents\Camunda-Software\utils\daily-brief\SKILL.md` in full, then write a new `SKILL.md` at this repo's root, keeping every section that has nothing to do with data sync unchanged verbatim: Purpose, Timezone Resolution, Timing Logic, Data Sources and What to Pull, Output Format (Sections 1-4 content/structure), Formatting Rules, Account and People Context, Error Handling, Tone. These sections describe what to generate, not how it's synced — no v2 changes needed there.

- [ ] **Step 2: Rewrite the Admin Config block**

Replace:
```
DAILY_BRIEF_API_BASE_URL: <base URL of your hosted daily-brief webapp...>
MEETING_RUN_LOG_SHEET_ID: <your meeting-manager run log sheet ID>
RECURRING_ACTIVITIES_PROJECT_GID: <your Asana recurring-activities project GID>
STATUS_UPDATE_CACHE_FILE_ID: <Drive file ID of the Section 3/4 daily cache JSON>
SKILL_SOURCE_SHA: ...
REFERENCES_SOURCE_SHA: ...
SYNC_CHECK_LAST_RUN: ...
```
with:
```
BRIEF_DATA_FOLDER_ID: <Drive folder ID that holds /briefs, /config, and /state for this skill's output — see references/item-sync.md for the layout. Create it once, then link the same folder ID in the webapp's Account panel>
MEETING_RUN_LOG_SHEET_ID: <your meeting-manager run log sheet ID>
RECURRING_ACTIVITIES_PROJECT_GID: <your Asana recurring-activities project GID>
STATUS_UPDATE_CACHE_FILE_ID: <Drive file ID of the Section 3/4 daily cache JSON — unchanged from before, still its own separate file, not inside BRIEF_DATA_FOLDER_ID — see references/status-updates.md>
SKILL_SOURCE_SHA: <maintained automatically by the Skill Sync Check below>
REFERENCES_SOURCE_SHA: <maintained automatically by the Skill Sync Check below>
SYNC_CHECK_LAST_RUN: <maintained automatically by the Skill Sync Check below>
```
Remove the paragraph below the source's Admin Config block that explains the MCP-connector-based auth model ("No API token lives in this file... a direct curl call from this skill would just fail; the connector is a separate network path..."). Replace it with:
```
Item sync writes directly to Google Drive via the "Google Drive: create_file" connector — the same connector already used for the meeting-run-log sheet and status-update cache above. There is no separate connector to add for this, no bearer token, and no custom MCP server: this skill never calls any webapp directly. See references/item-sync.md for the file layout and write mechanics.
```

- [ ] **Step 3: Update the Skill Sync Check section**

Change every reference from `aaron-hubbart/daily-brief` to `aaron-hubbart/daily-brief-v2` in the Skill Sync Check section (canonical source repo, the `GET /repos/...` API paths). Keep the rest of the check's logic (rate-limit gate, two-marker SKILL_SOURCE_SHA/REFERENCES_SOURCE_SHA comparison, self-heal behavior) unchanged — it's repo-agnostic logic that just needs the new repo name substituted in.

- [ ] **Step 4: Replace the "Data Sync" section**

Replace:
```
## Data Sync

Every brief run syncs its content into the hosted viewer's Postgres store, in addition to the in-chat response, per the full spec in `references/item-sync.md`. Read that file when you reach the sync step in a run — it covers section/item_key conventions, badge/link/content shape, and the API calls that create or refresh items.
```
with:
```
## Data Sync

Every brief run writes its content as JSON files into `BRIEF_DATA_FOLDER_ID` on Google Drive, in addition to the in-chat response, per the full spec in `references/item-sync.md`. Read that file when you reach the sync step in a run — it covers the file layout, section/item_key conventions, badge/link/content shape, and the exact `Google Drive: create_file` calls to make.
```

- [ ] **Step 5: Update "Post-Meeting Patch Runs" and "Section Refresh Runs" section text**

These two sections just point at their respective reference files — update only the one sentence in each that describes the underlying mechanism, from "patch that item via the API" to "write a new version of the affected file(s) to Drive," keeping everything else (trigger conditions, when each fires) unchanged.

- [ ] **Step 6: Self-check — grep for leftover v1 references**

Read the new `SKILL.md` back in full and confirm:
- Zero occurrences of "Postgres", "MCP", "MCP server", "daily-brief-mcp-server", "bearer", "DAILY_BRIEF_API_BASE_URL", or "aaron-hubbart/daily-brief" (without `-v2`).
- Every Admin Config key listed is one either the webapp (`viewer-backend/`) or a reference file in this same plan actually reads — cross-check `BRIEF_DATA_FOLDER_ID` and `STATUS_UPDATE_CACHE_FILE_ID` against `viewer-backend/drive_store.py`'s `_briefs_root`/`_find_child` calls and `token_store.py`'s `brief_data_folder_id` column, both already merged in this repo.

- [ ] **Step 7: Commit**

```bash
git add SKILL.md
git commit -m "Rewrite SKILL.md for the Drive-only v2 skill (no Postgres, no MCP server)"
```

---

### Task 2: `README.md` rewrite

**Files:**
- Create: `README.md` (repo root)

**Interfaces:**
- Consumes: the source `README.md` at `C:\Users\AaronHubbart\Documents\Camunda-Software\utils\daily-brief\README.md`.
- Consumes: `viewer-backend/DEPLOYMENT.md` (already merged) for the current, accurate description of what the hosted webapp actually requires — don't describe the webapp's setup from memory of the old Postgres model, cross-check against the real file.

- [ ] **Step 1: Rewrite the Structure and Prerequisites sections**

Keep the `Structure` section's shape (one bullet per file, brief description) but update every file's description to match this repo's actual files (this rewrite's `SKILL.md`, `references/item-sync.md`, `references/status-updates.md`, `references/post-meeting-patch.md`, `references/section-refresh.md`).

In `Prerequisites`, remove the `daily-brief-mcp-server (custom connector)` row from the MCP Connectors table entirely — there is no custom connector to add in v2. Update the `Google Drive` row's "Used for" text to also mention brief-data JSON output, not just the meeting run log sheet and status-update cache. Remove the entire `Daily Brief webapp` subsection's token/connector instructions (signing in to retrieve an API token, adding the connector) — replace with a short pointer: "See `viewer-backend/DEPLOYMENT.md` in this repo for deploying and linking the hosted webapp; there is no API token to retrieve, since the skill never calls the webapp directly."

- [ ] **Step 2: Rewrite "What it does" / "Output" / "Hosted deployment" sections**

`What it does` stays materially the same (recap, forward look, meeting manager automation, recurring tasks, status summary) — these are skill behaviors, not sync mechanics, so leave them alone except for wording that explicitly says "Postgres" or "via the MCP connector."

Replace `Output`'s "Destination" and "Format" paragraphs (which describe the Postgres upsert API) with a description of the Drive JSON layout — point at `references/item-sync.md` for the authoritative shape rather than duplicating it here, matching the source README's own stated philosophy of keeping this file as an overview, not a spec.

Replace `Hosted deployment`'s entire description of the Flask/Postgres/MSAL stack with a short paragraph: the hosted viewer is `viewer-backend/` in this same repo — Flask, MSAL for Entra ID sign-in (unchanged from before), plus its own per-user Google OAuth for reading Drive — and point at `viewer-backend/DEPLOYMENT.md` for the full walkthrough rather than duplicating deployment steps in this file.

- [ ] **Step 3: Remove the "Viewer (legacy, local, optional)" section entirely**

The standalone local viewer (`daily-brief-viewer.html`, `server.py`, launch scripts) was explicitly decided against being carried into v2 (per the brainstorming session) — delete this whole section rather than describing something that doesn't exist in this repo.

- [ ] **Step 4: Rewrite the Configuration section's table**

Match the new Admin Config keys from Task 1's `SKILL.md` (`BRIEF_DATA_FOLDER_ID` instead of `DAILY_BRIEF_API_BASE_URL`), and remove the two "Update `viewer/...`" bullets at the end (they reference the deleted legacy viewer).

- [ ] **Step 5: Self-check**

Read the new `README.md` back in full. Confirm: no reference to the legacy viewer, no reference to a custom MCP connector or API token retrieval step, and every Admin Config key matches Task 1's `SKILL.md` exactly (same key names, same casing).

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "Rewrite README.md for the Drive-only v2 architecture"
```

---

### Task 3: `references/item-sync.md` rewrite

**Files:**
- Create: `references/item-sync.md`

**Interfaces:**
- Consumes: the source `references/item-sync.md` at `C:\Users\AaronHubbart\Documents\Camunda-Software\utils\daily-brief\references\item-sync.md` (already read in full during design).
- Consumes: `viewer-backend/drive_store.py`'s actual read functions (already merged, this repo) as the ground truth for the exact file layout and item shape this file must produce.
- Produces: the file layout, item_key conventions, and per-section content notes every other reference file (Tasks 4-6) and the skill's own generation logic point back to.

- [ ] **Step 1: Keep section-specific content notes unchanged**

Everything in the source file describing *what* goes in each section — the "Yesterday's Meetings," "Account / Initiative Recap," "Today," "Action Items," "FYI," "Customer Updates," "Manager Update" subsections, the item_key conventions table, the `item_type`/`badge`/`links`/`content`/`display_order` field rules, the Slack posting affordances — describes content shape, not sync mechanics. Carry all of it forward verbatim except for two specific changes covered in Steps 3 and 4 below.

- [ ] **Step 2: Replace the top-level sync mechanism description**

Replace the source's opening paragraphs (sections 1-2, "Every brief run syncs its content as structured items to the hosted viewer's Postgres store...") and the "Auth token" and "API calls" sections entirely with:

```markdown
## Drive data layout

Every brief run writes JSON files into `BRIEF_DATA_FOLDER_ID` (your own Drive
folder, configured in SKILL.md's Admin Config) via the native
`Google Drive: create_file` connector — the same one already used for the
meeting-run-log sheet and status-update cache. There is no API to call and
no separate connector to add.

```
/briefs/{date}/manifest.json          — date, brief_type, section list, item count, generated_at
/briefs/{date}/meetings.json          — Section 1 Part A, array of items
/briefs/{date}/accounts/{slug}.json   — Section 1 Part B, one file per account/initiative (a single item object, not an array)
/briefs/{date}/today.json             — Section 2, array of items
/briefs/{date}/action-items.json      — Section 2 action items (New Items only — see the Action Items note below), array of items
/briefs/{date}/fyi.json               — array of items
/briefs/{date}/updates/{slug}.json    — Section 3, one file per account (a single item object, not an array)
/briefs/{date}/manager-update.json    — Section 4, a single item object
```

`{date}` is the brief's `YYYY-MM-DD` date. `{slug}` is the same lowercase,
hyphenated account/initiative slug already used in `item_key` conventions
below.

`manifest.json` is `{"brief_date": "...", "brief_type": "morning"|"midday"|"evening", "generated_at": "<ISO timestamp>"}` — the webapp reads this to know a brief exists for that date and what type it was; it doesn't need a section list or item count (those are derived from the section files themselves at render time).

**Every array-shaped section file (`meetings.json`, `today.json`, `action-items.json`, `fyi.json`) holds the WHOLE section's items for that date in one file** — not one file per item. A full brief run writes the complete array in one `create_file` call. **A patch to a single item within one of these sections (post-meeting-patch, a single-item refresh) means re-reading the array (if this run isn't the first write of the day), changing just the one item by matching on `item_key`, and writing the complete updated array back via `create_file`** — the create-only connector means this is always a new file version, never an in-place edit; the webapp always reads the newest-by-creation-time file per path. See `references/post-meeting-patch.md` and `references/section-refresh.md` for exactly when and how this applies.

The one-file-per-account sections (`accounts/{slug}.json`, `updates/{slug}.json`) don't have this merge step — the whole file already is the one item, so writing a fresh version of it via `create_file` is a complete, self-contained patch with nothing else to preserve.

## Account/Asana project config

`/config/account-config.json` (inside `BRIEF_DATA_FOLDER_ID`) replaces this skill's reliance on `Meeting Manager Config.xlsx` for the account → Slack channel ID → Asana project GID mapping used below and in Action Items. Shape:
```json
{"accounts": [{"account_name": "Bank of America", "slack_channel_id": "C0395GFC4PR", "project_gid": "111222333"}, ...]}
```
You maintain this file by hand (same as the .xlsx is maintained today for the equivalent columns) — this skill reads it, never writes it. The hosted webapp also reads it directly (its own Drive access), which is what lets it poll Asana live for Overdue/Due Next 7 Days/No Due Date without this skill syncing anything to it — there is no `daily_brief_sync_account_projects`-equivalent call in v2; that entire sync step is gone.
```

- [ ] **Step 3: Update the item_key conventions section's intro sentence**

The item_key conventions table itself (`ym-{HHmm}-{slug(title)}`, `recap-{slug(...)}`, etc.) is unchanged — carry it forward verbatim. Just replace the sentence introducing it ("`(brief_date, section, item_key)` is the natural key an upsert targets...") with: "`(section, item_key)` is the natural key that identifies an item within a given date's files — a patch (post-meeting-patch, section-refresh) has to recompute the same `item_key` a full run would have produced for that same item, exactly as before, so it can find and replace the matching entry when rewriting a section's file."

- [ ] **Step 4: Update the Action Items section's account-config reference and remove the sync-tool call**

In the source's "Action Items" subsection, replace every mention of "Meeting Manager Config.xlsx" (for the account → Asana project GID lookup, and the "Internal Asana Project GID" Config Key/Value row) with "`/config/account-config.json`" — same lookup, new source file. If the source's Internal Asana Project GID convention doesn't have an obvious home in the new JSON shape from Step 2, add it as a top-level `internal_project_gid` key alongside `accounts` in `account-config.json`'s shape (update Step 2's JSON example accordingly if you do this).

Remove the entire "Account→project GID sync" paragraph (the one describing calling `daily_brief_sync_account_projects` once per run) — there is no sync call in v2; the webapp reads `/config/account-config.json` directly.

- [ ] **Step 5: Self-check against the merged webapp code**

Read `viewer-backend/drive_store.py` in this repo (already merged) and confirm: the section-to-filename mapping in `SECTION_FILES`/`SECTION_SUBFOLDERS` matches what Step 2 documents exactly (same slugs, same filenames, same array-vs-single-object distinction), and `get_account_projects`'s expected `account-config.json` shape (`{"accounts": [{"account_name", "project_gid"}, ...]}`, ignoring extra keys like `slack_channel_id`) is a subset of what this file's Step 2 documents (extra keys the webapp doesn't read, like `slack_channel_id`, are fine — the skill and webapp don't need to read identical subsets of the same file).

- [ ] **Step 6: Commit**

```bash
git add references/item-sync.md
git commit -m "Rewrite references/item-sync.md: Drive file layout replaces Postgres API upsert"
```

---

### Task 4: `references/status-updates.md` rewrite

**Files:**
- Create: `references/status-updates.md`

**Interfaces:**
- Consumes: the source file at `C:\Users\AaronHubbart\Documents\Camunda-Software\utils\daily-brief\references\status-updates.md`.
- Consumes: Task 3's `references/item-sync.md` (must already be written — this task references its Drive layout by name).

- [ ] **Step 1: Carry forward the cache schema, generation gate, and section content rules verbatim**

The cache schema (keyed by Account Name, `{content, generated_at, window_start}` per entry), the six-point generation gate, and the full Section 3/Customer Updates and Section 4/Manager Update content-generation rules (Slack search window logic, post format, synthesis rules) don't reference Postgres, the MCP server, or an API call anywhere in the source file — carry all of this forward unchanged.

- [ ] **Step 2: Update the two Slack-channel-mapping references**

Both mentions of reading the Slack channel ID mapping from "Meeting Manager Config.xlsx" (in the "Slack channel mapping" paragraph of Section 3) change to "`/config/account-config.json`" — same lookup (`slack_channel_id` per account), new source file, per Task 3's Step 2 JSON shape. Remove the "Do not hardcode channel IDs here... Add new accounts to the Meeting Manager Config.xlsx Accounts sheet" instructions and replace with the equivalent for the new file: "Add new accounts to `/config/account-config.json` as they're onboarded — this file is hand-maintained, not generated by this skill."

- [ ] **Step 3: Update the two "full item shape and the upsert call are in references/item-sync.md" sentences**

Change "the upsert call" to "the Drive write" in both places (end of the Customer Updates and Manager Update subsections) — the pointer to `references/item-sync.md` for the full item shape stays correct as-is, just the wording describing the mechanism changes.

- [ ] **Step 4: Confirm the cache file itself needs no format change**

Explicitly note in this file (a short paragraph near the Cache schema heading) that `STATUS_UPDATE_CACHE_FILE_ID` is unchanged from v1 — still its own separately-configured Drive file (not inside `BRIEF_DATA_FOLDER_ID`, not part of the `/briefs/{date}/` layout), since it tracks generation state across however many brief runs happen in a day, a different lifetime than one day's section content. This makes the design spec's previously-open item explicit and resolved, not silently assumed.

- [ ] **Step 5: Self-check**

Read the new file back in full. Confirm zero references to Postgres, the MCP server, or "upsert" as an API concept (only as a description of "update this one entry in the cache JSON," which is a Drive file write, is fine to keep). Confirm `/config/account-config.json` is referenced consistently with Task 3's shape.

- [ ] **Step 6: Commit**

```bash
git add references/status-updates.md
git commit -m "Rewrite references/status-updates.md: account-config.json replaces the .xlsx lookup"
```

---

### Task 5: `references/post-meeting-patch.md` rewrite

**Files:**
- Create: `references/post-meeting-patch.md`

**Interfaces:**
- Consumes: the source file at `C:\Users\AaronHubbart\Documents\Camunda-Software\utils\daily-brief\references\post-meeting-patch.md`.
- Consumes: Task 3's `references/item-sync.md` (the array-file merge-and-rewrite mechanic this task's Step 4 below depends on).

- [ ] **Step 1: Carry forward the trigger condition and item_key recomputation steps unchanged**

Steps 1-2 of the source file (determine `brief_date`, recompute `item_key` as `ym-{HHmm}-{slug(title)}`) and the "Build the updated item body" bullet list (drop the badge, update subtitle/links, keep `checked: false`, keep everything else) describe content, not sync mechanics — carry forward verbatim.

- [ ] **Step 2: Replace the "Upsert" step**

Replace:
```
4. **Upsert.** `POST $DAILY_BRIEF_API_BASE_URL/api/items/upsert` with the body above, per `references/item-sync.md`. This updates the existing row in place — no other item, section, or brief_day is touched.
```
with:
```
4. **Read, merge, rewrite `meetings.json`.** Read the current `/briefs/{brief_date}/meetings.json` (the newest version, per references/item-sync.md — if this skill's memory of that day's brief run already has it in context from generating the brief, use that rather than re-reading). Find the entry whose `item_key` matches the one recomputed in Step 2, replace it with the updated item body from Step 3, and write the complete array (every other item unchanged, byte-for-byte) back to `/briefs/{brief_date}/meetings.json` via `Google Drive: create_file`. This creates a new version of the whole file — the webapp always reads the newest-by-creation-time version, so this supersedes the version written at brief-generation time. No other section file is touched.
```

- [ ] **Step 3: Update Step 5's "won't correspond to anything meaningful" fallback**

The source's Step 5 (if the recomputed `item_key` doesn't match anything — brief already regenerated with different meetings, or was never flagged) currently says "the upsert will simply create a new row rather than update one. That's harmless but not useful." Replace with: "there's no matching entry to replace in `meetings.json`'s array — don't append a new, unrelated entry to the array in that case (unlike an upsert, a straight append here would be a real, visible extra item, not a harmless no-op row). If there's a clear signal beforehand that the brief already moved on (a new calendar day, or a re-check of the current `meetings.json` shows no `item_key` match), stop and note it once in the post-meeting completion summary instead of writing anything."

- [ ] **Step 4: Update Step 4 (now Step 6)'s link reference**

The final "Don't reproduce brief content in chat" step's link (`$DAILY_BRIEF_API_BASE_URL/brief/{brief_date}`) needs a new base — this skill no longer has a `DAILY_BRIEF_API_BASE_URL` value (removed from Admin Config in Task 1). Replace with a generic instruction: "note that the patch is reflected in the hosted viewer on next page load, without needing to construct or share a direct link" (the viewer's own URL is whatever the user already has bookmarked/deployed at, not something this skill needs to know or construct).

- [ ] **Step 5: Self-check**

Read the new file back in full. Confirm the merge-and-rewrite mechanic (Step 2 above) matches Task 3's `references/item-sync.md` description exactly (same file path, same "read current, replace matching item_key, write complete array" language). Confirm no `$DAILY_BRIEF_API_BASE_URL` or `/api/items/upsert` references remain.

- [ ] **Step 6: Commit**

```bash
git add references/post-meeting-patch.md
git commit -m "Rewrite references/post-meeting-patch.md: read-merge-rewrite replaces per-row upsert"
```

---

### Task 6: `references/section-refresh.md` rewrite

**Files:**
- Create: `references/section-refresh.md`

**Interfaces:**
- Consumes: the source file at `C:\Users\AaronHubbart\Documents\Camunda-Software\utils\daily-brief\references\section-refresh.md`.
- Consumes: Task 3's `references/item-sync.md` and Task 5's `references/post-meeting-patch.md` (both establish the read-merge-rewrite mechanic this task applies to five more sections).

- [ ] **Step 1: Carry forward trigger phrases, prompt format, and target-identification steps unchanged**

The source's "Trigger phrases and prompt format" section (card-level vs. section-level vs. single-item command shapes, the `date:{brief_date}` rule, the legacy-fallback note) and each flow's early "identify the target" steps describe what triggers this and what to regenerate — not how the write happens. Carry forward verbatim except for the specific write-mechanic replacements in Steps 2-4 below.

- [ ] **Step 2: Replace the card-level flow's "Upsert the item" step**

Replace:
```
5. **Upsert the item.** `POST $DAILY_BRIEF_API_BASE_URL/api/items/upsert` (per `references/item-sync.md`) with: [...]. This updates the one existing row in place — every other item, card, and section is untouched by definition, since each is its own row.
```
with:
```
5. **Write the card's file.** Customer account: write `/briefs/{brief_date}/updates/{slug}.json` (per `references/item-sync.md`) with `{"item_key": "cust-update-{slug}", "item_type": "card", "content": {"textarea": "<new update>", "channel_id": "<from account-config.json>", "last_posted_at": "<now>"}, ...}` via `Google Drive: create_file`. Manager update: write `/briefs/{brief_date}/manager-update.json` the same way, `{"item_key": "mgr-update", "item_type": "text-block", "content": {"textarea": "<new update>"}, ...}`. Both of these are one-file-per-item sections (per `references/item-sync.md`), so this write is a complete, self-contained replacement — no read-merge step needed, and every other item, card, and section is untouched by definition, since each lives in its own file.
```

- [ ] **Step 3: Replace the section-level flow's "Batch-upsert" step**

Replace:
```
4. **Batch-upsert only this section's items.** `POST $DAILY_BRIEF_API_BASE_URL/api/items/batch-upsert` with `brief_date` and an `items` array containing only entries for the refreshed section, using the same `item_key` conventions from `references/item-sync.md` so existing rows are updated in place rather than duplicated. Items in every other section are untouched by definition, since each row is addressed by its own `(section, item_key)`.
```
with:
```
4. **Write the section's file.** For an array-shaped section (`meetings.json`, `today.json`, `action-items.json`, `fyi.json` — per `references/item-sync.md`), this is a full-section refresh, so write the complete regenerated array for that one file via `Google Drive: create_file` — unlike the single-item merge in `references/post-meeting-patch.md`, there's nothing to read-and-merge first, since every item in the section is being regenerated. For the one-file-per-account sections (`accounts/{slug}.json`), refreshing "a section" doesn't really apply the same way — Account/Initiative Recap is a whole-section refresh across every account/initiative subsection at once, so write each account's file that changed. Files for every other section (or, for `accounts/`, every other account) are untouched by definition, since each lives in its own path.
```

- [ ] **Step 4: Replace the single-item-refresh's "api/items/upsert" reference**

In the "Single-item refresh" bullet under "Partial run handling," replace the reference to `api/items/upsert` with a pointer to `references/post-meeting-patch.md`'s read-merge-rewrite mechanic: "When the command includes `item:{item_key}`, only that one entry needs regenerating — apply the same read-current-array/replace-matching-item_key/write-complete-array mechanic `references/post-meeting-patch.md` describes, scoped to this section's file instead of `meetings.json`. Same partial-failure and drift handling as above."

- [ ] **Step 5: Replace the "Item count drift" bullet's stale-marking mechanic**

Replace:
```
**Item count drift.** ... there's no delete endpoint to remove the orphaned row. Instead, upsert that row with `stale: true` added to its `content` so the viewer can gray it out rather than show it as current.
```
with:
```
**Item count drift.** If the fresh pull returns fewer items than the section's current file has (a meeting got cancelled, a task got completed elsewhere), there's no way to delete just one entry from a file that's about to be fully rewritten anyway — but there's also no reason to invent one: since a full-section refresh writes the complete regenerated array, an item that no longer exists in the fresh pull simply isn't in the array you write, and it disappears from the section on next page load. This is different from `references/post-meeting-patch.md`'s single-item patch, which must explicitly preserve every item it isn't updating — a whole-section refresh doesn't have that constraint, since the whole array is authoritative. Never fabricate a reason an item disappeared; if it's worth calling out, note it once in the chat response.
```

- [ ] **Step 6: Update the closing link references and the Action Items exception**

Same `$DAILY_BRIEF_API_BASE_URL/brief/{brief_date}` link replacement as Task 5's Step 4, in both flows' final "Respond briefly" steps.

In the "Action Items exception" section, replace "re-run the Asana search/create step described in `references/item-sync.md` for that subsection only, and batch-upsert just those rows" with "...and write the regenerated New Items array to `/briefs/{brief_date}/action-items.json`" — same logic, new write mechanic. Keep the rest of that paragraph (only New Items has any real work to do; Overdue/Due/No Due Date are always live from Asana) unchanged, since that's a webapp behavior this skill doesn't touch either way.

- [ ] **Step 7: Self-check**

Read the new file back in full. Confirm every write-mechanic paragraph is internally consistent with Task 3's file-layout description and Task 5's read-merge-rewrite mechanic (same terminology, same file paths). Confirm zero remaining `$DAILY_BRIEF_API_BASE_URL`, `/api/items/`, "upsert," or "batch-upsert" references anywhere in the file.

- [ ] **Step 8: Commit**

```bash
git add references/section-refresh.md
git commit -m "Rewrite references/section-refresh.md: per-file writes replace batch-upsert"
```

---

### Task 7: Cross-file consistency pass

**Files:** None created — this task only reads and, if needed, patches the six files from Tasks 1-6.

**Interfaces:** None (verification-only task).

- [ ] **Step 1: Read all six files back in one pass**

Read `SKILL.md`, `README.md`, `references/item-sync.md`, `references/status-updates.md`, `references/post-meeting-patch.md`, `references/section-refresh.md` together.

- [ ] **Step 2: Check cross-references resolve correctly**

Confirm every "see references/X.md" pointer in one file actually points at a file this plan produced with the content it claims to have (e.g. `SKILL.md`'s pointer to `references/item-sync.md` for the file layout — confirm that file actually documents the layout, not a stale claim).

- [ ] **Step 3: Grep for any remaining v1-only terms across all six files**

Search for: `Postgres`, `MCP server`, `daily-brief-mcp-server`, `DAILY_BRIEF_API_BASE_URL`, `/api/items/`, `upsert` (as an API concept — "update this cache entry" prose is fine, an literal `/api/...upsert` path reference is not), `Meeting Manager Config.xlsx` (except where a task deliberately kept a reference to it for the *separate* meeting-manager skill's own use, not this skill's account/Slack/Asana lookup), and bare `aaron-hubbart/daily-brief` without `-v2`. Fix any leftover hit.

- [ ] **Step 4: Confirm the account-config.json shape is identical everywhere it's described**

`references/item-sync.md` (Task 3, Step 2) and `references/status-updates.md` (Task 4, Step 2) both describe `/config/account-config.json`'s shape — confirm they describe the exact same JSON structure (same key names: `accounts`, `account_name`, `slack_channel_id`, `project_gid`, and `internal_project_gid` if Task 3 added it).

- [ ] **Step 5: Final commit**

If Step 3 or 4 found anything to fix, commit those fixes:
```bash
git add -A
git commit -m "Cross-file consistency pass: fix leftover v1 references and align account-config.json shape"
```
If nothing needed fixing, no commit is needed for this task — note that in your report instead.
