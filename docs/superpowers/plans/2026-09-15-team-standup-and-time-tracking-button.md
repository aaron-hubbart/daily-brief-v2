# Team Standup Card & Weekly Time Tracking Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a cached "Team Standup Update" card to the Today section (Geekbot-ready bullets split into Customer/Internal), and a Weekly Time Tracking deep-link button in the hosted viewer's toolbar.

**Architecture:** This is a prompt-engineering change (the skill's own instructions in `SKILL.md` and `references/*.md`, which an LLM reads and follows at brief-generation time — there is no code to unit test there) plus a small Flask/Jinja template change in the hosted viewer (`viewer/webapp/templates/`), which does get automated tests. No new data pulls, no new Drive files, no new top-level brief section — everything rides inside the existing `today.json` file and the existing status-update cache file.

**Tech Stack:** Markdown/prose (skill instructions), Flask 3.0 + Jinja2 (hosted viewer), pytest 8.3 (viewer tests).

## Global Constraints

- No real customer/account names anywhere in the repo — use fictional examples only (e.g. "Acme, Inc.", "Test Customer"), per `references/item-sync.md`'s Repo Hygiene section and this feature's design doc.
- `config.json` gains exactly two new top-level keys: `geekbot_channel_id`, `manager_channel_id`. No other config shape changes.
- The Team Standup card's `item_key` is always exactly `today-standup`; its `section` is `today` (not a new section slug).
- Every "Post to Slack"/"Post to Manager" button in the viewer builds `https://slack.com/app_redirect?channel={content.channel_id}` from that item's own `content.channel_id` — never a hardcoded ID.
- Full design reference: `docs/superpowers/specs/2026-09-15-team-standup-and-time-tracking-button-design.md`.

---

## Task 1: Config keys, cache schema, and de-identified examples

**Files:**
- Modify: `SKILL.md` (config key list, ~line 41)
- Modify: `references/status-updates.md` (title, cache schema block, generation gate, Manager Update channel sourcing)
- Modify: `references/item-sync.md` (`item_type` line, Slack posting affordances paragraph)

**Interfaces:**
- Produces: the documented `config.json` keys `geekbot_channel_id` and `manager_channel_id`, which Task 2 and Task 3 both reference by name.
- Produces: the `team_standup` key in the `STATUS_UPDATE_CACHE_FILE_ID` schema, which Task 2 references.

This task is pure prose editing — there's no test runner for skill instructions, so each step's "verification" is a `grep` confirming the exact text landed and the old text is gone.

- [ ] **Step 1: Add the two new config keys to `SKILL.md`'s config key list**

In `SKILL.md`, find this sentence (in the "Loading config" numbered list, step 3):

```
3. Otherwise, read `config.json` from Drive by that file ID (`Google Drive` connector — the same read path already used for `account-config.json` and the status-update cache). It provides, as top-level keys: `brief_data_folder_id`, `meeting_run_log_sheet_id`, `recurring_activities_project_gid`, `status_update_cache_file_id`, `slack_user_id`, `key_contacts`, and optionally a `google_drive_pat_file_id`. Everywhere below that refers to one of the old Admin Config IDs (e.g. `BRIEF_DATA_FOLDER_ID`), use the corresponding value from `config.json`.
```

Replace it with:

```
3. Otherwise, read `config.json` from Drive by that file ID (`Google Drive` connector — the same read path already used for `account-config.json` and the status-update cache). It provides, as top-level keys: `brief_data_folder_id`, `meeting_run_log_sheet_id`, `recurring_activities_project_gid`, `status_update_cache_file_id`, `slack_user_id`, `key_contacts`, `geekbot_channel_id`, `manager_channel_id`, and optionally a `google_drive_pat_file_id`. `geekbot_channel_id` is the Slack channel/DM the Today section's Team Standup card posts to (see Section 2 below); `manager_channel_id` is the Manager Update's Slack DM target — both replace what used to be a hardcoded ID. Everywhere below that refers to one of the old Admin Config IDs (e.g. `BRIEF_DATA_FOLDER_ID`), use the corresponding value from `config.json`.
```

- [ ] **Step 2: Verify Step 1**

Run: `grep -n "geekbot_channel_id" SKILL.md`
Expected: one match, inside the config key list sentence above.

- [ ] **Step 3: Rename `references/status-updates.md`'s title and de-identify the cache schema example**

In `references/status-updates.md`, replace the title line:

```
# Status Updates Reference (Sections 3 & 4)
```

with:

```
# Status Updates & Team Standup Reference (Section 2 Addendum, 3 & 4)
```

Then replace the cache schema JSON block:

```json
{
  "customer_updates": {
    "Bank of America": { "content": "...", "generated_at": "2026-07-20T13:05:00Z", "window_start": "2026-07-13T00:00:00Z" },
    "JPMorgan Chase": { "content": "...", "generated_at": "2026-07-20T13:05:00Z", "window_start": "..." }
  },
  "manager_update": { "content": "...", "generated_at": "2026-07-20T13:05:00Z" }
}
```

with:

```json
{
  "customer_updates": {
    "Acme, Inc.": { "content": "...", "generated_at": "2026-07-20T13:05:00Z", "window_start": "2026-07-13T00:00:00Z" },
    "Test Customer": { "content": "...", "generated_at": "2026-07-20T13:05:00Z", "window_start": "..." }
  },
  "manager_update": { "content": "...", "generated_at": "2026-07-20T13:05:00Z" },
  "team_standup": { "content": "...", "generated_at": "2026-07-20T13:05:00Z" }
}
```

- [ ] **Step 4: Verify Step 3**

Run: `grep -n "Bank of America\|JPMorgan Chase" references/status-updates.md`
Expected: no matches.

Run: `grep -n "team_standup" references/status-updates.md`
Expected: at least one match (the cache schema block).

- [ ] **Step 5: Update the generation gate to cover `team_standup`**

In `references/status-updates.md`, replace this paragraph:

```
Evaluate this **per account** (and separately for the manager update), not once for the whole section — a full brief run can end up reusing six cached accounts and regenerating two, all in the same pass.
```

with:

```
Evaluate this **per account** (and separately for the manager update and the Today section's Team Standup card), not once for the whole section — a full brief run can end up reusing six cached accounts and regenerating two, all in the same pass.
```

Replace:

```
3. **Manager update:** same rule against `manager_update.generated_at`.
```

with:

```
3. **Manager update and Team Standup card:** same rule, against `manager_update.generated_at` and `team_standup.generated_at` respectively.
```

Replace:

```
4. **Explicit refresh request** ("refresh the BofA update," "regenerate manager update," or a click on a card's Refresh button — see `references/section-refresh.md`) forces regeneration for that one named entry regardless of its `generated_at` date, and overwrites only that entry.
```

with:

```
4. **Explicit refresh request** ("refresh the BofA update," "regenerate manager update," "refresh team standup," or a click on a card's Refresh button — see `references/section-refresh.md`) forces regeneration for that one named entry regardless of its `generated_at` date, and overwrites only that entry.
```

Replace:

```
This gate only affects Sections 3/4. Sections 1, 2, and the other synced sections (Yesterday's Meetings, Today, Action Items, FYI) still run in full on every brief, regardless of cache state.

A card's Refresh button (see `references/section-refresh.md`) is the normal path for an out-of-band update once the daily gate has already run once — it patches a single card via a single-item Drive write rather than triggering a full brief.
```

with:

```
This gate affects Sections 3/4 and the Today section's Team Standup card. Sections 1, 2 (aside from that one card), and the other synced sections (Yesterday's Meetings, Action Items, FYI) still run in full on every brief, regardless of cache state.

A card's Refresh button (see `references/section-refresh.md`) is the normal path for an out-of-band update once the daily gate has already run once — it patches a single card via a single-item Drive write rather than triggering a full brief. The Team Standup card is the one exception: it lives inside `today.json` rather than its own file, so its Refresh instead does a read-current-array/replace-by-`item_key`/write-complete-array update to `today.json` — see `references/section-refresh.md`.
```

- [ ] **Step 6: Verify Step 5**

Run: `grep -n "team_standup.generated_at\|refresh team standup" references/status-updates.md`
Expected: two matches.

- [ ] **Step 7: Fix Manager Update's channel sourcing in `references/status-updates.md`**

Replace:

```
Search the manager DM channel (`D0A25TNDGJJ`) for `[TAM-UPDATE] #claude-brief-skill`. Use the same 7-day lookback logic as customer updates.
```

with:

```
Search the manager DM channel (`manager_channel_id` from `config.json`) for `[TAM-UPDATE] #claude-brief-skill`. Use the same 7-day lookback logic as customer updates.
```

Replace:

```
**Posting:** Generate this as a `text-block` item (`section: manager-update`, `item_key: mgr-update`) with `content: {"textarea": "<generated update>"}` — full item shape and the Drive write are in `references/item-sync.md`. The webapp renders the "Post to Manager" button (`https://slack.com/app_redirect?channel=D0A25TNDGJJ`) directly from this item; nothing else to generate for it. Note the last manager update timestamp the same way as customer updates — omit if none found; when served from cache, that's `manager_update.generated_at`, not the current run time.
```

with:

```
**Posting:** Generate this as a `text-block` item (`section: manager-update`, `item_key: mgr-update`) with `content: {"textarea": "<generated update>", "channel_id": "<manager_channel_id from config.json>"}` — full item shape and the Drive write are in `references/item-sync.md`. The webapp renders the "Post to Manager" button (`https://slack.com/app_redirect?channel={channel_id}`) directly from this item's `content.channel_id`, same as Customer Updates; nothing else to generate for it. Note the last manager update timestamp the same way as customer updates — omit if none found; when served from cache, that's `manager_update.generated_at`, not the current run time.
```

- [ ] **Step 8: Verify Step 7**

Run: `grep -n "D0A25TNDGJJ" references/status-updates.md`
Expected: no matches.

Run: `grep -n "manager_channel_id" references/status-updates.md`
Expected: two matches (the search step and the posting step).

- [ ] **Step 9: Update `references/item-sync.md`'s `item_type` line and Slack posting affordances paragraph**

Replace:

```
- **`item_type`** — one of `checkable`, `card`, `fyi`, `text-block`. Sections 1 (both parts), Today, and Action Items are `checkable`. FYI is `fyi`. Customer Updates cards are `card`. Manager Update is `text-block`.
```

with:

```
- **`item_type`** — one of `checkable`, `card`, `fyi`, `text-block`. Sections 1 (both parts), Today, and Action Items are `checkable`, except Today's single `today-standup` entry, which is `card`. FYI is `fyi`. Customer Updates cards are `card`. Manager Update is `text-block`.
```

Replace:

```
The webapp renders a "Post to Slack" button on each Customer Update card (`https://slack.com/app_redirect?channel={channel_id}`, from `content.channel_id`) and a "Post to Manager" button on the Manager Update (`https://slack.com/app_redirect?channel=D0A25TNDGJJ`) — these are static links the template builds from the item's own content, not something the skill needs to construct or send separately. The skill just needs `content.channel_id` populated correctly.
```

with:

```
The webapp renders a "Post to Slack" button on each Customer Update card, on the Manager Update, and on the Today section's Team Standup card — all three build the same `https://slack.com/app_redirect?channel={channel_id}` URL from that item's own `content.channel_id`, not something the skill needs to construct or send separately. Customer Updates source `channel_id` from the account's entry in `/config/account-config.json`; Manager Update and the Team Standup card source theirs from `config.json`'s `manager_channel_id` and `geekbot_channel_id` respectively. The skill just needs `content.channel_id` populated correctly in each case.
```

- [ ] **Step 10: Verify Step 9**

Run: `grep -n "D0A25TNDGJJ" references/item-sync.md`
Expected: no matches.

Run: `grep -rn "D0A25TNDGJJ" SKILL.md references/`
Expected: no matches anywhere in the skill (confirms the hardcoded ID is fully retired).

- [ ] **Step 11: Commit**

```bash
git add SKILL.md references/status-updates.md references/item-sync.md
git commit -m "docs: move config channel IDs out of hardcoded values, add team_standup cache key"
```

---

## Task 2: Team Standup content/format specification

**Files:**
- Modify: `SKILL.md` (Section 2, add pointer paragraph, ~line 324)
- Modify: `references/status-updates.md` (new "Team Standup" subsection)
- Modify: `references/item-sync.md` (`item_key` conventions list, Today section-specific note)

**Interfaces:**
- Consumes: `geekbot_channel_id` from Task 1.
- Produces: the `today-standup` `item_key` convention and the full generation/format spec that Task 3's refresh flow and Task 4's template both depend on by name.

- [ ] **Step 1: Add the Section 2 pointer paragraph in `SKILL.md`**

Find this line (end of Section 2, "Today / Tomorrow Ahead"):

```
End with a brief **Open Time** note if there are meaningful unblocked blocks in the day.

---

### Section 3: Customer Updates & Section 4: Manager/Leadership Update
```

Replace with:

```
End with a brief **Open Time** note if there are meaningful unblocked blocks in the day.

Today also includes a Team Standup subsection: a single cached card (`item_key: today-standup`) giving a terse, Geekbot-ready recap of the day split into Customer and Internal bullets, editable in the viewer before posting. Same generate-once-per-day caching as Sections 3/4 below — see `references/status-updates.md` for content/format and the generation gate, and `references/item-sync.md` for the item shape. Unlike the rest of Today, a whole-section Refresh does not regenerate this card; only its own Refresh link does (see `references/section-refresh.md`).

---

### Section 3: Customer Updates & Section 4: Manager/Leadership Update
```

- [ ] **Step 2: Verify Step 1**

Run: `grep -n "today-standup" SKILL.md`
Expected: one match.

- [ ] **Step 3: Add the `today-standup` `item_key` convention to `references/item-sync.md`**

Find:

```
7. **Manager Update** — always exactly `mgr-update`.
```

Replace with:

```
7. **Manager Update** — always exactly `mgr-update`.
8. **Team Standup Card** (Today) — always exactly `today-standup`.
```

- [ ] **Step 4: Add the Today section-specific note about the standup card**

Find this paragraph in `references/item-sync.md`:

```
**Today** — checkable item per meeting for the full current day, past or future. Append " (occurred)" to `title` for any meeting whose end time has already passed at brief-generation time. Include a Join link in `links` if a Zoom/Webex/Teams URL is present, plus a meeting-prep output link once prep exists or has just been generated by this run (see `SKILL.md` for the meeting-manager pre-meeting trigger rule).
```

Replace with:

```
**Today** — checkable item per meeting for the full current day, past or future. Append " (occurred)" to `title` for any meeting whose end time has already passed at brief-generation time. Include a Join link in `links` if a Zoom/Webex/Teams URL is present, plus a meeting-prep output link once prep exists or has just been generated by this run (see `SKILL.md` for the meeting-manager pre-meeting trigger rule).

Today also includes exactly one `card` item, `item_key: today-standup` — a Team Standup Update summarizing the day for Geekbot, gated by the same daily cache as Customer Updates/Manager Update (see `references/status-updates.md` for the full generation/format spec). `content`: `{"textarea": "<generated bullets>", "channel_id": "<geekbot_channel_id from config.json>"}` — no `last_posted_at`, since there's no searchable prior-post history to check for a daily standup prompt. A whole-section Today refresh regenerates the checkable meeting items above but leaves this card untouched; only its own Refresh link (see `references/section-refresh.md`) regenerates it.
```

- [ ] **Step 5: Verify Steps 3-4**

Run: `grep -c "today-standup" references/item-sync.md`
Expected: `3` (the `item_key` conventions list entry, and two mentions in the new Today paragraph).

- [ ] **Step 6: Add the "Team Standup" content/format subsection to `references/status-updates.md`**

Find:

```
## Section 3: Customer Updates
```

Insert this new section immediately before it (so it reads in brief-section order: Team Standup is part of Section 2, ahead of Sections 3/4). The new text ends by repeating the `---` and `## Section 3: Customer Updates` heading that was found above, so this is a full replacement of that one heading line, not an append — don't end up with the heading twice:

````
## Team Standup (Section 2 Addendum)

Same cache gate as Sections 3/4 above, keyed by `team_standup` in `STATUS_UPDATE_CACHE_FILE_ID`. Generated fresh only on a cache miss or explicit refresh (`/daily-brief Refresh section:today date:{brief_date} item:today-standup` — see `references/section-refresh.md`).

**Source data:** no new data pulls. Synthesize over the same "organize by customer account or internal initiative" buckets already computed for Section 2 (Today/Tomorrow Ahead — see `SKILL.md`), plus Action Items due today folded in per account/initiative. Include one bullet per account/initiative with something on today's docket (a meeting or a due-today action item); omit anything with nothing to report, same rule used everywhere else in this skill. A "Training" bullet appears under Internal only when a calendar block or task actually indicates a training session today.

**Format** — plain text in `content.textarea`, two fixed top-level groups, each bullet a short name-plus-note line:

```
Customer
- {Account Name} — {short note on what's driving today's docket for this account}
- {Account Name} — {short note}

Internal
- Training — {short note, only when a training block exists today}
- {Initiative Name} — {short note}
```

Example (fictional names only):

```
Customer
- Acme, Inc. — renewal call prep, contract review due
- Test Customer — quarterly business review at 2pm

Internal
- Training — 10am required compliance session
- AI-First CS Tiger Team — PR review with a teammate
```

Generate this as a `card` item (`section: today`, `item_key: today-standup`) with `content: {"textarea": "<generated bullets>", "channel_id": "<geekbot_channel_id from config.json>"}` — full item shape and the Drive write mechanics are in `references/item-sync.md`. No `last_posted_at` — unlike the TAM-UPDATE posts, there's no searchable prior-post history to check for a daily standup prompt, so this field is simply omitted.

---

## Section 3: Customer Updates
````

- [ ] **Step 7: Verify Step 6**

Run: `grep -n "^## " references/status-updates.md`
Expected output includes, in this order: `## Cache schema`, `## Generation gate...`, `## Team Standup (Section 2 Addendum)`, `## Section 3: Customer Updates`, `## Section 4: Manager/Leadership Update`.

- [ ] **Step 8: Commit**

```bash
git add SKILL.md references/status-updates.md references/item-sync.md
git commit -m "docs: add Team Standup card generation and format spec"
```

---

## Task 3: Refresh mechanics for the Team Standup card

**Files:**
- Modify: `references/section-refresh.md`

**Interfaces:**
- Consumes: `today-standup` item_key and `team_standup` cache key from Tasks 1-2.
- Produces: the exact refresh command format (`/daily-brief Refresh section:today date:{brief_date} item:today-standup`) that Task 4's Refresh link sends.

- [ ] **Step 1: Update the "Single-item section refresh" trigger phrase note**

Replace:

```
- Single-item section refresh: `/daily-brief Refresh section:{slug} date:{brief_date} item:{item_key}` — narrower than a full section refresh, regenerates only that one item's entry. Not yet sent by any viewer button, but recognize it when typed or sent by a future per-item control.
```

with:

```
- Single-item section refresh: `/daily-brief Refresh section:{slug} date:{brief_date} item:{item_key}` — narrower than a full section refresh, regenerates only that one item's entry. Sent by the Today section's Team Standup card's own Refresh link (`item:today-standup`); recognize it for any other item typed or sent by a future per-item control too.
```

- [ ] **Step 2: Add a "Card-level refresh (Team Standup)" subsection**

Find the end of the existing "## Card-level steps (Customer Update / Manager Update)" section — it ends with this paragraph, immediately before the "## Section-level refresh" heading:

```
If the Refresh click arrives well after the day's brief was first generated, that's expected and fine — this flow only ever touches the one card, so staleness elsewhere is not this flow's concern.

## Section-level refresh (the other five sections)
```

Replace with:

```
If the Refresh click arrives well after the day's brief was first generated, that's expected and fine — this flow only ever touches the one card, so staleness elsewhere is not this flow's concern.

## Card-level refresh (Team Standup)

The Today section's Team Standup card (`item_key: today-standup`) is cache-gated like Customer Updates/Manager Update, but — unlike those two, which each live in their own per-item file — it lives inside `today.json`, an array-shaped file. Its Refresh link sends the single-item syntax above: `/daily-brief Refresh section:today date:{brief_date} item:today-standup`.

1. **Use `brief_date` from the command.**
2. **Regenerate just this entry.** Run the Team Standup generation process from `references/status-updates.md` — no other Today items, no other section.
3. **Update the cache.** Write the new `content` and `generated_at` (now) into the `team_standup` entry in `STATUS_UPDATE_CACHE_FILE_ID`. Leave `customer_updates` and `manager_update` untouched.
4. **Write `today.json`.** Read the current `/briefs/{brief_date}/today.json` array, replace the entry matching `item_key: today-standup` (or append it, if this is the first time it's been generated this run), keep every other item in the array byte-for-byte untouched, and write the complete array back via `Google Drive: create_file` — the same read-current-array/replace-by-`item_key`/write-complete-array mechanic used for the "Single-item refresh" case under Section-level refresh below, and by `references/post-meeting-patch.md`.
5. **Respond briefly.** Same one-line confirmation convention as the other card-level refreshes above.

## Section-level refresh (the other five sections)
```

- [ ] **Step 3: Add the Today-section exception to the section-level refresh flow**

Find this paragraph (end of the "### Steps" list under "## Section-level refresh"):

```
5. **Respond briefly.** One line confirming which section refreshed; note that the refresh is reflected in the hosted viewer on next page load, without needing to construct or share a direct link. Same no-reproduction rule as a normal brief run and the card-level refresh above. If step 3 hit partial failures, name them here (see below) rather than only reporting success.

### Partial run handling
```

Replace with:

```
5. **Respond briefly.** One line confirming which section refreshed; note that the refresh is reflected in the hosted viewer on next page load, without needing to construct or share a direct link. Same no-reproduction rule as a normal brief run and the card-level refresh above. If step 3 hit partial failures, name them here (see below) rather than only reporting success.

**Exception for `today`:** a whole-section refresh of `today` regenerates only the checkable meeting items — it never regenerates the `today-standup` card, which is cached separately (see "Card-level refresh (Team Standup)" above and `references/status-updates.md`). When reading the current `today.json` to merge in the freshly-regenerated meeting items, always carry the existing `today-standup` entry forward unchanged, unless the command explicitly targets `item:today-standup` (in which case follow "Card-level refresh (Team Standup)" instead of this section-level flow).

### Partial run handling
```

- [ ] **Step 4: Verify Steps 1-3**

Run: `grep -n "today-standup" references/section-refresh.md`
Expected: at least 5 matches (trigger phrase note, the new subsection's heading text and body, and the today-exception paragraph).

- [ ] **Step 5: Commit**

```bash
git add references/section-refresh.md
git commit -m "docs: document Team Standup card refresh flow and today-section exception"
```

---

## Task 4: Viewer — Today card rendering & Manager Update channel-ID fix

**Files:**
- Create: `viewer/webapp/tests/template_test_utils.py`
- Create: `viewer/webapp/tests/test_today_section_card.py`
- Create: `viewer/webapp/tests/test_manager_update_channel_id.py`
- Modify: `viewer/webapp/templates/section_fragment.html`

**Interfaces:**
- Produces: `template_test_utils.make_env()` — a standalone `jinja2.Environment` wired with this app's two custom filters (`autolink_jira`, `resolve_link_url`), loading templates from `viewer/webapp/templates/`. Task 5 reuses this helper.

This app has no existing Flask-app-level test harness (importing `app.py` requires `FLASK_SECRET_KEY`/`AZURE_*` env vars and `psycopg2`, which isn't installed in this environment — see `viewer/webapp/tests/test_asana_discovery.py`'s docstring for the existing pattern of testing pure logic without importing `app.py`). These tests extend that same pattern to template rendering: a standalone Jinja2 `Environment` pointed at the real template files, with the same two filters `app.py` registers reimplemented verbatim (they're simple, pure, regex-based functions — see `app.py:541-569`).

- [ ] **Step 1: Create the shared template-rendering test helper**

Create `viewer/webapp/tests/template_test_utils.py`:

```python
"""Shared helper for rendering this app's Jinja templates in isolation,
without importing app.py. Importing app.py requires Flask/Azure env vars
(FLASK_SECRET_KEY, AZURE_TENANT_ID, etc. — see its _require_env calls) and
psycopg2 (via `import db`), neither of which this test environment has.
Template-only tests render the real template files through a standalone
Jinja2 Environment instead, with the same two custom filters app.py
registers (kept in sync by hand with app.py:541-569 below)."""
import re
from pathlib import Path

import jinja2
from markupsafe import Markup, escape

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / 'templates'

JIRA_TICKET_RE = re.compile(r'\b([A-Z]{2,}-\d+)\b')
JIRA_BASE_URL = 'https://jira.camunda.com/browse'


def _autolink_jira(text):
    if not text:
        return text
    safe_text = str(escape(text))

    def _replace(m):
        key = m.group(1)
        return f'<a class="lbtn" href="{JIRA_BASE_URL}/{key}" target="_blank">{key}</a>'

    return Markup(JIRA_TICKET_RE.sub(_replace, safe_text))


def _resolve_link_url(url):
    if not url:
        return url
    if url.startswith(('http://', 'https://', 'claude://', '//', '/')):
        return url
    if JIRA_TICKET_RE.fullmatch(url):
        return f'{JIRA_BASE_URL}/{url}'
    return url


def make_env():
    """A Jinja2 Environment wired up like app.py's Flask app, minus
    anything that needs a running Flask app (callers that render a
    template using `url_for` must stub it themselves via env.globals)."""
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)))
    env.filters['autolink_jira'] = _autolink_jira
    env.filters['resolve_link_url'] = _resolve_link_url
    return env
```

- [ ] **Step 2: Write the failing tests for the Today card rendering**

Create `viewer/webapp/tests/test_today_section_card.py`:

```python
from urllib.parse import unquote

from template_test_utils import make_env


def render_today(items):
    env = make_env()
    template = env.get_template('section_fragment.html')
    return template.render(
        section_slug='today',
        section_items=items,
        action_subsections=[],
        asana_pat_configured=False,
        brief_date='2026-09-15',
        today_iso='2026-09-15',
    )


def test_standup_card_renders_textarea_and_post_to_slack_link():
    items = [{
        'item_key': 'today-standup',
        'item_type': 'card',
        'title': 'Team Standup Update',
        'content': {
            'textarea': 'Customer\n- Acme, Inc. — renewal call prep',
            'channel_id': 'D0TESTGEEKBOT',
        },
    }]

    html = render_today(items)

    assert 'Team Standup Update' in html
    assert 'Customer\n- Acme, Inc. — renewal call prep' in html
    assert 'https://slack.com/app_redirect?channel=D0TESTGEEKBOT' in html
    assert 'Post to Slack' in html


def test_standup_card_refresh_link_targets_today_item():
    items = [{
        'item_key': 'today-standup',
        'item_type': 'card',
        'title': 'Team Standup Update',
        'content': {'textarea': '...', 'channel_id': 'D0TESTGEEKBOT'},
    }]

    html = render_today(items)
    decoded = unquote(html)

    assert '/daily-brief Refresh section:today date:2026-09-15 item:today-standup' in decoded


def test_checkable_meeting_items_still_render_normally():
    items = [{
        'item_key': 'today-0900-acme-sync',
        'item_type': 'checkable',
        'title': 'Acme, Inc. Sync',
        'subtitle': '9:00 AM with a colleague',
        'checked': False,
        'content': {'time': '9:00 AM'},
    }]

    html = render_today(items)

    assert 'Acme, Inc. Sync' in html
    assert '9:00 AM with a colleague' in html
    assert 'type="checkbox"' in html


def test_card_and_checkable_items_render_together():
    items = [
        {
            'item_key': 'today-standup',
            'item_type': 'card',
            'title': 'Team Standup Update',
            'content': {'textarea': 'Customer\n- Acme, Inc.', 'channel_id': 'D0TESTGEEKBOT'},
        },
        {
            'item_key': 'today-0900-acme-sync',
            'item_type': 'checkable',
            'title': 'Acme, Inc. Sync',
            'checked': False,
            'content': {},
        },
    ]

    html = render_today(items)

    assert 'Team Standup Update' in html
    assert 'Acme, Inc. Sync' in html
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd viewer/webapp && python -m pytest tests/test_today_section_card.py -v`
Expected: all 4 tests FAIL — `section_fragment.html`'s `today` slug currently falls through to the generic checkable-only branch, so `content.textarea`, "Post to Slack", and the card's Refresh link never appear (the card item would render as a broken checkable item instead).

- [ ] **Step 4: Implement the `today` card branch in `section_fragment.html`**

In `viewer/webapp/templates/section_fragment.html`, find the `account-recap` branch's closing and the final generic `else`:

```
{% elif section_slug == 'account-recap' %}
  {% for item in section_items %}
  {% if item.item_type == 'card' %}
  <details class="acct-card" data-id="{{ item.item_key }}">
    <summary>
      <span class="acct-card-name">{{ item.title }}</span>
      {% if item.get('content', {}).get('status') %}<span class="acct-card-meta">{{ item.get('content', {}).get('status')|capitalize }}</span>{% endif %}
    </summary>
    <div class="acct-card-body">
      {% if item.get('content', {}).get('html_content') %}<div style="line-height:1.5;color:var(--t1);">{{ item.get('content', {}).get('html_content')|safe }}</div>{% endif %}
      {% if item.get('content', {}).get('action_items') %}
      <div style="margin-top:10px;padding-top:10px;border-top:1px solid var(--border);">
        <div style="font-size:10px;font-weight:700;color:var(--accent-t);text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px;">Action Items</div>
        <ul style="margin:0;padding-left:18px;font-size:12px;color:var(--t2);line-height:1.5;">
          {% for action in item.get('content', {}).get('action_items', []) %}
          <li>{{ action }}</li>
          {% endfor %}
        </ul>
      </div>
      {% endif %}
      <a class="lbtn" href="claude://claude.ai/new?q={{ ('/daily-brief Refresh section:account-recap account:' + (item.title|replace(' & ', '-')|replace('.', '')|replace(',', '')|replace(' ', '-')|lower) + ' date:' + brief_date)|urlencode }}" target="_blank" style="margin-top:8px;display:inline-block;">Refresh</a>
    </div>
  </details>
  {% else %}
  <div class="item{% if item.checked %} done{% endif %}" data-id="{{ item.item_key }}">
    <div class="icb"><input type="checkbox" {% if item.checked %}checked{% endif %}></div>
    <div class="ibody">
      <div class="ititle">{{ item.title|autolink_jira }}{% if item.badge %} <span class="badge {{ item.badge.get('class', '') }}">{{ item.badge.get('label', '') }}</span>{% endif %}</div>
      {% if item.subtitle %}<div class="isub">{{ item.subtitle|autolink_jira }}</div>{% endif %}
      {% if item.links %}
      <div class="ilinks">
        {% for link in item.links %}
        <a class="{{ link.get('class', 'lbtn') }}" href="{{ link.url|resolve_link_url }}" target="_blank">{{ link.label }}</a>
        {% endfor %}
      </div>
      {% endif %}
    </div>
  </div>
  {% endif %}
  {% endfor %}

{% else %}
  {% for item in section_items %}
  <div class="item{% if item.checked %} done{% endif %}" data-id="{{ item.item_key }}">
    <div class="icb"><input type="checkbox" {% if item.checked %}checked{% endif %}></div>
    {% if item.get('content', {}).get('time') %}<div class="itime">{{ item.get('content', {}).get('time') }}</div>{% endif %}
    <div class="ibody">
      <div class="ititle">{{ item.title|autolink_jira }}{% if item.badge %} <span class="badge {{ item.badge.get('class', '') }}">{{ item.badge.get('label', '') }}</span>{% endif %}</div>
      {% if item.subtitle %}<div class="isub">{{ item.subtitle|autolink_jira }}</div>{% endif %}
      {% if item.links %}
      <div class="ilinks">
        {% for link in item.links %}
        <a class="{{ link.get('class', 'lbtn') }}" href="{{ link.url|resolve_link_url }}" target="_blank">{{ link.label }}</a>
        {% endfor %}
      </div>
      {% endif %}
    </div>
  </div>
  {% endfor %}
{% endif %}
```

Insert a new `{% elif section_slug == 'today' %}` branch immediately before the final `{% else %}` (i.e. right after the `account-recap` block's closing `{% endfor %}`, before the line `{% else %}` that precedes the generic fallback):

```
{% elif section_slug == 'today' %}
  {% for item in section_items %}
  {% if item.item_type == 'card' %}
  <details class="acct-card" data-id="{{ item.item_key }}">
    <summary>
      <span class="acct-card-name">{{ item.title or 'Team Standup Update' }}</span>
    </summary>
    <div class="acct-card-body">
      <textarea class="update-textarea">{{ item.get('content', {}).get('textarea', '') }}</textarea>
      <div class="update-row">
        <input class="channel-input" type="text" value="{{ item.get('content', {}).get('channel_id', '') }}" readonly>
        <a class="post-btn" href="https://slack.com/app_redirect?channel={{ item.get('content', {}).get('channel_id', '') }}" target="_blank">Post to Slack</a>
        <a class="lbtn" href="claude://claude.ai/new?q={{ ('/daily-brief Refresh section:today date:' ~ brief_date ~ ' item:' ~ item.item_key)|urlencode }}" target="_blank">Refresh</a>
      </div>
    </div>
  </details>
  {% else %}
  <div class="item{% if item.checked %} done{% endif %}" data-id="{{ item.item_key }}">
    <div class="icb"><input type="checkbox" {% if item.checked %}checked{% endif %}></div>
    {% if item.get('content', {}).get('time') %}<div class="itime">{{ item.get('content', {}).get('time') }}</div>{% endif %}
    <div class="ibody">
      <div class="ititle">{{ item.title|autolink_jira }}{% if item.badge %} <span class="badge {{ item.badge.get('class', '') }}">{{ item.badge.get('label', '') }}</span>{% endif %}</div>
      {% if item.subtitle %}<div class="isub">{{ item.subtitle|autolink_jira }}</div>{% endif %}
      {% if item.links %}
      <div class="ilinks">
        {% for link in item.links %}
        <a class="{{ link.get('class', 'lbtn') }}" href="{{ link.url|resolve_link_url }}" target="_blank">{{ link.label }}</a>
        {% endfor %}
      </div>
      {% endif %}
    </div>
  </div>
  {% endif %}
  {% endfor %}

{% else %}
```

(Everything else — the generic `else` block and its closing `{% endif %}` — stays exactly as it was; `yesterday-meetings` still falls through to it unchanged.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd viewer/webapp && python -m pytest tests/test_today_section_card.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 6: Write the failing test for the Manager Update channel-ID fix**

Create `viewer/webapp/tests/test_manager_update_channel_id.py`:

```python
from template_test_utils import make_env


def render_manager_update(items):
    env = make_env()
    template = env.get_template('section_fragment.html')
    return template.render(
        section_slug='manager-update',
        section_items=items,
        action_subsections=[],
        asana_pat_configured=False,
        brief_date='2026-09-15',
        today_iso='2026-09-15',
    )


def test_post_to_manager_link_built_from_channel_id():
    items = [{
        'item_key': 'mgr-update',
        'item_type': 'text-block',
        'title': 'Manager Update',
        'content': {
            'textarea': 'TAM Weekly Update...',
            'channel_id': 'D0TESTMANAGER',
        },
    }]

    html = render_manager_update(items)

    assert 'https://slack.com/app_redirect?channel=D0TESTMANAGER' in html
    assert 'Post to Manager' in html
```

- [ ] **Step 7: Run the test to verify it fails**

Run: `cd viewer/webapp && python -m pytest tests/test_manager_update_channel_id.py -v`
Expected: FAIL — the current template builds the href from `content.post_url` (which this test doesn't set), so it renders `href="#"` instead of the expected `app_redirect` URL.

- [ ] **Step 8: Fix the Manager Update post-link in `section_fragment.html`**

Find:

```
{% elif section_slug == 'manager-update' %}
  {% for item in section_items %}
  <textarea class="update-textarea">{{ item.get('content', {}).get('textarea', '') }}</textarea>
  <div class="update-row">
    <a class="post-btn" href="{{ item.get('content', {}).get('post_url', '#') }}" target="_blank">Post to Manager</a>
    <a class="lbtn" href="claude://claude.ai/new?q={{ ('/daily-brief Refresh manager update date:' ~ brief_date)|urlencode }}" target="_blank">Refresh</a>
  </div>
  {% endfor %}
```

Replace with:

```
{% elif section_slug == 'manager-update' %}
  {% for item in section_items %}
  <textarea class="update-textarea">{{ item.get('content', {}).get('textarea', '') }}</textarea>
  <div class="update-row">
    <a class="post-btn" href="https://slack.com/app_redirect?channel={{ item.get('content', {}).get('channel_id', '') }}" target="_blank">Post to Manager</a>
    <a class="lbtn" href="claude://claude.ai/new?q={{ ('/daily-brief Refresh manager update date:' ~ brief_date)|urlencode }}" target="_blank">Refresh</a>
  </div>
  {% endfor %}
```

- [ ] **Step 9: Run the test to verify it passes**

Run: `cd viewer/webapp && python -m pytest tests/test_manager_update_channel_id.py -v`
Expected: PASS.

- [ ] **Step 10: Run the full test suite to confirm no regressions**

Run: `cd viewer/webapp && python -m pytest tests/ -v`
Expected: all tests PASS (the original 6 `test_asana_discovery.py` tests plus the new ones from this task).

- [ ] **Step 11: Commit**

```bash
git add viewer/webapp/tests/template_test_utils.py viewer/webapp/tests/test_today_section_card.py viewer/webapp/tests/test_manager_update_channel_id.py viewer/webapp/templates/section_fragment.html
git commit -m "feat: render Team Standup card in Today section, fix Manager Update post link"
```

---

## Task 5: Viewer — Weekly Time Tracking toolbar button

**Files:**
- Create: `viewer/webapp/tests/test_toolbar_time_tracking_link.py`
- Modify: `viewer/webapp/templates/brief_fragment.html`

**Interfaces:**
- Consumes: `template_test_utils.make_env()` from Task 4.

- [ ] **Step 1: Write the failing test**

Create `viewer/webapp/tests/test_toolbar_time_tracking_link.py`:

```python
from urllib.parse import unquote

from template_test_utils import make_env


def render_brief_fragment():
    env = make_env()
    env.globals['url_for'] = lambda endpoint, **kwargs: '#'
    template = env.get_template('brief_fragment.html')
    return template.render(
        brief_date='2026-09-15',
        brief_date_label='Tuesday, September 15',
        brief_type='morning',
        checkable_count=0,
        sections=[],
        items_by_section={},
        action_subsections=[],
        asana_pat_configured=False,
        today_iso='2026-09-15',
        progressive=False,
    )


def test_toolbar_has_weekly_time_tracking_link():
    html = render_brief_fragment()
    decoded = unquote(html)

    assert 'Weekly Time Tracking' in html
    assert 'claude://claude.ai/new?q=' in html
    assert '/weekly-time-tracking' in decoded
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd viewer/webapp && python -m pytest tests/test_toolbar_time_tracking_link.py -v`
Expected: FAIL — no "Weekly Time Tracking" text exists in `brief_fragment.html` yet.

- [ ] **Step 3: Add the toolbar button**

In `viewer/webapp/templates/brief_fragment.html`, find:

```html
  <div class="toolbar">
    <button type="button" class="toolbtn" id="expand-all-btn">Expand all</button>
    <button type="button" class="toolbtn" id="collapse-all-btn">Collapse all</button>
  </div>
```

Replace with:

```html
  <div class="toolbar">
    <button type="button" class="toolbtn" id="expand-all-btn">Expand all</button>
    <button type="button" class="toolbtn" id="collapse-all-btn">Collapse all</button>
    <a class="toolbtn" href="claude://claude.ai/new?q={{ '/weekly-time-tracking'|urlencode }}" target="_blank">Weekly Time Tracking</a>
  </div>
```

Also find this CSS rule (so the anchor doesn't render with a default underline):

```css
.toolbtn{font-size:11px;font-weight:500;padding:4px 10px;background:var(--surface);color:var(--t2);border:1px solid var(--border-strong);border-radius:var(--r);cursor:pointer;font-family:var(--font);}
```

Replace with:

```css
.toolbtn{font-size:11px;font-weight:500;padding:4px 10px;background:var(--surface);color:var(--t2);border:1px solid var(--border-strong);border-radius:var(--r);cursor:pointer;font-family:var(--font);text-decoration:none;display:inline-block;}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd viewer/webapp && python -m pytest tests/test_toolbar_time_tracking_link.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full test suite to confirm no regressions**

Run: `cd viewer/webapp && python -m pytest tests/ -v`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add viewer/webapp/tests/test_toolbar_time_tracking_link.py viewer/webapp/templates/brief_fragment.html
git commit -m "feat: add Weekly Time Tracking button to viewer toolbar"
```

---

## Final check

- [ ] Run `cd viewer/webapp && python -m pytest tests/ -v` one more time from a clean `git status` to confirm everything is committed and green.
- [ ] Run `grep -rn "D0A25TNDGJJ" SKILL.md references/` — expect no matches, confirming the hardcoded manager channel is fully gone.
- [ ] Run `grep -n "Bank of America\|JPMorgan Chase" references/status-updates.md` — expect no matches, confirming the cache-schema example names are de-identified. (Real account names may still appear as examples elsewhere in `SKILL.md`/`references/` — sanitizing those was explicitly out of scope for this branch; see the design doc's "Out of scope" section.)
