# Storage model

Applies `schema.sql`. See `../DEPLOYMENT.md` for how to actually run it against the cluster's Postgres.

## Why per-item rows instead of one HTML blob per day

The old model (`data/{slug}/Daily Brief_*.html`) stored a whole rendered page per run. Refreshing one Customer Update card meant downloading the latest file, finding the right `<details>` node by `data-id`, splicing in new markup, and re-uploading a whole new timestamped file (`references/section-refresh.md` in the skill repo does exactly this). That's the price of treating a day's brief as one opaque document.

With one row per item: refreshing a single account's update, or a single meeting's recording-found status, is one `UPSERT` on one row. The brief a user sees is assembled from whatever rows currently exist for that day, at request time — so a mid-day refresh shows up the next time they load the page, without regenerating anything else.

## `content` JSONB shape by `item_type`

- **`checkable`** (Yesterday's Meetings, Account/Initiative Recap, Today, Action Items): `content` is usually `{}` — `title`, `subtitle`, `badge`, and `links` columns carry everything needed to render the row. `checked` holds the checkbox state. **Action Items is the exception**: `content` holds `{"due_on": "YYYY-MM-DD" or null, "is_new": true, "project_name": "..." or null}` — see `../references/item-sync.md` for how the skill populates these. The skill only ever upserts rows with `is_new: true` (see the New Items note below); `due_on`/`is_new` drive subsection placement (New Items, Overdue, Due Next 7 Days, No Due Date), `project_name` is display-only, the Asana board the task belongs to (`null` renders as "My Tasks"). The live-pulled Overdue/Due Next 7 Days/No Due Date items app.py constructs at render time use this same shape (with `is_new: false`) but are never written to this table — see the note below.
- **`fyi`**: same as `checkable` but `checked` is always `NULL` — FYI items were never checkable in the file-based model either.
- **`card`** (Customer Updates — one row per account): `content` holds `{"textarea": "...", "channel_id": "C0395GFC4PR", "last_posted_at": "2026-07-13T18:00:00Z"}`.
- **`text-block`** (Manager Update — always exactly one row per day, `item_key = 'mgr-update'`): `content` holds `{"textarea": "..."}`.

## Upsert key

`(brief_day_id, section, item_key)` is the natural key items upsert against. `brief_day_id` itself comes from a `(user_id, brief_date)` upsert done first — see the API in `../app.py`'s `/api/items/upsert` and `/api/items/batch-upsert` for how both steps happen together in one call.

## Archival semantics (see `../archive_briefs.py`)

- **14 days**: `brief_days` rows with `brief_date` more than 14 days ago and `status = 'active'` get `status = 'archived'`, `archived_at = now()`. Archived days are excluded from `/api/briefs` (the "no longer visible to the end user" requirement) but the rows and their items still exist.
- **30 days**: `brief_days` rows with `brief_date` more than 30 days ago get hard-deleted, `ON DELETE CASCADE` removes their `items` rows with them. This is irreversible.
- Both checks run independently every time the job runs — a day that's already archived just gets skipped by the 14-day pass (its `status` is no longer `'active'`) and picked up by the 30-day pass on schedule.

## `users.asana_pat` and `account_projects`

As of `migrations/003_add_asana_pat.sql` and `004_add_account_projects.sql`, Action Items has two data sources instead of one:

- **New Items** — still Postgres-backed, exactly as before. The skill only upserts items where `content.is_new` is true (the task it just created this run); it no longer syncs Overdue/Due Next 7 Days/No Due Date rows to Postgres at all.
- **Overdue / Due Next 7 Days / No Due Date** — pulled live from Asana's API at page-render time (see `app.py`'s `_fetch_live_action_items`), using the signed-in user's own `users.asana_pat` and the project GIDs in `account_projects` for that `user_id`. Never persisted; recomputed on every page load. If `asana_pat` is `NULL` (the person skipped that step of setup), these three subsections are omitted entirely and only New Items renders.

`account_projects` is a full replace-per-user mirror — the skill re-syncs the whole table for a user on every brief run via `daily_brief_sync_account_projects`, so a stale row for a removed account doesn't linger.
