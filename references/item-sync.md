# Item Sync Reference

Read this file when you reach the sync step in a brief run. It is used on every run (items are always synced), but lives here rather than in `SKILL.md` so the core skill file stays short for the trigger/timing/data-pull decisions that happen before sync starts.

## Drive data layout

Every brief run writes JSON files into `BRIEF_DATA_FOLDER_ID` (your own Drive
folder, its ID stored in `config.json`). Two write paths are used:

1. **New section files** (everything under `/briefs/{date}/`): use the
   `Google Drive: create_file` connector. These files are new each date.
2. **Existing files updated in place** (`config.json` and the status-update
   cache): use the Google Drive REST API v3 PATCH method via `bash_tool`
   with an OAuth2 token (see "Google Drive write mechanics" in `SKILL.md`).
   These files have stable IDs that must not change between runs.

**This skill is responsible for creating the folder hierarchy below itself, but only for folders that don't already exist.** Before creating any folder, query `BRIEF_DATA_FOLDER_ID` to check if `/briefs`, `/config`, `/briefs/{date}`, `/briefs/{date}/accounts`, and `/briefs/{date}/updates` folders already exist. Use the existing folder IDs for all file writes; only create new folders if they don't exist. This prevents duplicate folder creation on subsequent brief runs — the first run creates the hierarchy, and later runs reuse the existing folder IDs instead of creating duplicates.

The folder hierarchy is: `/briefs` (root for all briefs), `/briefs/{date}` (date-specific subfolder), `/briefs/{date}/accounts` and `/briefs/{date}/updates` (category subfolders), and `/config` (configuration files). `viewer-backend/drive_store.py` (the hosted webapp's backend) never creates any of these; the only folder it ever creates is `/state`, lazily, on the first checkbox/due-date edit from the webapp — every read path there just returns empty/None when `/briefs`, `/config`, or a given `{date}` folder is absent. Confirm at runtime whether creating a file at a nested path via `Google Drive: create_file` auto-creates intermediate folders, or whether folders must be created explicitly first with a separate step/tool — check what's actually available in the connector rather than assuming either behavior.

```
/briefs/{date}/manifest.json          — date, brief_type, generated_at
/briefs/{date}/meetings.json          — Section 1 Part A, array of items
/briefs/{date}/accounts/{slug}.json   — Section 1 Part B, one file per account/initiative (a single item object, not an array)
/briefs/{date}/today.json             — Section 2, array of items
/briefs/{date}/action-items.json      — Section 2 action items (New Items only — see the Action Items note below), array of items
/briefs/{date}/fyi.json               — array of items
/briefs/{date}/updates/{slug}.json    — Section 3, one file per account (a single item object, not an array)
/briefs/{date}/manager-update.json    — Section 4, a single item object
/state/...                            — per-date, per-user checkbox/due-date overrides — written by the hosted webapp only; this skill never creates or reads this folder
```

`{date}` is the brief's `YYYY-MM-DD` date. `{slug}` is the same lowercase,
hyphenated account/initiative slug already used in `item_key` conventions
below.

`manifest.json` is `{"brief_date": "...", "brief_type": "morning"|"midday"|"evening", "generated_at": "<ISO timestamp>"}` — the webapp reads this to know a brief exists for that date and what type it was; it doesn't need a section list or item count (those are derived from the section files themselves at render time).

**Every array-shaped section file (`meetings.json`, `today.json`, `action-items.json`, `fyi.json`) holds the WHOLE section's items for that date in one file** — not one file per item. A full brief run writes the complete array in one `create_file` call — **except `action-items.json`, which is a read-merge-rewrite on every run, not a blind overwrite; see the Action Items section below for why it's the one exception.** A patch to a single item within one of these sections (post-meeting-patch, a single-item refresh) means re-reading the array (if this run isn't the first write of the day), changing just the one item by matching on `item_key`, and writing the complete updated array back via `create_file`** — the create-only connector means this is always a new file version, never an in-place edit; the webapp always reads the newest-by-creation-time file per path. See `references/post-meeting-patch.md` and `references/section-refresh.md` for exactly when and how this applies.

The one-file-per-account sections (`accounts/{slug}.json`, `updates/{slug}.json`) don't have this merge step — the whole file already is the one item, so writing a fresh version of it via `create_file` is a complete, self-contained patch with nothing else to preserve.

## Account/Asana project config

The `/config` folder inside `BRIEF_DATA_FOLDER_ID` holds two hand-relevant files: `config.json` (the skill's own settings, created and written by the First-Run Setup flow — see `SKILL.md`) and `account-config.json` (below, built and updated by the First-Run Setup flow). The skill reads `config.json` at the start of every run to resolve `BRIEF_DATA_FOLDER_ID` and its other settings.

`/config/account-config.json` (inside `BRIEF_DATA_FOLDER_ID`) replaces this skill's reliance on `Meeting Manager Config.xlsx` for the account → Slack channel ID → Asana project GID mapping used below and in Action Items. Shape:
```json
{
  "accounts": [
    {
      "account_name": "Acme Financial",
      "tier": "primary",
      "run_day": null,
      "slack_channel_id": "C0XXXXXXX",
      "supporting_slack_channel_ids": ["C0XXXXXXX"],
      "project_gid": "111222333",
      "asana_board_name": "Acme Financial",
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

### Sections, in order

Seven fixed section slugs, matching the webapp's `SECTIONS` list and the existing skill section conventions: `yesterday-meetings`, `account-recap`, `today`, `action-items`, `fyi`, `customer-updates`, `manager-update`. There is no eighth "header" item — the header (date, brief type, progress) is computed by the webapp from the date's `manifest.json` (`brief_type`) and its items, not generated by the skill.

### Item shape

Every item written is: `{section, item_key, item_type, title?, subtitle?, badge?, links?, content?, checked?, display_order?}`. See `viewer-backend/drive_store.py`'s `get_items_for_day` and the "Drive data layout" section above for the authoritative shape; this section maps each brief section onto it.

- **`item_type`** — one of `checkable`, `card`, `fyi`, `text-block`. Sections 1 (both parts), Today, and Action Items are `checkable`, except Today's single `today-standup` entry, which is `card`. FYI is `fyi`. Customer Updates cards are `card`. Manager Update is `text-block`.
- **`title` is required on every `card` item** (the account name, e.g. `"Acme Financial"`) — the webapp's card header and its Refresh link both read `item.title` directly, and a missing value throws a template `TypeError` (string concatenation with `None`) that 500s the whole `/brief/{date}` page, not just that one card. Set it explicitly on every Customer Updates entry you write even though the general shape line above marks `title` as optional at the field level — that optionality is real for `checkable`/`fyi` items (where `subtitle` alone can carry the content) but not for `card`. Set `title` on the Manager Update's single `text-block` item too (e.g. `"Manager Update"`) for the same reason, even though today's template doesn't yet read it there — keeps both content-heavy types to the same rule rather than relying on the current template not needing it.
- **`badge`** — `{"label": "...", "class": "bwarn"|"bbad"}` or omit/null. `bwarn` for tentative/needs-confirmation/time-sensitive; `bbad` for overdue/blocking/critical.
- **`links`** — array of `{"label": "...", "url": "...", "class": "lbtn primary"|"lbtn"}`. Use `lbtn primary` for the primary CTA (Join Zoom, Open doc), `lbtn` for secondary links (Asana task, Slack thread, email). Every `url` must be a real URL from the data — never a placeholder. Omit the link entirely when no real URL exists; never send a placeholder link.
- **`checked`** — `false` for every `checkable` item on every write (including patches — see below). For `fyi`, `card`, and `text-block`, **omit the field entirely**, for JSON cleanliness — an explicit `null` is also acceptable to a JSON reader, but omission is the convention this skill uses, so stay consistent with it rather than sending `"checked": null`.
- **`content`** — `{}` for `checkable`/`fyi` items in most sections (everything needed to render lives in title/subtitle/badge/links), **except Action Items**, which requires `{"due_on": "YYYY-MM-DD" or null, "is_new": true, "project_name": "..." or null}` — see the Action Items note below for what populates these, and why `is_new` is always `true` for what this skill sends. For `card`: `{"textarea": "...", "channel_id": "...", "last_posted_at": "..."}`. For `text-block`: `{"textarea": "..."}`.
- **`display_order`** — 0-indexed integer reflecting the intended render order within that section (priority order for account-recap, chronological for meetings, etc.).

### item_key conventions

`(section, item_key)` is the natural key that identifies an item within a given date's files — a patch (post-meeting-patch, section-refresh) has to recompute the same `item_key` a full run would have produced for that same item, exactly as before, so it can find and replace the matching entry when rewriting a section's file. Use these conventions, all lowercase, spaces replaced with hyphens ("slug"):

1. **Yesterday's Meetings** (Section 1, Part A) — `ym-{HHmm}-{slug(title)}`, e.g. `ym-0900-acmefin-triage`. Time- and title-derived rather than positional (`ym-1`, `ym-2`, ...) specifically so `references/post-meeting-patch.md` can recompute the exact same key for the meeting it's patching without needing to find or parse anything — a position-based key would shift if the meeting list composition changed between the original run and the patch.
2. **Account / Initiative Recap** (Section 1, Part B) — `recap-{slug(account or initiative name)}`.
3. **Today** — `today-{HHmm}-{slug(title)}`, same reasoning as Yesterday's Meetings.
4. **Action Items** — `action-{asana_gid}`. Every action item resolves to a real Asana task (see below), so the task's own GID is the natural stable key — no separate numbering scheme needed.
5. **FYI** — `fyi-{n}` (1-indexed within the run). No patch flow reads this section, so positional numbering is fine here.
6. **Customer Updates** — `cust-update-{slug(account name)}`, one card per assigned account.
7. **Manager Update** — always exactly `mgr-update`.

### Section-specific notes

**Yesterday's Meetings** — one checkable item per meeting from the last business day. Title, time, attendees in `title`/`subtitle`; a recording/transcript link in `links` if `get_meeting_assets` found one; an Asana action-item status line folded into `subtitle`. If no recording/transcript was found, `badge` is `{"label": "not found — needs input", "class": "bbad"}` and `subtitle` asks directly for a link or transcript; include the `claude://claude.ai/new?q=` deep-link (see Action Items below) as a `links` entry so the person can click straight into a Claude Desktop conversation pre-filled with `/meeting-manager Run post-meeting notes for: [meeting] ([date])`. The `get_meeting_assets` check runs for every meeting regardless of the calendar's hosting platform - the Zoom lookup is by title+date, not by the calendar's join URL.

**Account / Initiative Recap** — one checkable item per account/initiative, ordered per the priority rule in `SKILL.md` (active-signal accounts first, then internal initiatives, then the mandatory "General / Admin" catch-all). `title` is the account/initiative name; `subtitle` is the synthesized narrative paragraph. Include a `links` entry only when a specific source link is directly relevant; most recap items have no badge and no links.

**Today** — checkable item per meeting for the full current day, past or future. Append " (occurred)" to `title` for any meeting whose end time has already passed at brief-generation time. Include a Join link in `links` if a Zoom/Webex/Teams URL is present, plus a meeting-prep output link once prep exists or has just been generated by this run (see `SKILL.md` for the meeting-manager pre-meeting trigger rule).

**Every Today item also always carries two `claude://` deep-links, regardless of meeting type, size, or whether prep already exists — no qualifying criteria, no exceptions:**
- **Pre-meeting prep**: `href="claude://claude.ai/new?q=" + encodeURIComponent('/meeting-manager Run pre-meeting prep for: ' + meetingTitle + ' (' + dateOrTime + ')')`, labeled "Prep in Claude Desktop". For use before the meeting concludes.
- **Post-meeting notes**: `href="claude://claude.ai/new?q=" + encodeURIComponent('/meeting-manager Run post-meeting notes for: ' + meetingTitle + ' (' + dateOrTime + ')')`, labeled "Process in Claude Desktop" (same pattern already used for Yesterday's Meetings and the "recording not found" flow). For use once the meeting has concluded.

Both links are added to every Today item unconditionally, in addition to the Join link and any meeting-prep output link — they do not replace either of those, and their presence is independent of whether meeting-prep has already run for that meeting.

**Action Items** — checkable item per actionable thing needing attention today. **Every action item must resolve to a real Asana task, created automatically if one doesn't already exist, and every such task must always land on a project — never bare "My Tasks" with no project at all.** Before generating this section, collect the full list of action items needing a new task, then create them in a single `Asana:create_tasks` call (accepts 1-50 tasks per call) rather than one at a time. Search Asana first for an existing matching task (by text, scoped to the relevant account project if known); only include items with no existing match in the batch create call. Use `assignee: "me"`, `due_on` today, and set `project_id` per this priority, in order:

1. **The account's Asana Project GID** from `/config/account-config.json`, when the action item is clearly tied to a specific customer account.
2. **The Internal Asana Project GID** — read from `/config/account-config.json`'s top-level `internal_project_gid` key, for anything not tied to a specific customer account: internal admin, tiger-team work, personal follow-ups, or a customer-account item where the account genuinely has no configured project GID in `account-config.json`. This is a different project than `RECURRING_ACTIVITIES_PROJECT_GID` (that one is specifically for recurring TAM activities, not a general catch-all) — don't conflate the two.

There is no third option and no "leave it unassigned" fallback — a missing account mapping is a reason to use the internal board, never a reason to omit `project_id` and let the task land bare in My Tasks. Always put the real Asana permalink (`https://app.asana.com/0/0/{gid}/f`) in `links` — never a placeholder.

**Only write newly-created tasks to `action-items.json`.** As of the live-pull architecture below, this skill only writes an Action Items entry for a task where `content.is_new` is `true` — i.e. the exact tasks this run just created via `Asana:create_tasks`. Do NOT write an entry for a task that already existed and was found via search rather than created. The webapp pulls those directly from Asana itself at page-render time (see "Live-pulled subsections" below), so a skill-side entry for them would just be a second, staler copy of the same task competing with the live one. This means the search-first step above still matters for avoiding duplicate task creation, but its result (a found match) no longer needs a corresponding entry written — only its absence (triggering a create) does.

**This creates a read-merge-rewrite requirement on `action-items.json` for every run, not just refreshes.** Because only newly-created tasks are ever written, and a same-day re-run's search-first step finds earlier same-day creates rather than re-creating them, a second (or third) full brief run's "what this run newly created" is only whatever's new *this* run — not the tasks logged by the earlier run(s) that day. Blind-overwriting `action-items.json` with just this run's new creates would silently drop those earlier entries even though the tasks are still open and still logged in Asana — unlike Overdue/Due Next 7 Days/No Due Date, New Items has no live-pull fallback, so a dropped entry is simply gone from the brief until someone notices. This is why Action Items differs from the other array-shaped sections (`meetings.json`, `today.json`, `fyi.json`): for those, a full brief run's blind overwrite is correct, because a fresh full data-source re-pull (recalendaring the day, re-summarizing Slack, etc.) is authoritative and is meant to fully replace what came before. Action Items is not like that — its write set is a strict subset (creates-only) of what must persist across repeat same-day runs, so a full overwrite is never correct here. Therefore, **before writing `action-items.json` on any run — full brief or patch, not only a section-level refresh** — read the current `/briefs/{brief_date}/action-items.json` first if one exists for that date (skip the read only if this is the first write of the day), keep every existing entry in that file unconditionally, append only the entries for tasks this run's Asana search/create step just newly created (a newly-created task always gets a brand-new `action-{asana_gid}` key, so there's no collision to resolve), and write the resulting merged array back via `Google Drive: create_file`. This is the same read-merge-rewrite pattern already established for the Action Items exception in `references/section-refresh.md` — applied here to every run of the day, since that file's version only covers the section-refresh trigger.

Populate `content.project_name` on every item you do write (the newly-created ones) from the task's own project membership, not from the account mapping used to create it. Do not assume `create_tasks` responses already include project names — they don't reliably return the `projects` field without it being explicitly requested, which is why this previously defaulted to null on every item. After each task is created, call `Asana:get_task` on its GID with `opt_fields: "projects.name"` and read the project name(s) from that response — this is a required step, not an optional enrichment. Use the first project's `name`; if the task belongs to more than one project, join the names with ", ". Since every task now always gets a `project_id` at creation (customer board or the internal fallback — see the Action Items note above), a genuinely empty `projects` array back from `get_task` means something went wrong with the create call itself, not an expected "no mapping" case — treat `project_name: null` as a signal worth a line in the brief's error handling, not a normal outcome to silently accept. For items where meeting-manager applies (post-meeting processing needed, most commonly a missing recording/transcript from Yesterday's Meetings), add a second `links` entry using the same `claude://` deep-link pattern: `href="claude://claude.ai/new?q=" + encodeURIComponent('/meeting-manager Run post-meeting notes for: ' + meetingTitle + ' (' + dateOrTime + ')')`. Only add this when meeting-manager genuinely applies. Note once in the brief output (not per item) that this link requires Claude Desktop registered as the `claude://` protocol handler.

Set `content` on every entry you write to `{"due_on": "<the new task's due_on>", "is_new": true, "project_name": "..." or null}`. `is_new` is always `true` here since, per the rule above, this skill no longer writes any entry where it would be `false` — there's no later "refresh" of an Action Items entry that flips it. The webapp still labels this bucket "New Items" and always renders it first.

**Live-pulled subsections (Overdue, Due Next 7 Days, No Due Date) — this skill has no role in these.** The webapp fetches them directly from Asana on every page load, using the signed-in person's own Asana Personal Access Token (set up via the viewer's Account panel, entirely separate from this skill's own Asana connector) and the account→project-GID mapping it reads directly from `/config/account-config.json` (see "Account/Asana project config" above) — there's no sync step involved, per that section's note that the entire `daily_brief_sync_account_projects`-equivalent sync step is gone. If that person hasn't configured a token, the webapp simply omits those three subsections and shows New Items only — this skill doesn't need to detect or work around that either way.

New Items' due date can still be edited directly from the webapp's due-date box after the fact (see `viewer-backend/templates/brief_fragment.html`) — that write goes straight to that date's own `/state/{date}.json` file (via `drive_store.py`'s `set_item_due_date`) and the linked Asana task, bypassing this skill entirely, so if the same task is still new enough to be re-written on a same-day patch, reflect whatever `due_on` Asana now reports rather than assuming this skill's own last-sent value is still current.

**FYI** — non-actionable signals worth knowing: post-meeting summaries generated, recurring tasks spawned, informational Slack threads, status summary highlights. Same link standard as Action Items — a real URL in `links` whenever one exists (Zoom summary/recording, Slack permalink, calendar `webLink`, Asana permalink for a spawned recurring task); omit when none exists.

**Customer Updates** — `item_type: card`, one per in-scope account (all primary accounts plus any in-scope secondary accounts — see Resolve In-Scope Accounts in `SKILL.md`; not just accounts with signals this run). `content.textarea` holds the generated update (see `references/status-updates.md`); `content.channel_id` the account's Slack channel ID; `content.last_posted_at` the timestamp of the last found `[TAM-UPDATE] #claude-brief-skill` post, or omit if none was found. Content is gated by the cache in `references/status-updates.md` — read that file before regenerating.

**Manager Update** — `item_type: text-block`, always exactly one item, `item_key: mgr-update`. `content.textarea` holds the synthesized update. Same caching rule as Customer Updates.

### Slack posting affordances

The webapp renders a "Post to Slack" button on each Customer Update card, on the Manager Update, and on the Today section's Team Standup card — all three build the same `https://slack.com/app_redirect?channel={channel_id}` URL from that item's own `content.channel_id`, not something the skill needs to construct or send separately. Customer Updates source `channel_id` from the account's entry in `/config/account-config.json`; Manager Update and the Team Standup card source theirs from `config.json`'s `manager_channel_id` and `geekbot_channel_id` respectively. The skill just needs `content.channel_id` populated correctly in each case.

### Error handling

If a Drive write fails (the `create_file` call errors, or `BRIEF_DATA_FOLDER_ID` isn't accessible), don't block or retry the in-chat response — note briefly in the brief output that a file didn't write, and why if known. The in-chat response is the reliable fallback either way.

### Repo hygiene

Never commit a real token value, real payload content (real names, meeting titles, account data), or this skill's local `CONFIG_FILE_ID` value to the public repo. The `example/` folder is for sanitized demo content only, with fictional names and companies (e.g. "Acme Financial", "Pinnacle Health", "Meridian Bank") — never real account names, email addresses, Slack user IDs, Asana GIDs, Zoom meeting IDs, or calendar event IDs.
