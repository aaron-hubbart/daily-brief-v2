"""
Database access layer for the Postgres-backed daily-brief storage.

One connection per request, opened lazily and closed in a Flask teardown
handler — simplest option that's correct for this app's traffic level
(a handful of users, occasional requests). A connection pool would be
overkill here and adds a failure mode (pool exhaustion) this app doesn't
need to think about yet.
"""
import json
import os
import secrets
from contextlib import contextmanager
from typing import Optional

import psycopg2
import psycopg2.extras
from flask import g

DATABASE_URL = os.environ.get('DATABASE_URL')


def get_conn():
    if 'db_conn' not in g:
        if not DATABASE_URL:
            # No database configured - app runs in read-only mode
            # Data should be read from Google Drive instead
            return None
        g.db_conn = psycopg2.connect(DATABASE_URL)
    return g.db_conn


def close_conn(exc=None):
    conn = g.pop('db_conn', None)
    if conn is not None:
        if exc is not None:
            conn.rollback()
        conn.close()


@contextmanager
def cursor(commit=False):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


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


def get_user_by_id(user_id: int):
    with cursor() as cur:
        cur.execute(
            "SELECT id, email, slug, asana_pat, created_at, onboarding_completed_at FROM users WHERE id = %s",
            (user_id,),
        )
        return cur.fetchone()


def create_sso_session(user_id: int, ttl_hours: int = 8) -> str:
    """Creates a shared cross-app SSO session row and returns its opaque
    token. Called from /auth/callback once Flask's own sign-in succeeds —
    the token is what gets set as the shared cookie a second app (the TAM
    Dashboard's Express proxy) can hand to /internal/sso/verify to resolve
    the signed-in user without ever seeing this app's own session cookie."""
    token = secrets.token_urlsafe(32)
    with cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO sso_sessions (token, user_id, expires_at)
            VALUES (%s, %s, now() + (%s || ' hours')::interval)
            """,
            (token, user_id, ttl_hours),
        )
    return token


def get_user_by_sso_token(token: str):
    """Resolves a shared-cookie token to its user, or None if the token is
    missing, unknown, or expired. Also bumps last_seen_at so an idle-session
    cleanup pass (not implemented yet) could distinguish idle from active."""
    with cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE sso_sessions SET last_seen_at = now()
            WHERE token = %s AND expires_at > now()
            RETURNING user_id
            """,
            (token,),
        )
        row = cur.fetchone()
        if not row:
            return None
        cur.execute(
            "SELECT id, email, slug FROM users WHERE id = %s",
            (row['user_id'],),
        )
        return cur.fetchone()


def invalidate_sso_session(token: str) -> None:
    """Called from /logout so a signed-out user's shared cookie can't still
    resolve to a valid session in another app after this app forgets them."""
    with cursor(commit=True) as cur:
        cur.execute("DELETE FROM sso_sessions WHERE token = %s", (token,))


def get_asana_pat(user_id: int):
    """Returns the user's Asana PAT, or None if they've never set one (or
    skipped that step of setup). None disables the live Action Items pull
    and the two-way checkbox/due-date sync back to Asana for this user."""
    with cursor() as cur:
        cur.execute("SELECT asana_pat FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        return row['asana_pat'] if row else None


def set_asana_pat(user_id: int, pat: str) -> None:
    with cursor(commit=True) as cur:
        cur.execute("UPDATE users SET asana_pat = %s WHERE id = %s", (pat, user_id))


def clear_asana_pat(user_id: int) -> None:
    """Removing the PAT is the 'disconnect' action from the Account panel —
    same effect as skipping it during setup: live pull and two-way sync
    both turn off immediately for this user."""
    with cursor(commit=True) as cur:
        cur.execute("UPDATE users SET asana_pat = NULL WHERE id = %s", (user_id,))


def count_users_with_asana_pat() -> int:
    """For the admin panel's presence check — never the actual token values."""
    with cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM users WHERE asana_pat IS NOT NULL")
        return cur.fetchone()['n']


def mark_onboarding_complete(user_id: int) -> None:
    """Idempotent — only sets the timestamp the first time; re-completing
    (e.g. clicking through the walkthrough again from the Account panel)
    doesn't reset it to a later time."""
    with cursor(commit=True) as cur:
        cur.execute(
            "UPDATE users SET onboarding_completed_at = COALESCE(onboarding_completed_at, now()) WHERE id = %s",
            (user_id,),
        )


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


def list_active_briefs(user_id: int) -> list:
    """Days visible to the end user — active only, newest first."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT brief_date, brief_type, last_updated_at
            FROM brief_days
            WHERE user_id = %s AND status = 'active'
            ORDER BY brief_date DESC
            """,
            (user_id,),
        )
        return cur.fetchall()


def get_brief_day(user_id: int, brief_date: str):
    with cursor() as cur:
        cur.execute(
            """
            SELECT id, brief_date, brief_type, status, last_updated_at
            FROM brief_days
            WHERE user_id = %s AND brief_date = %s AND status = 'active'
            """,
            (user_id, brief_date),
        )
        return cur.fetchone()


def get_items_for_day(brief_day_id: int) -> list:
    with cursor() as cur:
        cur.execute(
            """
            SELECT id, section, item_key, item_type, title, subtitle, badge,
                   links, content, checked, display_order, generated_at
            FROM items
            WHERE brief_day_id = %s
            ORDER BY section, display_order, id
            """,
            (brief_day_id,),
        )
        return cur.fetchall()


def upsert_brief_day(user_id: int, brief_date: str, brief_type: str = None) -> int:
    with cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO brief_days (user_id, brief_date, brief_type)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, brief_date) DO UPDATE
                SET brief_type = COALESCE(EXCLUDED.brief_type, brief_days.brief_type),
                    last_updated_at = now(),
                    -- A fresh upsert on an archived day un-archives it — the
                    -- skill regenerating or refreshing content for an old
                    -- date is a deliberate signal it should be visible again.
                    status = 'active',
                    archived_at = NULL
            RETURNING id
            """,
            (user_id, brief_date, brief_type),
        )
        return cur.fetchone()['id']


def upsert_item(brief_day_id: int, item: dict) -> None:
    with cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO items (
                brief_day_id, section, item_key, item_type, title, subtitle,
                badge, links, content, checked, display_order, generated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (brief_day_id, section, item_key) DO UPDATE SET
                item_type = EXCLUDED.item_type,
                title = EXCLUDED.title,
                subtitle = EXCLUDED.subtitle,
                badge = EXCLUDED.badge,
                links = EXCLUDED.links,
                content = EXCLUDED.content,
                checked = EXCLUDED.checked,
                display_order = EXCLUDED.display_order,
                generated_at = now(),
                updated_at = now()
            """,
            (
                brief_day_id,
                item['section'],
                item['item_key'],
                item.get('item_type', 'checkable'),
                item.get('title'),
                item.get('subtitle'),
                json.dumps(item['badge']) if item.get('badge') is not None else None,
                json.dumps(item.get('links', [])),
                json.dumps(item.get('content', {})),
                item.get('checked'),
                item.get('display_order', 0),
            ),
        )


def set_item_checked(brief_day_id: int, section: str, item_key: str, checked: bool) -> bool:
    with cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE items SET checked = %s, updated_at = now()
            WHERE brief_day_id = %s AND section = %s AND item_key = %s
            """,
            (checked, brief_day_id, section, item_key),
        )
        return cur.rowcount > 0


def set_item_due_date(brief_day_id: int, section: str, item_key: str, due_on) -> bool:
    """
    Updates content.due_on for a single item — the write side of the
    Action Items due-date box. due_on is an ISO date string ('YYYY-MM-DD')
    or None to clear it. jsonb_set with a NULL value would delete the key
    entirely under some Postgres versions' semantics, so a None due_on is
    written as JSON null via to_jsonb(NULL::text) rather than removed,
    keeping the key present with an empty value for the template to check.
    """
    with cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE items
            SET content = jsonb_set(COALESCE(content, '{}'::jsonb), '{due_on}', to_jsonb(%s::text), true),
                updated_at = now()
            WHERE brief_day_id = %s AND section = %s AND item_key = %s
            """,
            (due_on, brief_day_id, section, item_key),
        )
        return cur.rowcount > 0


def get_google_refresh_token(user_id: int) -> Optional[str]:
    """Get the user's stored Google refresh token."""
    if not DATABASE_URL:
        return None
    
    with cursor() as cur:
        cur.execute('SELECT google_refresh_token FROM users WHERE id = %s', (user_id,))
        row = cur.fetchone()
        return row['google_refresh_token'] if row else None


def set_google_refresh_token(user_id: int, refresh_token: Optional[str]) -> bool:
    """Store or clear the user's Google refresh token."""
    if not DATABASE_URL:
        return False
    
    try:
        with cursor(commit=True) as cur:
            cur.execute(
                'UPDATE users SET google_refresh_token = %s WHERE id = %s',
                (refresh_token, user_id),
            )
        return True
    except Exception:
        return False


def get_google_drive_folder_id(user_id: int) -> Optional[str]:
    """Get the user's Google Drive folder ID for storing briefs."""
    if not DATABASE_URL:
        return None
    
    with cursor() as cur:
        cur.execute('SELECT google_drive_folder_id FROM users WHERE id = %s', (user_id,))
        row = cur.fetchone()
        return row['google_drive_folder_id'] if row else None


def set_google_drive_folder_id(user_id: int, folder_id: Optional[str]) -> bool:
    """Store or clear the user's Google Drive folder ID."""
    if not DATABASE_URL:
        return False

    try:
        with cursor(commit=True) as cur:
            cur.execute(
                'UPDATE users SET google_drive_folder_id = %s WHERE id = %s',
                (folder_id, user_id),
            )
        return True
    except Exception:
        return False


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
