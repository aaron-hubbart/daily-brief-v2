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

import psycopg2
import psycopg2.extras
from flask import g

DATABASE_URL = os.environ.get('DATABASE_URL')


def get_conn():
    if 'db_conn' not in g:
        if not DATABASE_URL:
            raise RuntimeError(
                'DATABASE_URL is not set. See DEPLOYMENT.md for the Postgres connection string format.'
            )
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
    first sign-in and — this is what makes new-user setup automatic —
    assigns a random api_token at the same time, with no admin step
    required. Returns {'id': ..., 'api_token': ...}.
    """
    with cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO users (email, slug) VALUES (%s, %s)
            ON CONFLICT (email) DO UPDATE SET email = EXCLUDED.email
            RETURNING id, api_token
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
        cur.execute("SELECT id, email, slug, api_token, created_at FROM users WHERE id = %s", (user_id,))
        return cur.fetchone()


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
