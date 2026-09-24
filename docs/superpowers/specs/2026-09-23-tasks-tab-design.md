# Tasks Tab — Design

## Goal

A new, standalone **Tasks** view in the hosted viewer showing every open
Asana task relevant to the signed-in user — assigned to them anywhere in
their workspace, plus every open task on a linked primary-tier account's
board — independent of any single brief day. Today this data only surfaces
inside a specific day's "live action items" section in the brief; there's no
persistent "what's on my plate right now" view.

Read-only for this phase: tasks link out to Asana to be actioned or
completed there. No write-back to Asana, no new data sources beyond Asana,
no changes to the existing brief or Customers views.

## 1. Data layer — extract the existing pull logic

`app.py`'s `_fetch_live_action_items(pat, account_projects, exclude_gids)`
already does almost exactly this pull (two Asana queries: assignee-is-me
across the workspace, and every task in each linked account project;
de-duplicated by GID; shaped into item dicts with title, due date, project
name, and an Asana permalink). Today it's called only from the brief's
live-items endpoint with `exclude_gids` set to whatever's already tracked in
Postgres as a New Item for that day.

For the Tasks tab, call the same function with `exclude_gids=set()` (nothing
to exclude — this view isn't deduplicating against a specific day's stored
items) and no changes to its signature or behavior. The function itself
doesn't change; only a new caller is added.

## 2. Routes

Mirrors the existing `/customers` + `/api/customers/config` pattern:

- **`GET /tasks`** — renders `templates/tasks.html` (page shell), same
  `@_require_login` guard as every other authenticated page route.
- **`GET /api/tasks`** — reads the signed-in user's stored Asana PAT (same
  lookup `/api/asana-pat` already uses) and linked account projects (same
  `gdrive_briefs.get_account_projects` call the brief's live-items endpoint
  uses), calls `_fetch_live_action_items(pat, account_projects, set())`, and
  returns the resulting list as JSON.
  - No PAT saved yet → `200` with `{"items": [], "needs_pat": true}` so the
    page can show the same "add your Asana PAT" prompt the brief already
    shows in that case, instead of a bare error.
  - Asana call fails (rate limit, outage) → matches
    `_fetch_live_action_items`'s existing best-effort behavior: log and
    return whatever partial results came back rather than a 500.

## 3. Tasks page — grouping & display

`templates/tasks.html`, modeled on `customers.html`'s structure (same nav
shell, same fetch-and-render-into-a-`<div>` pattern already used across the
viewer's pages).

Client-side, tasks are grouped into four buckets by `due_on` relative to
today (viewer's local date, same as the rest of the app):

1. **Overdue** — `due_on` before today
2. **Due today**
3. **Due this week** — after today, within 7 days
4. **No due date / later**

Each bucket is sorted by `due_on` ascending (no-due-date tasks last within
their bucket, by title). Each task row shows: title, project/account name
(already computed by `_fetch_live_action_items` as `project_name`), the
existing assignee badge (unassigned / assigned to someone else — relevant
here since account-project tasks aren't filtered to "assigned to me"), and
an "Open in Asana" link (already provided as `permalink_url`). Empty
buckets are hidden rather than shown with a "nothing here" placeholder,
matching the terse style of the rest of the viewer.

No pagination or filtering controls in this phase — the existing brief's
live-items pull isn't paginated either (Asana's own 100-per-query limit is
the practical ceiling), and account-scoped task volume at this scale
doesn't need it yet.

## 4. Nav

Add a "Tasks" link to the shared nav alongside the existing Brief /
Customers / Admin links (wherever that shell lives — same include/partial
every authenticated page already uses).

## 5. Testing

`tests/test_tasks_view.py`, following the existing per-feature test file
pattern (e.g. `test_fyi_section_checkable.py`):

- `GET /tasks` redirects to `/login` when not signed in; returns 200 when
  signed in.
- `GET /api/tasks` returns `{"items": [], "needs_pat": true}` when no PAT is
  stored, without calling Asana.
- The due-date bucketing logic is factored into a small pure function
  (e.g. `_bucket_tasks_by_due_date(items, today)`) so it's unit-tested
  directly against fixed `today` values, rather than only through the route.
