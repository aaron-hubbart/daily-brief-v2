"""Tests for db's Asana-PAT-at-rest encryption helpers (_encrypt_asana_pat /
_decrypt_asana_pat) — pure functions, no Postgres connection needed. See
DEPLOYMENT.md's "Asana PAT encryption" section for why this exists."""
import pytest
from cryptography.fernet import Fernet

import db


def test_round_trips_through_encrypt_and_decrypt(monkeypatch):
    monkeypatch.setattr(db, 'ASANA_PAT_ENCRYPTION_KEY', Fernet.generate_key().decode('utf-8'))

    encrypted = db._encrypt_asana_pat('1/1234567890abcdef')

    assert encrypted != '1/1234567890abcdef'
    assert db._decrypt_asana_pat(encrypted) == '1/1234567890abcdef'


def test_decrypt_passes_through_legacy_plaintext_unchanged(monkeypatch):
    """Rows written before encryption existed aren't valid Fernet tokens —
    decrypting them must return the original value rather than raising, so
    existing users' PATs keep working with no backfill migration."""
    monkeypatch.setattr(db, 'ASANA_PAT_ENCRYPTION_KEY', Fernet.generate_key().decode('utf-8'))

    assert db._decrypt_asana_pat('1/legacy-plaintext-pat') == '1/legacy-plaintext-pat'


def test_decrypt_with_wrong_key_is_treated_as_legacy_plaintext(monkeypatch):
    monkeypatch.setattr(db, 'ASANA_PAT_ENCRYPTION_KEY', Fernet.generate_key().decode('utf-8'))
    encrypted = db._encrypt_asana_pat('1/1234567890abcdef')

    monkeypatch.setattr(db, 'ASANA_PAT_ENCRYPTION_KEY', Fernet.generate_key().decode('utf-8'))

    assert db._decrypt_asana_pat(encrypted) == encrypted


def test_encrypt_without_a_configured_key_raises(monkeypatch):
    monkeypatch.setattr(db, 'ASANA_PAT_ENCRYPTION_KEY', None)

    with pytest.raises(RuntimeError, match='ASANA_PAT_ENCRYPTION_KEY'):
        db._encrypt_asana_pat('1/1234567890abcdef')
