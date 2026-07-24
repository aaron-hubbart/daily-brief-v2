# Tier-Aware Accounts + Auto-Building Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make First-Run Setup gather all inputs then write each config file once, auto-build `account-config.json` via discover→confirm, and add a per-account primary/secondary tier that makes secondary accounts run one weekday per week (with catch-up) in their own brief subsection.

**Architecture:** All changes are to the skill's markdown definition (`SKILL.md`, two `references/*.md` files, `README.md`) plus text-only wording in the viewer HTML. `account-config.json` gains per-account fields (`tier`, `run_day`, `supporting_slack_channel_ids`, `asana_board_name`, `gdrive_folder_id`) while preserving `account_name` and `project_gid` so the Flask webapp is untouched. A single "Resolve in-scope accounts" step at the top of each brief run computes which accounts the rest of the run processes.

**Tech Stack:** Markdown skill definition; a static HTML/JS viewer (`viewer-backend/daily-brief-viewer.html`) whose Python/Flask backend is unchanged and whose pytest suite is used only as a regression guard for the HTML text edit.

## Global Constraints

- `account-config.json` MUST keep `account_name` and `project_gid` on every account object — the webapp's `get_account_projects()` (viewer-backend/drive_store.py) reads exactly those two and ignores unknown keys. Do not rename or drop them.
- No Flask/backend changes: `app.py`, `drive_store.py`, and the webapp API are untouched. Only `daily-brief-viewer.html` text changes.
- The skill writes `account-config.json` ONLY during First-Run Setup / re-run, never during a normal brief run.
- `config.json`'s shape, the config-load step, and the Skill Sync Check are unchanged by this plan — do not touch them.
- The per-account `gdrive_folder_id` is stored only; build no brief behavior on it (YAGNI).
- Match the existing SKILL.md prose voice (peer-level, direct); keep the file readable — it's read in full on every trigger.
- Do NOT add a `Co-Authored-By` trailer to commits. Do NOT modify the frontmatter `description` (it is at its 1024-char budget).

---

## account-config.json canonical shape

Every task that references account fields uses exactly these names:

```json
{
  "accounts": [
    {
      "account_name": "Bank of America",
      "tier": "primary",
      "run_day": null,
      "slack_channel_id": "C0395GFC4PR",
      "supporting_slack_channel_ids": ["C0XXXXXXX"],
      "project_gid": "111222333",
      "asana_board_name": "Bank of America",
      "gdrive_folder_id": "1AbCdEf..."
    }
  ],
  "internal_project_gid": "444555666"
}
```

Semantics: `tier` is `"primary"`|`"secondary"`; `run_day` is a weekday name (`"Monday"`…`"Sunday"`) for secondary accounts and `null` for primary; `slack_channel_id` is the main channel; `supporting_slack_channel_ids` is an array (may be empty); `project_gid` is the resolved Asana board GID (required for the webapp); `asana_board_name` is the human-facing board name; `gdrive_folder_id` is the account docs folder ID or `null`.

## In-scope resolution rule (used verbatim in Tasks 3 and 5)

Today's weekday and "start of week" are in the user's local timezone (already resolved by SKILL.md's Timezone Resolution step). Week starts Monday 00:00 local.

- Every `primary` account is in scope.
- A `secondary` account is in scope if **its `run_day` equals today's weekday**, OR (catch-up) **the weekday `run_day` falls on-or-before today within the current week AND the account has not run this week.** "Has not run this week" = its `customer_updates[account_name].generated_at` in the status-update cache is missing or earlier than this week's Monday 00:00 local.
- A `secondary` account that is not in scope is omitted entirely from the brief.

---

### Task 1: Update account-config.json shape and section in item-sync.md

Establish the canonical shape and semantics in the reference file that documents it, and change the wording from "hand-maintained" to "built by setup."

**Files:**
- Modify: `references/item-sync.md` (the `## Account/Asana project config` section)

**Interfaces:**
- Produces: the canonical `account-config.json` shape + field semantics that Tasks 2–6 reference.

- [ ] **Step 1: Update the "two hand-relevant files" paragraph.** In `references/item-sync.md`, in the paragraph beginning "The `/config` folder inside `BRIEF_DATA_FOLDER_ID` holds two hand-relevant files", replace the clause `and \`account-config.json\` (below, hand-maintained)` with `and \`account-config.json\` (below, built and updated by the First-Run Setup flow)`.

- [ ] **Step 2: Replace the shape block and trailing paragraph.** Replace the shape code block and the paragraph that begins "You maintain this file by hand" with:

````markdown
```json
{
  "accounts": [
    {
      "account_name": "Bank of America",
      "tier": "primary",
      "run_day": null,
      "slack_channel_id": "C0395GFC4PR",
      "supporting_slack_channel_ids": ["C0XXXXXXX"],
      "project_gid": "111222333",
      "asana_board_name": "Bank of America",
      "gdrive_folder_id": "1AbCdEf..."
    },
    {
      "account_name": "Acme Financial",
      "tier": "secondary",
      "run_day": "Wednesday",
      "slack_channel_id": "C0YYYYYYY",
      "supporting_slack_channel_ids": [],
      "project_gid": "222333444",
      "asana_board_name": "Acme Financial",
      "gdrive_folder_id": null
    }
  ],
  "internal_project_gid": "444555666"
}
```

Field semantics: `tier` is `primary` or `secondary`. `run_day` is a weekday name (`Monday`…`Sunday`) for secondary accounts, `null` for primary. `slack_channel_id` is the account's main Slack channel; `supporting_slack_channel_ids` lists additional channels to include in that account's Slack pull (may be empty). `project_gid` is the Asana board's GID (required — the webapp reads it); `asana_board_name` is the human-facing board name the setup flow resolves to that GID. `gdrive_folder_id` is the account's docs folder ID or `null` (stored only; the brief does not act on it yet).

The First-Run Setup flow builds and updates this file (discover → confirm — see `SKILL.md`). The skill reads it on every run but never writes it during a normal brief. The hosted webapp also reads it directly (its own Drive access) to poll Asana live for Overdue/Due Next 7 Days/No Due Date — it uses only `account_name` and `project_gid` and ignores the other keys, so those two keys must always be present. There is no `daily_brief_sync_account_projects`-equivalent call in v2; that entire sync step is gone.
````

- [ ] **Step 3: Verify.**

Run: `sed -n '/## Account\/Asana project config/,/### Sections, in order/p' references/item-sync.md`
Expected: shows the new multi-field shape (with `tier`, `run_day`, `supporting_slack_channel_ids`, `asana_board_name`, `gdrive_folder_id`), the field-semantics paragraph, and the "built and updated by the First-Run Setup flow" wording; no "hand-maintained" / "maintain this file by hand" text remains in the section.

Run: `grep -n "hand-maintained\|maintain this file by hand" references/item-sync.md`
Expected: no matches.

- [ ] **Step 4: Commit.**

```bash
git add references/item-sync.md
git commit -m "Document tier-aware account-config.json shape, built by setup"
```

---

### Task 2: Restructure First-Run Setup into gather → build-accounts → write-once

Rewrite `## First-Run Setup` in `SKILL.md` so it collects every global input and the full account list before writing anything, then writes `config.json` and `account-config.json` once each.

**Files:**
- Modify: `SKILL.md` (the entire `## First-Run Setup` section)

**Interfaces:**
- Consumes: the canonical `account-config.json` shape (Task 1); `config.json` keys (unchanged from prior work: `brief_data_folder_id`, `meeting_run_log_sheet_id`, `recurring_activities_project_gid`, `status_update_cache_file_id`, `slack_user_id`, `key_contacts`, `sync_state`).
- Produces: the three-phase setup that later tasks reference for "how account-config.json comes to exist."

- [ ] **Step 1: Read the current section.** Read `SKILL.md` and locate the `## First-Run Setup` section (from its heading through the `**Re-running setup**` paragraph, ending at the `---` before `## Skill Sync Check`).

- [ ] **Step 2: Replace the whole section** with:

````markdown
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
````

- [ ] **Step 3: Verify.**

Run: `sed -n '/## First-Run Setup/,/## Skill Sync Check/p' SKILL.md`
Expected: shows the three phases (A — Gather, B — Build the account list, C — Write once), the "gathers everything before writing anything" framing, and both files created via a single `create_file` each in Phase C.

Run: `grep -n "account-config.json\|Phase A\|Phase B\|Phase C" SKILL.md`
Expected: the First-Run Setup section references building `account-config.json` and the three phases.

- [ ] **Step 4: Commit.**

```bash
git add SKILL.md
git commit -m "Restructure First-Run Setup: gather-all then write both configs once"
```

---

### Task 3: Add the "Resolve in-scope accounts" step to the run start

Add a step near the top of a brief run that computes which accounts the rest of the run processes, honoring tier + run-day + catch-up.

**Files:**
- Modify: `SKILL.md` (add a `## Resolve In-Scope Accounts` section after the Timing Logic section and before `## Data Sources and What to Pull`)

**Interfaces:**
- Consumes: `account-config.json` (`tier`, `run_day`); the status-update cache `generated_at` per account (`references/status-updates.md`); the local timezone from Timezone Resolution.
- Produces: the "in-scope accounts" set + the primary/secondary split that Tasks 4 and 5 reference.

- [ ] **Step 1: Read the current SKILL.md** and locate the end of the `## Timing Logic` section and the start of `## Data Sources and What to Pull`.

- [ ] **Step 2: Insert a new section** between them:

````markdown
## Resolve In-Scope Accounts

Before pulling data, read `/config/account-config.json` and compute which accounts this run processes. Today's weekday and the start of the current week are in the user's local timezone (from Timezone Resolution above); the week starts Monday 00:00 local.

- Every `primary` account is in scope.
- A `secondary` account is in scope if its `run_day` equals today's weekday, OR (catch-up) its `run_day` falls on-or-before today within the current week AND it has not run this week. "Has not run this week" means its `customer_updates[account_name].generated_at` in the status-update cache (`STATUS_UPDATE_CACHE_FILE_ID`) is missing or earlier than this week's Monday 00:00 local.
- A `secondary` account that is not in scope is omitted entirely from this run — no recap entry, no Customer Update card, no Slack pull.

Carry two groups forward: **primary in-scope** and **secondary in-scope**. Every later step that iterates accounts (the account/initiative recap, the Slack pull, Sections 3/4) uses these groups, not the raw file. If reading `account-config.json` fails, note it under Unavailable Sources and treat the account list as empty rather than blocking the brief.
````

- [ ] **Step 3: Verify.**

Run: `grep -n "## Resolve In-Scope Accounts\|catch-up\|secondary in-scope" SKILL.md`
Expected: the new section heading and the catch-up / in-scope wording appear, located before `## Data Sources and What to Pull`.

- [ ] **Step 4: Commit.**

```bash
git add SKILL.md
git commit -m "Add Resolve In-Scope Accounts step (tier + run-day + catch-up)"
```

---

### Task 4: Secondary Accounts subsection + supporting Slack channels

Make the recap sections group in-scope secondary accounts into their own subsection, and make the Slack pull include each in-scope account's supporting channels.

**Files:**
- Modify: `SKILL.md` (the Slack data-source section; Section 1 Part B "Account / Initiative Recap"; Section 2 "Today / Tomorrow Ahead")

**Interfaces:**
- Consumes: the primary/secondary in-scope groups (Task 3); `slack_channel_id` + `supporting_slack_channel_ids` (Task 1 shape).

- [ ] **Step 1: Read the current SKILL.md** Slack data-source section and the Section 1 Part B / Section 2 headings so edits match exact bytes.

- [ ] **Step 2: Update the Slack account-channels query.** In the Slack data-source section, the item that builds the per-account channel query currently reads a single `slack_channel_id` per account from `account-config.json`. Replace its channel-source sentence so it reads (keep the surrounding "multiple `in:` modifiers / verify the first few times / fall back to per-channel" guidance intact):

```
Build a single query with one `in:<#CHANNEL_ID>` modifier per in-scope account (primary + in-scope secondary from Resolve In-Scope Accounts), including each account's `slack_channel_id` plus every ID in its `supporting_slack_channel_ids`. Never hard-code a channel list here.
```

- [ ] **Step 3: Add the Secondary Accounts subsection rule to Section 1 Part B.** In "#### Part B: Account / Initiative Recap", after the paragraph describing subsection ordering (customer accounts, then internal initiatives, then General / Admin), add:

```
In-scope secondary accounts (see Resolve In-Scope Accounts) are grouped into a dedicated "Secondary Accounts" subsection placed after the primary customer-account and internal-initiative subsections and before the General / Admin bucket. Secondary accounts that are not in scope this run do not appear at all. Primary accounts are grouped as usual above.
```

- [ ] **Step 4: Add the same scoping note to Section 2.** In "### Section 2: Today / Tomorrow Ahead", after its "organize by customer account or internal initiative" line, add:

```
Only in-scope accounts appear (all primary, plus secondary accounts scheduled or caught-up for today per Resolve In-Scope Accounts); in-scope secondary accounts go in the same "Secondary Accounts" subsection used in Section 1.
```

- [ ] **Step 5: Verify.**

Run: `grep -n "Secondary Accounts\|supporting_slack_channel_ids\|in-scope" SKILL.md`
Expected: the Slack query references `supporting_slack_channel_ids` and in-scope accounts; both Section 1 Part B and Section 2 reference the "Secondary Accounts" subsection.

- [ ] **Step 6: Commit.**

```bash
git add SKILL.md
git commit -m "Group in-scope secondary accounts in own subsection; add supporting Slack channels"
```

---

### Task 5: Section 3 honors tier (in-scope accounts only)

Update the Customer Updates section so it generates a card per in-scope account instead of every account in the file.

**Files:**
- Modify: `references/status-updates.md` (Section 3 opening paragraph; a note in the generation gate)

**Interfaces:**
- Consumes: the in-scope groups (Task 3).

- [ ] **Step 1: Update the Section 3 opening.** In `references/status-updates.md`, in the paragraph under `## Section 3: Customer Updates` that begins "One collapsible card per customer account on your assigned list — every account listed in `/config/account-config.json`", replace "every account listed in `/config/account-config.json`" with "every in-scope account (all primary accounts plus any in-scope secondary accounts — see the Resolve In-Scope Accounts step in `SKILL.md`)". Leave the rest of the paragraph (read the list fresh, generate a card even with no activity, ordering) intact.

- [ ] **Step 2: Add a tier note to the generation gate.** In the `## Generation gate` list, after item 6 ("New account not yet in the cache file"), add:

```
7. **Tier / scope:** generate cards only for in-scope accounts (Resolve In-Scope Accounts in `SKILL.md`). Primary accounts follow the daily gate above. A secondary account is only reached on a run where it is in scope (its run-day or a catch-up); on that run the same per-account `generated_at`-vs-today gate applies, so it generates at most once on its weekly run day. Off-day secondary accounts produce no card.
```

- [ ] **Step 3: Verify.**

Run: `grep -n "in-scope\|Tier / scope\|Resolve In-Scope" references/status-updates.md`
Expected: the Section 3 opening references in-scope accounts and the gate has the new tier/scope item.

- [ ] **Step 4: Commit.**

```bash
git add references/status-updates.md
git commit -m "Section 3 generates cards for in-scope accounts only (tier-aware)"
```

---

### Task 6: Update README for auto-built account-config.json + tiers

Reflect that setup builds `account-config.json` and document the new fields and tier behavior.

**Files:**
- Modify: `README.md` (the `account-config.json` line ~92; the "What it does" status-summary bullet if it implies every account daily)

**Interfaces:**
- Consumes: the shape (Task 1) and tier behavior (Tasks 3–5).

- [ ] **Step 1: Replace the account-config.json line.** Replace the sentence at README ~line 92 that begins "`sync_state` is maintained automatically by the Skill Sync Check. `account-config.json` (the account → Slack channel → Asana project mapping) remains a separate hand-maintained file" with:

```
`sync_state` is maintained automatically by the Skill Sync Check. `account-config.json` is a separate file in the same `/config` folder holding the per-account mapping (name, tier, run day, main + supporting Slack channels, Asana board, docs folder); the First-Run Setup flow builds and updates it for you (discover → confirm) — see `references/item-sync.md`. Accounts are tiered: primary accounts run every day; secondary accounts run one configured weekday per week (with catch-up if a run day is missed) and appear in their own brief subsection, hidden on other days.
```

- [ ] **Step 2: Verify.**

Run: `grep -n "hand-maintained\|tier\|secondary accounts run" README.md`
Expected: no "hand-maintained" remains for account-config.json; the tier behavior sentence is present.

- [ ] **Step 3: Commit.**

```bash
git add README.md
git commit -m "README: setup builds account-config.json; document account tiers"
```

---

### Task 7: Update the webapp walkthrough wording (text only)

Step 4 of the viewer walkthrough tells users to hand-maintain `account-config.json`; change it to say setup builds it. Confirm the pytest suite still passes.

**Files:**
- Modify: `viewer-backend/daily-brief-viewer.html` (the `data-step="4"` account-config bullet, ~line 223)
- Test: `viewer-backend/tests/` (existing suite, run as-is)

**Interfaces:**
- Consumes: the setup behavior (Task 2).

- [ ] **Step 1: Replace the account-config bullet.** In the `data-step="4"` block, replace the `<li>` that begins "A `/config/account-config.json` file inside your Drive folder from step 1 — account name, Slack channel ID, and Asana project GID per account. See the skill repo's `references/item-sync.md` for the exact shape; you maintain this by hand as accounts are added or changed" with:

```html
          <li>Your <code>/config/account-config.json</code> — the per-account mapping (name, tier, run day, Slack channels, Asana board, docs folder). You don't hand-build this: <code>/daily-brief setup</code> discovers your accounts and details, then asks you to confirm and fill gaps. See the skill repo's <code>references/item-sync.md</code> for the shape</li>
```

- [ ] **Step 2: Verify the wording changed.**

Run: `grep -n "you maintain this by hand\|discovers your accounts" viewer-backend/daily-brief-viewer.html`
Expected: no "you maintain this by hand"; the "discovers your accounts" wording is present.

- [ ] **Step 3: Run the pytest suite as a regression guard.**

Run: `cd viewer-backend && python -m pytest -q`
Expected: all tests pass (a text-only HTML edit must not change the suite result).

- [ ] **Step 4: Commit.**

```bash
git add viewer-backend/daily-brief-viewer.html
git commit -m "Walkthrough: account-config.json is built by setup, not hand-maintained"
```

---

## Notes for the implementer

- Tasks 2, 3, 4 all edit `SKILL.md` and are ordered by dependency (Task 3 defines "in-scope" which Task 4 consumes). Do them in order; Read the current `SKILL.md` before each since earlier tasks changed it.
- There are no unit tests for the skill markdown — verification for Tasks 1–6 is the `grep`/`sed` checks shown plus reading the changed section for flow and voice. Task 7 is the only one with an executable test (the existing pytest suite, confirming the HTML text edit didn't break the app).
- Do not touch `config.json`, the config-load step, the Skill Sync Check, or the frontmatter `description`.
