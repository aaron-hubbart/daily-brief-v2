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
    ('/api/client-config', 'GET'),
])
def test_skill_facing_routes_are_gone(client, path, method):
    resp = client.open(path, method=method)
    assert resp.status_code == 404


def test_readyz_checks_token_store(client):
    resp = client.get('/readyz')
    assert resp.status_code == 200
