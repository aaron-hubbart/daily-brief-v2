import importlib
import pytest


@pytest.fixture(autouse=True)
def _app_context():
    from flask import Flask
    import token_store
    app = Flask(__name__)
    with app.app_context():
        yield
        token_store.close_conn()


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
