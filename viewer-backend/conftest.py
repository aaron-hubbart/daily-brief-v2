import os
import tempfile

import pytest


@pytest.fixture
def token_db_path(monkeypatch):
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    os.remove(path)
    monkeypatch.setenv('TOKEN_DB_PATH', path)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def encryption_key(monkeypatch):
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    monkeypatch.setenv('TOKEN_ENCRYPTION_KEY', key)
    return key
