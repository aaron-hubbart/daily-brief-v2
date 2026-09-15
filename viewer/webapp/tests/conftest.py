"""Ensures the tests/ directory itself is importable as a top-level module
path (not just the package `tests.*`), so sibling test modules can do
`from template_test_utils import make_env` without an app.py import.
Needed because tests/__init__.py makes `tests` a package: pytest's default
import mode then only adds the package's parent (viewer/webapp) to
sys.path, not tests/ itself."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
