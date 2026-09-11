# Setup Flow Redesign & Account Finder Feature

Date: 2026-09-11  
Status: Design approved, ready for implementation planning  
Repo: `aaron-hubbart/daily-brief-v2`

## Problem

The current setup flow has three pain points:

1. **Too many upfront decisions** — users must gather and provide many configuration values (Drive folder ID, meeting run log sheet ID, Asana project GID, status cache file ID, Slack user ID, key contacts) before seeing any result.
2. **Lengthy account discovery loop** — three separate phases (gather globals, discover accounts, confirm) with a multi-step confirmation process that requires manual review/edit of each account.
3. **Overall complexity** — from first interaction to first brief run takes many steps and feels like high friction for new users.

Additionally, there's no easy way to discover and add new customer accounts after the initial setup. Users must either re-run the full setup or manually configure each new account.

## Solution: Smart Setup + Account Finder

**Smart Setup** reduces friction by minimizing upfront configuration, automating discovery, and batching confirmation.

**Account Finder** is a reusable discovery tool embedded in both setup and the webapp's customers tab, allowing users to scan for new accounts anytime.

## Chosen Approach: Smart Setup (Progressive, Hybrid)

### Phase 1: Minimal Configuration (2 questions)

User provides only essentials:

1. **Drive folder ID** — "Where should I save your briefs?" User copies ID from their Drive folder URL
2. **Slack user ID** — "What's your Slack user ID?" (format: `UXXXXXXXXXX`, found in Slack profile)

**Output:** Captured values; nothing written to Drive yet.

### Phase 2: Automated Discovery (synchronous)

The skill automatically scans for accounts and configuration:

**Four-pass discovery:**

1. **Email seed** — Scan Outlook email (last 30 days, 50 unique senders) for company/account names
2. **Slack match** — For each potential account, search Slack for matching channels; capture main channel + supporting channels
3. **Asana match** — For each account, search Asana for matching projects; handle ambiguities
4. **Internal board detection** — Find Asana projects with names like "Internal", "Admin", "Team", "Recurring Activities"; ask user which is the main internal board

**Output:** Ranked results (high confidence → medium → low):
- High: Both Slack channel AND Asana project found
- Medium: Only Slack or only Asana found
- Low: Email-seeded but no Slack/Asana match

### Phase 3: User Confirmation & Edit (table UI)

Present all discovered accounts in a **table/card view**:

```
DISCOVERED ACCOUNTS — Review & Confirm

☑ Bank of America
   Slack: #boa-main, #boa-support
   Asana: Project GID: 123456 (Bank of America Engagement)
   Tier: [Primary ▼] | Run Day: —
   
☑ JPMorgan Chase  
   Slack: #jpmc
   Asana: Project GID: 789012 (JPMC Banking Platform)
   Tier: [Primary ▼] | Run Day: —

☐ Acme Corp
   Slack: #acme-internal (found, but no matching Asana project)
   Asana: —
   Tier: [Secondary ▼] | Run Day: [Monday ▼]
   
   [+ Add Slack Channel] [+ Link Asana Project]

INTERNAL BOARD
   Asana: Project GID: 999888 (Internal Tasks & Recurring)

KEY CONTACTS
   [Input field: type names, comma-separated]
   Example: Alice Smith, Bob Chen, Carol Martinez
```

**User interactions:**
- ☑/☐ checkboxes: toggle which accounts to add
- Tier dropdown: Primary or Secondary (if Secondary, run_day weekday picker appears)
- `[+ Add Slack Channel]`: add supporting channels to an account
- `[+ Link Asana Project]`: link/override Asana project for an account
- Edit account name inline if discovery got it wrong
- Delete row to exclude an account
- **Key Contacts** field: comma-separated list of people whose emails/messages should be prioritized

### Phase 4: Write & Hand-Off

**On "Confirm & Setup":**

1. Write `/config/config.json` with:
   - `brief_data_folder_id`
   - `slack_user_id`
   - `key_contacts`
   - `internal_project_gid`
   - Placeholder values for: `meeting_run_log_sheet_id`, `recurring_activities_project_gid`, `status_update_cache_file_id` (user can update these later or via next setup run)

2. Write `/config/account-config.json` with:
   - All checked accounts (name, tier, run_day, Slack channels, Asana project GID)
   - `internal_project_gid`

3. Create folder structure:
   - `/briefs/` (for brief runs)
   - `/config/` (for config files)
   - `/{today's date}/` (for today's brief, if running a test brief)

4. Report the `config.json` file ID and instruct user to paste it into `CONFIG_FILE_ID` in `SKILL.md`

**This is the only manual edit required.**

---

## Account Finder: Reusable Discovery Tool

The discovery engine is a standalone, reusable component usable in two contexts:

### 1. During Setup (as described above)

### 2. Post-Setup: On-Demand Account Scanning

**In the skill** (user says "find new accounts" or "scan for customers"):
- Runs four-pass discovery
- Shows results in the same confirmation UI
- User checks which to add
- Writes new accounts to `account-config.json` (incremental append, not full rewrite)
- Confirms: "Added X new accounts. They'll appear in your next brief."

**In the webapp** (Customers tab, new "Scan for Accounts" button):
- **Scoped to Asana only.** The webapp has a stored per-user Asana PAT (already used for live action items) and Google Drive OAuth, but no Slack or Outlook access — those connectors exist only inside the skill's Claude runtime. The webapp's discovery pass therefore:
  - Searches Asana for projects not yet linked to any account in `account-config.json`
  - For each candidate project, proposes an account name (from the project name) and lets the user match it to an existing account or create a new one
  - Does NOT attempt Slack channel discovery or email-seeded account discovery — those fields stay manually editable in the same UI (already supported by the existing `customers.html` add/edit rows)
- Opens modal with discovery results (Asana matches only)
- Same table/cards UI pattern as the skill's confirmation table, minus the Slack/email columns
- User confirms selections, optionally fills in Slack channel manually
- Updates `account-config.json` via webapp's Google OAuth
- Refreshes customers list immediately

**Key design principle:** The skill (full four-pass: email, Slack, Asana, internal board) and the webapp (Asana-only) both write to the same `account-config.json` shape and both offer a "scan and confirm" UX, but they discover from different source sets because of where each one runs. A user who wants full email+Slack+Asana discovery uses the skill; the webapp is a lighter-weight, Asana-only complement for quick additions without opening Claude.

---

## Data Files & Structure

### Config Files (written to `/config/` on Drive)

**`config.json`** (global configuration — unchanged shape from today; `internal_project_gid` lives in `account-config.json`, not here, per the existing `references/item-sync.md` schema):
```json
{
  "brief_data_folder_id": "...",
  "meeting_run_log_sheet_id": "...",
  "recurring_activities_project_gid": "...",
  "status_update_cache_file_id": "...",
  "slack_user_id": "UXXXXXXXXXX",
  "key_contacts": ["Alice Smith", "Bob Chen"],
  "sync_state": { "skill_source_sha": "...", "references_source_sha": "...", "sync_check_last_run": "..." }
}
```

**`account-config.json`** (accounts + internal project):
```json
{
  "internal_project_gid": "999888",
  "internal_project_name": "Internal Tasks & Recurring",
  "accounts": [
    {
      "account_name": "Bank of America",
      "tier": "primary",
      "run_day": null,
      "slack_channel_name": "boa-main",
      "slack_channel_id": "C12345678",
      "supporting_slack_channel_ids": ["C87654321"],
      "project_gid": "123456",
      "asana_board_name": "Bank of America Engagement",
      "gdrive_folder_id": "folder_abc123"
    },
    {
      "account_name": "Acme Corp",
      "tier": "secondary",
      "run_day": "Monday",
      "slack_channel_name": "acme-internal",
      "slack_channel_id": "C22222222",
      "supporting_slack_channel_ids": [],
      "project_gid": "555666",
      "asana_board_name": "Acme - Platform Work",
      "gdrive_folder_id": "folder_xyz789"
    }
  ]
}
```

### Folder Structure

```
BRIEF_DATA_FOLDER_ID/
  /config/
    config.json
    account-config.json
  /briefs/
    (populated on each brief run; see references/item-sync.md)
  /state/
    (populated by webapp for checkbox state; see references/item-sync.md)
```

---

## Error Handling & Edge Cases

### Discovery Failures

- **Slack API unavailable:** Skip Slack match pass; show "Couldn't scan Slack channels. You can manually link them after setup."
- **Asana API unavailable:** Skip Asana match pass; proceed with email-seeded accounts only; offer manual linking.
- **Email scan fails:** Skip email seed; proceed with empty account list; user can type names manually or rely on Slack/Asana keyword search.

### Ambiguous Matches

- **Multiple Asana projects match one account name:** Show all with radio buttons; user selects the main board.
- **Multiple Slack channels match one account name:** Show all; user checks which to include (first is primary, others are supporting).
- **Multiple candidates for internal board:** Show list; user selects the correct one.

### No Matches Found

- Show: "Couldn't find any accounts. Try entering account names manually or checking Slack channel names."
- Allow user to type account names directly and skip to link-channels step.

### Duplicate Detection

- If user tries to add an account already in `account-config.json`: warn "Bank of America is already configured. Want to update its settings instead?"
- Prevent duplicate additions via the confirmation UI (pre-check before allowing a "confirm" action).

### Missing/Incomplete Config

- On brief run, if `config.json` is missing: offer to re-run setup instead of erroring.
- If `account-config.json` is missing: treat account list as empty; offer to run account discovery.
- If folder structure is incomplete: create missing folders on next brief run.

---

## User Flows

### Flow A: First-Time Setup

```
User: "set up daily brief"
↓
Skill: Asks Drive folder ID
User: Pastes ID
↓
Skill: Asks Slack user ID
User: Provides ID
↓
Skill: Runs discovery (auto, no user wait)
↓
Skill: Shows confirmed accounts table
User: Confirms/edits accounts, adds key contacts
↓
Skill: Writes config.json & account-config.json
↓
Skill: Reports config.json file ID
User: Pastes ID into SKILL.md CONFIG_FILE_ID
↓
Ready for first brief run
```

### Flow B: Add New Accounts (post-setup, in skill)

```
User: "find new accounts" or "scan for customers"
↓
Skill: Runs discovery
↓
Skill: Shows confirmation table (only new/candidate accounts)
User: Checks which to add
↓
Skill: Appends to account-config.json
Skill: Confirms "Added X accounts"
↓
Next brief run includes new accounts
```

### Flow C: Add New Accounts (post-setup, in webapp, Asana-only)

```
User: Clicks "Scan for Accounts" in Customers tab
↓
Webapp: Searches Asana (via stored PAT) for projects not yet linked
        to any account in account-config.json
↓
Webapp: Modal opens with candidate accounts (name + Asana project only;
        no Slack data — user can type a Slack channel manually)
User: Checks which to add, optionally fills in Slack channel details
↓
Webapp: Updates account-config.json via Google OAuth
Webapp: Refreshes customers list
↓
Customers tab now shows new accounts
```

---

## Testing Strategy

### Unit/Integration Tests (Skill)

- **Discovery engine:** Mock Slack, Asana, and email APIs; verify four-pass discovery produces expected results (ranked by confidence)
- **Config file write:** Verify `config.json` and `account-config.json` are written correctly with all required fields
- **Folder structure:** Verify folder creation or retrieval of existing folders works correctly
- **Conflict handling:** Test ambiguous matches (multiple projects, multiple channels); verify user is asked to disambiguate
- **Error scenarios:** Network failures, empty results, missing data; verify graceful fallback

### Unit/Integration Tests (Webapp)

- **Account discovery modal:** Render with mock discovery results; verify checkboxes, edit fields, and confirm button work
- **Config file update:** Verify webapp can read and write `account-config.json` via Google OAuth
- **Incremental append:** Verify new accounts are added without overwriting existing ones
- **Duplicate detection:** Verify adding an existing account shows a warning, not a duplicate entry

### Manual Testing (End-to-End)

- **Setup flow:** Run through complete setup (minimal → discovery → confirmation) with real Slack/Asana/email; verify config files are written correctly
- **First brief:** Run a brief after setup; verify accounts appear in the recap and forward-look sections
- **Add accounts mid-stream:** Use "find new accounts" command; verify new accounts appear in next brief
- **Webapp customers tab:** Click "Scan for Accounts"; verify modal appears with results and updates work
- **Account edits:** Edit tier, run_day, or channels for an account; verify updates persist and appear in next brief

---

## Non-Goals

- Migrating existing accounts from the old setup to this new setup (this is a clean forward cutover)
- Automating the creation of Slack channels or Asana projects (discovery links existing ones only)
- Supporting per-user account assignment or role-based filtering (all discovered accounts are presented to the user)
- Scheduling future account activations or time-boxing account scopes (setup is single-pass, accounts are persistent until manually removed)

---

## Open Questions for Implementation

1. **Email seed heuristics:** What company-name extraction rules are reliable? (e.g., domain names, "from: [Company] [Person]", email subject patterns)
2. **Slack channel matching:** Should we match on channel topic/description in addition to name? How permissive should substring matching be?
3. **Asana project matching:** Same question — name only, or description + custom fields?
4. **Duplicate account handling:** If a user adds "BofA" and "Bank of America" separately, should we warn about near-duplicates?
5. **Discovery caching:** Should discovery results be cached during setup, or always fresh on each pass?
6. **Account name normalization:** Should we normalize names (e.g., remove "the", convert to title case) to improve matching?

---

## Implementation Breakdown

### Part 1: Discovery Engine (Shared Logic)

- Email seed extraction (Outlook connector)
- Slack channel search & matching
- Asana project search & matching
- Internal board detection
- Confidence scoring & ranking

### Part 2: Skill Setup Flow

- Minimal phase (Drive folder ID, Slack user ID collection)
- Invoke discovery engine
- Present confirmation UI (table/cards with editable rows)
- Write config files to Drive
- Offer re-run on error

### Part 3: Post-Setup Account Scanning (Skill)

- Listen for "find new accounts" / "scan for customers" triggers
- Invoke discovery engine
- Present confirmation UI (filtered to new/candidate accounts only)
- Append to account-config.json

### Part 4: Webapp Integration (Asana-only discovery)

- New "Scan for Accounts" button in Customers tab
- Backend: search Asana (stored per-user PAT) for projects not already referenced by `project_gid` in `account-config.json`
- Modal UI with discovery results (account name candidate + Asana project only — no Slack columns)
- Google OAuth read/write of account-config.json
- Incremental append logic
- Refresh customers list on success

### Part 5: Error Handling & Edge Cases

- Implement graceful fallbacks for API failures
- Conflict resolution (multiple matches, duplicates)
- Empty result handling
- Config validation on brief runs
