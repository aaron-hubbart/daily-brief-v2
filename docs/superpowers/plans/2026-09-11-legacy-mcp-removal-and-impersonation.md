# Legacy MCP/Token Removal, Setup Rewrite, and Admin Impersonation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decommission the old v1 bearer-token/MCP-connector subsystem (confirmed dead — everyone is on v2), rewrite the webapp's Setup walkthrough and Account panel to match v2's real architecture, remove the dead "Skill Sync Check" documentation, and add an admin-only "impersonate a throwaway test user" feature so new-user flows can be tested without touching real data.

**Architecture:** Two removal passes (database/backend, then frontend/docs) followed by one new feature (impersonation) built on the same `users` table. All work is confined to `viewer/webapp/`, `viewer/daily-brief-viewer.html`, and the root `README.md` — no changes to `SKILL.md` or `references/` (the skill itself never referenced any of this).

**Tech Stack:** Python 3 / Flask / psycopg2 (existing), plain SQL migrations (existing convention: sequential numbered files, forward-only, no down-migrations), vanilla JS/HTML templates (existing, no build step).

## Global Constraints

- Field/column names must match exactly: the column being dropped is `users.api_token` (not `api_key` or similar); the table being dropped is `account_projects`; the new column is `is_test BOOLEAN NOT NULL DEFAULT FALSE`.
- Do NOT touch `brief_days`, `items`, `db.get_brief_day`, `db.set_item_checked`, `db.set_item_due_date`, or the `/api/items/<section>/<item_key>/checked` and `.../due-date` routes — these back a separate, still-active checkbox/due-date feature used by all users regardless of v1/v2 brief-content source. Confirmed this is out of scope for this work.
- Do NOT touch `gdrive_briefs.py`'s `get_account_projects` function — this is a different, correct, currently-live v2 function (reads Drive's `account-config.json`) despite sharing a name with the `db.py` function being removed.
- Migrations in this repo are forward-only and never edited after being committed (001-006 already exist) — this work adds a new `007_...sql` file, never modifies 001-006.
- `schema.sql` must always reflect the cumulative effect of all migrations (existing convention — verify by comparing schema.sql's current `users`/`account_projects` definitions against migrations 001 and 004, which is exactly where those columns/tables came from).
- Admin impersonation may only ever target a user with `is_test = TRUE` — never a real user, even via a crafted ID. This must be enforced server-side in every impersonation-related route, not just hidden in the UI.

---

## File Structure

**New files:**
- `viewer/webapp/db/migrations/007_drop_api_token_and_account_projects.sql` — drops `users.api_token`, drops `account_projects` table, adds `users.is_test`.

**Modified files:**
- `viewer/webapp/db/schema.sql` — remove `api_token` column/index, remove `account_projects` table/index, add `is_test` column.
- `viewer/webapp/db.py` — remove token/account-projects functions, add test-user functions, filter `list_users_with_stats`.
- `viewer/webapp/app.py` — remove `MCP_CONNECTOR_URL`, token routes, item-upsert routes, `ensure_upload_context`; fix the `api_live_action_items` fallback; add impersonation routes; add `impersonating` to `/api/whoami`.
- `viewer/webapp/templates/admin.html` — remove "Rotate token" column/button; add "Test Users" panel.
- `viewer/daily-brief-viewer.html` — remove Account panel's token section; rewrite Setup walkthrough steps 1-3 into one new step; add impersonation banner.
- `viewer/webapp/k8s/deployment.yaml` — remove `MCP_CONNECTOR_URL` env var.
- `viewer/webapp/DEPLOYMENT.md` — remove/rewrite sections describing the token-based rollout, MCP connector, old setup walkthrough, and account-panel token UI.
- `viewer/webapp/db/README.md` — update the Action Items data-source description to drop the Postgres `account_projects` fallback.
- `README.md` (repo root) — remove the dead `sync_state` field from the `config.json` example.

---

## Task 1: Database Migration

**Files:**
- Create: `viewer/webapp/db/migrations/007_drop_api_token_and_account_projects.sql`
- Modify: `viewer/webapp/db/schema.sql`

**Interfaces:**
- Produces: final schema shape — `users` table with no `api_token` column, a new `is_test BOOLEAN NOT NULL DEFAULT FALSE` column; no `account_projects` table. Consumed by Task 2 (backend code must not reference the dropped column/table) and Task 7 (impersonation code relies on `is_test`).

- [ ] **Step 1: Write the migration**

Create `viewer/webapp/db/migrations/007_drop_api_token_and_account_projects.sql`:

```sql
-- Decommission the v1 bearer-token/MCP-connector sync path (confirmed
-- fully unused — every user is on the v2 Drive-backed skill now) and add
-- support for admin-created throwaway test users (impersonation feature).

-- Postgres automatically drops any indexes/constraints defined directly on
-- a dropped column or table (idx_users_api_token, idx_account_projects_user,
-- and account_projects' own PK/unique constraints all go with it) — no
-- separate DROP INDEX statements needed.
ALTER TABLE users DROP COLUMN api_token;
DROP TABLE IF EXISTS account_projects;

ALTER TABLE users ADD COLUMN is_test BOOLEAN NOT NULL DEFAULT FALSE;
```

- [ ] **Step 2: Update schema.sql to match**

In `viewer/webapp/db/schema.sql`, find:
```sql
CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    email       TEXT NOT NULL UNIQUE,
    slug        TEXT NOT NULL UNIQUE,
    -- Bearer token the daily-brief skill authenticates with when calling
    -- /api/items/upsert and /api/items/batch-upsert. Assigned automatically
    -- the first time this user signs in through the browser (see
    -- get_or_create_user in db.py) -- nobody has to hand-provision this.
    api_token   TEXT UNIQUE,
    -- Per-user Asana Personal Access Token — see migrations/003_add_asana_pat.sql
    -- for what it's used for. NULL means the person skipped that step of
    -- setup; the webapp treats that as "live Action Items pull disabled."
    asana_pat   TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Set once the person has clicked through the in-app setup walkthrough
    -- (or dismissed it). NULL means "show it automatically on next login."
    onboarding_completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_users_api_token ON users (api_token);
```
Replace with:
```sql
CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    email       TEXT NOT NULL UNIQUE,
    slug        TEXT NOT NULL UNIQUE,
    -- Per-user Asana Personal Access Token — see migrations/003_add_asana_pat.sql
    -- for what it's used for. NULL means the person skipped that step of
    -- setup; the webapp treats that as "live Action Items pull disabled."
    asana_pat   TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Set once the person has clicked through the in-app setup walkthrough
    -- (or dismissed it). NULL means "show it automatically on next login."
    onboarding_completed_at TIMESTAMPTZ,
    -- Admin-created throwaway account for testing the new-user experience
    -- via impersonation (see migrations/007_...sql) — never a real person.
    is_test     BOOLEAN NOT NULL DEFAULT FALSE
);
```

In the same file, find:
```sql
-- Mirror of the account -> Asana project GID mapping from Meeting Manager
-- Config.xlsx, re-synced by the skill on every run (full replace-per-user)
-- since the webapp has no Google Drive access of its own. See
-- migrations/004_add_account_projects.sql and app.py's live Action Items
-- pull for how this gets used.
CREATE TABLE IF NOT EXISTS account_projects (
    id           SERIAL PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_name TEXT NOT NULL,
    project_gid  TEXT NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, account_name)
);

CREATE INDEX IF NOT EXISTS idx_account_projects_user ON account_projects (user_id);
```
Delete this whole block (the table is gone as of migration 007 — the account→Asana-project mapping now comes exclusively from Google Drive's `account-config.json` via `gdrive_briefs.get_account_projects`).

- [ ] **Step 3: Verify**

Run: `python -c "import re; content = open('viewer/webapp/db/schema.sql').read(); assert 'api_token' not in content; assert 'account_projects' not in content; assert 'is_test' in content; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add viewer/webapp/db/migrations/007_drop_api_token_and_account_projects.sql viewer/webapp/db/schema.sql
git commit -m "db: drop api_token/account_projects, add is_test for impersonation"
```

---

## Task 2: Backend Removal — db.py and app.py

**Files:**
- Modify: `viewer/webapp/db.py`
- Modify: `viewer/webapp/app.py`

**Interfaces:**
- Consumes: Task 1's final schema (no `api_token` column, no `account_projects` table).
- Produces: `get_or_create_user(email, slug) -> {'id': ..., 'onboarding_completed_at': ...}` (no `api_token` key). `get_user_by_id(user_id) -> {'id', 'email', 'slug', 'asana_pat', 'created_at', 'onboarding_completed_at'}` (no `api_token` key). Consumed by Task 7 (impersonation reuses `get_or_create_user`'s row shape expectations) and Task 3/4 (frontend no longer calls the removed routes).

- [ ] **Step 1: Remove token/account-projects functions from db.py**

In `viewer/webapp/db.py`, find:
```python
def get_user_by_token(token: str):
    with cursor() as cur:
        cur.execute("SELECT id, email, slug, api_token FROM users WHERE api_token = %s", (token,))
        return cur.fetchone()


def get_user_token(user_id: int) -> str:
    with cursor() as cur:
        cur.execute("SELECT api_token FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        return row['api_token'] if row else None


def get_user_by_id(user_id: int):
    with cursor() as cur:
        cur.execute(
            "SELECT id, email, slug, api_token, asana_pat, created_at, onboarding_completed_at FROM users WHERE id = %s",
            (user_id,),
        )
        return cur.fetchone()
```
Replace with:
```python
def get_user_by_id(user_id: int):
    with cursor() as cur:
        cur.execute(
            "SELECT id, email, slug, asana_pat, created_at, onboarding_completed_at FROM users WHERE id = %s",
            (user_id,),
        )
        return cur.fetchone()
```

In the same file, find:
```python
def get_account_projects(user_id: int) -> list:
    """The account -> Asana project GID mapping mirrored from Meeting
    Manager Config.xlsx, used to know which boards to poll for the live
    Action Items pull. Empty list if the skill hasn't synced this yet."""
    with cursor() as cur:
        cur.execute(
            "SELECT account_name, project_gid FROM account_projects WHERE user_id = %s ORDER BY account_name",
            (user_id,),
        )
        return cur.fetchall()


def replace_account_projects(user_id: int, accounts: list) -> None:
    """Full replace, not an upsert-per-row — the skill sends its complete
    current mapping on every run, so a row for an account that's been
    removed or renamed in the source sheet shouldn't linger here. Runs as
    one transaction: delete-then-insert, never a visible empty gap."""
    with cursor(commit=True) as cur:
        cur.execute("DELETE FROM account_projects WHERE user_id = %s", (user_id,))
        for acct in accounts:
            cur.execute(
                """
                INSERT INTO account_projects (user_id, account_name, project_gid)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, account_name) DO UPDATE
                    SET project_gid = EXCLUDED.project_gid, updated_at = now()
                """,
                (user_id, acct['account_name'], acct['project_gid']),
            )


def mark_onboarding_complete(user_id: int) -> None:
```
Replace with:
```python
def mark_onboarding_complete(user_id: int) -> None:
```

In the same file, find:
```python
def rotate_user_token(user_id: int) -> str:
    """Invalidates the old token and assigns a new one. The old token stops
    working immediately — whatever's using it (the person's skill config)
    needs updating with the new value."""
    new_token = secrets.token_hex(32)
    with cursor(commit=True) as cur:
        cur.execute(
            "UPDATE users SET api_token = %s WHERE id = %s RETURNING api_token",
            (new_token, user_id),
        )
        return cur.fetchone()['api_token']


def list_active_briefs(user_id: int) -> list:
```
Replace with:
```python
def list_active_briefs(user_id: int) -> list:
```

- [ ] **Step 2: Update get_or_create_user to stop assigning a token**

In `viewer/webapp/db.py`, find:
```python
def get_or_create_user(email: str, slug: str) -> dict:
    """
    Called from the Azure AD sign-in callback. Creates the user row on
    first sign-in and — this is what makes new-user setup automatic —
    assigns a random api_token at the same time, with no admin step
    required. Returns {'id': ..., 'api_token': ...}.
    """
    with cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO users (email, slug) VALUES (%s, %s)
            ON CONFLICT (email) DO UPDATE SET email = EXCLUDED.email
            RETURNING id, api_token, onboarding_completed_at
            """,
            (email, slug),
        )
        row = cur.fetchone()

    if row['api_token'] is None:
        # Either a brand-new user, or an existing one from before api_token
        # existed (see migrations/001_add_api_token.sql) — assign one now.
        # COALESCE makes this race-safe: if two requests hit this for the
        # same user at once, only one write actually takes effect and both
        # end up returning that same value.
        token = secrets.token_hex(32)
        with cursor(commit=True) as cur:
            cur.execute(
                "UPDATE users SET api_token = COALESCE(api_token, %s) WHERE id = %s RETURNING api_token",
                (token, row['id']),
            )
            row['api_token'] = cur.fetchone()['api_token']

    return row
```
Replace with:
```python
def get_or_create_user(email: str, slug: str) -> dict:
    """
    Called from the Azure AD sign-in callback. Creates the user row on
    first sign-in, with no admin step required. Returns
    {'id': ..., 'onboarding_completed_at': ...}.
    """
    with cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO users (email, slug) VALUES (%s, %s)
            ON CONFLICT (email) DO UPDATE SET email = EXCLUDED.email
            RETURNING id, onboarding_completed_at
            """,
            (email, slug),
        )
        return cur.fetchone()
```

- [ ] **Step 3: Filter list_users_with_stats to exclude test users**

In `viewer/webapp/db.py`, find:
```python
def list_users_with_stats() -> list:
    """One row per user for the admin panel: sign-up date, how many brief
    days they have, and when they were last active. Left joins so a user
    who signed in but whose skill has never synced anything still shows up
    (with brief_count 0 / last_active null) rather than being hidden."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT
                u.id, u.email, u.slug, u.created_at,
                COUNT(bd.id) FILTER (WHERE bd.status = 'active') AS active_brief_count,
                MAX(bd.last_updated_at) AS last_active_at
            FROM users u
            LEFT JOIN brief_days bd ON bd.user_id = u.id
            GROUP BY u.id
            ORDER BY u.email
            """
        )
        return cur.fetchall()
```
Replace with:
```python
def list_users_with_stats() -> list:
    """One row per real (non-test) user for the admin panel: sign-up date,
    how many brief days they have, and when they were last active. Left
    joins so a user who signed in but whose skill has never synced anything
    still shows up (with brief_count 0 / last_active null) rather than being
    hidden. Test users (is_test = TRUE) are excluded — they appear in the
    separate Test Users panel instead (see list_test_users)."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT
                u.id, u.email, u.slug, u.created_at,
                COUNT(bd.id) FILTER (WHERE bd.status = 'active') AS active_brief_count,
                MAX(bd.last_updated_at) AS last_active_at
            FROM users u
            LEFT JOIN brief_days bd ON bd.user_id = u.id
            WHERE u.is_test = FALSE
            GROUP BY u.id
            ORDER BY u.email
            """
        )
        return cur.fetchall()
```

- [ ] **Step 4: Remove MCP_CONNECTOR_URL and its exposure in app.py**

In `viewer/webapp/app.py`, find:
```python
# Optional, display-only — the daily-brief-mcp-server connector's public
# URL (e.g. https://mcp.dashboard.es-sandbox.com/mcp), shown verbatim in
# the in-app setup walkthrough so people don't have to go find it
# themselves. Not used for anything security-relevant by this app itself.
MCP_CONNECTOR_URL = os.environ.get('MCP_CONNECTOR_URL', '').strip() or None

AZURE_AUTHORITY = f'https://login.microsoftonline.com/{AZURE_TENANT_ID}'
```
Replace with:
```python
AZURE_AUTHORITY = f'https://login.microsoftonline.com/{AZURE_TENANT_ID}'
```

In the same file, find:
```python
@app.route('/api/client-config')
@login_required
def api_client_config():
    """Values the setup walkthrough and Account panel need to render
    correct copy-paste instructions, computed server-side rather than
    guessed from window.location (this app is deployed at a sub-path, and
    the MCP connector lives on an entirely different subdomain that the
    browser has no way to derive on its own)."""
    return jsonify({
        # request.script_root is where ForcePrefixMiddleware put the
        # /daily-brief prefix back (see its docstring) — same value this
        # deployment's DAILY_BRIEF_API_BASE_URL is set to.
        'api_base_url': request.host_url.rstrip('/') + request.script_root,
        'mcp_connector_url': MCP_CONNECTOR_URL,
    })
```
Replace with:
```python
@app.route('/api/client-config')
@login_required
def api_client_config():
    """Values the setup walkthrough needs to render correct copy-paste
    instructions, computed server-side rather than guessed from
    window.location (this app is deployed at a sub-path)."""
    return jsonify({
        # request.script_root is where ForcePrefixMiddleware put the
        # /daily-brief prefix back (see its docstring).
        'api_base_url': request.host_url.rstrip('/') + request.script_root,
    })
```

- [ ] **Step 5: Remove ensure_upload_context and the three item-upload routes**

In `viewer/webapp/app.py`, find:
```python
def ensure_upload_context():
    """Shared bearer-token check for the skill-facing item endpoints.
    Returns the resolved user_id. Tokens are auto-assigned per user at
    first sign-in (db.get_or_create_user) — there's no admin-managed token
    list to keep in sync anymore."""
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        abort(401)
    token = auth[len('Bearer '):].strip()
    user = db.get_user_by_token(token)
    if not user:
        abort(403)
    return user['id']


# ── Auth routes ──────────────────────────────────────────────────────────
```
Replace with:
```python
# ── Auth routes ──────────────────────────────────────────────────────────
```

In the same file, find:
```python
@app.route('/api/config/account-projects', methods=['POST'])
def api_config_account_projects():
    """
    Called by the daily-brief skill (via the daily_brief_sync_account_projects
    MCP tool) on every run to mirror its account -> Asana project GID
    mapping from Meeting Manager Config.xlsx. Full replace, not a merge —
    see db.replace_account_projects. This is what the live Action Items
    pull (_fetch_live_action_items) reads to know which boards to poll;
    the webapp has no Google Drive access of its own to read the sheet
    directly.

    Not behind @login_required, same reasoning as the items endpoints
    below: the skill runs headless, authenticated by its own bearer token.

    Body: {accounts: [{account_name, project_gid}, ...]}
    """
    user_id = ensure_upload_context()
    body = request.get_json(silent=True) or {}
    accounts = body.get('accounts')
    if not isinstance(accounts, list):
        abort(400, 'accounts must be an array')
    for acct in accounts:
        if not acct.get('account_name') or not acct.get('project_gid'):
            abort(400, 'every account needs account_name and project_gid')
    db.replace_account_projects(user_id, accounts)
    return jsonify({'status': 'ok', 'count': len(accounts)})


@app.route('/api/items/upsert', methods=['POST'])
def api_items_upsert():
    """
    Called by the daily-brief skill to create or refresh one item. This is
    the single operation for both "generate a brand-new day's brief" (call
    once per item) and "refresh one thing later" (call again for just that
    item_key) — the old file-based model needed a whole separate patch flow
    (references/section-refresh.md in the skill repo) for the second case;
    an upsert doesn't need that distinction.

    Not behind @login_required: the skill runs headless and has no browser
    session for an interactive Azure AD sign-in. Guarded by its own bearer
    token instead, scoped to exactly one user.

    Body: {brief_date, brief_type?, section, item_key, item_type?, title?,
           subtitle?, badge?, links?, content?, checked?, display_order?}
    """
    user_id = ensure_upload_context()
    body = request.get_json(silent=True) or {}

    brief_date = body.get('brief_date', '')
    if not DATE_RE.match(brief_date):
        abort(400, 'brief_date must be YYYY-MM-DD')
    if not body.get('section') or not body.get('item_key'):
        abort(400, 'section and item_key are required')

    brief_day_id = db.upsert_brief_day(user_id, brief_date, body.get('brief_type'))
    db.upsert_item(brief_day_id, body)
    return jsonify({'status': 'ok'}), 201


@app.route('/api/items/batch-upsert', methods=['POST'])
def api_items_batch_upsert():
    """
    Same as /api/items/upsert but for a whole day's worth of items in one
    call — what a full brief-generation run should use, rather than one
    HTTP round trip per item. Body: {brief_date, brief_type?, items: [...]}
    where each entry in items is the same shape as the single-upsert body
    (minus brief_date/brief_type, which apply to the whole batch).
    """
    user_id = ensure_upload_context()
    body = request.get_json(silent=True) or {}

    brief_date = body.get('brief_date', '')
    if not DATE_RE.match(brief_date):
        abort(400, 'brief_date must be YYYY-MM-DD')
    items = body.get('items')
    if not isinstance(items, list) or not items:
        abort(400, 'items must be a non-empty array')
    for item in items:
        if not item.get('section') or not item.get('item_key'):
            abort(400, 'every item needs section and item_key')

    brief_day_id = db.upsert_brief_day(user_id, brief_date, body.get('brief_type'))
    for item in items:
        db.upsert_item(brief_day_id, item)
    return jsonify({'status': 'ok', 'count': len(items)}), 201


@app.route('/healthz')
```
Replace with:
```python
@app.route('/healthz')
```
Replace that entire span with just:
```python
@app.route('/healthz')
```

- [ ] **Step 6: Remove /api/token, /api/token/rotate, and the admin rotate-token route**

In `viewer/webapp/app.py`, find:
```python
@app.route('/api/token')
@login_required
def api_token():
    """
    Lets a signed-in person retrieve their own api_token — this is the
    self-service half of automatic setup. There's no admin step between
    "person signs in for the first time" and "person has a token they can
    put in their own daily-brief skill's Admin Config": db.get_or_create_user
    already assigned one at sign-in time (see /auth/callback); this just
    surfaces it.
    """
    token = db.get_user_token(request.brief_user['id'])
    return jsonify({'token': token, 'email': request.brief_user['email']})


@app.route('/api/token/rotate', methods=['POST'])
@login_required
def api_token_rotate():
    """Invalidates the current token and issues a new one — for when a
    token leaks or someone just wants a fresh one. The old value stops
    working immediately; whatever skill config used it needs updating."""
    new_token = db.rotate_user_token(request.brief_user['id'])
    return jsonify({'token': new_token})


@app.route('/api/asana-pat')
```
Replace with:
```python
@app.route('/api/asana-pat')
```

In the same file, find:
```python
@app.route('/api/admin/users/<int:user_id>/rotate-token', methods=['POST'])
@login_required
@admin_required
def admin_rotate_user_token(user_id):
    """Rotates another user's token from the admin panel — for troubleshooting
    a stuck sync (401/403 from the skill) without asking the person to find
    and revisit /api/token themselves. Whoever's token this is needs their
    skill's Admin Config (DAILY_BRIEF_API_TOKEN_FILE_ID's Drive file) updated
    with the new value before their next brief run — this only invalidates
    the old one, it doesn't push the new one anywhere."""
    user = db.get_user_by_id(user_id)
    if not user:
        abort(404)
    new_token = db.rotate_user_token(user_id)
    return jsonify({'email': user['email'], 'token': new_token})


@app.route('/api/admin/config')
```
Replace with:
```python
@app.route('/api/admin/config')
```

- [ ] **Step 7: Fix the api_live_action_items fallback**

In `viewer/webapp/app.py`, find:
```python
    account_projects = (
        gdrive_briefs.get_account_projects(google_token, folder_id)
        if google_token
        else db.get_account_projects(request.brief_user['id'])
    )
```
Replace with:
```python
    account_projects = (
        gdrive_briefs.get_account_projects(google_token, folder_id)
        if google_token
        else []
    )
```

- [ ] **Step 8: Verify**

Run: `python -m py_compile viewer/webapp/app.py viewer/webapp/db.py`
Expected: no output, exit code 0.

Run: `python -c "content = open('viewer/webapp/app.py').read(); assert 'api_token' not in content; assert 'MCP_CONNECTOR' not in content; assert 'ensure_upload_context' not in content; assert '/api/items/upsert' not in content; assert '/api/config/account-projects' not in content; print('OK')"`
Expected: `OK`

Run: `python -c "content = open('viewer/webapp/db.py').read(); assert 'api_token' not in content; assert 'account_projects' not in content; print('OK')"`
Expected: `OK`

- [ ] **Step 9: Commit**

```bash
git add viewer/webapp/db.py viewer/webapp/app.py
git commit -m "backend: remove dead v1 bearer-token/MCP-connector API"
```

---

## Task 3: Frontend Removal — admin.html and the Account panel

**Files:**
- Modify: `viewer/webapp/templates/admin.html`
- Modify: `viewer/daily-brief-viewer.html`

**Interfaces:**
- Consumes: Task 2's removed routes (`/api/admin/users/<id>/rotate-token`, `/api/token`, `/api/token/rotate` no longer exist — this task removes the last callers of them).

- [ ] **Step 1: Remove the admin panel's "Rotate token" column**

In `viewer/webapp/templates/admin.html`, find:
```html
            <th>Last active</th>
            <th></th>
```
Replace with:
```html
            <th>Last active</th>
```

In the same file, find:
```javascript
        <td>${fmtDate(u.last_active_at)}</td>
        <td><button class="btn danger" onclick="rotateToken(${u.id}, '${u.email}')">Rotate token</button></td>
      </tr>
    `).join('');
```
Replace with:
```javascript
        <td>${fmtDate(u.last_active_at)}</td>
      </tr>
    `).join('');
```

In the same file, find:
```javascript
async function rotateToken(userId, email) {
  if (!confirm(`Rotate ${email}'s API token? Their existing token stops working immediately — they'll need to sign in and revisit /api/token to get the new one before their skill can sync again.`)) {
    return;
  }
  const msg = document.getElementById('users-msg');
  msg.className = 'msg';
  msg.textContent = 'Rotating…';
  try {
    const res = await fetch(`api/admin/users/${userId}/rotate-token`, { method: 'POST' });
    if (!res.ok) throw new Error('status ' + res.status);
    msg.className = 'msg ok';
    msg.textContent = `Token rotated for ${email}. They should revisit /api/token while signed in to get the new value.`;
  } catch (e) {
    msg.className = 'msg err';
    msg.textContent = `Could not rotate token for ${email}.`;
  }
}

loadConfig();
loadUsers();
```
Replace with:
```javascript
loadConfig();
loadUsers();
```

- [ ] **Step 2: Remove the Account panel's token section in daily-brief-viewer.html**

In `viewer/daily-brief-viewer.html`, find:
```html
<div class="modal-overlay" id="account-overlay">
  <div class="modal" style="max-width:440px;">
    <div class="modal-head">
      <h2>Account &amp; API token</h2>
      <button class="modal-close" onclick="closeAccount()" title="Close">&times;</button>
    </div>
    <div class="modal-body">
      <div class="account-row">Signed in as <strong id="account-email">…</strong></div>
      <div class="copy-row">
        <input class="copy-input" id="account-token" readonly value="Loading…">
        <button class="copy-btn" onclick="copyField('account-token', this)">Copy</button>
      </div>
      <button class="icon-btn" id="account-rotate" onclick="rotateToken()">Rotate token</button>
      <p style="font-size:11.5px;color:var(--t3);margin-top:10px;line-height:1.5;">Rotating invalidates your current token immediately. Afterward, update the <code>Authorization</code> header on your daily-brief-mcp-server connector (Claude Settings &rarr; Connectors) with the new value — your skill can't sync again until you do.</p>
      <div class="account-msg" id="account-msg"></div>
      <hr class="account-hr">
```
Replace with:
```html
<div class="modal-overlay" id="account-overlay">
  <div class="modal" style="max-width:440px;">
    <div class="modal-head">
      <h2>Account</h2>
      <button class="modal-close" onclick="closeAccount()" title="Close">&times;</button>
    </div>
    <div class="modal-body">
      <div class="account-row">Signed in as <strong id="account-email">…</strong></div>
      <hr class="account-hr">
```

- [ ] **Step 3: Remove openAccount()'s token fetch and rotateToken()**

In `viewer/daily-brief-viewer.html`, find:
```javascript
async function openAccount() {
  document.getElementById('account-overlay').classList.add('show');
  document.getElementById('account-msg').className = 'account-msg';
  document.getElementById('account-msg').textContent = '';
  document.getElementById('account-asana-msg').className = 'account-msg';
  document.getElementById('account-asana-msg').textContent = '';
  document.getElementById('account-google-msg').className = 'account-msg';
  document.getElementById('account-google-msg').textContent = '';
  document.getElementById('account-asana-pat').value = '';

  try {
    const res = await fetch('api/token');
    const d = await res.json();
    document.getElementById('account-email').textContent = d.email || '';
    document.getElementById('account-token').value = d.token || '(unavailable)';
  } catch (e) {
    document.getElementById('account-token').value = '(unavailable)';
  }

  refreshGoogleStatus();
  refreshAsanaStatus();
}

function closeAccount() {
  document.getElementById('account-overlay').classList.remove('show');
}

async function rotateToken() {
  if (!confirm('Rotate your API token? Your current token stops working immediately — update your daily-brief-mcp-server connector\'s Authorization header with the new value before your skill can sync again.')) {
    return;
  }
  const msg = document.getElementById('account-msg');
  msg.className = 'account-msg';
  msg.textContent = 'Rotating…';
  try {
    const res = await fetch('api/token/rotate', { method: 'POST' });
    if (!res.ok) throw new Error('status ' + res.status);
    const d = await res.json();
    document.getElementById('account-token').value = d.token;
    msg.className = 'account-msg ok';
    msg.textContent = 'Token rotated. Update your connector\'s Authorization header with this new value now.';
  } catch (e) {
    msg.className = 'account-msg err';
    msg.textContent = 'Could not rotate token — try again in a moment.';
  }
}

function copyField(inputId, btn) {
```
Replace with:
```javascript
async function openAccount() {
  document.getElementById('account-overlay').classList.add('show');
  document.getElementById('account-asana-msg').className = 'account-msg';
  document.getElementById('account-asana-msg').textContent = '';
  document.getElementById('account-google-msg').className = 'account-msg';
  document.getElementById('account-google-msg').textContent = '';
  document.getElementById('account-asana-pat').value = '';

  try {
    const res = await fetch('api/whoami');
    const d = await res.json();
    document.getElementById('account-email').textContent = d.email || '';
  } catch (e) {
    document.getElementById('account-email').textContent = '(unavailable)';
  }

  refreshGoogleStatus();
  refreshAsanaStatus();
}

function closeAccount() {
  document.getElementById('account-overlay').classList.remove('show');
}

function copyField(inputId, btn) {
```

**Note:** `/api/whoami` already returns `email` (see `app.py`'s `whoami()`), so this reuses an existing route rather than needing a new one.

- [ ] **Step 4: Verify**

Manually confirm (reading, not executing — no live browser in this environment): `grep -c "account-token\|account-rotate\|rotateToken" viewer/daily-brief-viewer.html` returns `0`, and `grep -c "rotate-token\|rotateToken" viewer/webapp/templates/admin.html` returns `0`.

- [ ] **Step 5: Commit**

```bash
git add viewer/webapp/templates/admin.html viewer/daily-brief-viewer.html
git commit -m "frontend: remove dead token/rotate UI from admin panel and Account panel"
```

---

## Task 4: Setup Walkthrough Rewrite

**Files:**
- Modify: `viewer/daily-brief-viewer.html`

**Interfaces:**
- Consumes: Task 2's `/api/client-config` (now returns only `api_base_url`, no `mcp_connector_url`).

- [ ] **Step 1: Replace setup steps 1-3 with one new step**

In `viewer/daily-brief-viewer.html`, find:
```html
      <div class="setup-step active" data-step="1">
        <h3>1. Get your API token</h3>
        <p>This token is how your daily-brief skill authenticates to sync briefs into this viewer. It's tied to your Camunda sign-in — never share it with anyone else.</p>
        <div class="copy-row">
          <input class="copy-input" id="setup-token" readonly value="Loading…">
          <button class="copy-btn" onclick="copyField('setup-token', this)">Copy</button>
        </div>
        <p>Keep this handy — you'll paste it into a connector setting in the next step.</p>
      </div>

      <div class="setup-step" data-step="2">
        <h3>2. Add the daily-brief connector in Claude</h3>
        <p>This is what actually lets your skill push brief items here — Claude's sandboxed tools can't reach this domain directly, so syncing goes through a dedicated MCP connector instead of a plain web request.</p>
        <ol>
          <li>In Claude, go to <strong>Settings &rarr; Connectors &rarr; Add custom connector</strong></li>
          <li>URL:</li>
        </ol>
        <div class="copy-row">
          <input class="copy-input" id="setup-mcp-url" readonly value="Loading…">
          <button class="copy-btn" onclick="copyField('setup-mcp-url', this)">Copy</button>
        </div>
        <ol start="3">
          <li>Auth type: <strong>static header</strong></li>
          <li>Header name <code>Authorization</code>, value <code>Bearer &lt;your token from step 1&gt;</code></li>
        </ol>
        <p>If this token is ever rotated, update this connector's header with the new value — see the Account panel for rotating.</p>
      </div>

      <div class="setup-step" data-step="3">
        <h3>3. Install the daily-brief skill</h3>
        <p>Add the skill to a Claude project from <a href="https://github.com/aaron-hubbart/daily-brief" target="_blank" rel="noopener">github.com/aaron-hubbart/daily-brief</a> — copy <code>SKILL.md</code> and the <code>references/</code> folder in.</p>
        <p>Then set this in your local copy's <strong>Admin Config</strong> block at the top of <code>SKILL.md</code>:</p>
        <div class="copy-row">
          <input class="copy-input" id="setup-base-url" readonly value="Loading…">
          <button class="copy-btn" onclick="copyField('setup-base-url', this)">Copy</button>
        </div>
        <p>That's <code>DAILY_BRIEF_API_BASE_URL</code> — reference only. Syncing itself goes through the connector from step 2, so there's no token value to store in this file.</p>
      </div>

      <div class="setup-step" data-step="4">
        <h3>4. Connect your data sources</h3>
        <p>The skill pulls from these — enable whichever apply to you under Claude's <strong>Settings &rarr; Connectors</strong>:</p>
        <ul>
          <li><strong>Microsoft 365</strong> — Outlook calendar, email, availability</li>
          <li><strong>Slack</strong> — DMs, channel activity, mentions, posting status updates</li>
          <li><strong>Zoom</strong> — meeting summaries</li>
          <li><strong>Asana</strong> — task tracking</li>
          <li><strong>Google Drive</strong> — meeting run log sheet and status-update cache</li>
        </ul>
        <p>Only connect what you actually use — the skill flags a source as "not found" rather than failing when one isn't hooked up.</p>
      </div>

      <div class="setup-step" data-step="5">
        <h3>5. A few other things</h3>
        <ul>
          <li><strong>Claude Desktop</strong>, if you want the <code>claude://</code> refresh and meeting-manager deep links in your briefs to work</li>
          <li>Your own Asana recurring-activities project GID (<code>RECURRING_ACTIVITIES_PROJECT_GID</code>) and a Drive sheet for the meeting run log (<code>MEETING_RUN_LOG_SHEET_ID</code>) — set these in Admin Config as you go</li>
          <li>See the skill repo's <code>README.md</code> for the full prerequisites list</li>
        </ul>
      </div>

      <div class="setup-step" data-step="6">
        <h3>6. Connect Asana (optional)</h3>
```
Replace with:
```html
      <div class="setup-step active" data-step="1">
        <h3>1. Set up the daily-brief skill</h3>
        <p>Install the skill in a Claude project from <a href="https://github.com/aaron-hubbart/daily-brief-v2" target="_blank" rel="noopener">github.com/aaron-hubbart/daily-brief-v2</a> — copy <code>SKILL.md</code> and the <code>references/</code> folder in.</p>
        <p>Then, in Claude, run:</p>
        <p><code>/daily-brief setup</code></p>
        <p>Follow the prompts — it'll ask for your Drive folder ID and Slack user ID, then discover your customer accounts, Slack channels, and Asana projects automatically. Review and confirm what it finds.</p>
        <p>When it finishes, it reports a <code>config.json</code> Drive file ID. Paste that into <code>CONFIG_FILE_ID</code> at the top of your local <code>SKILL.md</code> — that's the only manual edit.</p>
      </div>

      <div class="setup-step" data-step="2">
        <h3>2. Connect your data sources</h3>
        <p>The skill pulls from these — enable whichever apply to you under Claude's <strong>Settings &rarr; Connectors</strong>:</p>
        <ul>
          <li><strong>Microsoft 365</strong> — Outlook calendar, email, availability</li>
          <li><strong>Slack</strong> — DMs, channel activity, mentions, posting status updates</li>
          <li><strong>Zoom</strong> — meeting summaries</li>
          <li><strong>Asana</strong> — task tracking</li>
          <li><strong>Google Drive</strong> — where your briefs, config, and status-update cache all live</li>
        </ul>
        <p>Only connect what you actually use — the skill flags a source as "not found" rather than failing when one isn't hooked up.</p>
      </div>

      <div class="setup-step" data-step="3">
        <h3>3. A few other things</h3>
        <ul>
          <li><strong>Claude Desktop</strong>, if you want the <code>claude://</code> refresh and meeting-manager deep links in your briefs to work</li>
          <li>See the skill repo's <code>README.md</code> for the full prerequisites list</li>
        </ul>
      </div>

      <div class="setup-step" data-step="4">
        <h3>4. Connect Asana (optional)</h3>
```

- [ ] **Step 2: Update SETUP_STEP_COUNT and the trailing setup-step's data-step number**

In `viewer/daily-brief-viewer.html`, find the remainder of what was step 6's body (now step 4) — locate:
```html
        <p>Once your skill runs once, your brief shows up here automatically. Run <code>/daily-brief</code> in Claude any time to generate one — you're all set.</p>
      </div>
    </div>
    <div class="modal-foot">
```
This confirms the old step 6 body is otherwise unchanged (only its `data-step` attribute moved from `"6"` to `"4"` in Step 1 above) — no further edit needed here beyond what Step 1 already did.

In the same file, find:
```javascript
let clientConfig = null; // {api_base_url, mcp_connector_url} — cached after first fetch
let setupStepIndex = 1;
const SETUP_STEP_COUNT = 6;

async function getClientConfig() {
  if (clientConfig) return clientConfig;
  try {
    const res = await fetch('api/client-config');
    clientConfig = await res.json();
  } catch (e) {
    clientConfig = { api_base_url: null, mcp_connector_url: null };
  }
  return clientConfig;
}
```
Replace with:
```javascript
let clientConfig = null; // {api_base_url} — cached after first fetch
let setupStepIndex = 1;
const SETUP_STEP_COUNT = 4;

async function getClientConfig() {
  if (clientConfig) return clientConfig;
  try {
    const res = await fetch('api/client-config');
    clientConfig = await res.json();
  } catch (e) {
    clientConfig = { api_base_url: null };
  }
  return clientConfig;
}
```

- [ ] **Step 3: Remove openSetup()'s token/mcp-url population**

In `viewer/daily-brief-viewer.html`, find:
```javascript
async function openSetup(fromReplay) {
  setupStepIndex = 1;
  renderSetupStep();
  document.getElementById('setup-overlay').classList.add('show');
  document.getElementById('setup-asana-pat').value = '';
  document.getElementById('setup-asana-msg').className = 'account-msg';
  document.getElementById('setup-asana-msg').textContent = '';

  fetch('api/token').then(r => r.json()).then(d => {
    document.getElementById('setup-token').value = d.token || '(unavailable)';
  }).catch(() => { document.getElementById('setup-token').value = '(unavailable)'; });

  const cfg = await getClientConfig();
  document.getElementById('setup-base-url').value = cfg.api_base_url || '(unavailable)';
  document.getElementById('setup-mcp-url').value = cfg.mcp_connector_url || '(ask your admin for this URL)';
}
```
Replace with:
```javascript
async function openSetup(fromReplay) {
  setupStepIndex = 1;
  renderSetupStep();
  document.getElementById('setup-overlay').classList.add('show');
  document.getElementById('setup-asana-pat').value = '';
  document.getElementById('setup-asana-msg').className = 'account-msg';
  document.getElementById('setup-asana-msg').textContent = '';
}
```

**Note:** `getClientConfig()`/`cfg.api_base_url` are no longer used anywhere in the setup walkthrough after this change (the new step 1 has no copy-paste base-URL field). Leave the `getClientConfig()` function itself defined (harmless, and `/api/client-config` still exists for it to call) unless a later check finds another caller — do not remove it speculatively.

- [ ] **Step 4: Verify**

`grep -c "setup-token\|setup-mcp-url\|mcp_connector_url" viewer/daily-brief-viewer.html` returns `0`.

- [ ] **Step 5: Commit**

```bash
git add viewer/daily-brief-viewer.html
git commit -m "frontend: rewrite Setup walkthrough for v2 (no token/MCP connector steps)"
```

---

## Task 5: Deployment Config and Docs Cleanup

**Files:**
- Modify: `viewer/webapp/k8s/deployment.yaml`
- Modify: `viewer/webapp/DEPLOYMENT.md`
- Modify: `viewer/webapp/db/README.md`

**Interfaces:** None — configuration and documentation only.

- [ ] **Step 1: Remove MCP_CONNECTOR_URL from deployment.yaml**

In `viewer/webapp/k8s/deployment.yaml`, find:
```yaml
            # Plain value, not a secret — just the connector's public URL,
            # shown verbatim in the in-app setup walkthrough.
            - name: MCP_CONNECTOR_URL
              value: "https://mcp.dashboard.es-sandbox.com/mcp"
            # Built from postgres-credentials via $(VAR) interpolation
```
Replace with:
```yaml
            # Built from postgres-credentials via $(VAR) interpolation
```

- [ ] **Step 2: Update DEPLOYMENT.md's migration note (step 4 area) and rollout section (step 8)**

In `viewer/webapp/DEPLOYMENT.md`, find:
```
**If Postgres is already running from a previous deploy** (true as of the `api_token` column being added — anyone who stood this up before that change needs this): apply the migration by hand once, against the running database:

```powershell
Get-Content -Raw viewer/webapp/db/migrations/001_add_api_token.sql | kubectl exec -i -n daily-brief postgres-0 -- psql -U dailybrief -d dailybrief
```

Safe to run more than once. Existing users don't need a separate backfill step — `db.get_or_create_user` assigns each of them a token automatically the next time they sign in (see step 8).
```
Replace with:
```
**If Postgres is already running from a previous deploy** (true for any cluster that predates migration 007): apply each new migration by hand once, against the running database — for example:

```powershell
Get-Content -Raw viewer/webapp/db/migrations/007_drop_api_token_and_account_projects.sql | kubectl exec -i -n daily-brief postgres-0 -- psql -U dailybrief -d dailybrief
```

Safe to run more than once.
```

In the same file, find:
```
## 8. Roll out to test users

This is now fully self-service — no `kubectl` step per person:

1. **They sign in.** Visit the URL, sign in with any `@camunda.com` account. `db.get_or_create_user` creates their `users` row and assigns them a random `api_token` in that same call — nothing for you to provision.
2. **They grab their token.** While signed in, visiting `/daily-brief/api/token` in the browser returns `{"token": "...", "email": "..."}`. That's the value they put in their own copy of the daily-brief skill's Admin Config to authenticate `/api/items/upsert` and `/api/items/batch-upsert` calls.
3. **Their skill starts pushing items**, and their brief shows up next time they load the viewer.

If someone's token ever leaks or they just want a fresh one, `POST /daily-brief/api/token/rotate` (while signed in) issues a new one and immediately invalidates the old one.

**Ordering matters**: a token only exists once someone has signed in through the browser at least once — there's no way to provision a token for an email that's never authenticated, since Azure AD sign-in is the only trusted identity check in this system. A new person's sequence is always sign in first, then configure their skill, never the other way around.

Signing in and having reports show up are still two separate things — a person can sign in today and see an empty state until either their own skill upserts some items using their token, or you manually insert a test row for a quick look (see `db/README.md`'s schema for the shape).
```
Replace with:
```
## 8. Roll out to test users

This is fully self-service — no `kubectl` step per person:

1. **They sign in.** Visit the URL, sign in with any `@camunda.com` account. `db.get_or_create_user` creates their `users` row automatically — nothing for you to provision.
2. **They run `/daily-brief setup` in Claude** (see the in-app Setup walkthrough, or the skill repo's own `README.md`) — this writes their brief config directly to their own Google Drive.
3. **They connect Google Drive and (optionally) Asana** from the Account panel or the Setup walkthrough.
4. **Their skill starts writing briefs to Drive**, and their brief shows up next time they load the viewer (after connecting Drive).

Signing in and having reports show up are still two separate things — a person can sign in today and see an empty state until they've connected Google Drive and run the skill at least once.
```

- [ ] **Step 3: Update the "What this doesn't do yet" bullets**

In `viewer/webapp/DEPLOYMENT.md`, find:
```
- **The skill now calls `/api/items/upsert` and `/api/items/batch-upsert`.** These replace what would have been `/api/upload` in the old file-based design — the skill calls `batch-upsert` once per full brief generation, and `upsert` again later for a single item's refresh (no separate "patch a file" flow needed anymore, unlike the old `references/section-refresh.md` approach). See `references/item-sync.md`, `references/post-meeting-patch.md`, and `references/section-refresh.md` in the skill repo for the wiring.
- **Checked-state sync.** Done. Checkbox toggles call `/api/items/<section>/<item_key>/checked`, which persists across devices and, for Action Items, mirrors onto the linked Asana task's completed state when the signed-in person has their own `asana_pat` configured (see the section above).
```
Replace with:
```
- **Checked-state sync.** Done. Checkbox toggles call `/api/items/<section>/<item_key>/checked`, which persists across devices and, for Action Items, mirrors onto the linked Asana task's completed state when the signed-in person has their own `asana_pat` configured (see the section above).
```

In the same file, find:
```
- **Admin panel.** `/admin` lists every signed-in user (sign-up date, active brief count, last-active date) and can rotate any user's token — useful for unblocking a stuck sync without asking them to self-diagnose a 401/403. Gated by `ADMIN_EMAILS` (comma-separated, case-insensitive) in `deployment.yaml`; empty/unset 404s the panel for everyone. Not a secret value, so it's a plain env var rather than a Kubernetes Secret — edit `deployment.yaml` directly and `kubectl -n daily-brief rollout restart deployment/daily-brief-viewer` to pick up a change.
```
Replace with:
```
- **Admin panel.** `/admin` lists every real signed-in user (sign-up date, active brief count, last-active date) and lets an admin create/impersonate/delete throwaway test users for exercising the new-user experience safely (see the Admin Impersonation section below). Gated by `ADMIN_EMAILS` (comma-separated, case-insensitive) in `deployment.yaml`; empty/unset 404s the panel for everyone. Not a secret value, so it's a plain env var rather than a Kubernetes Secret — edit `deployment.yaml` directly and `kubectl -n daily-brief rollout restart deployment/daily-brief-viewer` to pick up a change.
```

In the same file, find:
```
- **Live Action Items pull.** Overdue, Due Next 7 Days, and No Due Date are no longer synced by the skill at all — the webapp fetches them straight from Asana on every `/brief/<date>` page render (`app.py`'s `_fetch_live_action_items`), using `users.asana_pat` and the `account_projects` table (mirrored from `Meeting Manager Config.xlsx` by the skill's `daily_brief_sync_account_projects` MCP tool — see `migrations/004_add_account_projects.sql`). Only New Items — tasks the brief run itself just created — are ever written to Postgres for this section now.
- **In-app setup walkthrough.** First sign-in (`onboarding_completed_at IS NULL` on the `users` row) automatically opens a 6-step modal in the viewer: get your API token, add the daily-brief-mcp-server connector in Claude, install the skill and set `DAILY_BRIEF_API_BASE_URL`, connect data-source MCP connectors, a few odds and ends (Claude Desktop, Asana/Drive IDs), and an optional step to connect a personal Asana PAT for the live Overdue/Due Next 7 Days/No Due Date pull (skippable — New Items keeps working either way). It calls `/api/onboarding/complete` on finishing so it doesn't reopen automatically, but anyone can reopen it any time via the "Setup" button in the topbar. The walkthrough's copy-paste values (base URL, MCP connector URL) come from `/api/client-config` — the connector URL is the plain `MCP_CONNECTOR_URL` env var below, set to whatever `mcp/DEPLOYMENT.md` (or `mcp/README.md`) says your daily-brief-mcp-server is actually reachable at.
- **Account panel.** The "Account" button in the topbar shows the signed-in person's own token (with copy) and a "Rotate token" button with inline instructions on what to update afterward (the connector's `Authorization` header) — this is the self-service alternative to having an admin do it from `/admin`. It also shows Asana connection status with save/disconnect controls for `asana_pat`, so connecting or removing Asana doesn't require replaying the whole setup walkthrough.
```
Replace with:
```
- **Live Action Items pull.** Overdue, Due Next 7 Days, and No Due Date are no longer synced by the skill at all — the webapp fetches them straight from Asana on every `/brief/<date>` page render (`app.py`'s `_fetch_live_action_items`), using `users.asana_pat` and the account→project-GID mapping read live from that user's Drive `account-config.json` (`gdrive_briefs.get_account_projects`). Only New Items — tasks the brief run itself just created — are ever written to Postgres for this section now.
- **In-app setup walkthrough.** First sign-in (`onboarding_completed_at IS NULL` on the `users` row) automatically opens a 4-step modal in the viewer: install the skill and run its First-Run Setup, connect data-source connectors, a couple of odds and ends (Claude Desktop, README pointer), and an optional step to connect a personal Asana PAT for the live Overdue/Due Next 7 Days/No Due Date pull (skippable — New Items keeps working either way). It calls `/api/onboarding/complete` on finishing so it doesn't reopen automatically, but anyone can reopen it any time via the "Setup" button in the topbar.
- **Account panel.** The "Account" button in the topbar shows the signed-in person's email, Google Drive connection status, and Asana connection status with save/disconnect controls for `asana_pat`, so connecting or removing Asana doesn't require replaying the whole setup walkthrough.
- **Admin impersonation.** `/admin` can create throwaway test users (synthetic `@daily-brief.local` emails, `is_test = TRUE`) and impersonate them to exercise the new-user onboarding flow without touching real data. A banner shows while impersonating, with a one-click return to the admin's own session. Impersonation can only ever target a test user — never a real one, even via a crafted user ID.
```

- [ ] **Step 4: Update db/README.md's account_projects description**

In `viewer/webapp/db/README.md`, find:
```
## `users.asana_pat` and `account_projects`

As of `migrations/003_add_asana_pat.sql` and `004_add_account_projects.sql`, Action Items has two data sources instead of one:

- **New Items** — still Postgres-backed, exactly as before. The skill only upserts items where `content.is_new` is true (the task it just created this run); it no longer syncs Overdue/Due Next 7 Days/No Due Date rows to Postgres at all.
- **Overdue / Due Next 7 Days / No Due Date** — pulled live from Asana's API at page-render time (see `app.py`'s `_fetch_live_action_items`), using the signed-in user's own `users.asana_pat` and the project GIDs in `account_projects` for that `user_id`. Never persisted; recomputed on every page load. If `asana_pat` is `NULL` (the person skipped that step of setup), these three subsections are omitted entirely and only New Items renders.

`account_projects` is a full replace-per-user mirror — the skill re-syncs the whole table for a user on every brief run via `daily_brief_sync_account_projects`, so a stale row for a removed account doesn't linger.
```
Replace with:
```
## `users.asana_pat`

As of `migrations/003_add_asana_pat.sql`, Action Items has two data sources instead of one:

- **New Items** — still Postgres-backed, exactly as before. The skill only upserts items where `content.is_new` is true (the task it just created this run); it no longer syncs Overdue/Due Next 7 Days/No Due Date rows to Postgres at all.
- **Overdue / Due Next 7 Days / No Due Date** — pulled live from Asana's API at page-render time (see `app.py`'s `_fetch_live_action_items`), using the signed-in user's own `users.asana_pat` and the account→project-GID mapping read live from that user's Google Drive `account-config.json` (`gdrive_briefs.get_account_projects`) — no Postgres table involved. Never persisted; recomputed on every page load. If `asana_pat` is `NULL` (the person skipped that step of setup), or Google Drive isn't connected, these three subsections are omitted entirely and only New Items renders.

(As of migration 007, the earlier Postgres-backed `account_projects` mirror table this section used to describe has been dropped — the mapping now comes exclusively from Drive.)
```

- [ ] **Step 5: Verify**

`grep -c "MCP_CONNECTOR\|api_token\|account_projects\b" viewer/webapp/k8s/deployment.yaml viewer/webapp/DEPLOYMENT.md viewer/webapp/db/README.md` — each file should report `0` matches, except any remaining historical reference to migration file names themselves (e.g. `004_add_account_projects.sql` as a filename mention is fine to keep as historical context if it appears in an unrelated sentence — re-read the diff once to confirm nothing stale remains describing it as a currently-used table).

- [ ] **Step 6: Commit**

```bash
git add viewer/webapp/k8s/deployment.yaml viewer/webapp/DEPLOYMENT.md viewer/webapp/db/README.md
git commit -m "docs: update deployment docs for v2-only architecture"
```

---

## Task 6: Skill Sync Check Removal

**Files:**
- Modify: `README.md` (repo root)

**Interfaces:** None — documentation only.

- [ ] **Step 1: Remove the sync_state field**

In `README.md`, find:
```json
{
  "brief_data_folder_id": "...",
  "meeting_run_log_sheet_id": "...",
  "recurring_activities_project_gid": "...",
  "status_update_cache_file_id": "...",
  "slack_user_id": "UXXXXXXXXXX",
  "key_contacts": ["First Last", "..."],
  "sync_state": { "skill_source_sha": "...", "references_source_sha": "...", "sync_check_last_run": "..." }
}
```
Replace with:
```json
{
  "brief_data_folder_id": "...",
  "meeting_run_log_sheet_id": "...",
  "recurring_activities_project_gid": "...",
  "status_update_cache_file_id": "...",
  "slack_user_id": "UXXXXXXXXXX",
  "key_contacts": ["First Last", "..."]
}
```

- [ ] **Step 2: Verify**

`grep -c "sync_state\|Skill Sync Check" README.md` returns `0`.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: remove dead Skill Sync Check field from config.json example"
```

---

## Task 7: Admin Impersonation Backend

**Files:**
- Modify: `viewer/webapp/db.py`
- Modify: `viewer/webapp/app.py`

**Interfaces:**
- Consumes: Task 1's `users.is_test` column; the session shape set by `auth_callback` (`{email, name, oid, slug, id}`, see `app.py`).
- Produces: `db.create_test_user(label=None) -> {'id', 'email', 'slug', 'is_test', 'created_at'}`, `db.list_test_users() -> list`, `db.delete_test_user(user_id) -> bool` (True if a test user was actually deleted, False if the id didn't exist or wasn't a test user). New routes: `POST /api/admin/test-users`, `GET /api/admin/test-users`, `DELETE /api/admin/test-users/<int:user_id>`, `POST /api/admin/impersonate/<int:user_id>/start`, `POST /api/admin/impersonate/stop`. `/api/whoami` gains `impersonating` (bool) and, when true, `real_admin_email`. Consumed by Task 8 (frontend).

- [ ] **Step 1: Add test-user functions to db.py**

At the end of `viewer/webapp/db.py`, append:

```python


def create_test_user(label: Optional[str] = None) -> dict:
    """Creates a throwaway test-user row for admin impersonation. Never a
    real person — email is always a synthetic @daily-brief.local address,
    optionally incorporating an admin-supplied label for readability in the
    admin panel's Test Users list."""
    suffix = secrets.token_hex(4)
    local_part = f"test-{label.strip().lower().replace(' ', '-')}-{suffix}" if label and label.strip() else f"test-{suffix}"
    email = f"{local_part}@daily-brief.local"
    slug = slugify_test_email(local_part)
    with cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO users (email, slug, is_test)
            VALUES (%s, %s, TRUE)
            RETURNING id, email, slug, is_test, created_at
            """,
            (email, slug),
        )
        return cur.fetchone()


def slugify_test_email(local_part: str) -> str:
    """Test-user emails are already URL-safe lowercase-with-hyphens, so the
    slug is just the local part itself — no dependency on app.py's
    slugify_user (which expects a real email with an @domain to strip)."""
    return local_part


def list_test_users() -> list:
    """All admin-created throwaway test users, for the admin panel's Test
    Users panel and its impersonation picker."""
    with cursor() as cur:
        cur.execute(
            "SELECT id, email, slug, created_at FROM users WHERE is_test = TRUE ORDER BY created_at DESC"
        )
        return cur.fetchall()


def delete_test_user(user_id: int) -> bool:
    """Deletes a test user row. Returns False (does nothing) if user_id
    doesn't exist or isn't a test user — this is the safety guard that
    keeps a crafted ID from ever deleting a real person's account."""
    with cursor(commit=True) as cur:
        cur.execute("DELETE FROM users WHERE id = %s AND is_test = TRUE", (user_id,))
        return cur.rowcount > 0


def is_test_user(user_id: int) -> bool:
    """Used to gate impersonation start — never let an admin impersonate a
    real user, even via a crafted ID in the request."""
    with cursor() as cur:
        cur.execute("SELECT is_test FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        return bool(row and row['is_test'])
```

- [ ] **Step 2: Add impersonation routes to app.py**

In `viewer/webapp/app.py`, find:
```python
@app.route('/api/admin/config')
@login_required
@admin_required
def admin_config_status():
```
Replace with:
```python
@app.route('/api/admin/test-users', methods=['GET'])
@login_required
@admin_required
def admin_list_test_users():
    return jsonify(db.list_test_users())


@app.route('/api/admin/test-users', methods=['POST'])
@login_required
@admin_required
def admin_create_test_user():
    body = request.get_json(silent=True) or {}
    user = db.create_test_user(body.get('label'))
    return jsonify(user), 201


@app.route('/api/admin/test-users/<int:user_id>', methods=['DELETE'])
@login_required
@admin_required
def admin_delete_test_user(user_id):
    deleted = db.delete_test_user(user_id)
    if not deleted:
        abort(404, 'Not a test user, or already deleted.')
    return jsonify({'status': 'ok'})


@app.route('/api/admin/impersonate/<int:user_id>/start', methods=['POST'])
@login_required
@admin_required
def admin_impersonate_start(user_id):
    """Switches the current session to view as a throwaway test user.
    Guarded twice: @admin_required above, and the is_test check here — this
    route can never target a real user's account, even via a crafted ID."""
    if not db.is_test_user(user_id):
        abort(404, 'Can only impersonate a test user.')
    if session.get('admin_original_user'):
        abort(400, 'Already impersonating — stop first.')
    test_user = db.get_user_by_id(user_id)
    if not test_user:
        abort(404)
    session['admin_original_user'] = session['user']
    session['user'] = {
        'email': test_user['email'],
        'name': test_user['email'],
        'oid': f"test-{test_user['id']}",
        'slug': test_user['slug'],
        'id': test_user['id'],
    }
    return jsonify({'status': 'ok', 'email': test_user['email']})


@app.route('/api/admin/impersonate/stop', methods=['POST'])
@login_required
def admin_impersonate_stop():
    """Ends impersonation and restores the real admin's session. Not
    admin-gated: by construction only someone who started an impersonation
    can have admin_original_user set, and they must always be able to end
    it even if ADMIN_EMAILS changes mid-session."""
    original = session.pop('admin_original_user', None)
    if original:
        session['user'] = original
    return jsonify({'status': 'ok'})


@app.route('/api/admin/config')
@login_required
@admin_required
def admin_config_status():
```

- [ ] **Step 3: Surface impersonation state in /api/whoami**

In `viewer/webapp/app.py`, find:
```python
@app.route('/api/whoami')
@login_required
def whoami():
    user = db.get_user_by_id(request.brief_user['id'])
    return jsonify({
        'name': request.brief_user['name'],
        'email': request.brief_user['email'],
        'onboarding_completed': bool(user and user['onboarding_completed_at']),
    })
```
Replace with:
```python
@app.route('/api/whoami')
@login_required
def whoami():
    user = db.get_user_by_id(request.brief_user['id'])
    original = session.get('admin_original_user')
    response = {
        'name': request.brief_user['name'],
        'email': request.brief_user['email'],
        'onboarding_completed': bool(user and user['onboarding_completed_at']),
        'impersonating': bool(original),
    }
    if original:
        response['real_admin_email'] = original['email']
    return jsonify(response)
```

- [ ] **Step 4: Verify**

Run: `python -m py_compile viewer/webapp/app.py viewer/webapp/db.py`
Expected: no output, exit code 0.

Run: `python -c "
import ast
tree = ast.parse(open('viewer/webapp/db.py').read())
names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
assert {'create_test_user', 'list_test_users', 'delete_test_user', 'is_test_user'} <= names
print('OK')
"`
Expected: `OK`

Since a live Postgres instance isn't available in this environment to fully exercise these functions end-to-end, this verification is limited to syntax/import correctness — note this explicitly in the task report as a concern for manual follow-up (per the plan's testing strategy).

- [ ] **Step 5: Commit**

```bash
git add viewer/webapp/db.py viewer/webapp/app.py
git commit -m "feat: add admin test-user creation and impersonation backend"
```

---

## Task 8: Admin Impersonation Frontend

**Files:**
- Modify: `viewer/webapp/templates/admin.html`
- Modify: `viewer/daily-brief-viewer.html`

**Interfaces:**
- Consumes: Task 7's routes (`/api/admin/test-users` GET/POST, `/api/admin/test-users/<id>` DELETE, `/api/admin/impersonate/<id>/start`, `/api/admin/impersonate/stop`) and `/api/whoami`'s new `impersonating`/`real_admin_email` fields.

- [ ] **Step 1: Add a Test Users panel to admin.html**

In `viewer/webapp/templates/admin.html`, find:
```html
  <div class="panel">
    <div class="panel-head">Users</div>
```
Replace with:
```html
  <div class="panel">
    <div class="panel-head">Test Users</div>
    <div class="panel-body">
      <div style="display:flex;gap:8px;margin-bottom:10px;">
        <input class="btn" id="test-user-label" type="text" placeholder="Optional label" style="flex:1;text-align:left;cursor:text;">
        <button class="btn" onclick="createTestUser()">Create test user</button>
      </div>
      <table id="test-users-table" style="display:none;">
        <thead>
          <tr>
            <th>Email</th>
            <th>Created</th>
            <th></th>
          </tr>
        </thead>
        <tbody id="test-users-body"></tbody>
      </table>
      <div class="empty" id="test-users-loading">Loading…</div>
      <div class="msg" id="test-users-msg"></div>
    </div>
  </div>

  <div class="panel">
    <div class="panel-head">Users</div>
```

- [ ] **Step 2: Add the Test Users JS**

In `viewer/webapp/templates/admin.html`, find:
```javascript
loadConfig();
loadUsers();
```
Replace with:
```javascript
async function loadTestUsers() {
  const table = document.getElementById('test-users-table');
  const body = document.getElementById('test-users-body');
  const loading = document.getElementById('test-users-loading');
  try {
    const res = await fetch('api/admin/test-users');
    if (!res.ok) throw new Error('status ' + res.status);
    const users = await res.json();
    loading.style.display = 'none';
    if (!users.length) {
      loading.style.display = '';
      loading.textContent = 'No test users yet.';
      return;
    }
    table.style.display = '';
    body.innerHTML = users.map(u => `
      <tr data-id="${u.id}">
        <td class="email">${u.email}</td>
        <td>${fmtDate(u.created_at)}</td>
        <td>
          <button class="btn" onclick="impersonateUser(${u.id}, '${u.email}')">Impersonate</button>
          <button class="btn danger" onclick="deleteTestUser(${u.id}, '${u.email}')">Delete</button>
        </td>
      </tr>
    `).join('');
  } catch (e) {
    loading.textContent = 'Could not load test users.';
  }
}

async function createTestUser() {
  const labelInput = document.getElementById('test-user-label');
  const msg = document.getElementById('test-users-msg');
  msg.className = 'msg';
  msg.textContent = 'Creating…';
  try {
    const res = await fetch('api/admin/test-users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ label: labelInput.value.trim() || null }),
    });
    if (!res.ok) throw new Error('status ' + res.status);
    labelInput.value = '';
    msg.className = 'msg ok';
    msg.textContent = 'Test user created.';
    loadTestUsers();
  } catch (e) {
    msg.className = 'msg err';
    msg.textContent = 'Could not create test user.';
  }
}

async function impersonateUser(userId, email) {
  if (!confirm(`View the app as ${email}? You can return to your own account anytime via the banner.`)) {
    return;
  }
  try {
    const res = await fetch(`api/admin/impersonate/${userId}/start`, { method: 'POST' });
    if (!res.ok) throw new Error('status ' + res.status);
    window.location.href = './';
  } catch (e) {
    document.getElementById('test-users-msg').className = 'msg err';
    document.getElementById('test-users-msg').textContent = `Could not impersonate ${email}.`;
  }
}

async function deleteTestUser(userId, email) {
  if (!confirm(`Delete test user ${email}? This can't be undone.`)) return;
  const msg = document.getElementById('test-users-msg');
  try {
    const res = await fetch(`api/admin/test-users/${userId}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('status ' + res.status);
    msg.className = 'msg ok';
    msg.textContent = `Deleted ${email}.`;
    loadTestUsers();
  } catch (e) {
    msg.className = 'msg err';
    msg.textContent = `Could not delete ${email}.`;
  }
}

loadConfig();
loadUsers();
loadTestUsers();
```

- [ ] **Step 3: Add the impersonation banner to daily-brief-viewer.html**

In `viewer/daily-brief-viewer.html`, find:
```html
<div class="status-bar" id="status-bar">
  <div class="spinner" id="spinner"></div>
  <span id="status-msg"></span>
```
Replace with:
```html
<div class="modal-overlay" id="impersonation-banner" style="display:none;position:fixed;top:0;left:0;right:0;background:#b02520;color:#fff;padding:8px 16px;text-align:center;font-size:13px;z-index:2000;">
  Viewing as: <strong id="impersonation-email"></strong> (test) &mdash;
  <button style="background:#fff;color:#b02520;border:none;border-radius:4px;padding:3px 10px;font-size:12px;cursor:pointer;margin-left:6px;" onclick="stopImpersonating()">Return to my account</button>
</div>

<div class="status-bar" id="status-bar">
  <div class="spinner" id="spinner"></div>
  <span id="status-msg"></span>
```

- [ ] **Step 4: Add the banner's JS**

In `viewer/daily-brief-viewer.html`, find:
```javascript
async function checkOnboarding() {
  try {
    const res = await fetch('api/whoami');
    const d = await res.json();
    if (!d.onboarding_completed) openSetup();
  } catch (e) {
    // Fails open — no walkthrough rather than blocking the viewer over it.
  }
}

initMode();
loadBriefList();
refreshGoogleStatus();
checkOnboarding();
```
Replace with:
```javascript
async function checkOnboarding() {
  try {
    const res = await fetch('api/whoami');
    const d = await res.json();
    if (d.impersonating) {
      document.getElementById('impersonation-email').textContent = d.email;
      document.getElementById('impersonation-banner').style.display = 'block';
    }
    if (!d.onboarding_completed) openSetup();
  } catch (e) {
    // Fails open — no walkthrough rather than blocking the viewer over it.
  }
}

async function stopImpersonating() {
  try {
    await fetch('api/admin/impersonate/stop', { method: 'POST' });
  } catch (e) { /* best-effort */ }
  window.location.href = './admin';
}

initMode();
loadBriefList();
refreshGoogleStatus();
checkOnboarding();
```

- [ ] **Step 5: Verify**

Run: `python -m py_compile viewer/webapp/app.py` (unaffected by this task, but confirms the working tree is still consistent after Task 7).

Read through both modified files once to confirm the new markup/JS is well-formed (matching element IDs between HTML and JS: `test-user-label`, `test-users-table`, `test-users-body`, `test-users-loading`, `test-users-msg` in admin.html; `impersonation-banner`, `impersonation-email` in daily-brief-viewer.html) — no live browser available in this environment, so this is a by-inspection check, not a click-through.

- [ ] **Step 6: Commit**

```bash
git add viewer/webapp/templates/admin.html viewer/daily-brief-viewer.html
git commit -m "feat: add Test Users panel and impersonation banner to frontend"
```

---

## Self-Review Notes

**Spec coverage:**
- Part 1 (Skill Sync Check) → Task 6
- Part 2 (MCP/token backend removal, incl. DB migration) → Tasks 1, 2
- Part 2's frontend/deployment pieces (admin.html, Account panel, k8s, DEPLOYMENT.md, db/README.md) → Tasks 3, 5
- Part 3 (Setup walkthrough rewrite) → Task 4
- Part 4 (admin impersonation) → Tasks 7, 8
- Scope-boundary constraint (brief_days/items untouched) → explicitly called out in Global Constraints and Task 2's step 5 (the removed route span stops before touching `/api/items/<section>/<item_key>/checked`)

**Type/interface consistency check:** `db.get_or_create_user`'s new return shape (`{id, onboarding_completed_at}`, no `api_token`) is consistent with its only caller (`app.py`'s `auth_callback`, which never read `api_token` from it anyway — confirmed by the exact code already shown at app.py:668). `is_test` is added in Task 1 and consumed correctly by Task 7's `create_test_user`/`list_test_users`/`delete_test_user`/`is_test_user` and Task 2's `list_users_with_stats` filter.

**No placeholders:** every step contains complete code/exact diffs; the two "cannot fully verify without a live Postgres/browser" notes (Task 7 Step 4, Task 8 Step 5) are explicit, honest scope limits for this sandboxed environment, not vague hand-waving — each names exactly what manual follow-up is needed.
