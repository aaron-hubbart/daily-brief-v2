# Status Updates & Team Standup Reference (Section 2 Addendum, 3 & 4)

Read this file only when the generation gate below says to actually generate or regenerate. On runs where the gate says "reuse cache," skip this file entirely and pull the cached content straight from `STATUS_UPDATE_CACHE_FILE_ID` — do not re-run the searches or synthesis described here. This is the single biggest cost item in the whole skill (a fresh per-account Slack search plus full narrative synthesis for every account, every run), so the gate exists specifically to stop that from happening on every "brief me" of the day.

## Cache schema

`STATUS_UPDATE_CACHE_FILE_ID` is a small JSON file in Drive holding per-entry state, not one global flag — this is what makes a single-account refresh possible without touching the other seven:

```json
{
  "customer_updates": {
    "Acme Financial": { "content": "...", "generated_at": "2026-07-20T13:05:00Z", "window_start": "2026-07-13T00:00:00Z" },
    "Zebra Financial": { "content": "...", "generated_at": "2026-07-20T13:05:00Z", "window_start": "..." }
  },
  "manager_update": { "content": "...", "generated_at": "2026-07-20T13:05:00Z" },
  "team_standup": { "content": "...", "generated_at": "2026-07-20T13:05:00Z" }
}
```

Key by Account Name exactly as it appears in `/config/account-config.json`'s `account_name` field, so entries line up with the account list read at generation time.

`STATUS_UPDATE_CACHE_FILE_ID` is unchanged from v1: it is still its own separately-configured Drive file, not inside `BRIEF_DATA_FOLDER_ID` and not part of the `/briefs/{date}/` layout described in `references/item-sync.md`. It tracks generation state across however many brief runs happen in a day — a different lifetime than one day's section content, which is why it stays outside that per-day layout rather than becoming, say, a `/briefs/{date}/status-cache.json` file.

## Generation gate (check this first, every run that reaches Section 2's Team Standup card, or Section 3/4)

Evaluate this **per account** (and separately for the manager update and the Today section's Team Standup card), not once for the whole section — a full brief run can end up reusing six cached accounts and regenerating two, all in the same pass.

1. Read `STATUS_UPDATE_CACHE_FILE_ID`.
2. **For each account:** if `customer_updates[account].generated_at` falls on today's local date, reuse that `content` verbatim — no Slack search, no synthesis. If it's missing or dated before today, generate fresh per the process below, then write the new `content` and `generated_at` (now) back into that account's entry only. Leave every other account's entry in the file untouched. **Write the updated cache back to the same file ID using the Google Drive REST API v3 PATCH method** (see "Google Drive write mechanics" in `SKILL.md`) — do not create a new file, as that would change the file ID and break the pointer in `config.json`.
3. **Manager update and Team Standup card:** same rule, against `manager_update.generated_at` and `team_standup.generated_at` respectively.
4. **Explicit refresh request** ("refresh the AcmeFin update," "regenerate manager update," "refresh team standup," or a click on a card's Refresh button — see `references/section-refresh.md`) forces regeneration for that one named entry regardless of its `generated_at` date, and overwrites only that entry.
5. **Cache read fails** (Drive error, file missing and can't be created): treat every entry as a miss for this run — generate fresh for all of them, and note in the brief that the cache couldn't be read. Don't block the brief on this.
6. **New account not yet in the cache file:** treat as a miss, generate, add its entry.
7. **Tier / scope:** generate cards only for in-scope accounts (Resolve In-Scope Accounts in `SKILL.md`). Primary accounts follow the daily gate above. A secondary account is only reached on a run where it is in scope (its run-day or a catch-up); on that run the same per-account `generated_at`-vs-today gate applies, so it generates at most once per week. Off-day secondary accounts produce no card.

This gate affects Sections 3/4 and the Today section's Team Standup card. Sections 1, 2 (aside from that one card), and the other synced sections (Yesterday's Meetings, Action Items, FYI) still run in full on every brief, regardless of cache state.

A card's Refresh button (see `references/section-refresh.md`) is the normal path for an out-of-band update once the daily gate has already run once — it patches a single card via a single-item Drive write rather than triggering a full brief. The Team Standup card is the one exception: it lives inside `today.json` rather than its own file, so its Refresh instead does a read-current-array/replace-by-`item_key`/write-complete-array update to `today.json` — see `references/section-refresh.md`.

---

## Team Standup (Section 2 Addendum)

Same cache gate as Sections 3/4 above, keyed by `team_standup` in `STATUS_UPDATE_CACHE_FILE_ID`. Generated fresh only on a cache miss or explicit refresh (`/daily-brief Refresh section:today date:{brief_date} item:today-standup` — see `references/section-refresh.md`).

**Source data:** no new data pulls. Synthesize over the same "organize by customer account or internal initiative" buckets already computed for Section 2 (Today/Tomorrow Ahead — see `SKILL.md`), plus Action Items due today folded in per account/initiative. Include one bullet per account/initiative with something on today's docket (a meeting or a due-today action item); omit anything with nothing to report, same rule used everywhere else in this skill. A "Training" bullet appears under Internal only when a calendar block or task actually indicates a training session today.

**Format** — plain text in `content.textarea`, two fixed top-level groups, each bullet a short name-plus-note line. **Never include a time** (meeting start time, due time, etc.) in any bullet, Customer or Internal — this is a terse Geekbot-ready recap, and clock times are a detail the post doesn't need:

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
- Test Customer — quarterly business review

Internal
- Training — required compliance session
- AI-First CS Tiger Team — PR review with a teammate
```

Generate this as a `card` item (`section: today`, `item_key: today-standup`) with `content: {"textarea": "<generated bullets>", "channel_id": "<geekbot_channel_id from config.json>"}` — full item shape and the Drive write mechanics are in `references/item-sync.md`. No `last_posted_at` — unlike the TAM-UPDATE posts, there's no searchable prior-post history to check for a daily standup prompt, so this field is simply omitted.

---

## Section 3: Customer Updates

One collapsible card per customer account on your assigned list — every in-scope account — all primary accounts plus any in-scope secondary accounts (see the Resolve In-Scope Accounts step in `SKILL.md`, and `references/item-sync.md` for the file's Drive location and shape) — not just accounts with signals in the current pull. Read the account list fresh from that file each time this section is actually generated (i.e., on a cache miss or explicit refresh) — do not rely on a previously-known or hardcoded list, since accounts can be added or removed in the config independent of this skill. The entire section is also collapsed by default.

If an account has no new activity in the update window, still generate its card — state plainly that there's nothing new to report since the last update rather than omitting the account. Order cards with active-signal accounts first, then quiet ones.

For each account, generate a plain-text update summarizing recent activity suitable for posting to the account's internal Slack channel. The update should be factual, professional, and peer-level — written as a TAM status post, not a brief excerpt.

**Finding the last update window:**
1. Search the account's Slack channel for posts containing `[TAM-UPDATE] #claude-brief-skill`. Use `slack_search_public_and_private` with that query scoped to the channel.
2. If a matching post exists within the last 7 days, use its timestamp as the start of the summary window.
3. If no matching post exists, or the most recent one is older than 7 days, default to a 7-day lookback from today.

**Update content:** Summarize what has happened across the account in that window — meetings, email threads, support tickets, Slack activity, decisions made, next steps. Do not copy verbatim from sources; synthesize into a coherent narrative.

**Format of each update post:**
```
[TAM-UPDATE] #claude-brief-skill

*[Account Name] — TAM Update*
[Date range covered]

[Narrative summary — 2–5 sentences or short bullets]

Next steps:
• [item]
• [item]
```

**Slack channel mapping** — read at runtime from `/config/account-config.json` (inside `BRIEF_DATA_FOLDER_ID` — see `references/item-sync.md` for the full shape). Each account entry's `slack_channel_id` field gives the channel to post to; it's read like any other file in `BRIEF_DATA_FOLDER_ID`, with no separate lookup step needed. Index accounts by `account_name` and all aliases. The channel ID for each account is used to pre-populate the post destination.

Do not hardcode channel IDs here. Always read from `/config/account-config.json` so additions and changes made to that file are automatically reflected.

Add new accounts through First-Run Setup (discover → confirm — see `SKILL.md`); this skill reads `/config/account-config.json` on every run but never writes it during a normal brief.

Generate this as a `card` item (`section: customer-updates`, `item_key: cust-update-{slug}`) with `content: {"textarea": "<generated update>", "channel_id": "<from config>", "last_posted_at": "<timestamp or omitted>"}` — full item shape and the Drive write are in `references/item-sync.md`. Also note the timestamp of the last found `[TAM-UPDATE] #claude-brief-skill` post (or omit `last_posted_at` if none found) next to each account name; when the card's content came from cache, that timestamp is the cache entry's `generated_at`, not the current run time.

---

## Section 4: Manager/Leadership Update

A single collapsed section (collapsed by default) containing one editable text area with a synthesized update across all active accounts and initiatives. Suitable for a quick verbal or written update to your manager. Generated fresh only on a cache miss or explicit refresh, same gate as Section 3.

**Format:**
```
[TAM-UPDATE] #claude-brief-skill

*TAM Weekly Update — [Your Name]*
[Date]

[Account]: [1–2 sentence status]
[Account]: [1–2 sentence status]
...

Key risks: [brief list]
Focus this week: [brief list]
```

**Finding the last manager update:**
Search the manager DM channel (`manager_channel_id` from `config.json`) for `[TAM-UPDATE] #claude-brief-skill`. Use the same 7-day lookback logic as customer updates.

**Posting:** Generate this as a `text-block` item (`section: manager-update`, `item_key: mgr-update`) with `content: {"textarea": "<generated update>", "channel_id": "<manager_channel_id from config.json>"}` — full item shape and the Drive write are in `references/item-sync.md`. The webapp renders the "Post to Manager" button (`https://slack.com/app_redirect?channel={channel_id}`) directly from this item's `content.channel_id`, same as Customer Updates; nothing else to generate for it. Note the last manager update timestamp the same way as customer updates — omit if none found; when served from cache, that's `manager_update.generated_at`, not the current run time.
