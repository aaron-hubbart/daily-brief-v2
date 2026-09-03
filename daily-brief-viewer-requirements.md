
# Daily Brief Viewer: Build Requirements

Prepared for a Lovable or Replit build. Pulled directly from `main` on `aaron-hubbart/daily-brief-v2` (repo cloned via the stored GitHub PAT), specifically `viewer/webapp/` (the hosted Flask app: `app.py`, `db.py`, `gdrive_briefs.py`, `db/schema.sql`, `templates/`), `viewer/webapp/DEPLOYMENT.md`, and the skill's own `references/item-sync.md`.

This revision splits the document into what exists today (As-Is) and what the new build should be (To-Be). The As-Is section documents the current production app's live Google Drive read approach. The To-Be section describes the target: a backend database that holds all brief data, so the app queries its own store instead of calling Drive and Asana on every page load.

## Executive summary

The Daily Brief Viewer displays a TAM's daily briefing, generated separately by a Claude skill and written to Google Drive. The production app today reads that Drive data live on every page load, plus polls Asana live for overdue and upcoming tasks. That design works but ties every page load to two third-party APIs, so a Drive hiccup or a slow Asana response shows up directly as a slow or broken page.

The recommended target replaces those live calls with a small backend database. A sync job reads Drive and Asana on a schedule (plus on demand, for a Refresh click or a new date) and loads everything into that database; the app itself only ever queries its own store. This is a standard pattern, not a novel one, and both Lovable and Replit support it natively. It also opens up things the live-read version can't easily do: a retention policy, sync-health visibility per user, and faster, more consistent page loads.

The rebuild does not touch the Claude skill or how it generates brief content; it only changes how the viewer gets that content onto the page. Scope-wise, this is a data layer and a handful of screens, not a large product. The main decision left open is in Section 13: how much of the multi-user/admin surface and the Asana two-way sync to carry into a personal tool versus building single-user and simpler.

## 1. What this application is

A web app that renders a TAM's daily briefing. It does not generate the briefing; a separate Claude skill (`daily-brief-v2`) pulls from Outlook, Slack, Zoom, and Asana, synthesizes the content, and writes it as JSON files into Google Drive. Today the viewer reads that Drive data live, on every page load. The new build should instead ingest that data into a proper backend database and serve every page from it.

## 2. As-Is: current production architecture (Drive-read)

### 2.1 Data flow today

Claude skill → writes JSON directly into the signed-in user's own Google Drive folder → webapp reads that folder live, at the moment someone opens a brief → renders the page. Nothing about brief content is stored by the webapp itself; the only thing it persists is account/session state and per-date checkbox/due-date overrides.

### 2.2 Auth

Two stages. Company SSO first (Microsoft Entra ID via MSAL in the reference app, restricted to `@camunda.com`). Then, separately, each signed-in person connects their own Google account (OAuth, Drive read-only scope) and enters the Drive folder ID where their brief data lives. There is no shared service account and no single folder ID; it's per user.

### 2.3 Read path

`GET /brief/{date}` loads just the manifest and a placeholder per section, then each section's content loads via its own async call (`GET /api/brief/{date}/section/{slug}`), so a slow Drive call for one section never blocks the rest of the page. Action Items is handled separately again: its live Asana portion loads through its own async endpoint (`GET /api/brief/{date}/live-action-items`), since an Asana round trip is the slowest single call on the page.

### 2.4 Drive layout being read

```
/briefs/{date}/manifest.json          — {"brief_date", "brief_type", "generated_at"}
/briefs/{date}/meetings.json          — array of items (Yesterday's Meetings)
/briefs/{date}/accounts/{slug}.json   — one file per account/initiative (Account/Initiative Recap)
/briefs/{date}/today.json             — array of items (Today)
/briefs/{date}/action-items.json      — array of items, "new items" only (Action Items)
/briefs/{date}/fyi.json               — array of items (FYI)
/briefs/{date}/updates/{slug}.json    — one file per account (Customer Updates)
/briefs/{date}/manager-update.json    — single item (Manager Update)
/config/account-config.json           — account list, Slack channel IDs, Asana project GIDs
```

### 2.5 State the webapp itself owns

`/state/{date}.json`, written back into the same Drive folder, lazily, on the first checkbox toggle or due-date edit for that date: `{"{section}:{item_key}": {"checked": bool|null, "due_on_override": "YYYY-MM-DD"|null}, ...}`. On load, source files render first, then this file's overrides apply on top.

### 2.6 Live Asana pull and two-way sync

Action Items' Overdue, Due Next 7 Days, and No Due Date subsections are fetched live from Asana on every render, using the signed-in person's own Asana personal access token plus the `account_name` → `project_gid` map from `/config/account-config.json`. No token configured means those three subsections are simply omitted. Checking a box or editing a due date on an item whose `item_key` matches `action-{asana_gid}` also best-effort mirrors onto the Asana task itself (complete/reopen, or update `due_on`); this never blocks or rolls back the primary write.

### 2.7 Known inconsistency, not to be carried forward

Older code paths in the reference app (`db.py`, a `users`/`brief_days`/`items` Postgres schema, `POST /api/items/upsert`) still exist from an earlier design where the skill pushed content to the webapp via a bearer-token API instead of writing to Drive. That path is legacy; the skill has moved to writing Drive directly and the render path no longer reads from it. Don't reproduce this half-migrated state in a fresh build — pick one design, which is exactly what Section 3 does.

## 3. To-Be: target architecture (backend database)

### 3.1 Why

Live Drive and Asana calls on every page load mean every request is only as fast and as reliable as two third-party APIs, and browsing history means re-fetching data that hasn't changed since the last visit. Loading brief data into a backend database once, then serving every page from that database, fixes both: fast, consistent reads regardless of Drive or Asana's mood that day, and a real place to apply retention, run cross-date queries, or extend the product later without touching the ingestion path.

### 3.2 Data flow to build

Claude skill → writes JSON into Google Drive, unchanged, since the skill itself is out of scope for this build → a sync/ingestion process reads Drive and upserts into the backend database → the webapp reads only from that database, never from Drive at page-render time → renders the page. Asana move the same direction: ingest into the database on a short cycle rather than calling Asana synchronously inside a page request.

### 3.3 Ingestion mechanism

Two triggers, and building both is worth it rather than picking one:

- **Scheduled sync.** A background job, on a short interval (every few minutes is reasonable for a personal tool), that pulls each connected user's Drive folder for recent dates (today, plus however many days back the UI still shows) and upserts any items into the database. Reuses the same per-user Google OAuth refresh token described in Section 2.2.
- **On-demand sync.** A manual "Sync now" control in the UI, and an automatic sync check whenever someone opens a date that isn't in the database yet or whose `manifest.json` `generated_at` in Drive is newer than what's stored. This covers the gap between scheduled runs without needing a tight polling interval.

Ingestion is additive/upsert, keyed on `(user, brief_date, section, item_key)` — the same natural key the skill already uses in Drive. A re-sync of a date that's already ingested updates existing rows rather than duplicating them.

Asana ingestion (Overdue, Due Next 7 Days, No Due Date) runs on the same scheduled-plus-on-demand pattern, writing into its own table with a short freshness window (a few minutes), rather than being fetched inline during a page request. Refreshing the Action Items section in the UI can force an immediate re-pull for that one user rather than waiting for the next scheduled cycle.

### 3.4 Database schema

```sql
CREATE TABLE users (
    id                    SERIAL PRIMARY KEY,
    email                 TEXT NOT NULL UNIQUE,
    google_refresh_token  TEXT,            -- encrypted at rest
    google_drive_folder_id TEXT,
    asana_pat             TEXT,            -- encrypted at rest
    last_synced_at        TIMESTAMPTZ,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE brief_days (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    brief_date      DATE NOT NULL,
    brief_type      TEXT,                 -- 'morning' | 'midday' | 'evening'
    source_generated_at TIMESTAMPTZ,       -- manifest.json's generated_at, used to detect a newer Drive version
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    UNIQUE (user_id, brief_date)
);

CREATE TABLE items (
    id            SERIAL PRIMARY KEY,
    brief_day_id  INTEGER NOT NULL REFERENCES brief_days(id) ON DELETE CASCADE,
    section       TEXT NOT NULL,
    item_key      TEXT NOT NULL,
    item_type     TEXT NOT NULL CHECK (item_type IN ('checkable', 'card', 'fyi', 'text-block')),
    title         TEXT,
    subtitle      TEXT,
    badge         JSONB,
    links         JSONB NOT NULL DEFAULT '[]',
    content       JSONB NOT NULL DEFAULT '{}',
    checked       BOOLEAN,                -- user-editable directly; replaces the old /state file for this
    due_on        DATE,                   -- user-editable directly, Action Items only
    display_order INTEGER NOT NULL DEFAULT 0,
    synced_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (brief_day_id, section, item_key)
);

CREATE TABLE account_projects (
    id           SERIAL PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_name TEXT NOT NULL,
    project_gid  TEXT NOT NULL,
    synced_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, account_name)
);

CREATE TABLE live_action_items (
    id           SERIAL PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    asana_gid    TEXT NOT NULL,
    bucket       TEXT NOT NULL CHECK (bucket IN ('overdue', 'due-soon', 'no-due-date')),
    title        TEXT,
    due_on       DATE,
    project_name TEXT,
    url          TEXT,
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, asana_gid)
);
```

`checked` and `due_on` live directly on `items` now, so there's no separate overrides file to merge at render time the way `/state/{date}.json` worked in Section 2.5 — an edit is just an `UPDATE` on the row, and a re-sync from Drive should never blindly overwrite a `checked` or `due_on` value a person has already set locally; only overwrite the source-derived fields (`title`, `subtitle`, `badge`, `links`, `content`) on re-sync, and only set `checked`/`due_on` from Drive on first insert of a row.

`live_action_items` is a full-replace-per-sync table (delete the user's rows for a bucket and reinsert on each pull), since these three subsections have no local edits to preserve between syncs the way New Items does — the New Items bucket is stored as ordinary `items` rows (`section = 'action-items'`) which do carry edits.

### 3.5 Two-way Asana sync

Keep the same behavior as Section 2.6: editing `checked` or `due_on` on an `items` row whose `item_key` is `action-{asana_gid}` writes to the database immediately and best-effort mirrors to the Asana task afterward, never blocking on the Asana call's success. Editing a row in `live_action_items` (an Overdue/Due Next 7 Days/No Due Date item) writes straight to Asana, since that table is a cache that gets wiped on the next sync rather than a place to store a durable local edit.

### 3.6 Retention and archival

Now meaningful again, since the database is genuinely this app's own storage rather than a live window onto someone else's Drive: mark `brief_days` older than some threshold (14 days is what the reference app used) as `archived` (hidden from the normal date picker, still queryable), and delete rows past a longer threshold (30 days). Run this on a schedule. This does not touch anything in the user's Drive; it only prunes the ingested copy.

### 3.7 Rendering

With reads coming from the database, the progressive per-section loading pattern in Section 2.3 becomes optional rather than load-bearing; a database query for one date's items is cheap enough to return the whole page in one request. Keep progressive loading only if there's a product reason to want it (perceived performance, a nicer loading state), not because the backend needs it.

## 4. Item shape (unchanged by the storage backend)

```json
{
  "section": "yesterday-meetings",
  "item_key": "ym-0900-acmefin-triage",
  "item_type": "checkable",
  "title": "...",
  "subtitle": "...",
  "badge": { "label": "...", "class": "bwarn" },
  "links": [ { "label": "...", "url": "...", "class": "lbtn primary" } ],
  "content": {},
  "checked": false,
  "display_order": 0
}
```

`item_type` is one of `checkable`, `card`, `fyi`, `text-block`. `title` is required and must render safely even if null. `badge.class` is `bwarn` (tentative/time-sensitive) or `bbad` (overdue/blocking); style them distinctly. `links[].class` is `lbtn primary` (primary call-to-action) or `lbtn` (secondary); only render a link when `url` is present. `checked` applies only to `checkable` items. `display_order` is 0-indexed render order within its section.

The seven canonical section slugs, in fixed order, with default expand state:

| Slug | Label | Open by default |
|---|---|---|
| `yesterday-meetings` | Yesterday's Meetings | yes |
| `account-recap` | Account / Initiative Recap | yes |
| `today` | Today | yes |
| `action-items` | Action Items | yes |
| `fyi` | FYI | yes |
| `customer-updates` | Customer Updates | no |
| `manager-update` | Manager / Leadership Update | no |

## 5. Section-by-section rendering requirements

**Yesterday's Meetings** (checkable) — one row per meeting from the prior business day, chronological. Title, time, attendees, recording/transcript status. A `bbad` "not found — needs input" badge means render its `subtitle` (a direct ask for a link or transcript) and its Claude Desktop deep link prominently.

**Account / Initiative Recap** (checkable) — one row per account or initiative, narrative in `subtitle`, ordered by `display_order`. A "Secondary Accounts" grouping and a catch-all "General / Admin" row are normal, expected rows.

**Today** (checkable) — one row per meeting for the current day; titles may already carry "(occurred)". Up to four links per row: Join, meeting-prep output, "Prep in Claude Desktop," "Process in Claude Desktop." Render whichever are present.

**Action Items** (checkable, the most complex screen) — four fixed subsections, in this order and with these exact labels: **New Items**, **Overdue**, **Due Next 7 Days**, **No Due Date**. New Items comes from `items` rows; the other three come from `live_action_items` (Section 3.4), excluding any Asana GID already present in New Items. If no Asana token is configured, omit the three live subsections and show New Items only, with a visible prompt to connect one in settings. Every item, stored or live, gets a due-date control with one-click shortcut buttons (Today, Tomorrow, Next week, Next month) alongside the date input.

**FYI** (`fyi`) — non-actionable, no checkbox, a link where one exists.

**Customer Updates** (`card`) — one collapsible card per in-scope account, section collapsed by default. Body is `content.textarea`, editable. "Post to Slack" opens `https://slack.com/app_redirect?channel={content.channel_id}` in a new tab. Show `content.last_posted_at` next to the account name if present. Each card has its own Refresh control.

**Manager Update** (`text-block`) — exactly one card, collapsed by default, same editable-textarea pattern. "Post to Manager" targets a fixed Slack channel ID. One Refresh control.

## 6. Refresh and meeting deep links

Refresh is never performed by this app; every Refresh control is a `claude://` deep link that hands off to Claude Desktop with a pre-filled command, always including the date shown on screen so refreshing an archived brief regenerates the right one, not today's:

- Card-level: `/daily-brief Refresh customer update for {Account Name} date:{brief_date}` or `/daily-brief Refresh manager update date:{brief_date}`
- Section-level: `/daily-brief Refresh section:{slug} date:{brief_date}`

A Refresh click regenerates content in Drive; this app only sees it on its next sync (Section 3.3), so a card-level or section-level Refresh should also kick an immediate on-demand sync for that one user rather than waiting for the scheduled cycle, so the update shows up promptly after the person finishes in Claude Desktop.

Every meeting row (Yesterday's Meetings and Today) also carries `claude://claude.ai/new?q=<url-encoded prompt>` links for `/meeting-manager Run pre-meeting prep for: {meetingTitle} ({dateOrTime})` and `/meeting-manager Run post-meeting notes for: {meetingTitle} ({dateOrTime})`. These require Claude Desktop installed and registered as the `claude://` handler; a link that opens nothing on a machine without it is expected, not a bug. Surface a one-time note about this requirement in the UI.

## 7. Account settings and admin

**Account panel** (every signed-in user): Google Drive connection status with connect/disconnect and a folder ID field; Asana connection status with save/disconnect for the personal access token. A "Sync now" control (Section 3.3) belongs here too.

**Admin view**, gated by an admin email allow-list: a table of every signed-in user — email, sign-up date, active brief count, last sync time — for support purposes. With a real database behind this now, it's also the natural place to surface sync health (last successful sync per user, last error) rather than just user counts, which is worth adding now that there's a database to query.

## 8. Onboarding

On first sign-in, open a short setup walkthrough covering: connect Google Drive (OAuth) and confirm the folder ID, confirm the Claude skill's own Drive folder ID configuration points at that same folder, optionally connect a personal Asana token, and a note about installing Claude Desktop for the `claude://` deep links. Let the person dismiss it and reopen it later from the Account panel; record completion so it doesn't reopen automatically afterward.

## 9. Non-functional requirements

Render a friendly empty state, not an error, for a date with no brief at all and for any section with no rows. Handle a null or missing `title` on any item without crashing the page. Don't do your own timezone math on top of the data; the source's language ("occurred," "not found") already reflects the brief's own timezone resolution, and this app should only format `brief_date` for display. A sync failure for one user (a revoked Drive token, an Asana API error) should never affect any other user's data or page load; log it against that user's `last_synced_at`/error state and surface it in their Account panel, not as a global error. Desktop-first; mobile-responsive is a nice-to-have, not primary.

## 10. Explicitly out of scope

The Claude skill's own logic (data pulls from Outlook/Slack/Zoom/Asana, narrative synthesis, cache gating for Customer Updates/Manager Update) is not part of this build, and the skill's write target (Google Drive) is not changing — this build adds a sync layer in front of it, not a replacement for it. This app never calls Outlook's or Zoom's API at all, and never calls Slack's write API; posting to Slack is a deep link the user completes manually.

## 11. Migration path from As-Is to To-Be

Stand up the database and the sync job first, running against the same Drive data the current app already reads, without removing the live-read path yet. Backfill by running the scheduled sync once against however many days of Drive history should be preserved (matching whatever retention window Section 3.6 lands on). Once the database has full parity for a real day of use, switch the render path to read from the database and remove the live Drive/Asana calls from the request path entirely. Google OAuth and Asana PAT storage carry over unchanged; only where they're used (sync job instead of inline in a page request) changes.

## 12. Platform notes (Lovable vs. Replit)

Both platforms fit this cleanly now, more so than the Drive-live version did. Lovable's default Supabase/Postgres backend is a direct match for Section 3.4's schema; the sync job becomes a Supabase edge function on a schedule (or a `pg_cron` job calling it), and the two-way Asana sync is another edge function triggered from the same checkbox/due-date update path. Replit supports the same shape with any backend stack and a scheduled task or worker process for the sync job, talking to Postgres, SQLite, or whatever datastore is easiest to stand up there.

## 13. Open questions to confirm before starting the build

How far back the sync job should reach on first backfill, and what the ongoing retention window should be (Section 3.6 defaults to 14/30 days, matching the reference app, but this is a personal tool and a longer window may be worth the storage cost). Whether the Asana two-way sync (Section 3.5) is worth the complexity versus a simpler read-only Action Items view with local-only due-date edits. Whether to keep any multi-user/admin surface at all, or build single-user for Aaron only and drop the admin view in Section 7 entirely.
