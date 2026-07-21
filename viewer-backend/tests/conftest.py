import os
import pytest


@pytest.fixture(autouse=True)
def cleanup_db_files(token_db_path):
    """Ensure database connections are closed and WAL files are cleaned up."""
    yield
    # Close any open connections in token_store module
    try:
        import token_store
        token_store.close_conn()
    except Exception:
        pass

    # Clean up WAL and SHM files that SQLite creates
    for suffix in ['', '-wal', '-shm']:
        file_path = token_db_path + suffix
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass
