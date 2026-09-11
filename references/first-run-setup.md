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

## Phase 1: Minimal Configuration

Ask for exactly two values, one at a time:

1. **Drive folder ID** — "Where should I save your briefs? Paste the ID
   from your Drive folder's URL (the part after `folders/`)." If the user
   doesn't have one yet, tell them to create an empty Drive folder first.
2. **Slack user ID** — "What's your Slack user ID? (Format `UXXXXXXXXXX`
   — find it in your Slack profile under 'Copy member ID'.)"

Hold both values in the conversation. Do not write anything to Drive yet.

## Phase 2: Automated Discovery

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
"Bank of America" should match `#boa-main`). If multiple channels match
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
strong candidate is found, propose it as `internal_project_gid`. If
multiple candidates are found, list them and ask the user to pick one in
Phase 3. If none are found, leave it blank — the user can paste a GID
directly in Phase 3.

**Confidence ranking.** Sort the candidate account list for Phase 3
presentation: accounts with both a Slack channel AND an Asana project
first (high confidence), then accounts with only one of the two (medium),
then email-seeded-only accounts with neither (low). This ordering is
presentation only — every candidate is still shown, none are dropped for
low confidence.

## Phase 3: User Confirmation & Edit

Present the full discovered list in chat as a reviewable table, grouped
by confidence tier, something like:

```
DISCOVERED ACCOUNTS — Review & Confirm

High confidence:
1. [x] Bank of America — Slack: #boa-main, #boa-support | Asana: Bank of America Engagement (123456)
2. [x] JPMorgan Chase — Slack: #jpmc | Asana: JPMC Banking Platform (789012)

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
   `brief_data_folder_id`, `slack_user_id`, `key_contacts`, and empty-string
   placeholders for `meeting_run_log_sheet_id`,
   `recurring_activities_project_gid`, `status_update_cache_file_id` (the
   user can fill these in later, or by re-running setup — see
   `references/item-sync.md` for what these three unlock and how they're
   used).
2. Create `/config/account-config.json` via `Google Drive: create_file`
   with the confirmed `accounts` array and top-level `internal_project_gid`
   — exact field names per `references/item-sync.md`: `account_name`,
   `tier`, `run_day`, `slack_channel_id`, `supporting_slack_channel_ids`,
   `project_gid`, `asana_board_name`, `gdrive_folder_id` (set `null` for
   anything not resolved).
3. Run the Folder Existence Check (see `SKILL.md`) to create `/briefs`,
   `/config`, `/state` under the brief-data folder if they don't already
   exist.
4. Report the new `config.json` file ID and tell the user to paste it
   into `CONFIG_FILE_ID` at the top of their local `SKILL.md` — this is
   the only manual edit.

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
