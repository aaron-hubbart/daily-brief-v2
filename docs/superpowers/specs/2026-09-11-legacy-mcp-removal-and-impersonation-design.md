# Legacy MCP/Token Removal, Setup Walkthrough Rewrite, and Admin Impersonation

Date: 2026-09-11
Status: Design approved, ready for implementation planning
Repo: `aaron-hubbart/daily-brief-v2`

## Problem

Three cleanup items and one new feature, discovered/confirmed by direct investigation of the running codebase (not just historical design docs, which turned out to be an incomplete picture of what actually shipped):

1. **"Skill Sync Check"** is documented in `README.md` (a `sync_state` field in `config.json`, described as "maintained automatically by the Skill Sync Check") but does not correspond to any actual mechanism in `SKILL.md`. Dead documentation.

2. **The old v1 "daily-brief MCP connector" architecture is still fully present** in the webapp, even though the v2 migration's original design explicitly called for its removal. This is a real, functioning subsystem: a `users.api_token` column (Postgres), a bearer-token auth path (`ensure_upload_context`), three routes the old skill's MCP connector called to push brief content into Postgres (`/api/config/account-projects`, `/api/items/upsert`, `/api/items/batch-upsert`), an admin "rotate token" action, and a `MCP_CONNECTOR_URL` env var displayed in the setup walkthrough. Confirmed via user input: nobody is running the v1 skill against this webapp anymore — safe to remove entirely.

3. **The webapp's "Setup" button walkthrough is v1-era and inaccurate for v2.** Its first three steps (copy an API token, register an MCP connector in Claude with that token as a Bearer header, install the skill from the old `github.com/aaron-hubbart/daily-brief` repo and set `DAILY_BRIEF_API_BASE_URL`) describe an architecture that no longer applies. The remaining steps (connect data source connectors, misc config, optional Asana PAT) are still valid but need minor updates since some values they mention (`RECURRING_ACTIVITIES_PROJECT_GID`, `MEETING_RUN_LOG_SHEET_ID`) are now gathered automatically by the skill's First-Run Setup rather than hand-set in `SKILL.md`'s Admin Config.

4. **No way to test the webapp as a new user without disturbing the real account.** Users are keyed by email from real Azure AD sign-in; there's no fake-identity path today.

## Scope boundary: what this does NOT touch

The webapp's Postgres-backed checkbox/due-date toggle feature (`brief_days`/`items` tables, `db.get_brief_day`, `db.set_item_checked`, `db.set_item_due_date`, and the `/api/items/<section>/<item_key>/checked` and `.../due-date` routes) is a **separate, still-active mechanism** used by all users regardless of v1/v2 brief-content source. It happens to also live in Postgres, but it is not part of the MCP-connector/bearer-token system being removed here, and removing it was not requested. Do not touch it as part of this work.

## Part 1: Skill Sync Check removal

Remove the `sync_state` field and its description from `README.md`'s `config.json` example block and surrounding prose. This is documentation-only — no code references it.

## Part 2: Legacy MCP connector / bearer-token removal

### Database (new migration)

Create `viewer/webapp/db/migrations/007_drop_api_token_and_account_projects.sql`:
- `ALTER TABLE users DROP COLUMN api_token;` (and drop `idx_users_api_token` first, or let `DROP COLUMN` cascade the index automatically — Postgres drops dependent indexes automatically when the column is dropped, so an explicit `DROP INDEX` isn't required, but the implementation should verify this against the actual schema.sql conventions used by prior migrations)
- `DROP TABLE IF EXISTS account_projects;` (also drops `idx_account_projects_user` automatically)
- Update `viewer/webapp/db/schema.sql` to match the post-migration schema (remove `api_token` column + its index from the `users` table definition, remove the `account_projects` table + its index definition entirely) — `schema.sql` is the from-scratch bootstrap definition and must stay in sync with the cumulative effect of all migrations, per this repo's existing convention (each of migrations 001-006 has a corresponding change already reflected in `schema.sql`).

### Backend (`viewer/webapp/app.py`)

Remove entirely:
- `MCP_CONNECTOR_URL` env var definition and its inclusion in `/api/client-config`'s response (keep `api_base_url` in that response — only remove the `mcp_connector_url` key)
- `ensure_upload_context()` function
- `/api/token` route
- `/api/token/rotate` route
- `/api/admin/users/<int:user_id>/rotate-token` route
- `/api/config/account-projects` route
- `/api/items/upsert` route
- `/api/items/batch-upsert` route

### Backend (`viewer/webapp/db.py`)

Remove entirely:
- `get_user_by_token`
- `get_user_token`
- `rotate_user_token`
- `get_account_projects`
- `replace_account_projects`
- `upsert_brief_day`
- `upsert_item`

Modify `get_or_create_user`: remove the token-assignment block (the `if row['api_token'] is None: ...` section and the `RETURNING id, api_token, onboarding_completed_at` → becomes `RETURNING id, onboarding_completed_at`, and the docstring's claim about assigning a token). It should now just create-or-update the user row and return `{id, onboarding_completed_at}`.

Modify `get_user_by_id`: its `SELECT` currently includes `api_token` (`SELECT id, email, slug, api_token, asana_pat, created_at, onboarding_completed_at FROM users WHERE id = %s`) — drop `api_token` from that column list. Verified safe: its only caller (`app.py`'s `/api/whoami`) only reads `user['onboarding_completed_at']` from the result.

### Frontend (`viewer/webapp/templates/admin.html`)

Remove the "Rotate token" table column/button, the `rotateToken()` JS function, and its confirm-dialog copy. The Users table keeps Email/Slug/Signed up/Active briefs/Last active columns (the trailing action column becomes the new impersonation controls — see Part 4).

### Deployment (`viewer/webapp/k8s/deployment.yaml`, `viewer/webapp/DEPLOYMENT.md`)

Remove the `MCP_CONNECTOR_URL` env var block from `deployment.yaml`. Remove the `DEPLOYMENT.md` sections describing the `api_token` migration note and the MCP connector public URL setup.

## Part 3: Setup walkthrough rewrite (`viewer/daily-brief-viewer.html`)

Replace the current 6-step walkthrough's steps 1-3 with a single new Step 1:

```
1. Set up the daily-brief skill

Install the skill in a Claude project from github.com/aaron-hubbart/daily-brief-v2
— copy SKILL.md and the references/ folder in.

In Claude, run: /daily-brief setup

Follow the prompts — it'll ask for your Drive folder ID and Slack user ID,
then discover your customer accounts, Slack channels, and Asana projects
automatically. Review and confirm what it finds.

When it finishes, it reports a config.json Drive file ID. Paste that into
CONFIG_FILE_ID at the top of your local SKILL.md — that's the only manual
edit.
```

Renumber the remaining steps (old 4→2, 5→3, 6→4):
- **Step 2 (data sources):** keep as-is, only reword the Google Drive bullet from "meeting run log sheet and status-update cache" to "where your briefs, config, and status-update cache all live" (matches the actual v2 role).
- **Step 3 (misc):** remove the bullet instructing to manually set `RECURRING_ACTIVITIES_PROJECT_GID` and `MEETING_RUN_LOG_SHEET_ID` in Admin Config — First-Run Setup now gathers these (or defers them as blank placeholders you fill in afterward, per the existing First-Run Setup flow). Keep the Claude Desktop and README-pointer bullets.
- **Step 4 (Asana, optional):** unchanged.

Update `SETUP_STEP_COUNT` in the JS from `6` to `4`, and remove the `setup-token`/`setup-mcp-url` field references and their `fetch('api/token')` / `cfg.mcp_connector_url` population calls in `openSetup()`.

## Part 4: Admin impersonation feature

### Database (same migration file as Part 2)

Add `is_test BOOLEAN NOT NULL DEFAULT FALSE` to the `users` table in the same `007_...sql` migration, and reflect it in `schema.sql`.

### Backend (`viewer/webapp/db.py`)

New functions:
- `create_test_user(label: str) -> dict` — inserts a new user row with a synthetic email (`f"test-{secrets.token_hex(4)}@daily-brief.local"`, or incorporating `label` if given), `is_test = TRUE`, returns the created row. No `api_token` field to assign (removed in Part 2).
- `list_test_users() -> list` — returns all rows where `is_test = TRUE`, for the admin panel's impersonation picker.
- `delete_test_user(user_id: int) -> None` — removes a test user row (and cascades any of their onboarding/asana_pat/google token state) — lets the admin clean up throwaway test accounts.

Modify `list_users_with_stats`: add `WHERE u.is_test = FALSE` (before the `GROUP BY`) so test users appear only in the new Test Users panel, not duplicated in the existing real-user Users table.

### Backend (`viewer/webapp/app.py`)

New admin-only routes:
- `POST /api/admin/test-users` — calls `db.create_test_user`, returns the new user's `{id, email}`.
- `GET /api/admin/test-users` — calls `db.list_test_users`, returns the list for the admin panel.
- `DELETE /api/admin/test-users/<int:user_id>` — calls `db.delete_test_user`. Guard: 404 if the target user's `is_test` is not true (never let this delete a real user via a crafted ID).
- `POST /api/admin/impersonate/<int:user_id>/start` — guards: `admin_required`, and abort(404) unless the target user's `is_test` is true (matches your "throwaway test users only" decision — this route can never target a real user, even if an admin tries to). On success: store the CURRENT session's real identity dict into `session['admin_original_user']` (only if not already impersonating — reject a second nested impersonate attempt with 400, "already impersonating; stop first"), then overwrite `session['user']` with the target test user's identity shape (same fields `current_user()` expects: `id`, `email`, `oid` — synthesize a stable placeholder `oid` for test users, e.g. `f"test-{user_id}"`, since they never went through real Azure AD).
- `POST /api/admin/impersonate/stop` — if `session.get('admin_original_user')` is set, restore `session['user']` from it and clear the key; otherwise no-op. Available to any signed-in user (not admin-gated) since by definition only someone who started an impersonation can have this key set, and they need to be able to end it even if `ADMIN_EMAILS` changed mid-session.

New helper: `is_impersonating()` → `bool(session.get('admin_original_user'))`, used by a small addition to `/api/whoami`'s response (`impersonating: bool`, and `real_admin_email` when true) so the frontend banner knows what to show without a separate round trip.

### Frontend (`viewer/webapp/templates/admin.html`)

Add a "Test Users" panel (new, alongside the existing "Users" panel): a "Create test user" button (optionally with a label input), a table listing existing test users with "Impersonate" and "Delete" buttons per row.

### Frontend (`viewer/daily-brief-viewer.html`)

Add a persistent banner (hidden by default, shown when `/api/whoami`'s `impersonating` is true): fixed-position bar reading `Viewing as: {email} (test) — ` with a "Return to my account" button calling `POST api/admin/impersonate/stop` then reloading the page. Checked once on page load alongside the existing `checkOnboarding()` call.

## Testing Strategy

- **Migration:** apply `007_...sql` against a local/test Postgres instance (or the same manual `kubectl exec ... psql` pattern `DEPLOYMENT.md` already documents for prior migrations), verify `\d users` no longer shows `api_token`, `account_projects` table is gone, `is_test` column exists with default `FALSE`.
- **Backend removal:** grep the final diff for `api_token`, `MCP_CONNECTOR_URL`, `ensure_upload_context`, `account_projects` to confirm no stray references remain outside the migration/schema files (which correctly still mention them as the thing being dropped).
- **Impersonation:** manual walkthrough (no live Azure AD available in a sandbox) — create a test user via the admin panel, impersonate, confirm the banner appears and `/api/whoami` reflects the test identity, click "Return to my account," confirm the real admin session is restored. Confirm attempting to impersonate a non-test user ID 404s.
- **Setup walkthrough:** manual click-through of the rewritten 4-step modal, confirm no console errors from the removed `setup-token`/`setup-mcp-url` field references.

## Non-Goals

- Changing the checkbox/due-date persistence mechanism (`brief_days`/`items`, Postgres-backed) — explicitly out of scope, see Scope Boundary above.
- Migrating any historical `account_projects` data before dropping the table — this mapping is now read live from `account-config.json` on Drive for every v2 user; there is nothing to preserve.
- A full "impersonate any real user" admin feature — explicitly scoped to test users only, per design decision.
- Automatic cleanup/expiry of test users — an admin deletes them manually via the new Delete button when done.
