"""Tests for db.set_subitem_checked / db.get_subitem_checks (see
db/migrations/013_add_item_subchecks.sql). These are plain read/write
wrappers around a live Postgres connection with no pure logic to split out
(unlike get_pending_migrations's _pending_from) -- same situation
test_schema_migrations.py documents for get_pending_migrations itself:
"needs a live Postgres connection and isn't covered by this suite" by
default. Skipped unless DATABASE_URL points at a real database (a
throwaway one is fine -- rows are created and torn down via db's own
test-user helpers, same ones the admin-panel impersonation feature uses)."""
import os

import pytest
from flask import Flask

import db

pytestmark = pytest.mark.skipif(
    not os.environ.get('DATABASE_URL'),
    reason="needs a live Postgres connection (DATABASE_URL) with migration "
           "013_add_item_subchecks.sql applied -- not covered by the default "
           "suite, same as the rest of db.py's DB-touching functions",
)


@pytest.fixture
def brief_day_id():
    """A throwaway test user + brief_day row, cleaned up afterward.
    db.delete_test_user cascades (brief_days -> items/item_subchecks) via
    the users/brief_days/item_subchecks ON DELETE CASCADE chain, so no
    separate item_subchecks cleanup is needed."""
    app = Flask(__name__)
    with app.app_context():
        user = db.create_test_user('item-subchecks')
        try:
            yield db.upsert_brief_day(user['id'], '2026-11-18', 'morning')
        finally:
            db.delete_test_user(user['id'])


def test_set_subitem_checked_then_get_round_trips(brief_day_id):
    db.set_subitem_checked(brief_day_id, 'customer-updates', 'cust-update-acme', 'sb-fyi:0', True)
    result = db.get_subitem_checks(brief_day_id, 'customer-updates')
    assert result['cust-update-acme']['sb-fyi:0'] is True


def test_set_subitem_checked_is_idempotent_upsert(brief_day_id):
    db.set_subitem_checked(brief_day_id, 'manager-update', 'mgr-update', 'drafted', True)
    db.set_subitem_checked(brief_day_id, 'manager-update', 'mgr-update', 'drafted', False)
    result = db.get_subitem_checks(brief_day_id, 'manager-update')
    assert result['mgr-update']['drafted'] is False
