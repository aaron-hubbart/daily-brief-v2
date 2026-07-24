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
        {'section': 'yesterday-meetings', 'item_key': 'ym-0900-acmefin', 'item_type': 'checkable',
         'title': 'AcmeFin Sync', 'subtitle': None, 'badge': None, 'links': [], 'content': {},
         'checked': True, 'display_order': 0, 'generated_at': '2026-07-21T08:00:00Z'},
    ])
    mocker.patch('token_store.get_asana_pat', return_value=None)

    resp = client.get('/brief/2026-07-21')
    assert resp.status_code == 200
    assert b'AcmeFin Sync' in resp.data


def test_set_item_checked_calls_drive_store(client, mocker):
    _link_google_and_folder(client)
    mocker.patch('drive_store.get_brief_day', return_value={'brief_date': '2026-07-21', 'folder_id': 'date-folder'})
    write_spy = mocker.patch('drive_store.set_item_checked')
    mocker.patch('token_store.get_asana_pat', return_value=None)

    resp = client.patch('/api/items/yesterday-meetings/ym-0900-acmefin/checked?date=2026-07-21', json={'checked': True})
    assert resp.status_code == 200
    write_spy.assert_called_once_with('access-tok', 'folder-xyz', '2026-07-21', 'yesterday-meetings', 'ym-0900-acmefin', True)


def test_api_briefs_surfaces_drive_error_reason_instead_of_opaque_500(client, mocker):
    _link_google_and_folder(client)
    import drive_store
    mocker.patch('drive_store.list_active_briefs', side_effect=drive_store.DriveApiError(
        403,
        'insufficientFilePermissions: The user does not have sufficient permissions for this file.',
        '{"error": {"code": 403}}',
    ))

    resp = client.get('/api/briefs')
    assert resp.status_code == 502
    payload = resp.get_json()
    assert payload['drive_status'] == 403
    assert 'insufficientFilePermissions' in payload['error'] or 'access' in payload['error'].lower()
