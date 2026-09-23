# First-Run Setup & Account Finder

Full detail for the setup flow referenced from `SKILL.md`'s "First-Run
Setup" section. Read this file only when that flow triggers — it is not
needed on a normal brief run.

Runs when the user explicitly asks (`/daily-brief setup`, "set up daily
brief", etc.), and is auto-offered whenever a normal run finds
`CONFIG_FILE_ID` still set to the placeholder. The same discovery engine
(Phase 2 below) also powers the on-demand "find new accounts" flow
(see "On-Demand: Find New Accounts" at the end of this file), triggered
by "find new accounts", "scan for customers", or similar phrasing outside
of full setup.

Setup is **minimal → discovery → confirmation**: gather only the two
essentials up front, auto-discover everything else, then let the user
review and edit before anything is written to Drive.

## Phase 0: Connector Pre-Flight Check

Before asking anything, check which connectors are currently active: Google
Drive, Microsoft 365 / Outlook, Slack, Zoom, and Asana (e.g. via each
connector's own lightweight list/search call, or however connector status
is otherwise exposed in the current environment).

Report the result to the user as a short list of connected vs. missing
connectors.

- **Google Drive is required.** If it isn't connected, stop here — do not
  proceed to Phase 1. Ask the user to connect the Google Drive connector
  first, then restart setup.
- **Microsoft 365 / Outlook, Slack, Zoom, and Asana are recommended, not
  required.** If any are missing, note which ones and that the
  corresponding parts of the brief (calendar/email, Slack signals, Zoom
  transcripts, Asana tasks) won't work until connected — but continue
  with setup regardless.

## Phase 1: Minimal Configuration

Ask for exactly five values, one at a time:

1. **Drive folder ID** — "Where should I save your briefs? Paste the ID
   from your Drive folder's URL (the part after `folders/`)." If the user
   doesn't have one yet, tell them to create an empty Drive folder first.
2. **Slack user ID** — "What's your Slack user ID? (Format `UXXXXXXXXXX`
   — find it in your Slack profile under 'Copy member ID'.)"
3. **Geekbot channel/DM ID** — "What Slack channel or DM do you post your
   daily standup to (e.g. Geekbot's prompt)? Paste its ID — right-click
   the channel/DM in Slack → 'Copy link', and the ID is the last path
   segment (`C...`/`D...`/`G...`). Respond 'skip' if not applicable." This
   powers the Today section's Team Standup card's "Post to Slack" button
   (`geekbot_channel_id`). If the user responds "skip", leave it blank —
   the card still generates, just without a working post button.
4. **Manager DM ID** — "What's your manager's Slack DM ID, for posting
   your weekly/manager update? Respond 'skip' if not applicable." Same ID
   format and lookup method as above (`manager_channel_id`). If the user
   responds "skip", leave it blank.
5. **Slack completion notification (optional)** — "Want a Slack DM when
   each day's brief finishes running? If so, paste the DM channel ID to
   send it to (same ID format as above — right-click your own DM →
   'Copy link'). Respond 'skip' if not applicable." If the user gives a
   channel ID, capture it for `slack_notify.channel_id` and set
   `slack_notify.enabled: true`. If the user responds "skip", leave
   `slack_notify` unset.

Hold all five values in the conversation. Do not write anything to Drive yet.

## Phase 2: Automated Discovery

Before running the discovery passes below, ask: **"Do you manage customer
accounts, or would you prefer to track internal initiatives and
projects?"**

- **Customer accounts (default).** Proceed with the discovery passes
  below as written; every entry gets `account_type: "customer"`.
- **Internal initiatives/projects.** If the user says they don't manage
  customer accounts, identifies as an internal-facing role, or otherwise
  opts for this — run the same discovery passes below, but talk about
  the results as initiatives/projects rather than customers, and set
  `account_type: "initiative"` on every entry. Structurally nothing else
  changes: an initiative still gets a Slack channel, an Asana project, a
  tier/run_day, etc. the same way a customer account does — only the
  `account_type` field and the label used in conversation and in the
  brief differ.
- A user can mix both in the same setup (some entries `customer`, others
  `initiative`) if they say so during Phase 3 confirmation.

Run this automatically, without asking the user to confirm each pass —
show all results together at the end of Phase 2, then move to Phase 3.

**Pass 1 — Email seed.** Use `Microsoft 365: outlook_email_search` over
the last 30 days, look at the 50 most recent unique sender
organizations. Extract likely account/company names from sender domains
and email subjects (e.g. a sender at `@acmecorp.com` with subject lines
mentioning "Acme" suggests account name "Acme Corp"). Build a candidate
account-name list. If this pass fails or the connector errors, note it
and continue with an empty candidate list — the remaining passes can
still contribute matches for a smaller manually-typed list, or you can
proceed to Phase 3 with zero candidates and let the user type names.

**Pass 2 — Slack channel match.** For each candidate account name, use
the Slack connector's channel search (`Slack: slack_search_channels` or
equivalent) to find channels whose name contains the candidate name
(case-insensitive substring match, ignoring spaces/punctuation — e.g.
"Acme Financial" should match `#acme-financial-main`). If multiple channels match
one account, treat the shortest/most-exact-match name as the primary
channel and the rest as `supporting_slack_channel_ids`. If this pass
fails or errors, note it and continue — accounts simply carry no Slack
channel yet, editable in Phase 3.

**Pass 3 — Asana project match.** For each candidate account name, use
`Asana: search` or equivalent to find projects whose name contains the
candidate name. If exactly one matches, link it (`project_gid`,
`asana_board_name`). If multiple match, flag as ambiguous — surface all
matches to the user in Phase 3 and let them pick. If none match, leave
`project_gid` blank — editable in Phase 3. If this pass fails or errors,
note it and continue.

**Pass 4 — Internal board detection.** Search Asana for projects whose
name suggests an internal/non-customer board — look for names containing
"Internal", "Admin", "Team", "General", or "Recurring". If exactly one
strong candidate is found, propose it as `internal_project_gid` (with its
name as `internal_project_name`). If multiple candidates are found, list
them and ask the user to pick one in Phase 3. If none are found, leave it
blank — the user can paste a GID (and name) directly in Phase 3.

**Confidence ranking.** Sort the candidate account list for Phase 3
presentation: accounts with both a Slack channel AND an Asana project
first (high confidence), then accounts with only one of the two (medium),
then email-seeded-only accounts with neither (low). This ordering is
presentation only — every candidate is still shown, none are dropped for
low confidence.

## Phase 3: User Confirmation & Edit

Present the full discovered list in chat as a reviewable table, grouped
by confidence tier, something like (entries answered as initiatives in
Phase 2 are labeled as initiatives here and everywhere else in the
conversation, but use the same Slack/Asana columns and confirmation flow
as customer accounts):

```
DISCOVERED ACCOUNTS — Review & Confirm

High confidence:
1. [x] Acme Financial — Slack: #acme-financial-main, #acme-financial-support | Asana: Acme Financial Engagement (123456)
2. [x] Zebra Financial — Slack: #zebra-financial | Asana: Zebra Financial Banking Platform (789012)

Medium confidence:
3. [x] Acme Corp — Slack: #acme-internal | Asana: (none found — reply with a project name/GID to link one)

Low confidence:
4. [ ] Foo Industries — Slack: (none found) | Asana: Foo Corp - Legacy (555666)

Internal board: Internal Tasks & Recurring (999888) — confirm or reply with a different project?

Key contacts: (reply with names, comma-separated, e.g. "Alice Smith, Bob Chen")
```

Ask the user to reply with corrections: which numbers to exclude, tier
(primary/secondary — and if secondary, which weekday) for each account
they're keeping, any account name corrections, and manually-supplied
Slack channels or Asana projects for gaps. Default every account to
`tier: primary` unless the user says otherwise. Keep iterating on this
single message/reply exchange until the user says the list is correct —
do not write anything to Drive until they explicitly confirm.

## Phase 4: Write & Hand-Off

Once the user confirms:

1. Create `/config/config.json` via `Google Drive: create_file` with:
   `brief_data_folder_id`, `slack_user_id`, `key_contacts`,
   `geekbot_channel_id` and `manager_channel_id` (from Phase 1, either as
   entered or blank if the user skipped them), `slack_notify` (from
   Phase 1 question 5 — `{"enabled": true, "channel_id": "..."}` if the
   user opted in, otherwise omit it or write `{"enabled": false}`), and
   empty-string placeholders for `meeting_run_log_sheet_id`,
   `recurring_activities_project_gid`, `status_update_cache_file_id` (the
   user can fill these in later, or by re-running setup — see
   `references/item-sync.md` for what these three unlock and how they're
   used).
2. Create `/config/account-config.json` via `Google Drive: create_file`
   with the confirmed `accounts` array and top-level `internal_project_gid`
   plus `internal_project_name` (the human-readable name of that internal
   board) — exact field names per `references/item-sync.md`: `account_name`,
   `account_type` (`"customer"` default, or `"initiative"` — from Phase 2's
   branching question), `tier`, `run_day`, `slack_channel_id`,
   `slack_channel_name` (the human-readable Slack channel name, alongside
   the ID),
   `supporting_slack_channel_ids`, `project_gid`, `asana_board_name`,
   `default_section_name` (leave `""` if not provided — see below),
   `gdrive_folder_id` (set `null` for anything not resolved). Also write
   top-level `internal_default_section_name` (`""` if not provided),
   paired with `internal_project_gid` the same way `default_section_name`
   pairs with each account's `project_gid`.

   Setup doesn't need to ask for `default_section_name`/
   `internal_default_section_name` as a Phase 1/3 question — leave them
   blank on initial write and point the user at the Manage Customers page
   (`viewer/webapp/templates/customers.html`) to fill in the section name
   per account (and the internal board) once they know which Asana
   section their team triages from. If the user volunteers a section name
   unprompted during Phase 3 confirmation, capture it then instead of
   leaving it blank.
3. Announce what you're doing before creating anything — e.g. "Creating
   your Daily Briefs folder structure in Google Drive..." — then run the
   Folder Existence Check (see `SKILL.md`) to create `/briefs`, `/config`,
   `/state` under the brief-data folder if they don't already exist.
   Confirm when it's done (e.g. "Folder structure created.").
4. Store `CONFIG_FILE_ID` (the new `config.json` file's ID) in the
   user's Claude project instructions automatically — this is the value
   `SKILL.md`'s Admin Config resolution rule reads with precedence over
   the `SKILL.md` placeholder. If the current environment provides no way
   to write project instructions directly, instead announce the exact
   line clearly in chat for the user to paste into their project
   instructions themselves, e.g.:

   ```
   CONFIG_FILE_ID: 1AbCdEfGhIjKlMnOpQrStUvWxYz
   ```

   Never tell the user to edit `SKILL.md` — it's shared/committed and
   should keep the placeholder.
5. If the user opted into Slack completion notifications in Phase 1
   (question 5), confirm `slack_notify.enabled: true` and
   `slack_notify.channel_id` were written into `config.json`. If they
   didn't opt in during Phase 1 but ask about it later (or during a
   re-run), ask for their Slack DM channel ID and add `slack_notify` to
   `config.json` then — see `SKILL.md`'s "Run-Complete Slack
   Notification" section for how it's used at brief time.

## Phase 5: Schedule Automated Runs

After everything is configured, offer to set up a recurring schedule so
the brief runs automatically without the user having to type "daily
brief" each time.

### Step 1 — Choose a schedule

Ask the user when they want their brief generated. Common choices:

- **Weekday mornings** (e.g. 6:00 AM local time, Mon–Fri):
  cron expression `0 6 * * 1-5`
- **Every morning including weekends**: `0 6 * * *`
- **Twice daily** (morning + end of day): two separate scheduled tasks,
  e.g. `0 6 * * 1-5` and `0 17 * * 1-5`

If the user doesn't have a preference, recommend **weekday mornings at
6:00 AM** as the default.

### Step 2 — Create the scheduled task

Use the `create_scheduled_task` tool with:

- **taskName:** `daily-brief`
- **cronExpression:** the cron expression from Step 1
- **prompt:** a self-contained instruction that future scheduled runs can
  execute without any session context. The prompt should read roughly:

  > Run the daily-brief-v2 skill to generate today's morning brief.
  > Read SKILL.md from the daily-brief-v2 project, load config from
  > Google Drive using the CONFIG_FILE_ID in this project's instructions,
  > pull data from all connected sources (Outlook, Slack, Zoom, Asana),
  > and write the brief files to Google Drive. If any connector fails,
  > include the error in the Slack notification. This is a scheduled run,
  > not interactive — do not ask clarifying questions; use defaults and
  > proceed.

  Adapt the wording if the user has specific preferences (evening brief,
  specific accounts only, etc.), but keep it self-contained.

### Step 3 — Enable automatic approval

Scheduled runs execute without the user present. By default, Claude asks
for approval before each tool call, which blocks automated runs entirely.

Walk the user through enabling automatic approval for scheduled tasks:

1. Open **Claude desktop app → Settings → Scheduled Tasks**.
2. Set **Tool approval** to **Automatically approve** for the
   `daily-brief` task (or for all scheduled tasks, if the user prefers).

Without this step, the scheduled brief will stall on the first tool call
and never complete. This was reported as a friction point during testing,
so make it explicit: tell the user the brief will not run unattended
unless automatic approval is turned on.

### Step 4 — Confirm

Once the task is created and approval is configured, confirm with
something like:

> Your daily brief is now scheduled to run at 6:00 AM on weekdays.
> It will pull from Outlook, Slack, Zoom, and Asana, write the brief
> files to your Google Drive folder, and send you a Slack DM when it's
> done (or if something goes wrong). You can say "daily brief" any time
> to run one manually.

If the user also wants an evening/EOD brief, create a second scheduled
task with a separate name (e.g. `daily-brief-eod`) and the evening cron
expression.

## Re-running Setup

Before starting Phase 1, check whether `/config/config.json` and
`/config/account-config.json` already exist in the target Drive folder.
If neither exists, this is a first run — proceed with Phase 1 as written.

If one or both already exist, read them first and seed the flow from
their existing values instead of starting from zero:

- **Phase 1 starting point.** Use the existing `brief_data_folder_id`,
  `slack_user_id`, `geekbot_channel_id`, `manager_channel_id`, and
  `slack_notify` from `config.json` as the answers to Phase 1's five
  questions instead of re-asking them — confirm the values with the user
  ("Re-running setup — still using folder `<id>`, Slack user `<id>`,
  standup channel `<id>`, manager DM `<id>`, and completion notifications
  `<on/off>`?") rather than prompting from scratch. Only ask again if the
  user explicitly wants to change one. If `slack_notify` is missing on the
  existing config (e.g. it predates this field), ask question 5 fresh
  rather than assuming it's off. If either channel ID is blank/missing on
  the existing config (e.g. it predates this field), ask for it fresh
  rather than carrying forward a blank.
- **Phase 2/3 starting point.** Treat the existing `accounts` array (and
  `internal_project_gid` / `internal_project_name`) as the starting
  candidate list, not just something to check for duplicates against.
  Run Phase 2's discovery passes as usual to find anything new, then
  present Phase 3's confirmation table with *both* the already-configured
  accounts and the newly-discovered ones together, clearly marked which
  is which.
- **Never silently clobber hand-set fields.** Every existing account's
  current `account_type`, `tier`, `run_day`, `supporting_slack_channel_ids`,
  `default_section_name`, and `gdrive_folder_id` (and the top-level
  `internal_default_section_name`) must carry forward unchanged unless
  the user explicitly changes them during Phase 3 confirmation. A re-run's
  discovery pass not re-finding the same Slack/Asana match for an
  already-configured account is not a reason to blank out or drop fields
  that were already set — discovery only fills gaps and proposes
  additions, it never overwrites a hand-edited value on an existing
  account.
- **Phase 4 write.** When writing the fresh `account-config.json`, the
  written `accounts` array must be the merge of preserved existing
  accounts (with any user-confirmed edits from Phase 3) plus any
  newly-confirmed accounts — never just the newly-discovered set.

## On-Demand: Find New Accounts

Triggered by "find new accounts", "scan for customers", or a direct ask
to find more accounts, outside of full setup. Requires an existing valid
`CONFIG_FILE_ID` (if not set, offer full setup instead).

1. Read the current `/config/account-config.json` to know which
   `slack_channel_id`s and `project_gid`s are already in use.
2. Run Phase 2's four-pass discovery as above, but skip any candidate
   whose Slack channel or Asana project is already linked to an existing
   account.
3. Present results using the same Phase 3 table format, scoped to only
   the new candidates found.
4. On confirmation, append the newly-confirmed accounts to the existing
   `accounts` array (read-merge-rewrite — do not touch existing entries)
   and write a new version of `account-config.json` via
   `Google Drive: create_file`.
5. Confirm to the user: "Added N new accounts. They'll appear starting
   with your next brief."
