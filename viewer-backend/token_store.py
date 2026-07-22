"""
Encrypted per-user token store, replacing db.py's Postgres-backed users
table. Holds exactly the small secrets this app needs server-side now that
brief content itself lives entirely in each user's own Google Drive: their
Google OAuth tokens (to read/write Drive on their behalf), their Asana PAT
(unchanged from today), and which Drive folder holds their brief data.

One SQLite file on a PVC (TOKEN_DB_PATH), one row per user keyed by Entra
object id. WAL mode + a busy timeout so concurrent gunicorn workers don't
fail on lock contention at this app's traffic level (a handful of users,
occasional requests) -- same "simplest option that's correct" reasoning
db.py used for one-Postgres-connection-per-request.
"""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from cryptography.fernet import Fernet
from flask import g

TOKEN_DB_PATH = os.environ.get('TOKEN_DB_PATH', '/data/tokens.db')

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    entra_object_id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    brief_data_folder_id TEXT,
    google_access_token_enc BLOB,
    google_refresh_token_enc BLOB,
    google_token_expiry TEXT,
    asana_pat_enc BLOB,
    onboarding_completed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _fernet() -> Fernet:
    key = os.environ.get('TOKEN_ENCRYPTION_KEY')
    if not key:
        raise RuntimeError(
            'TOKEN_ENCRYPTION_KEY is not set. Generate one with '
            '`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` '
            'and store it as a Kubernetes Secret -- see DEPLOYMENT.md.'
        )
    return Fernet(key.encode())


def _encrypt(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode('utf-8'))


def _decrypt(ciphertext) -> str:
    return _fernet().decrypt(bytes(ciphertext)).decode('utf-8')


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn():
    if 'token_db_conn' not in g:
        conn = sqlite3.connect(TOKEN_DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=5000')
        conn.executescript(SCHEMA)
        g.token_db_conn = conn
    return g.token_db_conn


def close_conn(exc=None):
    conn = g.pop('token_db_conn', None)
    if conn is not None:
        conn.close()


@contextmanager
def cursor(commit=False):
    conn = get_conn()
    cur = conn.cursor()
    try:
        yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise


def _row_to_user(row) -> dict:
    return {
        'entra_object_id': row['entra_object_id'],
        'email': row['email'],
        'brief_data_folder_id': row['brief_data_folder_id'],
        'onboarding_completed_at': row['onboarding_completed_at'],
    }


def get_or_create_user(entra_object_id: str, email: str) -> dict:
    now = _now()
    with cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO users (entra_object_id, email, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (entra_object_id) DO UPDATE SET email = excluded.email, updated_at = ?
            """,
            (entra_object_id, email, now, now, now),
        )
        cur.execute('SELECT * FROM users WHERE entra_object_id = ?', (entra_object_id,))
        return _row_to_user(cur.fetchone())


def get_user(entra_object_id: str) -> dict | None:
    with cursor() as cur:
        cur.execute('SELECT * FROM users WHERE entra_object_id = ?', (entra_object_id,))
        row = cur.fetchone()
        return _row_to_user(row) if row else None


def set_brief_data_folder_id(entra_object_id: str, folder_id: str) -> None:
    with cursor(commit=True) as cur:
        cur.execute(
            'UPDATE users SET brief_data_folder_id = ?, updated_at = ? WHERE entra_object_id = ?',
            (folder_id, _now(), entra_object_id),
        )


def get_asana_pat(entra_object_id: str) -> str | None:
    with cursor() as cur:
        cur.execute('SELECT asana_pat_enc FROM users WHERE entra_object_id = ?', (entra_object_id,))
        row = cur.fetchone()
        if not row or row['asana_pat_enc'] is None:
            return None
        return _decrypt(row['asana_pat_enc'])


def set_asana_pat(entra_object_id: str, pat: str) -> None:
    with cursor(commit=True) as cur:
        cur.execute(
            'UPDATE users SET asana_pat_enc = ?, updated_at = ? WHERE entra_object_id = ?',
            (_encrypt(pat), _now(), entra_object_id),
        )


def clear_asana_pat(entra_object_id: str) -> None:
    with cursor(commit=True) as cur:
        cur.execute(
            'UPDATE users SET asana_pat_enc = NULL, updated_at = ? WHERE entra_object_id = ?',
            (_now(), entra_object_id),
        )


def count_users_with_asana_pat() -> int:
    with cursor() as cur:
        cur.execute('SELECT COUNT(*) AS n FROM users WHERE asana_pat_enc IS NOT NULL')
        return cur.fetchone()['n']


def get_google_tokens(entra_object_id: str) -> dict | None:
    with cursor() as cur:
        cur.execute(
            'SELECT google_access_token_enc, google_refresh_token_enc, google_token_expiry '
            'FROM users WHERE entra_object_id = ?',
            (entra_object_id,),
        )
        row = cur.fetchone()
        if not row or row['google_refresh_token_enc'] is None:
            return None
        return {
            'access_token': _decrypt(row['google_access_token_enc']),
            'refresh_token': _decrypt(row['google_refresh_token_enc']),
            'expiry': row['google_token_expiry'],
        }


def set_google_tokens(entra_object_id: str, access_token: str, refresh_token: str, expiry: str) -> None:
    with cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE users
            SET google_access_token_enc = ?, google_refresh_token_enc = ?,
                google_token_expiry = ?, updated_at = ?
            WHERE entra_object_id = ?
            """,
            (_encrypt(access_token), _encrypt(refresh_token), expiry, _now(), entra_object_id),
        )


def mark_onboarding_complete(entra_object_id: str) -> None:
    with cursor(commit=True) as cur:
        cur.execute(
            'UPDATE users SET onboarding_completed_at = COALESCE(onboarding_completed_at, ?), updated_at = ? '
            'WHERE entra_object_id = ?',
            (_now(), _now(), entra_object_id),
        )


def list_users() -> list[dict]:
    with cursor() as cur:
        cur.execute('SELECT entra_object_id, email, created_at FROM users ORDER BY email')
        return [dict(row) for row in cur.fetchall()]
