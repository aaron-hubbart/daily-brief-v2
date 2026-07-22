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
