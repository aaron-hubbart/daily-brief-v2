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
