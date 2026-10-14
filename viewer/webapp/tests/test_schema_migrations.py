"""Tests for db's migration-tracking helpers (see
db/migrations/011_add_schema_migrations.sql and DEPLOYMENT.md's "Schema
migrations" section for why this exists). Only the pure diff and the real
db/migrations/ directory listing are exercised here — get_pending_migrations
itself needs a live Postgres connection and isn't covered by this suite."""
from db import _migration_files_on_disk, _pending_from


def test_pending_from_returns_files_missing_from_applied():
    on_disk = ['001_a.sql', '002_b.sql', '003_c.sql']
    applied = {'001_a.sql', '003_c.sql'}
    assert _pending_from(on_disk, applied) == ['002_b.sql']


def test_pending_from_empty_when_everything_applied():
    on_disk = ['001_a.sql', '002_b.sql']
    applied = {'001_a.sql', '002_b.sql'}
    assert _pending_from(on_disk, applied) == []


def test_pending_from_preserves_disk_order():
    on_disk = ['001_a.sql', '002_b.sql', '003_c.sql']
    assert _pending_from(on_disk, set()) == on_disk


def test_migration_files_on_disk_includes_the_tracking_migration_itself():
    files = _migration_files_on_disk()
    assert '011_add_schema_migrations.sql' in files
    # Sorted lexicographically, which matches numeric order for the
    # zero-padded 3-digit prefixes every migration file uses.
    assert files == sorted(files)
