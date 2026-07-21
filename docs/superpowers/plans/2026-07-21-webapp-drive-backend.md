# Webapp Drive-Backed Storage Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hosted daily-brief webapp's Postgres-backed storage (`db.py`) with a Google-Drive-backed storage layer, while leaving every route's URL, request/response shape, template, and the Entra ID (M365) sign-in flow unchanged.

**Architecture:** Two new modules — `token_store.py` (a small encrypted SQLite file holding each user's Google OAuth tokens, Asana PAT, and linked Drive folder id) and `drive_store.py` (reads brief content from each user's own Drive via their OAuth token, and owns the two things the webapp writes: checkbox/due-date state and retention cleanup) — plus a new `google_oauth.py` for the OAuth consent/refresh flow. `app.py` keeps its existing routes and templates; only the bodies that called `db.*` are swapped to call the new modules. `db.py` and the Postgres dependency are deleted.

**Tech Stack:** Python 3.12, Flask 3.0.3 (unchanged), `msal` (unchanged, Entra ID flow untouched), `sqlite3` (stdlib) for the token store, `cryptography` (Fernet) for encrypting stored tokens, `urllib.request`/`urllib.error` (stdlib, matching the existing Asana-call style in `app.py` — no new HTTP client dependency) for both the Google OAuth token endpoint and the Drive v3 REST API, `pytest` + `pytest-mock` for tests.

## Global Constraints

- Every module in this plan lives under `viewer-backend/` in `aaron-hubbart/daily-brief-v2` (already created, private, `main` branch, spec committed at `docs/superpowers/specs/2026-07-21-daily-brief-v2-design.md`).
- `app.py`'s routes, URL paths, JSON response shapes, and template names/variables must not change — front-end behavior is out of scope for this plan.
- No new third-party HTTP client library (no `requests`, no `google-api-python-client`) — match the existing codebase's `urllib.request`-based style used for Asana calls.
- Secrets (encryption key, Azure/Google client secrets) are never read from anywhere but environment variables backed by Kubernetes Secrets — never hardcoded, never logged.
- `(section, item_key)` — already a stable, content-derived compound key per `references/item-sync.md`'s existing conventions (e.g. `ym-0900-bofa-triage`, `recap-bank-of-america`) — is the key used for per-item state (checked / due-date override). This resolves the design spec's open item about a separate "stable item ID hash": no new hashing scheme is needed, `section:item_key` (colon-joined) is the state-file key directly.
- The Drive data layout (read side) matches `docs/superpowers/specs/2026-07-21-daily-brief-v2-design.md`: `/briefs/{date}/manifest.json`, `/briefs/{date}/meetings.json`, `/briefs/{date}/accounts/{slug}.json`, `/briefs/{date}/today.json`, `/briefs/{date}/action-items.json`, `/briefs/{date}/fyi.json`, `/briefs/{date}/updates/{slug}.json`, `/briefs/{date}/manager-update.json`, `/config/account-config.json`.
- The state file (write side) is extended beyond the spec's original checkbox-only description to also hold due-date overrides, since `references/item-sync.md`'s Action Items due-date editing is existing front-end functionality that must be preserved: `/state/{date}.json` is `{"<section>:<item_key>": {"checked": bool|null, "due_on_override": "YYYY-MM-DD"|null}, ...}`.

---

### Task 1: Project scaffolding

**Files:**
- Create: `viewer-backend/requirements.txt`
- Create: `viewer-backend/requirements-dev.txt`
- Create: `viewer-backend/conftest.py`
- Create: `viewer-backend/pytest.ini`

**Interfaces:**
- Produces: a `viewer-backend/` directory that `pytest` runs cleanly against with zero tests collected, and the dependency set every later task assumes.

- [ ] **Step 1: Create `requirements.txt`**

```
flask==3.0.3
gunicorn==22.0.0
msal==1.31.0
cryptography==43.0.0
```

- [ ] **Step 2: Create `requirements-dev.txt`**

```
-r requirements.txt
pytest==8.3.2
pytest-mock==3.14.0
```

- [ ] **Step 3: Create `pytest.ini`**

```ini
[pytest]
testpaths = tests
```

- [ ] **Step 4: Create `conftest.py`**

```python
import os
import tempfile

import pytest


@pytest.fixture
def token_db_path(monkeypatch):
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    os.remove(path)
    monkeypatch.setenv('TOKEN_DB_PATH', path)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def encryption_key(monkeypatch):
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    monkeypatch.setenv('TOKEN_ENCRYPTION_KEY', key)
    return key
```

- [ ] **Step 5: Verify pytest runs with zero tests**

Run: `cd viewer-backend && python -m pip install -r requirements-dev.txt && python -m pytest -v`
Expected: `no tests ran` (exit code 5), no import errors.

- [ ] **Step 6: Commit**

```bash
git add viewer-backend/requirements.txt viewer-backend/requirements-dev.txt viewer-backend/conftest.py viewer-backend/pytest.ini
git commit -m "Scaffold viewer-backend project and test config"
```

---

### Task 2: `token_store.py` — schema, encryption, and accessors

**Files:**
- Create: `viewer-backend/token_store.py`
- Test: `viewer-backend/tests/test_token_store.py`

**Interfaces:**
- Consumes: `token_db_path` and `encryption_key` fixtures from `conftest.py` (Task 1).
- Produces (used by `app.py` in Task 7/8 and `google_oauth.py` in Task 3):
  - `get_or_create_user(entra_object_id: str, email: str) -> dict` — `{entra_object_id, email, brief_data_folder_id, onboarding_completed_at}`
  - `get_user(entra_object_id: str) -> dict | None` — same shape
  - `set_brief_data_folder_id(entra_object_id: str, folder_id: str) -> None`
  - `get_asana_pat(entra_object_id: str) -> str | None`
  - `set_asana_pat(entra_object_id: str, pat: str) -> None`
  - `clear_asana_pat(entra_object_id: str) -> None`
  - `count_users_with_asana_pat() -> int`
  - `get_google_tokens(entra_object_id: str) -> dict | None` — `{access_token, refresh_token, expiry}` (expiry is an ISO string)
  - `set_google_tokens(entra_object_id: str, access_token: str, refresh_token: str, expiry: str) -> None`
  - `mark_onboarding_complete(entra_object_id: str) -> None`
  - `list_users() -> list[dict]` — `{entra_object_id, email, created_at}`, for the admin panel

- [ ] **Step 1: Write failing tests for user creation and Asana PAT round-trip**

```python
# viewer-backend/tests/test_token_store.py
import importlib


def _fresh_store():
    import token_store
    importlib.reload(token_store)
    return token_store


def test_get_or_create_user_creates_then_returns_same_row(token_db_path, encryption_key):
    store = _fresh_store()
    created = store.get_or_create_user('oid-1', 'aaron@camunda.com')
    assert created['entra_object_id'] == 'oid-1'
    assert created['email'] == 'aaron@camunda.com'
    assert created['brief_data_folder_id'] is None
    assert created['onboarding_completed_at'] is None

    again = store.get_or_create_user('oid-1', 'aaron@camunda.com')
    assert again == created


def test_asana_pat_round_trip_is_encrypted_at_rest(token_db_path, encryption_key):
    store = _fresh_store()
    store.get_or_create_user('oid-1', 'aaron@camunda.com')

    assert store.get_asana_pat('oid-1') is None
    assert store.count_users_with_asana_pat() == 0

    store.set_asana_pat('oid-1', '1/abc123secret')
    assert store.get_asana_pat('oid-1') == '1/abc123secret'
    assert store.count_users_with_asana_pat() == 1

    with open(token_db_path, 'rb') as f:
        raw = f.read()
    assert b'1/abc123secret' not in raw

    store.clear_asana_pat('oid-1')
    assert store.get_asana_pat('oid-1') is None
    assert store.count_users_with_asana_pat() == 0


def test_google_tokens_round_trip(token_db_path, encryption_key):
    store = _fresh_store()
    store.get_or_create_user('oid-1', 'aaron@camunda.com')

    assert store.get_google_tokens('oid-1') is None

    store.set_google_tokens('oid-1', 'access-tok', 'refresh-tok', '2026-07-21T12:00:00+00:00')
    tokens = store.get_google_tokens('oid-1')
    assert tokens == {
        'access_token': 'access-tok',
        'refresh_token': 'refresh-tok',
        'expiry': '2026-07-21T12:00:00+00:00',
    }


def test_brief_data_folder_and_onboarding(token_db_path, encryption_key):
    store = _fresh_store()
    store.get_or_create_user('oid-1', 'aaron@camunda.com')

    store.set_brief_data_folder_id('oid-1', 'drive-folder-abc')
    assert store.get_user('oid-1')['brief_data_folder_id'] == 'drive-folder-abc'

    store.mark_onboarding_complete('oid-1')
    first = store.get_user('oid-1')['onboarding_completed_at']
    assert first is not None

    store.mark_onboarding_complete('oid-1')
    assert store.get_user('oid-1')['onboarding_completed_at'] == first


def test_list_users(token_db_path, encryption_key):
    store = _fresh_store()
    store.get_or_create_user('oid-1', 'aaron@camunda.com')
    store.get_or_create_user('oid-2', 'other@camunda.com')

    users = store.list_users()
    emails = sorted(u['email'] for u in users)
    assert emails == ['aaron@camunda.com', 'other@camunda.com']
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd viewer-backend && python -m pytest tests/test_token_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'token_store'`

- [ ] **Step 3: Implement `token_store.py`**

```python
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


def get_user(entra_object_id: str):
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


def get_asana_pat(entra_object_id: str):
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


def get_google_tokens(entra_object_id: str):
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


def list_users() -> list:
    with cursor() as cur:
        cur.execute('SELECT entra_object_id, email, created_at FROM users ORDER BY email')
        return [dict(row) for row in cur.fetchall()]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd viewer-backend && python -m pytest tests/test_token_store.py -v`
Expected: PASS (5 tests) — note these tests run outside a Flask app/request context, so `get_conn`'s use of `flask.g` needs an active app context. Add this to the top of `test_token_store.py` if the run above fails with "Working outside of application context":

```python
import pytest


@pytest.fixture(autouse=True)
def _app_context():
    from flask import Flask
    app = Flask(__name__)
    with app.app_context():
        yield
```

Re-run and confirm PASS.

- [ ] **Step 5: Commit**

```bash
git add viewer-backend/token_store.py viewer-backend/tests/test_token_store.py
git commit -m "Add encrypted SQLite token store, replacing db.py's users table"
```

---

### Task 3: `google_oauth.py` — consent URL, code exchange, token refresh

**Files:**
- Create: `viewer-backend/google_oauth.py`
- Test: `viewer-backend/tests/test_google_oauth.py`

**Interfaces:**
- Consumes: `token_store.get_google_tokens`, `token_store.set_google_tokens` (Task 2).
- Produces (used by `app.py` in Task 7):
  - `GoogleAuthRequired` — exception class, raised when no valid token is available and the user must be sent through consent again.
  - `get_authorization_url(state: str) -> str`
  - `exchange_code_for_tokens(code: str) -> dict` — `{access_token, refresh_token, expiry}`
  - `get_valid_access_token(entra_object_id: str) -> str` — raises `GoogleAuthRequired` if the user has no stored token or the refresh fails.

- [ ] **Step 1: Write failing tests**

```python
# viewer-backend/tests/test_google_oauth.py
import json
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'client-id-123')
    monkeypatch.setenv('GOOGLE_CLIENT_SECRET', 'client-secret-abc')
    monkeypatch.setenv('GOOGLE_REDIRECT_URI', 'https://dashboard.es-sandbox.com/daily-brief/auth/google/callback')


def test_get_authorization_url_includes_required_params():
    import google_oauth
    url = google_oauth.get_authorization_url('state-xyz')
    assert url.startswith('https://accounts.google.com/o/oauth2/v2/auth?')
    assert 'client_id=client-id-123' in url
    assert 'state=state-xyz' in url
    assert 'access_type=offline' in url
    assert 'prompt=consent' in url
    assert 'scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fdrive' in url


def test_exchange_code_for_tokens_posts_and_parses_response(mocker):
    import google_oauth

    fake_response = MagicMock()
    fake_response.read.return_value = json.dumps({
        'access_token': 'new-access',
        'refresh_token': 'new-refresh',
        'expires_in': 3600,
    }).encode('utf-8')
    fake_response.__enter__.return_value = fake_response
    mocker.patch('urllib.request.urlopen', return_value=fake_response)

    result = google_oauth.exchange_code_for_tokens('auth-code-1')
    assert result['access_token'] == 'new-access'
    assert result['refresh_token'] == 'new-refresh'
    assert result['expiry'] > '2026-07-21T00:00:00'


def test_get_valid_access_token_raises_when_no_stored_token(mocker):
    import google_oauth
    mocker.patch('token_store.get_google_tokens', return_value=None)

    with pytest.raises(google_oauth.GoogleAuthRequired):
        google_oauth.get_valid_access_token('oid-1')


def test_get_valid_access_token_returns_cached_token_when_not_expired(mocker):
    import google_oauth
    from datetime import datetime, timedelta, timezone

    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    mocker.patch('token_store.get_google_tokens', return_value={
        'access_token': 'still-good', 'refresh_token': 'r', 'expiry': future,
    })
    refresh_spy = mocker.patch('urllib.request.urlopen')

    token = google_oauth.get_valid_access_token('oid-1')
    assert token == 'still-good'
    refresh_spy.assert_not_called()


def test_get_valid_access_token_refreshes_when_expired(mocker):
    import google_oauth
    from datetime import datetime, timedelta, timezone

    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    mocker.patch('token_store.get_google_tokens', return_value={
        'access_token': 'stale', 'refresh_token': 'refresh-tok', 'expiry': past,
    })
    set_tokens_spy = mocker.patch('token_store.set_google_tokens')

    fake_response = MagicMock()
    fake_response.read.return_value = json.dumps({
        'access_token': 'refreshed-access',
        'expires_in': 3600,
    }).encode('utf-8')
    fake_response.__enter__.return_value = fake_response
    mocker.patch('urllib.request.urlopen', return_value=fake_response)

    token = google_oauth.get_valid_access_token('oid-1')
    assert token == 'refreshed-access'
    set_tokens_spy.assert_called_once()
    args = set_tokens_spy.call_args[0]
    assert args[0] == 'oid-1'
    assert args[1] == 'refreshed-access'
    assert args[2] == 'refresh-tok'  # refresh token itself doesn't rotate on a refresh grant
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd viewer-backend && python -m pytest tests/test_google_oauth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'google_oauth'`

- [ ] **Step 3: Implement `google_oauth.py`**

```python
"""
Google OAuth 2.0 authorization-code flow for the webapp's own per-user Drive
access -- separate from the skill's own Google Drive connector (a different
OAuth client entirely). Requires the broad `drive` scope (not the narrower
`drive.file` scope) since this app must read files created by that other
client -- see docs/superpowers/specs/2026-07-21-daily-brief-v2-design.md.

Hand-rolled via urllib, matching the existing Asana-call style in app.py,
rather than adding google-auth-oauthlib as a dependency for what is just two
simple form-encoded POSTs.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import token_store

GOOGLE_AUTH_BASE = 'https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
DRIVE_SCOPE = 'https://www.googleapis.com/auth/drive'

# Refresh this many seconds before actual expiry, so a request never races a
# token that's valid at the check but expired by the time it's used.
EXPIRY_SAFETY_MARGIN_SECONDS = 60


class GoogleAuthRequired(Exception):
    """Raised when the caller must be redirected through Google's consent
    screen again -- no stored token, or the refresh grant itself failed
    (e.g. the user revoked access from their Google Account settings)."""


def _client_id():
    val = os.environ.get('GOOGLE_CLIENT_ID')
    if not val:
        raise RuntimeError('GOOGLE_CLIENT_ID is not set. See DEPLOYMENT.md.')
    return val


def _client_secret():
    val = os.environ.get('GOOGLE_CLIENT_SECRET')
    if not val:
        raise RuntimeError('GOOGLE_CLIENT_SECRET is not set. See DEPLOYMENT.md.')
    return val


def _redirect_uri():
    val = os.environ.get('GOOGLE_REDIRECT_URI')
    if not val:
        raise RuntimeError('GOOGLE_REDIRECT_URI is not set. See DEPLOYMENT.md.')
    return val


def get_authorization_url(state: str) -> str:
    params = {
        'client_id': _client_id(),
        'redirect_uri': _redirect_uri(),
        'response_type': 'code',
        'scope': DRIVE_SCOPE,
        'state': state,
        # offline + consent: without both, a returning user who already
        # granted access once may not get a refresh_token back at all on a
        # later consent (Google only issues one on the *first* grant unless
        # prompt=consent forces the picker/consent screen every time).
        'access_type': 'offline',
        'prompt': 'consent',
    }
    return f'{GOOGLE_AUTH_BASE}?{urllib.parse.urlencode(params)}'


def _post_form(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode('utf-8')
    req = urllib.request.Request(url, data=body, method='POST',
                                  headers={'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode('utf-8'))


def _expiry_from_expires_in(expires_in: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()


def exchange_code_for_tokens(code: str) -> dict:
    data = _post_form(GOOGLE_TOKEN_URL, {
        'code': code,
        'client_id': _client_id(),
        'client_secret': _client_secret(),
        'redirect_uri': _redirect_uri(),
        'grant_type': 'authorization_code',
    })
    if 'refresh_token' not in data:
        raise GoogleAuthRequired(
            'Google did not return a refresh token. This happens if consent was already granted '
            'previously without prompt=consent -- try revoking access at myaccount.google.com/permissions '
            'and signing in again.'
        )
    return {
        'access_token': data['access_token'],
        'refresh_token': data['refresh_token'],
        'expiry': _expiry_from_expires_in(data['expires_in']),
    }


def _refresh(refresh_token: str) -> dict:
    try:
        data = _post_form(GOOGLE_TOKEN_URL, {
            'refresh_token': refresh_token,
            'client_id': _client_id(),
            'client_secret': _client_secret(),
            'grant_type': 'refresh_token',
        })
    except urllib.error.HTTPError as e:
        raise GoogleAuthRequired(f'Google token refresh failed: HTTP {e.code}') from e
    return {
        'access_token': data['access_token'],
        'expiry': _expiry_from_expires_in(data['expires_in']),
    }


def get_valid_access_token(entra_object_id: str) -> str:
    tokens = token_store.get_google_tokens(entra_object_id)
    if not tokens:
        raise GoogleAuthRequired('No Google account linked yet.')

    expiry = datetime.fromisoformat(tokens['expiry'])
    now_with_margin = datetime.now(timezone.utc) + timedelta(seconds=EXPIRY_SAFETY_MARGIN_SECONDS)
    if expiry > now_with_margin:
        return tokens['access_token']

    refreshed = _refresh(tokens['refresh_token'])
    token_store.set_google_tokens(
        entra_object_id, refreshed['access_token'], tokens['refresh_token'], refreshed['expiry'],
    )
    return refreshed['access_token']
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd viewer-backend && python -m pytest tests/test_google_oauth.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add viewer-backend/google_oauth.py viewer-backend/tests/test_google_oauth.py
git commit -m "Add Google OAuth consent/refresh flow for per-user Drive access"
```

---

### Task 4: `drive_store.py` — low-level Drive REST primitives

**Files:**
- Create: `viewer-backend/drive_store.py`
- Test: `viewer-backend/tests/test_drive_store_primitives.py`

**Interfaces:**
- Consumes: an `access_token: str` (from `google_oauth.get_valid_access_token`, Task 3) passed into every function — this module never fetches tokens itself, keeping it testable without mocking OAuth.
- Produces (internal, used by Tasks 5 and 6 in this same module, prefixed `_` since they're not part of the public API `app.py` calls):
  - `_drive_request(access_token, method, url, params=None, body=None, extra_headers=None) -> dict | bytes`
  - `_find_child(access_token, parent_id, name) -> dict | None` — `{id, name, createdTime}` of a file or folder named `name` directly inside `parent_id`
  - `_list_children(access_token, parent_id, name=None) -> list[dict]` — all matches, newest `createdTime` first
  - `_download_json(access_token, file_id) -> dict`
  - `_upload_json_update(access_token, file_id, content: dict) -> None` — in-place update of an existing file
  - `_create_json_file(access_token, parent_id, name, content: dict) -> dict` — `{id, name}`
  - `_trash_file(access_token, file_id) -> None`

- [ ] **Step 1: Write failing tests**

```python
# viewer-backend/tests/test_drive_store_primitives.py
import json
from unittest.mock import MagicMock

import pytest


def _fake_response(payload_bytes):
    resp = MagicMock()
    resp.read.return_value = payload_bytes
    resp.__enter__.return_value = resp
    return resp


def test_find_child_returns_first_match_or_none(mocker):
    import drive_store

    mocker.patch('urllib.request.urlopen', return_value=_fake_response(json.dumps({
        'files': [{'id': 'file-1', 'name': 'manifest.json', 'createdTime': '2026-07-21T08:00:00.000Z'}]
    }).encode('utf-8')))
    found = drive_store._find_child('tok', 'folder-1', 'manifest.json')
    assert found == {'id': 'file-1', 'name': 'manifest.json', 'createdTime': '2026-07-21T08:00:00.000Z'}

    mocker.patch('urllib.request.urlopen', return_value=_fake_response(json.dumps({'files': []}).encode('utf-8')))
    assert drive_store._find_child('tok', 'folder-1', 'missing.json') is None


def test_list_children_sorted_newest_first(mocker):
    import drive_store

    mocker.patch('urllib.request.urlopen', return_value=_fake_response(json.dumps({
        'files': [
            {'id': 'f1', 'name': 'today.json', 'createdTime': '2026-07-21T08:00:00.000Z'},
            {'id': 'f2', 'name': 'today.json', 'createdTime': '2026-07-21T09:30:00.000Z'},
        ]
    }).encode('utf-8')))
    files = drive_store._list_children('tok', 'folder-1', 'today.json')
    assert [f['id'] for f in files] == ['f2', 'f1']


def test_download_json_parses_media_body(mocker):
    import drive_store

    mocker.patch('urllib.request.urlopen', return_value=_fake_response(
        json.dumps({'hello': 'world'}).encode('utf-8')
    ))
    assert drive_store._download_json('tok', 'file-1') == {'hello': 'world'}


def test_upload_json_update_sends_patch_with_media_body(mocker):
    import drive_store

    mock_urlopen = mocker.patch('urllib.request.urlopen', return_value=_fake_response(b'{}'))
    drive_store._upload_json_update('tok', 'file-1', {'checked': True})

    request_obj = mock_urlopen.call_args[0][0]
    assert request_obj.get_method() == 'PATCH'
    assert '/upload/drive/v3/files/file-1' in request_obj.full_url
    assert json.loads(request_obj.data.decode('utf-8')) == {'checked': True}


def test_create_json_file_sends_multipart_post(mocker):
    import drive_store

    mock_urlopen = mocker.patch('urllib.request.urlopen', return_value=_fake_response(
        json.dumps({'id': 'new-file-1', 'name': 'state.json'}).encode('utf-8')
    ))
    result = drive_store._create_json_file('tok', 'folder-1', 'state.json', {'a': 1})

    assert result == {'id': 'new-file-1', 'name': 'state.json'}
    request_obj = mock_urlopen.call_args[0][0]
    assert request_obj.get_method() == 'POST'
    assert '/upload/drive/v3/files' in request_obj.full_url
    assert b'"a": 1' in request_obj.data or b'"a":1' in request_obj.data
    assert b'folder-1' in request_obj.data


def test_trash_file_sends_patch_trashed_true(mocker):
    import drive_store

    mock_urlopen = mocker.patch('urllib.request.urlopen', return_value=_fake_response(b'{}'))
    drive_store._trash_file('tok', 'file-1')

    request_obj = mock_urlopen.call_args[0][0]
    assert request_obj.get_method() == 'PATCH'
    assert '/drive/v3/files/file-1' in request_obj.full_url
    assert json.loads(request_obj.data.decode('utf-8')) == {'trashed': True}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd viewer-backend && python -m pytest tests/test_drive_store_primitives.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'drive_store'`

- [ ] **Step 3: Implement the primitives in `drive_store.py`**

```python
"""
Google Drive-backed replacement for db.py. Reads brief content that the
daily-brief-v2 skill wrote via its own native Drive connector, and owns the
two things this webapp itself writes: per-item checked/due-date state and
retention cleanup -- both using the signed-in user's own OAuth access token
(full `drive` scope; see google_oauth.py), never a service account.

Every public function in this module takes access_token as an explicit
argument rather than fetching it itself, so callers (app.py) are the only
place that decides *whose* token is in play, and this module stays testable
without mocking OAuth at all.

Hand-rolled via urllib against the Drive v3 REST API, matching the existing
Asana-call style in app.py, rather than adding google-api-python-client as a
dependency.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
import uuid

DRIVE_API_BASE = 'https://www.googleapis.com/drive/v3'
DRIVE_UPLOAD_BASE = 'https://www.googleapis.com/upload/drive/v3'


def _drive_request(access_token, method, url, body_bytes=None, content_type=None):
    headers = {'Authorization': f'Bearer {access_token}'}
    if content_type:
        headers['Content-Type'] = content_type
    req = urllib.request.Request(url, data=body_bytes, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read()


def _list_children(access_token, parent_id, name=None):
    q = f"'{parent_id}' in parents and trashed = false"
    if name:
        q += f" and name = '{name}'"
    params = urllib.parse.urlencode({
        'q': q,
        'fields': 'files(id,name,createdTime)',
        'orderBy': 'createdTime desc',
        'pageSize': 100,
    })
    raw = _drive_request(access_token, 'GET', f'{DRIVE_API_BASE}/files?{params}')
    return json.loads(raw.decode('utf-8')).get('files', [])


def _find_child(access_token, parent_id, name):
    matches = _list_children(access_token, parent_id, name=name)
    return matches[0] if matches else None


def _download_json(access_token, file_id):
    raw = _drive_request(access_token, 'GET', f'{DRIVE_API_BASE}/files/{file_id}?alt=media')
    return json.loads(raw.decode('utf-8'))


def _upload_json_update(access_token, file_id, content):
    body = json.dumps(content).encode('utf-8')
    _drive_request(
        access_token, 'PATCH', f'{DRIVE_UPLOAD_BASE}/files/{file_id}?uploadType=media',
        body_bytes=body, content_type='application/json',
    )


def _create_json_file(access_token, parent_id, name, content):
    boundary = uuid.uuid4().hex
    metadata = json.dumps({'name': name, 'parents': [parent_id]})
    payload = (
        f'--{boundary}\r\n'
        'Content-Type: application/json; charset=UTF-8\r\n\r\n'
        f'{metadata}\r\n'
        f'--{boundary}\r\n'
        'Content-Type: application/json\r\n\r\n'
        f'{json.dumps(content)}\r\n'
        f'--{boundary}--'
    ).encode('utf-8')
    raw = _drive_request(
        access_token, 'POST', f'{DRIVE_UPLOAD_BASE}/files?uploadType=multipart',
        body_bytes=payload, content_type=f'multipart/related; boundary={boundary}',
    )
    data = json.loads(raw.decode('utf-8'))
    return {'id': data['id'], 'name': data['name']}


def _trash_file(access_token, file_id):
    body = json.dumps({'trashed': True}).encode('utf-8')
    _drive_request(
        access_token, 'PATCH', f'{DRIVE_API_BASE}/files/{file_id}',
        body_bytes=body, content_type='application/json',
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd viewer-backend && python -m pytest tests/test_drive_store_primitives.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add viewer-backend/drive_store.py viewer-backend/tests/test_drive_store_primitives.py
git commit -m "Add low-level Drive REST primitives to drive_store.py"
```

---

### Task 5: `drive_store.py` — reading brief content

**Files:**
- Modify: `viewer-backend/drive_store.py`
- Test: `viewer-backend/tests/test_drive_store_reads.py`

**Interfaces:**
- Consumes: `_find_child`, `_list_children`, `_download_json` (Task 4).
- Produces (used by `app.py` in Task 8):
  - `list_active_briefs(access_token, brief_data_folder_id) -> list[dict]` — `{brief_date, brief_type, last_updated_at}`, newest first
  - `get_brief_day(access_token, brief_data_folder_id, brief_date) -> dict | None` — the parsed `manifest.json`, plus `'folder_id'` (the `/briefs/{date}` folder's own id, needed by later reads)
  - `get_items_for_day(access_token, brief_data_folder_id, brief_date) -> list[dict]` — flattened items across every section file, each shaped exactly like `db.get_items_for_day`'s rows: `{section, item_key, item_type, title, subtitle, badge, links, content, checked, display_order, generated_at}`, with `checked`/`content.due_on` overridden by `/state/{brief_date}.json` when present
  - `get_account_projects(access_token, brief_data_folder_id) -> list[dict]` — `{account_name, project_gid}` from `/config/account-config.json`

- [ ] **Step 1: Write failing tests**

```python
# viewer-backend/tests/test_drive_store_reads.py
from unittest.mock import call


BRIEFS_ROOT = 'briefs-root-id'
DATE_FOLDER = 'date-folder-id'
CONFIG_ROOT = 'config-root-id'


def _child(id_, name, created='2026-07-21T08:00:00.000Z'):
    return {'id': id_, 'name': name, 'createdTime': created}


def test_list_active_briefs_reads_manifests_newest_first(mocker):
    import drive_store

    mocker.patch('drive_store._find_child', side_effect=lambda tok, parent, name: (
        _child('briefs-folder', 'briefs') if name == 'briefs' else None
    ))
    mocker.patch('drive_store._list_children', return_value=[
        _child('date-2026-07-21', '2026-07-21'),
        _child('date-2026-07-20', '2026-07-20'),
    ])
    manifests = {
        'date-2026-07-21': {'brief_date': '2026-07-21', 'brief_type': 'morning', 'generated_at': '2026-07-21T12:00:00Z'},
        'date-2026-07-20': {'brief_date': '2026-07-20', 'brief_type': 'evening', 'generated_at': '2026-07-20T22:00:00Z'},
    }

    def fake_find_manifest(tok, parent, name):
        if name != 'manifest.json':
            return None
        return _child('manifest-file', 'manifest.json')

    def fake_download(tok, file_id):
        # Map back from the folder being read via the _list_children call order
        return manifests['date-2026-07-21'] if file_id == 'manifest-file' else manifests['date-2026-07-20']

    result = drive_store.list_active_briefs('tok', 'root-folder')
    assert [d['brief_date'] for d in result] == ['2026-07-21', '2026-07-20']


def test_get_brief_day_returns_none_when_date_folder_missing(mocker):
    import drive_store

    mocker.patch('drive_store._find_child', return_value=None)
    assert drive_store.get_brief_day('tok', 'root-folder', '2026-07-19') is None


def test_get_items_for_day_flattens_sections_and_applies_state_overrides(mocker):
    import drive_store

    def fake_find_child(tok, parent, name):
        return _child(f'id-{name}', name)

    mocker.patch('drive_store._find_child', side_effect=fake_find_child)

    def fake_download(tok, file_id):
        if file_id == 'id-briefs':
            return None
        return {
            'id-2026-07-21': None,
            'id-meetings.json': [
                {'item_key': 'ym-0900-bofa', 'item_type': 'checkable', 'title': 'BofA Sync',
                 'subtitle': None, 'badge': None, 'links': [], 'content': {}, 'checked': False,
                 'display_order': 0, 'generated_at': '2026-07-21T08:00:00Z'},
            ],
            'id-today.json': [],
            'id-action-items.json': [
                {'item_key': 'action-999', 'item_type': 'checkable', 'title': 'Follow up',
                 'subtitle': None, 'badge': None, 'links': [], 'content': {'due_on': '2026-07-22', 'is_new': True, 'project_name': None},
                 'checked': False, 'display_order': 0, 'generated_at': '2026-07-21T08:00:00Z'},
            ],
            'id-fyi.json': [],
            'id-manager-update.json': {'item_key': 'mgr-update', 'item_type': 'text-block', 'title': 'Manager Update',
                                        'subtitle': None, 'badge': None, 'links': [], 'content': {'textarea': 'x'},
                                        'checked': None, 'display_order': 0, 'generated_at': '2026-07-21T08:00:00Z'},
            'id-state.json': {
                'yesterday-meetings:ym-0900-bofa': {'checked': True, 'due_on_override': None},
                'action-items:action-999': {'checked': None, 'due_on_override': '2026-07-25'},
            },
        }.get(file_id, [])

    mocker.patch('drive_store._download_json', side_effect=fake_download)
    mocker.patch('drive_store._list_children', return_value=[])

    items = drive_store.get_items_for_day('tok', 'root-folder', '2026-07-21')
    by_key = {f"{it['section']}:{it['item_key']}": it for it in items}

    assert by_key['yesterday-meetings:ym-0900-bofa']['checked'] is True
    assert by_key['action-items:action-999']['content']['due_on'] == '2026-07-25'


def test_get_account_projects_reads_config_file(mocker):
    import drive_store

    mocker.patch('drive_store._find_child', side_effect=lambda tok, parent, name: (
        _child('config-file', 'account-config.json') if name == 'account-config.json' else _child('config-folder', 'config')
    ))
    mocker.patch('drive_store._download_json', return_value={
        'accounts': [
            {'account_name': 'Bank of America', 'project_gid': '111', 'slack_channel_id': 'C0395GFC4PR'},
        ]
    })

    result = drive_store.get_account_projects('tok', 'root-folder')
    assert result == [{'account_name': 'Bank of America', 'project_gid': '111'}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd viewer-backend && python -m pytest tests/test_drive_store_reads.py -v`
Expected: FAIL — `AttributeError: module 'drive_store' has no attribute 'list_active_briefs'`

- [ ] **Step 3: Append the read functions to `drive_store.py`**

```python
SECTION_FILES = [
    ('meetings.json', 'yesterday-meetings'),
    ('today.json', 'today'),
    ('action-items.json', 'action-items'),
    ('fyi.json', 'fyi'),
]
SECTION_SUBFOLDERS = [
    ('accounts', 'account-recap'),
    ('updates', 'customer-updates'),
]


def _briefs_root(access_token, brief_data_folder_id):
    return _find_child(access_token, brief_data_folder_id, 'briefs')


def _date_folder(access_token, brief_data_folder_id, brief_date):
    root = _briefs_root(access_token, brief_data_folder_id)
    if not root:
        return None
    return _find_child(access_token, root['id'], brief_date)


def list_active_briefs(access_token, brief_data_folder_id):
    root = _briefs_root(access_token, brief_data_folder_id)
    if not root:
        return []
    results = []
    for date_folder in _list_children(access_token, root['id']):
        manifest_file = _find_child(access_token, date_folder['id'], 'manifest.json')
        if not manifest_file:
            continue
        manifest = _download_json(access_token, manifest_file['id'])
        results.append({
            'brief_date': manifest['brief_date'],
            'brief_type': manifest.get('brief_type'),
            'last_updated_at': manifest.get('generated_at'),
        })
    results.sort(key=lambda d: d['brief_date'], reverse=True)
    return results


def get_brief_day(access_token, brief_data_folder_id, brief_date):
    date_folder = _date_folder(access_token, brief_data_folder_id, brief_date)
    if not date_folder:
        return None
    manifest_file = _find_child(access_token, date_folder['id'], 'manifest.json')
    if not manifest_file:
        return None
    manifest = _download_json(access_token, manifest_file['id'])
    manifest['folder_id'] = date_folder['id']
    return manifest


def _read_section_file(access_token, folder_id, filename):
    f = _find_child(access_token, folder_id, filename)
    if not f:
        return []
    data = _download_json(access_token, f['id'])
    return data if isinstance(data, list) else ([data] if data else [])


def _read_section_subfolder(access_token, folder_id, subfolder_name):
    sub = _find_child(access_token, folder_id, subfolder_name)
    if not sub:
        return []
    items = []
    for child in _list_children(access_token, sub['id']):
        data = _download_json(access_token, child['id'])
        items.append(data)
    return items


def _read_state(access_token, brief_data_folder_id, brief_date):
    state_root = _find_child(access_token, brief_data_folder_id, 'state')
    if not state_root:
        return {}
    state_file = _find_child(access_token, state_root['id'], f'{brief_date}.json')
    if not state_file:
        return {}
    return _download_json(access_token, state_file['id'])


def get_items_for_day(access_token, brief_data_folder_id, brief_date):
    date_folder = _date_folder(access_token, brief_data_folder_id, brief_date)
    if not date_folder:
        return []

    items = []
    for filename, section_slug in SECTION_FILES:
        for item in _read_section_file(access_token, date_folder['id'], filename):
            items.append({**item, 'section': section_slug})

    for subfolder_name, section_slug in SECTION_SUBFOLDERS:
        for item in _read_section_subfolder(access_token, date_folder['id'], subfolder_name):
            items.append({**item, 'section': section_slug})

    manager_update_file = _find_child(access_token, date_folder['id'], 'manager-update.json')
    if manager_update_file:
        item = _download_json(access_token, manager_update_file['id'])
        items.append({**item, 'section': 'manager-update'})

    state = _read_state(access_token, brief_data_folder_id, brief_date)
    for item in items:
        key = f"{item['section']}:{item['item_key']}"
        override = state.get(key)
        if not override:
            continue
        if override.get('checked') is not None:
            item['checked'] = override['checked']
        if override.get('due_on_override') is not None:
            item.setdefault('content', {})['due_on'] = override['due_on_override']

    return items


def get_account_projects(access_token, brief_data_folder_id):
    config_folder = _find_child(access_token, brief_data_folder_id, 'config')
    if not config_folder:
        return []
    config_file = _find_child(access_token, config_folder['id'], 'account-config.json')
    if not config_file:
        return []
    config = _download_json(access_token, config_file['id'])
    return [
        {'account_name': a['account_name'], 'project_gid': a['project_gid']}
        for a in config.get('accounts', [])
        if a.get('project_gid')
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd viewer-backend && python -m pytest tests/test_drive_store_reads.py -v`
Expected: PASS (4 tests). If `test_list_active_briefs_reads_manifests_newest_first` fails on ordering, check that the two `_find_child`/`_download_json` mocks in that test are keyed correctly per the fixture above — this is the one test wiring multiple fakes together, most likely spot for a mock-configuration mistake rather than a `drive_store.py` bug.

- [ ] **Step 5: Commit**

```bash
git add viewer-backend/drive_store.py viewer-backend/tests/test_drive_store_reads.py
git commit -m "Add drive_store read functions: list_active_briefs, get_brief_day, get_items_for_day, get_account_projects"
```

---

### Task 6: `drive_store.py` — state writes and retention cleanup

**Files:**
- Modify: `viewer-backend/drive_store.py`
- Test: `viewer-backend/tests/test_drive_store_writes.py`

**Interfaces:**
- Consumes: `_find_child`, `_download_json`, `_upload_json_update`, `_create_json_file`, `_list_children`, `_trash_file` (Tasks 4-5).
- Produces (used by `app.py` in Task 8):
  - `set_item_checked(access_token, brief_data_folder_id, brief_date, section, item_key, checked) -> None`
  - `set_item_due_date(access_token, brief_data_folder_id, brief_date, section, item_key, due_on) -> None`
  - `run_retention_cleanup(access_token, brief_data_folder_id, active_days=14, hard_delete_days=30) -> dict` — `{trashed: [...], skipped: [...]}` — date folders older than `active_days` get trashed (soft-delete equivalent); this plan trashes rather than permanently deletes at both thresholds, since Drive's own Trash auto-empties after 30 days, giving an equivalent two-stage effect without a second destructive API call.

- [ ] **Step 1: Write failing tests**

```python
# viewer-backend/tests/test_drive_store_writes.py
def test_set_item_checked_updates_existing_state_file(mocker):
    import drive_store

    mocker.patch('drive_store._find_child', side_effect=lambda tok, parent, name: (
        {'id': 'state-root'} if name == 'state' else
        {'id': 'state-file'} if name == '2026-07-21.json' else None
    ))
    mocker.patch('drive_store._download_json', return_value={
        'yesterday-meetings:ym-0900-bofa': {'checked': False, 'due_on_override': None},
    })
    update_spy = mocker.patch('drive_store._upload_json_update')
    create_spy = mocker.patch('drive_store._create_json_file')

    drive_store.set_item_checked('tok', 'root-folder', '2026-07-21', 'yesterday-meetings', 'ym-0900-bofa', True)

    update_spy.assert_called_once()
    create_spy.assert_not_called()
    written_state = update_spy.call_args[0][2]
    assert written_state['yesterday-meetings:ym-0900-bofa']['checked'] is True


def test_set_item_checked_creates_state_file_and_folder_when_absent(mocker):
    import drive_store

    mocker.patch('drive_store._find_child', return_value=None)
    create_spy = mocker.patch('drive_store._create_json_file', side_effect=[
        {'id': 'new-state-root', 'name': 'state'},
        {'id': 'new-state-file', 'name': '2026-07-21.json'},
    ])
    update_spy = mocker.patch('drive_store._upload_json_update')

    drive_store.set_item_checked('tok', 'root-folder', '2026-07-21', 'today', 'today-0900-jpmc', False)

    assert create_spy.call_count == 2
    update_spy.assert_not_called()


def test_set_item_due_date_preserves_checked_value(mocker):
    import drive_store

    mocker.patch('drive_store._find_child', side_effect=lambda tok, parent, name: (
        {'id': 'state-root'} if name == 'state' else
        {'id': 'state-file'} if name == '2026-07-21.json' else None
    ))
    mocker.patch('drive_store._download_json', return_value={
        'action-items:action-999': {'checked': True, 'due_on_override': None},
    })
    update_spy = mocker.patch('drive_store._upload_json_update')

    drive_store.set_item_due_date('tok', 'root-folder', '2026-07-21', 'action-items', 'action-999', '2026-07-30')

    written_state = update_spy.call_args[0][2]
    entry = written_state['action-items:action-999']
    assert entry['due_on_override'] == '2026-07-30'
    assert entry['checked'] is True


def test_run_retention_cleanup_trashes_only_old_folders(mocker):
    import drive_store
    from datetime import date, timedelta

    today = date(2026, 7, 21)
    old_date = (today - timedelta(days=20)).isoformat()
    recent_date = (today - timedelta(days=2)).isoformat()

    mocker.patch('drive_store._find_child', return_value={'id': 'briefs-root'})
    mocker.patch('drive_store._list_children', return_value=[
        {'id': 'old-folder', 'name': old_date, 'createdTime': f'{old_date}T08:00:00.000Z'},
        {'id': 'recent-folder', 'name': recent_date, 'createdTime': f'{recent_date}T08:00:00.000Z'},
    ])
    trash_spy = mocker.patch('drive_store._trash_file')

    result = drive_store.run_retention_cleanup('tok', 'root-folder', active_days=14, today=today)

    trash_spy.assert_called_once_with('tok', 'old-folder')
    assert result == {'trashed': [old_date], 'skipped': [recent_date]}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd viewer-backend && python -m pytest tests/test_drive_store_writes.py -v`
Expected: FAIL — `AttributeError: module 'drive_store' has no attribute 'set_item_checked'`

- [ ] **Step 3: Append the write functions to `drive_store.py`**

```python
from datetime import date as _date


def _update_state_entry(access_token, brief_data_folder_id, brief_date, section, item_key, **fields):
    """
    Shared read-modify-write for both set_item_checked and
    set_item_due_date: 'state' is used as a folder-like container of
    per-date files -- Drive has no distinct "create folder" primitive
    exposed by this module (see _create_json_file's multipart body, which
    always sets a JSON mimetype), so the state root is itself just a
    zero-content JSON file used as a stable parent id for _find_child
    lookups on its date-named children. Intentionally simple over "correct
    Drive folder semantics" given the low volume involved (one file per
    active brief-date, per user).

    fields is exactly one of {checked: bool} or {due_on_override: str|None}
    -- whichever the caller didn't pass stays untouched on the existing
    entry, which is what lets a due-date edit preserve a prior checked
    value and vice versa.
    """
    state_root = _find_child(access_token, brief_data_folder_id, 'state')
    state = {}
    state_file = None
    if state_root:
        state_file = _find_child(access_token, state_root['id'], f'{brief_date}.json')
        if state_file:
            state = _download_json(access_token, state_file['id'])

    key = f'{section}:{item_key}'
    entry = state.get(key, {'checked': None, 'due_on_override': None})
    entry.update(fields)
    state[key] = entry

    if state_file:
        _upload_json_update(access_token, state_file['id'], state)
    else:
        if not state_root:
            state_root = _create_json_file(access_token, brief_data_folder_id, 'state', {})
        _create_json_file(access_token, state_root['id'], f'{brief_date}.json', state)


def set_item_checked(access_token, brief_data_folder_id, brief_date, section, item_key, checked):
    _update_state_entry(access_token, brief_data_folder_id, brief_date, section, item_key, checked=checked)


def set_item_due_date(access_token, brief_data_folder_id, brief_date, section, item_key, due_on):
    _update_state_entry(access_token, brief_data_folder_id, brief_date, section, item_key, due_on_override=due_on)


def run_retention_cleanup(access_token, brief_data_folder_id, active_days=14, hard_delete_days=30, today=None):
    """
    Trashes /briefs/{date} folders older than active_days. hard_delete_days
    is accepted for interface parity with the old 14/30-day Postgres model
    but not separately implemented: Drive auto-empties Trash after 30 days
    on its own, so a single trash call already produces the same two-stage
    effect without this module needing a second destructive delete call.
    """
    today = today or _date.today()
    root = _find_child(access_token, brief_data_folder_id, 'briefs')
    if not root:
        return {'trashed': [], 'skipped': []}

    trashed, skipped = [], []
    for folder in _list_children(access_token, root['id']):
        try:
            folder_date = _date.fromisoformat(folder['name'])
        except ValueError:
            continue
        if (today - folder_date).days > active_days:
            _trash_file(access_token, folder['id'])
            trashed.append(folder['name'])
        else:
            skipped.append(folder['name'])
    return {'trashed': trashed, 'skipped': skipped}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd viewer-backend && python -m pytest tests/test_drive_store_writes.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Re-run the full drive_store test suite**

Run: `cd viewer-backend && python -m pytest tests/test_drive_store_primitives.py tests/test_drive_store_reads.py tests/test_drive_store_writes.py -v`
Expected: PASS (14 tests total)

- [ ] **Step 6: Commit**

```bash
git add viewer-backend/drive_store.py viewer-backend/tests/test_drive_store_writes.py
git commit -m "Add drive_store state writes (checked/due-date) and retention cleanup"
```

---

### Task 7: `app.py` — Google OAuth consent wiring and Drive-folder onboarding

**Files:**
- Modify: `viewer-backend/app.py` (new file in this repo, copied forward from `viewer/webapp/app.py` in `aaron-hubbart/daily-brief` as the starting point for this task — see Step 1)
- Test: `viewer-backend/tests/test_app_auth.py`

**Interfaces:**
- Consumes: `token_store.get_or_create_user/get_user/set_brief_data_folder_id` (Task 2), `google_oauth.get_authorization_url/exchange_code_for_tokens/GoogleAuthRequired` (Task 3).
- Produces: `/auth/google/callback` route; `current_user()` now also carries whether Google is linked; a new `/api/drive-folder` endpoint (GET returns `{folder_id}`, POST body `{folder_id}` saves it) alongside the existing `/api/asana-pat` pattern.

- [ ] **Step 1: Copy `app.py` forward as the starting point**

```bash
cp "/c/Users/AaronHubbart/Documents/Camunda-Software/utils/daily-brief/viewer/webapp/app.py" \
   "/c/Users/AaronHubbart/Documents/Camunda-Software/utils/daily-brief-v2/viewer-backend/app.py"
cp -r "/c/Users/AaronHubbart/Documents/Camunda-Software/utils/daily-brief/viewer/webapp/templates" \
      "/c/Users/AaronHubbart/Documents/Camunda-Software/utils/daily-brief-v2/viewer-backend/templates"
```

This plan's remaining steps in Tasks 7-9 edit this copied `app.py` in place. Templates are carried over unmodified per the design (front-end behavior unchanged) and aren't touched by this plan.

- [ ] **Step 2: Write a failing test for the auth_callback → Google consent redirect**

```python
# viewer-backend/tests/test_app_auth.py
import pytest


@pytest.fixture
def client(monkeypatch, token_db_path, encryption_key):
    monkeypatch.setenv('FLASK_SECRET_KEY', 'test-secret')
    monkeypatch.setenv('AZURE_TENANT_ID', 'tenant-1')
    monkeypatch.setenv('AZURE_CLIENT_ID', 'client-1')
    monkeypatch.setenv('AZURE_CLIENT_SECRET', 'secret-1')
    monkeypatch.setenv('AZURE_REDIRECT_URI', 'https://example.com/daily-brief/auth/callback')
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'google-client-1')
    monkeypatch.setenv('GOOGLE_CLIENT_SECRET', 'google-secret-1')
    monkeypatch.setenv('GOOGLE_REDIRECT_URI', 'https://example.com/daily-brief/auth/google/callback')

    import app as app_module
    app_module.app.config['TESTING'] = True
    with app_module.app.test_client() as c:
        yield c


def _sign_in(client, monkeypatch):
    """Simulates a completed Azure AD sign-in by writing the session directly
    -- exercising the real /login -> Azure AD -> /auth/callback round trip
    would require mocking MSAL's network calls, which auth_callback's own
    existing behavior already covers; this test is only about what happens
    to a signed-in user who has not yet linked Google."""
    with client.session_transaction() as sess:
        sess['user'] = {'email': 'aaron@camunda.com', 'name': 'Aaron', 'oid': 'oid-1', 'slug': 'aaron', 'id': 'oid-1'}


def test_index_redirects_to_google_consent_when_not_linked(client, monkeypatch):
    _sign_in(client, monkeypatch)
    resp = client.get('/')
    assert resp.status_code == 302
    assert '/auth/google/login' in resp.headers['Location']


def test_google_login_redirects_to_google_authorization_url(client, monkeypatch):
    _sign_in(client, monkeypatch)
    resp = client.get('/auth/google/login')
    assert resp.status_code == 302
    assert resp.headers['Location'].startswith('https://accounts.google.com/o/oauth2/v2/auth?')


def test_google_callback_stores_tokens_and_redirects_to_onboarding(client, monkeypatch, mocker):
    _sign_in(client, monkeypatch)
    with client.session_transaction() as sess:
        sess['google_oauth_state'] = 'state-abc'

    mocker.patch('google_oauth.exchange_code_for_tokens', return_value={
        'access_token': 'a', 'refresh_token': 'r', 'expiry': '2026-07-21T13:00:00+00:00',
    })

    resp = client.get('/auth/google/callback?code=auth-code&state=state-abc')
    assert resp.status_code == 302

    import token_store
    with client.application.app_context():
        tokens = token_store.get_google_tokens('oid-1')
    assert tokens['access_token'] == 'a'
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd viewer-backend && python -m pytest tests/test_app_auth.py -v`
Expected: FAIL — `index` doesn't redirect to Google consent yet, `/auth/google/login` and `/auth/google/callback` don't exist (404).

- [ ] **Step 4: Edit `app.py` — replace the `import db` line and add the Google consent flow**

Replace:
```python
import db
```
with:
```python
import token_store as db_tokens
import google_oauth
```

Replace the `login_required` decorator's user-identity handling — after the existing `if not user:` block that redirects to `/login`, insert a Google-link check (a user can be signed in to Entra but not yet have linked Google):

```python
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            session['post_login_redirect'] = request.script_root + request.path
            return redirect(url_for('login'))
        request.brief_user = user
        if request.endpoint not in ('google_login', 'google_callback', 'logout') and not db_tokens.get_google_tokens(user['id']):
            session['post_google_link_redirect'] = request.script_root + request.path
            return redirect(url_for('google_login'))
        return view(*args, **kwargs)
    return wrapped
```

Add two new routes, right after the existing `/auth/callback` route:

```python
@app.route('/auth/google/login')
@login_required
def google_login():
    state = secrets.token_urlsafe(24)
    session['google_oauth_state'] = state
    return redirect(google_oauth.get_authorization_url(state))


@app.route('/auth/google/callback')
@login_required
def google_callback():
    expected_state = session.pop('google_oauth_state', None)
    if not expected_state or request.args.get('state') != expected_state:
        abort(400, 'Invalid or missing OAuth state for the Google consent step.')
    if 'error' in request.args:
        abort(401, request.args.get('error_description', 'Google sign-in failed.'))
    code = request.args.get('code')
    if not code:
        abort(400, 'No authorization code returned from Google.')

    tokens = google_oauth.exchange_code_for_tokens(code)
    db_tokens.set_google_tokens(
        request.brief_user['id'], tokens['access_token'], tokens['refresh_token'], tokens['expiry'],
    )
    dest = session.pop('post_google_link_redirect', None) or url_for('index')
    return redirect(dest)
```

Note `login_required`'s new check references `request.endpoint`, which requires `google_login` and `google_callback` be excluded from the check — both are already decorated with `@login_required` themselves above, so the exclusion only prevents an infinite redirect loop between `index` → `google_login` → (already linked check passes) → back to `index`.

- [ ] **Step 5: Update `get_or_create_user` call site in `auth_callback` to use `token_store`**

Replace:
```python
    user_row = db.get_or_create_user(email, slug)
    session['user'] = {
        'email': email,
        'name': claims.get('name', email),
        'oid': claims.get('oid'),
        'slug': slug,
        'id': user_row['id'],
    }
```
with:
```python
    user_row = db_tokens.get_or_create_user(claims.get('oid'), email)
    session['user'] = {
        'email': email,
        'name': claims.get('name', email),
        'oid': claims.get('oid'),
        'slug': slug,
        # Entra's own object id is now the primary key everywhere (token_store,
        # Drive folder linkage) -- simpler than db.py's separate auto-increment
        # id, since Entra already hands us a stable, globally-unique identifier.
        'id': claims.get('oid'),
    }
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd viewer-backend && python -m pytest tests/test_app_auth.py -v`
Expected: PASS (3 tests)

- [ ] **Step 7: Add the `/api/drive-folder` endpoint, mirroring `/api/asana-pat`'s shape**

Add near the existing `/api/asana-pat` routes:

```python
@app.route('/api/drive-folder')
@login_required
def api_drive_folder_status():
    user = db_tokens.get_user(request.brief_user['id'])
    return jsonify({'folder_id': user['brief_data_folder_id'] if user else None})


@app.route('/api/drive-folder', methods=['POST'])
@login_required
def api_drive_folder_save():
    body = request.get_json(silent=True) or {}
    folder_id = (body.get('folder_id') or '').strip()
    if not folder_id:
        abort(400, 'folder_id is required')
    db_tokens.set_brief_data_folder_id(request.brief_user['id'], folder_id)
    return jsonify({'status': 'ok'})
```

- [ ] **Step 8: Write and run a test for `/api/drive-folder`**

```python
# append to viewer-backend/tests/test_app_auth.py
def test_drive_folder_save_and_status_round_trip(client, monkeypatch, mocker):
    _sign_in(client, monkeypatch)
    mocker.patch('token_store.get_google_tokens', return_value={'access_token': 'a', 'refresh_token': 'r', 'expiry': '2099-01-01T00:00:00+00:00'})

    import token_store
    with client.application.app_context():
        token_store.get_or_create_user('oid-1', 'aaron@camunda.com')

    resp = client.post('/api/drive-folder', json={'folder_id': 'folder-xyz'})
    assert resp.status_code == 200

    resp = client.get('/api/drive-folder')
    assert resp.get_json() == {'folder_id': 'folder-xyz'}
```

Run: `cd viewer-backend && python -m pytest tests/test_app_auth.py -v`
Expected: PASS (4 tests)

- [ ] **Step 9: Commit**

```bash
git add viewer-backend/app.py viewer-backend/templates viewer-backend/tests/test_app_auth.py
git commit -m "Wire Google OAuth consent flow and Drive-folder linkage into app.py"
```

---

### Task 8: `app.py` — swap brief/asana/admin routes to the Drive-backed data layer

**Files:**
- Modify: `viewer-backend/app.py`
- Test: `viewer-backend/tests/test_app_briefs.py`

**Interfaces:**
- Consumes: `drive_store.list_active_briefs/get_brief_day/get_items_for_day/get_account_projects/set_item_checked/set_item_due_date` (Tasks 5-6), `google_oauth.get_valid_access_token` (Task 3), `token_store.get_asana_pat/set_asana_pat/clear_asana_pat/count_users_with_asana_pat/mark_onboarding_complete/list_users` (Task 2).

- [ ] **Step 1: Write a failing test for `serve_brief` reading from Drive instead of Postgres**

```python
# viewer-backend/tests/test_app_briefs.py
import pytest


@pytest.fixture
def client(monkeypatch, token_db_path, encryption_key):
    monkeypatch.setenv('FLASK_SECRET_KEY', 'test-secret')
    monkeypatch.setenv('AZURE_TENANT_ID', 'tenant-1')
    monkeypatch.setenv('AZURE_CLIENT_ID', 'client-1')
    monkeypatch.setenv('AZURE_CLIENT_SECRET', 'secret-1')
    monkeypatch.setenv('AZURE_REDIRECT_URI', 'https://example.com/daily-brief/auth/callback')
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'google-client-1')
    monkeypatch.setenv('GOOGLE_CLIENT_SECRET', 'google-secret-1')
    monkeypatch.setenv('GOOGLE_REDIRECT_URI', 'https://example.com/daily-brief/auth/google/callback')

    import app as app_module
    app_module.app.config['TESTING'] = True
    with app_module.app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user'] = {'email': 'aaron@camunda.com', 'name': 'Aaron', 'oid': 'oid-1', 'slug': 'aaron', 'id': 'oid-1'}
        yield c


def _link_google_and_folder(client):
    import token_store
    with client.application.app_context():
        token_store.get_or_create_user('oid-1', 'aaron@camunda.com')
        token_store.set_google_tokens('oid-1', 'access-tok', 'refresh-tok', '2099-01-01T00:00:00+00:00')
        token_store.set_brief_data_folder_id('oid-1', 'folder-xyz')


def test_api_briefs_lists_dates_from_drive_store(client, mocker):
    _link_google_and_folder(client)
    mocker.patch('drive_store.list_active_briefs', return_value=[
        {'brief_date': '2026-07-21', 'brief_type': 'morning', 'last_updated_at': '2026-07-21T12:00:00Z'},
    ])

    resp = client.get('/api/briefs')
    assert resp.get_json() == [{'name': '2026-07-21', 'label': '2026-07-21'}]


def test_serve_brief_renders_from_drive_items(client, mocker):
    _link_google_and_folder(client)
    mocker.patch('drive_store.get_brief_day', return_value={
        'brief_date': '2026-07-21', 'brief_type': 'morning', 'folder_id': 'date-folder',
    })
    mocker.patch('drive_store.get_items_for_day', return_value=[
        {'section': 'yesterday-meetings', 'item_key': 'ym-0900-bofa', 'item_type': 'checkable',
         'title': 'BofA Sync', 'subtitle': None, 'badge': None, 'links': [], 'content': {},
         'checked': True, 'display_order': 0, 'generated_at': '2026-07-21T08:00:00Z'},
    ])
    mocker.patch('token_store.get_asana_pat', return_value=None)

    resp = client.get('/brief/2026-07-21')
    assert resp.status_code == 200
    assert b'BofA Sync' in resp.data


def test_set_item_checked_calls_drive_store(client, mocker):
    _link_google_and_folder(client)
    mocker.patch('drive_store.get_brief_day', return_value={'brief_date': '2026-07-21', 'folder_id': 'date-folder'})
    write_spy = mocker.patch('drive_store.set_item_checked')
    mocker.patch('token_store.get_asana_pat', return_value=None)

    resp = client.patch('/api/items/yesterday-meetings/ym-0900-bofa/checked?date=2026-07-21', json={'checked': True})
    assert resp.status_code == 200
    write_spy.assert_called_once_with('access-tok', 'folder-xyz', '2026-07-21', 'yesterday-meetings', 'ym-0900-bofa', True)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd viewer-backend && python -m pytest tests/test_app_briefs.py -v`
Expected: FAIL — routes still call `db.*`, which no longer exists as an importable name (renamed to `db_tokens` in Task 7, and it never had these brief-reading functions in the first place).

- [ ] **Step 3: Edit `app.py` — add a helper for the resolved access token + folder id, then swap each route**

Add near the top of the route section:

```python
def _drive_context():
    """Every brief-reading/writing route needs both the caller's valid Drive
    access token and their linked brief_data_folder_id. Centralizing the
    lookup here means a route body reads exactly like its db.py-backed
    predecessor, just swapping db.X(user_id, ...) for
    drive_store.X(access_token, folder_id, ...)."""
    user = db_tokens.get_user(request.brief_user['id'])
    if not user or not user['brief_data_folder_id']:
        abort(400, 'No Google Drive folder linked yet — visit the Account panel to link one.')
    access_token = google_oauth.get_valid_access_token(request.brief_user['id'])
    return access_token, user['brief_data_folder_id']
```

Replace `api_briefs`:
```python
@app.route('/api/briefs')
@login_required
def api_briefs():
    access_token, folder_id = _drive_context()
    days = drive_store.list_active_briefs(access_token, folder_id)
    return jsonify([{'name': d['brief_date'], 'label': d['brief_date']} for d in days])
```

Replace `serve_brief`'s data-fetching lines (keep everything from `items_by_section = {}` onward unchanged — only the two `db.*` lines at the top change):
```python
@app.route('/brief/<date_str>')
@login_required
def serve_brief(date_str):
    if not DATE_RE.match(date_str):
        abort(400)
    access_token, folder_id = _drive_context()
    brief_day = drive_store.get_brief_day(access_token, folder_id, date_str)
    if not brief_day:
        abort(404)

    items = drive_store.get_items_for_day(access_token, folder_id, date_str)
    # ... unchanged from here: items_by_section loop, action items grouping, render_template call.
    # One further change further down: replace
    #   asana_pat = db.get_asana_pat(request.brief_user['id'])
    # with
    #   asana_pat = db_tokens.get_asana_pat(request.brief_user['id'])
    # and replace
    #   account_projects = db.get_account_projects(request.brief_user['id'])
    # with
    #   account_projects = drive_store.get_account_projects(access_token, folder_id)
    # brief_day['brief_date'] is now a plain 'YYYY-MM-DD' string (Drive JSON,
    # not a Postgres date object), so the existing
    #   brief_day['brief_date'].strftime('%A, %B %-d')
    # call must become
    #   date.fromisoformat(brief_day['brief_date']).strftime('%A, %B %-d')
```

Replace `set_item_checked`:
```python
@app.route('/api/items/<section>/<item_key>/checked', methods=['PATCH'])
@login_required
def set_item_checked(section, item_key):
    date_str = request.args.get('date', '')
    if not DATE_RE.match(date_str):
        abort(400, 'date query param (YYYY-MM-DD) is required')
    body = request.get_json(silent=True) or {}
    if 'checked' not in body:
        abort(400, 'checked (bool) is required')
    checked = bool(body['checked'])

    access_token, folder_id = _drive_context()
    brief_day = drive_store.get_brief_day(access_token, folder_id, date_str)
    if not brief_day:
        abort(404)
    drive_store.set_item_checked(access_token, folder_id, date_str, section, item_key, checked)

    pat = db_tokens.get_asana_pat(request.brief_user['id'])
    attempted, ok = _sync_asana_completed(pat, item_key, checked)
    result = {'status': 'ok'}
    if attempted:
        result['asana_synced'] = ok
    return jsonify(result)
```

Note: unlike the Postgres version, this drops the "no row found → fall back to writing straight to Asana" branch. In the Drive model there's no live-pulled-item-with-no-backing-row case for *state* writes — every checkable item, live-pulled or skill-sourced, gets a `section:item_key` entry in the same per-date state file, so `drive_store.set_item_checked` always succeeds; only the Asana mirror-write remains best-effort.

Replace `set_item_due_date` the same way (swap `db.get_brief_day`/`db.set_item_due_date` for `drive_store.get_brief_day`/`drive_store.set_item_due_date` via `_drive_context()`, keep the Asana sync call as-is).

Replace the Asana-PAT and onboarding routes' `db.*` calls with `db_tokens.*` (same function names, same signatures — `db.get_asana_pat` → `db_tokens.get_asana_pat`, `db.set_asana_pat` → `db_tokens.set_asana_pat`, `db.clear_asana_pat` → `db_tokens.clear_asana_pat`, `db.mark_onboarding_complete` → `db_tokens.mark_onboarding_complete`, `db.get_user_by_id` → `db_tokens.get_user`).

Replace `admin_list_users`:
```python
@app.route('/api/admin/users')
@login_required
@admin_required
def admin_list_users():
    # Drive-era admin panel shows registered users only -- no brief_count/
    # last_active_at columns, since computing those now means listing every
    # user's Drive folder on every admin page load rather than one indexed
    # Postgres query. Deliberately dropped rather than reimplemented at that
    # cost; revisit if the admin panel's user list needs it back.
    return jsonify(db_tokens.list_users())
```

Delete `admin_rotate_user_token` entirely — there is no more per-user API token to rotate, since the skill never authenticates to this webapp at all (Task 9 removes the routes that used it). Update `admin_config_status` to drop `db.count_users_with_asana_pat()` → `db_tokens.count_users_with_asana_pat()` and remove any remaining Postgres-specific fields.

- [ ] **Step 4: Add `import drive_store` alongside the existing `import google_oauth` / `import token_store as db_tokens`**

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd viewer-backend && python -m pytest tests/test_app_briefs.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Run the full test suite**

Run: `cd viewer-backend && python -m pytest -v`
Expected: PASS (all tests across all modules so far)

- [ ] **Step 7: Commit**

```bash
git add viewer-backend/app.py viewer-backend/tests/test_app_briefs.py
git commit -m "Swap serve_brief, checkbox/due-date, asana-pat, and admin routes to the Drive-backed data layer"
```

---

### Task 9: `app.py` — remove skill-facing routes, update health checks

**Files:**
- Modify: `viewer-backend/app.py`

**Interfaces:**
- Removes: `ensure_upload_context`, `/api/token`, `/api/token/rotate`, `/api/config/account-projects`, `/api/items/upsert`, `/api/items/batch-upsert`, `ASANA_ACTION_ITEM_PREFIX`-adjacent code stays (still used for live-pull grouping), `MCP_CONNECTOR_URL` config value.

- [ ] **Step 1: Delete the skill-facing routes and their shared helper**

Delete `ensure_upload_context`, `@app.route('/api/token')`/`api_token`, `@app.route('/api/token/rotate', ...)`/`api_token_rotate`, `@app.route('/api/config/account-projects', ...)`/`api_config_account_projects`, `@app.route('/api/items/upsert', ...)`/`api_items_upsert`, `@app.route('/api/items/batch-upsert', ...)`/`api_items_batch_upsert` — the skill never calls this webapp at all in v2 (writes go straight to Drive via its own connector, per `docs/superpowers/specs/2026-07-21-daily-brief-v2-design.md`).

Delete the `MCP_CONNECTOR_URL` env var and its use in `api_client_config` (the MCP server no longer exists):
```python
@app.route('/api/client-config')
@login_required
def api_client_config():
    """Values the setup walkthrough and Account panel need. request.host_url
    isn't reliable to derive client-side since this app is deployed at a
    sub-path (see ForcePrefixMiddleware's docstring)."""
    return jsonify({
        'api_base_url': request.host_url.rstrip('/') + request.script_root,
    })
```

- [ ] **Step 2: Update `/readyz` to check the token store instead of Postgres**

Replace:
```python
@app.route('/readyz')
def readyz():
    try:
        with db.cursor() as cur:
            cur.execute('SELECT 1')
    except Exception as e:
        return f'db unavailable: {e}', 503
    return 'ok', 200
```
with:
```python
@app.route('/readyz')
def readyz():
    try:
        with token_store.cursor() as cur:
            cur.execute('SELECT 1')
    except Exception as e:
        return f'token store unavailable: {e}', 503
    return 'ok', 200
```
(Note: `token_store` here is the actual module name; the `db_tokens` alias used elsewhere in `app.py` is just this task's import-site convenience — either works since they're the same module, but use `token_store.cursor` here to match this route's existing direct-module-access style rather than introducing a second alias.)

Also delete `app.teardown_appcontext(db.close_conn)` and replace with `app.teardown_appcontext(token_store.close_conn)` (add `import token_store` alongside the existing `import token_store as db_tokens`, or simply reuse `db_tokens.close_conn` — either is correct since it's the same module object; use `db_tokens.close_conn` to avoid a second import line).

- [ ] **Step 3: Write a smoke test confirming the removed routes are gone and `/readyz` still works**

```python
# viewer-backend/tests/test_app_routes_removed.py
import pytest


@pytest.fixture
def client(monkeypatch, token_db_path, encryption_key):
    monkeypatch.setenv('FLASK_SECRET_KEY', 'test-secret')
    monkeypatch.setenv('AZURE_TENANT_ID', 'tenant-1')
    monkeypatch.setenv('AZURE_CLIENT_ID', 'client-1')
    monkeypatch.setenv('AZURE_CLIENT_SECRET', 'secret-1')
    monkeypatch.setenv('AZURE_REDIRECT_URI', 'https://example.com/daily-brief/auth/callback')
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'google-client-1')
    monkeypatch.setenv('GOOGLE_CLIENT_SECRET', 'google-secret-1')
    monkeypatch.setenv('GOOGLE_REDIRECT_URI', 'https://example.com/daily-brief/auth/google/callback')
    import app as app_module
    app_module.app.config['TESTING'] = True
    with app_module.app.test_client() as c:
        yield c


@pytest.mark.parametrize('path,method', [
    ('/api/token', 'GET'),
    ('/api/token/rotate', 'POST'),
    ('/api/config/account-projects', 'POST'),
    ('/api/items/upsert', 'POST'),
    ('/api/items/batch-upsert', 'POST'),
])
def test_skill_facing_routes_are_gone(client, path, method):
    resp = client.open(path, method=method)
    assert resp.status_code == 404


def test_readyz_checks_token_store(client):
    resp = client.get('/readyz')
    assert resp.status_code == 200
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd viewer-backend && python -m pytest tests/test_app_routes_removed.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Run the full test suite one more time**

Run: `cd viewer-backend && python -m pytest -v`
Expected: PASS, all tests

- [ ] **Step 6: Commit**

```bash
git add viewer-backend/app.py viewer-backend/tests/test_app_routes_removed.py
git commit -m "Remove skill-facing routes (skill writes directly to Drive now); point readyz at token_store"
```

---

### Task 10: Deployment config — requirements, Dockerfile, k8s manifests

**Files:**
- Modify: `viewer-backend/requirements.txt` (already has the right deps from Task 1 — verify, no change expected)
- Create: `viewer-backend/Dockerfile` (adapted from `viewer/webapp/Dockerfile` in `daily-brief`)
- Create: `viewer-backend/k8s/deployment.yaml`
- Create: `viewer-backend/k8s/service.yaml` (copy unchanged from `daily-brief`'s `viewer/webapp/k8s/service.yaml` — no Postgres/MCP dependency in a Service definition)
- Create: `viewer-backend/k8s/pvc.yaml`
- Create: `viewer-backend/k8s/secret.template.yaml`

**Interfaces:** None (deployment config, not application code) — this task has no automated test; verification is a manual `kubectl apply --dry-run=client` check.

- [ ] **Step 1: Create `k8s/pvc.yaml` for the SQLite token file**

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: daily-brief-token-store
  namespace: daily-brief
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
```

- [ ] **Step 2: Create `k8s/secret.template.yaml`**

```yaml
# Copy to secret.yaml, fill in real values, and `kubectl apply -f secret.yaml`
# -- never commit the filled-in version. See DEPLOYMENT.md for how to
# generate TOKEN_ENCRYPTION_KEY and register the Google Cloud OAuth client.
apiVersion: v1
kind: Secret
metadata:
  name: daily-brief-secrets
  namespace: daily-brief
type: Opaque
stringData:
  FLASK_SECRET_KEY: "REPLACE_ME"
  AZURE_CLIENT_ID: "REPLACE_ME"
  AZURE_CLIENT_SECRET: "REPLACE_ME"
  AZURE_TENANT_ID: "REPLACE_ME"
  GOOGLE_CLIENT_ID: "REPLACE_ME"
  GOOGLE_CLIENT_SECRET: "REPLACE_ME"
  TOKEN_ENCRYPTION_KEY: "REPLACE_ME"
```

- [ ] **Step 3: Create `k8s/deployment.yaml`, adapted from `daily-brief`'s version**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: daily-brief-viewer
  namespace: daily-brief
  labels:
    app: daily-brief-viewer
spec:
  replicas: 1
  selector:
    matchLabels:
      app: daily-brief-viewer
  template:
    metadata:
      labels:
        app: daily-brief-viewer
    spec:
      containers:
        - name: daily-brief-viewer
          image: gcr.io/tam-aaron-hubbart/daily-brief-viewer-v2:latest
          ports:
            - containerPort: 8000
          env:
            - name: FLASK_SECRET_KEY
              valueFrom:
                secretKeyRef: {name: daily-brief-secrets, key: FLASK_SECRET_KEY}
            - name: AZURE_CLIENT_ID
              valueFrom:
                secretKeyRef: {name: daily-brief-secrets, key: AZURE_CLIENT_ID}
            - name: AZURE_CLIENT_SECRET
              valueFrom:
                secretKeyRef: {name: daily-brief-secrets, key: AZURE_CLIENT_SECRET}
            - name: AZURE_TENANT_ID
              valueFrom:
                secretKeyRef: {name: daily-brief-secrets, key: AZURE_TENANT_ID}
            - name: AZURE_REDIRECT_URI
              value: "https://dashboard.es-sandbox.com/daily-brief-v2/auth/callback"
            - name: GOOGLE_CLIENT_ID
              valueFrom:
                secretKeyRef: {name: daily-brief-secrets, key: GOOGLE_CLIENT_ID}
            - name: GOOGLE_CLIENT_SECRET
              valueFrom:
                secretKeyRef: {name: daily-brief-secrets, key: GOOGLE_CLIENT_SECRET}
            - name: GOOGLE_REDIRECT_URI
              value: "https://dashboard.es-sandbox.com/daily-brief-v2/auth/google/callback"
            - name: TOKEN_ENCRYPTION_KEY
              valueFrom:
                secretKeyRef: {name: daily-brief-secrets, key: TOKEN_ENCRYPTION_KEY}
            - name: TOKEN_DB_PATH
              value: "/data/tokens.db"
            - name: ADMIN_EMAILS
              value: ""
          volumeMounts:
            - name: token-store
              mountPath: /data
          resources:
            requests: {cpu: 50m, memory: 64Mi}
            limits: {cpu: 200m, memory: 128Mi}
          readinessProbe:
            httpGet: {path: /readyz, port: 8000}
            initialDelaySeconds: 5
            periodSeconds: 10
          livenessProbe:
            httpGet: {path: /healthz, port: 8000}
            initialDelaySeconds: 15
            periodSeconds: 30
      volumes:
        - name: token-store
          persistentVolumeClaim:
            claimName: daily-brief-token-store
```

Note this deploys to a *separate* image tag (`daily-brief-viewer-v2`) and a *separate* ingress path (`/daily-brief-v2/`, matching the rollout plan's "separate test path" step) rather than overwriting the existing `daily-brief-viewer` deployment — see the design spec's Rollout section. `k8s/ingress.yaml` for this test path is intentionally deferred to the rollout task (outside this plan's scope — this plan produces working, independently-testable backend code; wiring up the public test ingress is an infrastructure step to do once this code is deployed and manually verified via port-forward).

- [ ] **Step 4: Copy `k8s/service.yaml` unchanged**

```bash
cp "/c/Users/AaronHubbart/Documents/Camunda-Software/utils/daily-brief/viewer/webapp/k8s/service.yaml" \
   "/c/Users/AaronHubbart/Documents/Camunda-Software/utils/daily-brief-v2/viewer-backend/k8s/service.yaml"
```
Update `metadata.name`/`spec.selector` inside it from `daily-brief-viewer` only if the copied file's selector doesn't already match `k8s/deployment.yaml`'s `app: daily-brief-viewer` label above — check the two files match after copying; no change needed if they already agree.

- [ ] **Step 5: Verify manifests are well-formed**

Run: `kubectl apply --dry-run=client -f viewer-backend/k8s/pvc.yaml -f viewer-backend/k8s/deployment.yaml -f viewer-backend/k8s/service.yaml`
Expected: `... created (dry run)` for all three, no YAML/schema errors. (`secret.template.yaml` is intentionally not applied here — it has placeholder values and is filled in manually per `DEPLOYMENT.md`, not dry-run-validated as part of this task.)

- [ ] **Step 6: Create `Dockerfile`, adapted from `daily-brief`'s version**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /data
EXPOSE 8000
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:app"]
```

(Reuse `gunicorn.conf.py` from `daily-brief`'s `viewer/webapp/` unchanged — copy it forward in this step: `cp "C:\...\daily-brief\viewer\webapp\gunicorn.conf.py" "C:\...\daily-brief-v2\viewer-backend\gunicorn.conf.py"`.)

- [ ] **Step 7: Commit**

```bash
git add viewer-backend/Dockerfile viewer-backend/gunicorn.conf.py viewer-backend/k8s/
git commit -m "Add Dockerfile and k8s manifests for the Drive-backed viewer-backend"
```

---

### Task 11: End-to-end manual verification

**Files:** None modified — this task is a verification checklist, run locally against real (not mocked) Google/Asana/Drive accounts before considering this plan done.

- [ ] **Step 1: Run the full automated test suite one final time**

Run: `cd viewer-backend && python -m pytest -v`
Expected: PASS, all tests (should be roughly 30+ tests across all modules by this point)

- [ ] **Step 2: Manually create a test Drive folder matching the layout**

Create a folder in your own Drive, and inside it: a `briefs/2026-07-21/` subfolder with a hand-written `manifest.json`, `meetings.json`, `today.json`, `action-items.json`, `fyi.json`, `manager-update.json`, an `accounts/` subfolder with one account JSON, an `updates/` subfolder with one account JSON, and a top-level `config/account-config.json` — shapes per `docs/superpowers/specs/2026-07-21-daily-brief-v2-design.md` and this plan's `references/item-sync.md`-derived item fields.

- [ ] **Step 3: Set required local env vars and run the app locally**

```bash
export FLASK_SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
export TOKEN_ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
export TOKEN_DB_PATH=/tmp/tokens.db
export AZURE_TENANT_ID=... AZURE_CLIENT_ID=... AZURE_CLIENT_SECRET=... AZURE_REDIRECT_URI=http://localhost:8000/auth/callback
export GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback
cd viewer-backend && python app.py
```

- [ ] **Step 4: Walk through the real flow in a browser**

Sign in with Entra ID → get redirected to Google consent (grant the `drive` scope) → land on the viewer → confirm the test brief date appears in the dropdown → open it and confirm every section renders with the hand-written test content → toggle a checkbox and reload the page to confirm it persisted → edit an Action Item's due date and reload to confirm it persisted → confirm dark/light mode, timeline strip, and `claude://` deep-links still render exactly as they do on the current production viewer.

- [ ] **Step 5: Verify the Asana live-pull still works if a PAT is configured**

Save an Asana PAT via the Account panel, reload a brief with `account-config.json` pointing at a real Asana project with open tasks, and confirm Overdue/Due Next 7 Days/No Due Date subsections populate.

- [ ] **Step 6: Note any gaps found against the design spec's "Open items" section**

If the manual pass surfaces a mismatch with `docs/superpowers/specs/2026-07-21-daily-brief-v2-design.md`'s remaining open item (whether `references/status-updates.md`'s per-account cache file moves into `/briefs/{date}/` or stays separately configured), record the decision made here as a follow-up note for the skill-rewrite plan — that file lives in the skill repo side of this project, not `viewer-backend/`, so it's out of this plan's file scope.

- [ ] **Step 7: Final commit**

```bash
git add -A
git commit -m "Complete manual end-to-end verification of the Drive-backed viewer-backend"
```
