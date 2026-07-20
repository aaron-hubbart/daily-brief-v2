# Status Updates Reference (Sections 3 & 4)

Read this file only when the generation gate below says to actually generate or regenerate. On runs where the gate says "reuse cache," skip this file entirely and pull the cached content straight from `STATUS_UPDATE_CACHE_FILE_ID` — do not re-run the searches or synthesis described here. This is the single biggest cost item in the whole skill (a fresh per-account Slack search plus full narrative synthesis for every account, every run), so the gate exists specifically to stop that from happening on every "brief me" of the day.

## Cache schema

`STATUS_UPDATE_CACHE_FILE_ID` is a small JSON file in Drive holding per-entry state, not one global flag — this is what makes a single-account refresh possible without touching the other seven:

```json
{
  "customer_updates": {
    "Acme Financial": { "content": "...", "generated_at": "2026-07-20T13:05:00Z", "window_start": "2026-07-13T00:00:00Z" },
    "Zebra Financial": { "content": "...", "generated_at": "2026-07-20T13:05:00Z", "window_start": "..." }
  },
  "manager_update": { "content": "...", "generated_at": "2026-07-20T13:05:00Z" }
}
```

Key by Account Name exactly as it appears in `Meeting Manager Config.xlsx`, so entries line up with the account list read at generation time.

## Generation gate (check this first, every run that reaches Section 3/4)

Evaluate this **per account** (and separately for the manager update), not once for the whole section — a full brief run can end up reusing six cached accounts and regenerating two, all in the same pass.

1. Read `STATUS_UPDATE_CACHE_FILE_ID`.
2. **For each account:** if `customer_updates[account].generated_at` falls on today's local date, reuse that `content` verbatim — no Slack search, no synthesis. If it's missing or dated before today, generate fresh per the process below, then write the new `content` and `generated_at` (now) back into that account's entry only. Leave every other account's entry in the file untouched.
3. **Manager update:** same rule against `manager_update.generated_at`.
4. **Explicit refresh request** ("refresh the AcmeFin update," "regenerate manager update," or a click on a card's Refresh button — see `references/section-refresh.md`) forces regeneration for that one named entry regardless of its `generated_at` date, and overwrites only that entry.
5. **Cache read fails** (Drive error, file missing and can't be created): treat every entry as a miss for this run — generate fresh for all of them, and note in the brief that the cache couldn't be read. Don't block the brief on this.
6. **New account not yet in the cache file:** treat as a miss, generate, add its entry.

This gate only affects Sections 3/4. Sections 1, 2, and the HTML's other sections (Yesterday's Meetings, Today, Action Items, FYI) still run in full on every brief, regardless of cache state.

A card's Refresh button (see `references/section-refresh.md`) is the normal path for an out-of-band update once the daily gate has already run once — it patches a single card into the latest existing file rather than triggering a full brief.

---

## Section 3: Customer Updates

One collapsible card per customer account on your assigned list — every account listed in the Accounts sheet of `Meeting Manager Config.xlsx` (root of your Google Drive, file ID stored in Claude memory as `meeting_manager_config_id`), not just accounts with signals in the current pull. Read the account list fresh from the config file each time this section is actually generated (i.e., on a cache miss or explicit refresh) — do not rely on a previously-known or hardcoded list, since accounts can be added or removed in the config independent of this skill. The entire section is also collapsed by default.

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

**Slack channel mapping** — read at runtime from the Meeting Manager Config.xlsx file (file ID stored in Claude memory as `meeting_manager_config_id`). The Accounts sheet contains a `Slack Channel ID` column. Load the file using the same routing table logic in the meeting-manager skill (Step 1 of routing-table.md). Index accounts by Account Name and all aliases. The channel ID for each account is used to pre-populate the post destination.

Do not hardcode channel IDs here. Always read from the config file so additions and changes made to the xlsx are automatically reflected.

Add new accounts to the Meeting Manager Config.xlsx Accounts sheet (including their Slack Channel ID) as they are onboarded.

Generate this directly into the HTML: an editable `<textarea>` pre-populated with the generated update, a read-only channel field, a "Post to Slack" button (`https://slack.com/app_redirect?channel={channel_id}`), and a "Refresh" button — markup and `data-id` requirements for the card are in `references/html-output.md`. Also note the timestamp of the last found `[TAM-UPDATE] #claude-brief-skill` post (or "No previous update found") next to each account name; when the card's content came from cache, that timestamp is the cache entry's `generated_at`, not the current run time.

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
Search the manager DM channel (`D0A25TNDGJJ`) for `[TAM-UPDATE] #claude-brief-skill`. Use the same 7-day lookback logic as customer updates.

**Posting:** Generate a "Post to Manager" button in the HTML that opens `https://slack.com/app_redirect?channel=D0A25TNDGJJ`, plus a "Refresh" button (same markup pattern as Customer Updates — see `references/html-output.md`). Note the last manager update timestamp (or "No previous update found") the same way as customer updates; when served from cache, that's `manager_update.generated_at`, not the current run time.
