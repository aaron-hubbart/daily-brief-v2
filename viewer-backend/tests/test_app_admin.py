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
    monkeypatch.setenv('ADMIN_EMAILS', 'admin@camunda.com')

    import app as app_module
    app_module.app.config['TESTING'] = True
    with app_module.app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user'] = {
                'email': 'admin@camunda.com', 'name': 'Admin', 'oid': 'admin-oid',
                'slug': 'admin', 'id': 'admin-oid',
            }
        yield c


def _link_google(client, oid='admin-oid', email='admin@camunda.com'):
    import token_store
    with client.application.app_context():
        token_store.get_or_create_user(oid, email)
        token_store.set_google_tokens(oid, 'access-tok', 'refresh-tok', '2099-01-01T00:00:00+00:00')


def test_admin_users_lists_drive_folder_link_state(client):
    """The admin panel's per-user 'Rotate token' action was removed since
    there's no more per-user API token in the Drive-only v2 flow -- viewing
    whether (and where) a user has linked their Drive folder is what
    replaces it for troubleshooting a stuck user."""
    _link_google(client)
    import token_store
    with client.application.app_context():
        token_store.get_or_create_user('user-oid', 'user@camunda.com')
        token_store.set_brief_data_folder_id('user-oid', 'drive-folder-xyz')

    resp = client.get('/api/admin/users')
    assert resp.status_code == 200
    users = {u['email']: u for u in resp.get_json()}
    assert users['user@camunda.com']['brief_data_folder_id'] == 'drive-folder-xyz'
    assert users['admin@camunda.com']['brief_data_folder_id'] is None


def test_admin_rotate_token_route_is_gone(client):
    _link_google(client)
    resp = client.post('/api/admin/users/some-user-oid/rotate-token')
    assert resp.status_code == 404
