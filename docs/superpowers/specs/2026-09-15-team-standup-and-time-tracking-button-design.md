# Team Standup Card & Weekly Time Tracking Button — Design

## Goal

Two additions to the daily-brief-v2 skill and its hosted viewer:

1. A new subsection of the Today section (Section 2) that gives a terse,
   Geekbot-ready standup summary of the day — bullet points split into
   **Customer** and **Internal** groups — reviewable and editable in the
   viewer before posting, same pattern as the existing Customer Update /
   Manager Update cards.
2. A persistent button in the hosted viewer that opens `/weekly-time-tracking`
   in Claude Desktop, so time tracking is one click away from the brief.

Along the way, this also fixes a related pre-existing gap: the Manager
Update's "Post to Manager" button reads `content.post_url`, which the skill
never actually sets (it's always the template's `#` fallback). This gets
fixed by switching Manager Update to the same `content.channel_id` shape
Customer Updates already uses, sourced from config instead of a hardcoded ID.

## 1. Config & cache additions

`config.json` gains two new top-level keys:

- `geekbot_channel_id` — the Slack channel/DM the Team Standup card's
  "Post to Slack" button targets.
- `manager_channel_id` — replaces the hardcoded `D0A25TNDGJJ` currently
  embedded in `SKILL.md` and `references/status-updates.md` for the Manager
  Update's "last update" search and post button. Per-user configurable, same
  as every other ID in `config.json`.

Both are added to `SKILL.md`'s "Loading config" step (the list of top-level
keys read from `config.json`) and to `references/item-sync.md` wherever that
key list is described.

**Manager Update's `content` shape changes** from `{"textarea": "..."}` to
`{"textarea": "...", "channel_id": "..."}` — matching Customer Updates
exactly. `references/status-updates.md`'s Section 4 write-up updates its
"Finding the last manager update" step to search
`manager_channel_id` (from config) instead of the hardcoded ID, and its
"Posting" step to set `content.channel_id` instead of implying a hardcoded
`post_url`.

`STATUS_UPDATE_CACHE_FILE_ID`'s schema (documented in
`references/status-updates.md`) gains a `team_standup` entry alongside the
existing `customer_updates` and `manager_update`:

```json
{
  "customer_updates": {
    "Acme, Inc.": { "content": "...", "generated_at": "...", "window_start": "..." },
    "Test Customer": { "content": "...", "generated_at": "...", "window_start": "..." }
  },
  "manager_update": { "content": "...", "generated_at": "..." },
  "team_standup": { "content": "...", "generated_at": "..." }
}
```

(The existing example keys in that file — real customer names — are replaced
with generic placeholders as part of this change, per repo hygiene: no real
account names in committed docs.)

Same generate-once-per-day gate as the existing two entries: `generated_at`
on today's local date → reuse `content` verbatim; missing or stale → generate
fresh and write back only that entry.

## 2. Team Standup card — content & format

**Location**: one additional item in `today.json` (Section 2), alongside the
existing checkable meeting items — `item_type: card`, `item_key:
today-standup`. This mirrors the mixed-type pattern `accounts/{slug}.json`'s
sibling section, Account/Initiative Recap, already uses in the viewer
(`section_fragment.html`'s `account-recap` branch already special-cases
`item.item_type == 'card'` vs. checkable) — `today.json` gets the same
treatment.

**Source data**: no new data pulls. Built by synthesizing over the same
"organize by customer account or internal initiative" buckets Section 2
already computes, plus Action Items due today folded in per account/
initiative. One bullet per account/initiative that has something on today's
docket (a meeting, or a due-today action item) — omit anything with nothing
to report, same rule used everywhere else in this skill. Training only
appears when a calendar block or task actually indicates a training session
today.

**Format** — plain text in `content.textarea`, structured for direct
paste into Geekbot's standup prompt:

```
Customer
- {Account Name} — {short note, e.g. what meeting/task is driving today}
- {Account Name} — {short note}

Internal
- Training — {short note, only if a training block exists today}
- {Initiative Name} — {short note}
```

Two fixed top-level groups (`Customer`, `Internal`); `Internal` always
includes Training when applicable, plus one bullet per internal initiative
with something due/scheduled today (including the General/Admin catch-all
only when it has genuine, specific content — never a placeholder line).

**Card shape**:
```json
{
  "section": "today",
  "item_key": "today-standup",
  "item_type": "card",
  "title": "Team Standup Update",
  "content": {
    "textarea": "Customer\n- ...\n\nInternal\n- ...",
    "channel_id": "<geekbot_channel_id from config.json>"
  }
}
```
No `last_posted_at` — unlike the TAM-UPDATE posts, there's no searchable
prior-post history to check for a daily standup prompt, so this field is
simply omitted (consistent with the existing "omit when no real value
exists" convention).

Every example added to the docs for this feature uses fictional names only
(e.g. "Acme, Inc.", "Test Customer") — no real account names introduced
anywhere in the repo.

## 3. Sync, caching & refresh mechanics

`today.json` is array-shaped and normally fully regenerated on every run
(unlike Customer Updates/Manager Update, which each live in their own
per-item file). Three flows touch it:

- **Full brief run**: build the checkable Today items fresh as today, then
  check the `team_standup` cache gate — reuse cached `content` or generate
  fresh per the process in `references/status-updates.md` — and include the
  resulting card as one more entry in the `today.json` array being written.
- **Today section-level Refresh** (existing whole-section Refresh button):
  regenerates the checkable meeting items as it does today, but carries the
  existing `today-standup` entry over unchanged from the current file rather
  than regenerating it — same principle as the Action Items merge-by-
  `item_key` exception already documented in `references/section-refresh.md`,
  applied here specifically to preserve the cached card.
- **Card-only refresh** (new "Refresh" link on the card itself, next to
  "Post to Slack"): uses the existing single-item-refresh syntax already
  documented in `references/section-refresh.md` —
  `/daily-brief Refresh section:today date:{brief_date} item:today-standup`.
  Regenerates just this entry via the `references/status-updates.md` logic,
  updates the `team_standup` cache entry, then applies the standard
  read-current-array / replace-by-`item_key` / write-full-array merge already
  used for other single-item patches to `today.json`.

`references/item-sync.md`'s `item_key` conventions list gains one entry:
**Team Standup Card** — always exactly `today-standup`.

## 4. Viewer UI changes

All changes are in `viewer/webapp/templates/`:

- **`section_fragment.html`**: the `today` section currently falls through to
  the generic checkable-item `else` branch. Add a check (mirroring the
  `account-recap` branch's `item.item_type == 'card'` check) so the
  `today-standup` card renders like a Customer Updates card — collapsible,
  an editable `textarea`, a "Post to Slack" link
  (`https://slack.com/app_redirect?channel={{ item.content.channel_id }}`),
  and a "Refresh" link sending
  `/daily-brief Refresh section:today date:{brief_date} item:today-standup`.
  Non-card items in Today keep rendering exactly as they do today.
- **`manager-update` branch**: switch the "Post to Manager" link from
  `item.content.post_url` (currently always `#`, since the skill never sets
  it) to build the same `app_redirect` URL from `item.content.channel_id`,
  matching Customer Updates and the new Team Standup card.
- **`brief_fragment.html` toolbar**: add a "Weekly Time Tracking" button next
  to the existing Expand all/Collapse all buttons:
  ```html
  <a class="toolbtn" href="claude://claude.ai/new?q=/weekly-time-tracking" target="_blank">Weekly Time Tracking</a>
  ```
  A static deep link (same `claude://` convention used throughout this
  skill), not a JS-wired button — always available regardless of which
  section is open.
- The non-progressive fallback block in `brief_fragment.html` (already
  marked "not currently used but kept for safety") is left as-is — updating
  dead code in parallel with the real progressive path isn't worth the
  churn.

## Files touched

- `SKILL.md` — config key list, Section 2 pointer to the new card.
- `references/item-sync.md` — `today.json`'s section-specific notes, new
  `item_key` convention, config key list, Slack posting affordances.
- `references/status-updates.md` — cache schema (`team_standup` entry +
  de-identified example account names), generation gate, new "Team Standup"
  content/format subsection, Manager Update's channel-ID sourcing.
- `references/section-refresh.md` — card-only refresh trigger for
  `today-standup`, and the Today section-level refresh's exception to
  preserve it.
- `viewer/webapp/templates/section_fragment.html` — `today` card rendering,
  `manager-update` post-link fix.
- `viewer/webapp/templates/brief_fragment.html` — toolbar button.

## Out of scope

- Auto-posting to Slack without human review (explicitly rejected in favor
  of the existing edit-then-click-to-post pattern).
- Any change to the pre-existing `viewer/webapp` vs. `viewer-backend`
  directory-naming inconsistency across branches — unrelated to this
  feature, not touched here.
- Sanitizing real-sounding example account names anywhere outside
  `references/status-updates.md`'s cache schema block (the one place this
  change specifically touches).
