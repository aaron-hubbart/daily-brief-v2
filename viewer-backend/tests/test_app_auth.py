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
