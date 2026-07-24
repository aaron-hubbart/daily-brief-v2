# Design: tier-aware accounts + auto-building setup

Date: 2026-07-24
Status: Approved (pending spec review)

## Problem

Two rough edges remain after the single-config-file change:

1. The `## First-Run Setup` flow creates `config.json` first (as a near-empty
   stub) and then writes each value into it one at a time — several Drive writes
   for one logical setup.
2. `account-config.json` is still hand-built. Adding or changing an account means
   editing raw JSON by hand, and the file carries no notion of which accounts are
   worked daily vs. occasionally.

## Goal

- Make setup **gather all inputs first, then write each config file once.**
- Have setup **auto-build `account-config.json`** by discovering accounts and
  their details, then asking the user to confirm and fill gaps — no hand-editing.
- Introduce a per-account **primary/secondary tier** that changes brief behavior:
  primary accounts run every day; secondary accounts run one configured weekday
  per week (with catch-up) and appear in their own subsection, hidden otherwise.

## Decisions (from brainstorming)

- **Tier effect:** primary = daily; secondary = once per week on a
  **per-account fixed weekday**, segregated into its own "Secondary Accounts"
  subsection, and **hidden entirely on non-run days**.
- **Missed run day:** **catch up** — if a secondary account's `run_day` has
  already passed in the current week (Mon–Sun) and it has not run this week, run
  it on the next brief.
- **Per-account gdrive folder:** a customer/account docs folder — **stored only**
  for now (no brief behavior wired to it yet).
- **Account discovery seed:** the existing `account-config.json`, plus additions
  proposed from Slack account channels and Asana projects. (Future: a per-person
  account-assignment CSV becomes the seed; the discovery step is structured so
  that slots in without reshaping the flow.)
- **Setup writes both files once**, at the end, after the user confirms.

## Design

### 1. Setup: gather-then-write-once

`## First-Run Setup` in `SKILL.md` is restructured into three phases:

- **Phase A — Gather globals.** Collect every global input up front, holding them
  in the conversation (not written yet): brief-data Drive folder ID (still the
  first thing asked, since both config files live inside it), meeting run-log
  sheet ID, recurring-activities project GID, status-update cache file ID
  (offering to create an empty cache file if absent), Slack user ID, key contacts.
- **Phase B — Build accounts** (section 3 below). Produces the confirmed account
  list held in the conversation.
- **Phase C — Write once.** After the user confirms everything, create
  `/config/config.json` with all global values and a fresh `sync_state: {}` in a
  single `create_file`, and create `/config/account-config.json` with the full
  confirmed account list in a single `create_file`. Then report the new
  `config.json` Drive file ID and instruct the user to paste it into
  `CONFIG_FILE_ID` in their local `SKILL.md` (the only manual edit).

**Re-running setup** loads both existing files first, uses them as the starting
point, re-proposes/confirms, and writes a fresh version of each — never a
per-key incremental write.

The `config.json` shape and the config-load / Skill Sync Check behavior are
unchanged from the single-config-file change.

### 2. account-config.json shape

Each account object gains fields; `account_name` and `project_gid` are preserved
because the webapp's `get_account_projects()` (viewer-backend/drive_store.py)
reads exactly those two and ignores unknown keys — so this is backward
compatible and the webapp needs no change.

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

Field semantics:
- `tier` — `"primary"` or `"secondary"`.
- `run_day` — weekday name (`"Monday"`…`"Sunday"`) for secondary accounts;
  `null` for primary.
- `slack_channel_id` — the account's main Slack channel (unchanged meaning).
- `supporting_slack_channel_ids` — array of additional channel IDs to include in
  that account's Slack pull; may be empty.
- `project_gid` — the Asana board's GID (still required for the webapp);
  resolved by the skill from `asana_board_name` during setup.
- `asana_board_name` — human-facing board name the user supplies/confirms.
- `gdrive_folder_id` — the account's docs folder ID, or `null`; stored only, no
  brief behavior yet.

### 3. Auto-build accounts (discover → confirm)

During Phase B, the skill:
1. **Seeds** the account list from the existing `account-config.json` (if any).
2. **Proposes additions** it finds by scanning the user's Slack account channels
   and Asana projects for names that look like customer accounts not already in
   the list.
3. **Drafts each account's details by name-search:** the Slack channel(s) whose
   name matches the account, the Asana board matching the name (resolved to a
   `project_gid`), and a Drive folder matching the name for `gdrive_folder_id`.
4. **Presents the full draft** and asks the user to confirm, correct, and fill
   gaps. `tier` and `run_day` are always confirmed explicitly with the user
   because they are not discoverable; any detail the skill could not resolve is
   shown as blank for the user to supply.

The confirmed list is held for Phase C's single write. Nothing about discovery
writes to Drive until Phase C.

### 4. Tier-aware brief behavior

A single **"Resolve in-scope accounts"** step runs at the very start of every
brief, before data pulls, and produces the set of accounts the rest of the run
iterates:

- Every `primary` account is always in scope.
- A `secondary` account is in scope when **its `run_day` equals today's weekday**,
  OR (catch-up) **its `run_day` has already passed in the current week (Mon–Sun)
  and it has not yet run this week.** "Has run this week" is determined from the
  account's last-generation timestamp in the existing Section 3/4 status-update
  cache (compared against the start of the current week in the user's local
  timezone).
- Any `secondary` account not in scope is omitted entirely from the brief.

Downstream:
- **Sections 1 & 2 (recap / ahead):** in-scope secondary accounts are grouped
  into a dedicated **"Secondary Accounts"** subsection (after the primary
  account/initiative subsections, before General/Admin). Primary accounts are
  grouped as today.
- **Section 3 (Customer Updates):** a card is generated for each primary account
  (daily cache, unchanged) and for each in-scope secondary account. Off-day
  secondary accounts get no card.
- **Slack pull:** for each in-scope account, the multi-`in:` query includes its
  `slack_channel_id` plus every ID in `supporting_slack_channel_ids`.
- **Section 4 (Manager Update):** unchanged (daily).

### 5. Scope & constraints

- **Webapp untouched.** `account_name` + `project_gid` keys are preserved; the
  webapp remains tier-agnostic for its live Asana task polling (it may show tasks
  for secondary accounts on any day — that is acceptable and out of scope).
- The skill writes `account-config.json` only during setup / re-run, never during
  a normal brief.
- `config.json` shape, the config-load step, and the Skill Sync Check are
  unchanged from the prior change.
- The per-account docs folder is stored only; no linking or search behavior is
  built now (YAGNI).

## Out of scope

- Any webapp/backend change.
- Consuming a per-person assignment CSV (future; discovery is structured to allow
  it later, but no CSV parsing is built now).
- Any use of `gdrive_folder_id` in brief output.
- Changes to Section 4, the sync machinery, or `config.json`'s shape.

## Files touched

- `SKILL.md` — restructure `## First-Run Setup` into gather → build-accounts →
  write-once; add the "Resolve in-scope accounts" step to the run start; update
  the account/initiative recap (Sections 1/2) to add the Secondary Accounts
  subsection and honor scope; update the Slack pull to include supporting
  channels for in-scope accounts.
- `references/item-sync.md` — update the `account-config.json` shape block and
  the Account/Asana project config section for the new fields; note that setup
  now builds this file (still not written during normal briefs).
- `references/status-updates.md` — Section 3 gating honors tier: primary daily,
  secondary only when in scope (run-day / catch-up), and the cache read that
  determines "has run this week."
- `README.md` — reflect that setup auto-builds `account-config.json` and the new
  per-account fields / tier behavior.
- `viewer-backend/daily-brief-viewer.html` — walkthrough wording: step 4 no
  longer tells the user to hand-maintain `account-config.json`; setup builds it.
  (Text only; no backend change.)
