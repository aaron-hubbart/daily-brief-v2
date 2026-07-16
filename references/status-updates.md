# Status Updates Reference (Sections 3 & 4)

Read this file only when the generation gate below says to actually generate or regenerate. On runs where the gate says "reuse cache," skip this file entirely and pull the cached content straight from `STATUS_UPDATE_CACHE_FILE_ID` — do not re-run the searches or synthesis described here. This is the single biggest cost item in the whole skill (a fresh per-account Slack search plus full narrative synthesis for every account, every run), so the gate exists specifically to stop that from happening on every "brief me" of the day.

## Generation gate (check this first, every run)

1. Read `STATUS_UPDATE_CACHE_FILE_ID` (a small JSON file in Drive, ID stored in the local Admin Config block). It holds `{ "generated_date": "YYYY-MM-DD", "customer_updates": {...}, "manager_update": "..." }`.
2. **If `generated_date` is today's date:** reuse the cached `customer_updates` and `manager_update` content verbatim for Sections 3/4 in this run's HTML. Do not re-search Slack, do not re-synthesize, do not call any data source for this purpose. Note in the card badges that this is the cached version from earlier today (the existing "last-known-update timestamp" badge already covers this — just make sure it reflects when the cache was written, not the current run time).
3. **If `generated_date` is not today, or the file doesn't exist yet:** generate fresh per the process below, then write the result back to `STATUS_UPDATE_CACHE_FILE_ID` with today's date before finishing the run.
4. **If the user explicitly asks for a refresh** ("regenerate my status update," "there's been a big change with AcmeFin, redo the customer update," etc.) in this or a prior message this session: regenerate regardless of the cached date, and overwrite the cache file with the new content and today's date. A request to regenerate one account's update still requires reading the cache first — leave every other account's cached text untouched and only replace the one account's entry.
5. **If the cache file read fails** (Drive error, file missing and can't be created): fall back to generating fresh for this run, same as a cache miss, and note in the brief that the cache couldn't be read.

This gate only affects Sections 3/4. Sections 1, 2, and the HTML's other sections (Yesterday's Meetings, Today, Action Items, FYI) still run in full on every brief, regardless of cache state.

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

Generate this directly into the HTML: an editable `<textarea>` pre-populated with the generated update, a read-only channel field, and a "Post to Slack" button (`https://slack.com/app_redirect?channel={channel_id}`). Also note the timestamp of the last found `[TAM-UPDATE] #claude-brief-skill` post (or "No previous update found") next to each account name.

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

**Posting:** Generate a "Post to Manager" button in the HTML that opens `https://slack.com/app_redirect?channel=D0A25TNDGJJ`. Note the last manager update timestamp (or "No previous update found") the same way as customer updates.
