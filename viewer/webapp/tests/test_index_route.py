"""Regression test for the 'index' endpoint's url_for() resolution.

Final-review finding (Critical #2): the area routes (environments, tasks,
day-plan, account-health) were briefly registered as extra @app.route rules
stacked on the same `index` view function/endpoint. Flask/Werkzeug builds
url_for(endpoint) from the FIRST rule registered for that endpoint — and
since decorators apply bottom-up, the rule closest to the function wins.
With six stacked rules, url_for('index') stopped resolving to '/' (it
resolved to whichever area route happened to be innermost), which broke
the post-login redirect, the Google Drive connect callback's redirect, and
/logout's post_logout_redirect_uri — all three call url_for('index') with
no arguments and depend on it landing on Brief ('/').

This test imports app.py directly (unlike the other tests here, which
render templates standalone to avoid app.py's Flask/Azure env var and
psycopg2 requirements — see template_test_utils.py's module docstring).
The env vars below are dummy values only used to satisfy app.py's
_require_env() checks at import time; no network call or real Postgres
connection happens on import.
"""
import os

os.environ.setdefault('FLASK_SECRET_KEY', 'test-secret-key')
os.environ.setdefault('AZURE_TENANT_ID', 'test-tenant-id')
os.environ.setdefault('AZURE_CLIENT_ID', 'test-client-id')
os.environ.setdefault('AZURE_CLIENT_SECRET', 'test-client-secret')
os.environ.setdefault('AZURE_REDIRECT_URI', 'https://example.test/auth/callback')

import app as webapp  # noqa: E402 (env vars above must be set first)
from flask import url_for  # noqa: E402


def test_url_for_index_resolves_to_root():
    """The specific regression: url_for('index') must build '/', not an
    area path like '/account-health' or a sibling rule like '/index.html'."""
    with webapp.app.test_request_context():
        assert url_for('index') == '/'


def test_url_for_area_shell_resolves_each_area():
    """The migrated area routes still serve the shell, now under their own
    endpoint (area_shell) instead of colliding with 'index'."""
    with webapp.app.test_request_context():
        assert url_for('area_shell', area='environments') == '/environments'
        assert url_for('area_shell', area='tasks') == '/tasks'
        assert url_for('area_shell', area='day-plan') == '/day-plan'
        assert url_for('area_shell', area='account-health') == '/account-health'
