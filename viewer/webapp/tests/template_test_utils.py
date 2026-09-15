"""Shared helper for rendering this app's Jinja templates in isolation,
without importing app.py. Importing app.py requires Flask/Azure env vars
(FLASK_SECRET_KEY, AZURE_TENANT_ID, etc. — see its _require_env calls) and
psycopg2 (via `import db`), neither of which this test environment has.
Template-only tests render the real template files through a standalone
Jinja2 Environment instead, with the same two custom filters app.py
registers (kept in sync by hand with app.py:541-569 below)."""
import re
from pathlib import Path

import jinja2
from markupsafe import Markup, escape

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / 'templates'

JIRA_TICKET_RE = re.compile(r'\b([A-Z]{2,}-\d+)\b')
JIRA_BASE_URL = 'https://jira.camunda.com/browse'


def _autolink_jira(text):
    if not text:
        return text
    safe_text = str(escape(text))

    def _replace(m):
        key = m.group(1)
        return f'<a class="lbtn" href="{JIRA_BASE_URL}/{key}" target="_blank">{key}</a>'

    return Markup(JIRA_TICKET_RE.sub(_replace, safe_text))


def _resolve_link_url(url):
    if not url:
        return url
    if url.startswith(('http://', 'https://', 'claude://', '//', '/')):
        return url
    if JIRA_TICKET_RE.fullmatch(url):
        return f'{JIRA_BASE_URL}/{url}'
    return url


def make_env():
    """A Jinja2 Environment wired up like app.py's Flask app, minus
    anything that needs a running Flask app (callers that render a
    template using `url_for` must stub it themselves via env.globals).
    Autoescape matches Flask's `select_autoescape` default for `.html`
    templates — without this, hostile content renders differently here
    than in production, which would let a real escaping bug pass these
    tests unnoticed."""
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=jinja2.select_autoescape(['html', 'htm', 'xml', 'xhtml']),
    )
    env.filters['autolink_jira'] = _autolink_jira
    env.filters['resolve_link_url'] = _resolve_link_url
    return env
