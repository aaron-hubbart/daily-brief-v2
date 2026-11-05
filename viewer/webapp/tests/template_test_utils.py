"""Shared helper for rendering this app's Jinja templates in isolation,
without importing app.py. Importing app.py requires Flask/Azure env vars
(FLASK_SECRET_KEY, AZURE_TENANT_ID, etc. — see its _require_env calls) and
psycopg2 (via `import db`), neither of which this test environment has.
Template-only tests render the real template files through a standalone
Jinja2 Environment instead, with the same custom filters app.py registers
(kept in sync by hand with app.py's @app.template_filter functions)."""
import re
from pathlib import Path

import jinja2
from markupsafe import Markup, escape

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / 'templates'

JIRA_TICKET_RE = re.compile(r'\b([A-Z]{2,}-\d+)\b')
JIRA_BASE_URL = 'https://jira.camunda.com/browse'

STATUS_BUCKET_HEADERS = ('Updates/FYI', 'Pending Action Items', 'Blockers/Risks')
STATUS_BUCKET_CSS_CLASS = {
    'Updates/FYI': 'sb-fyi',
    'Pending Action Items': 'sb-action',
    'Blockers/Risks': 'sb-risk',
}
STATUS_BUCKET_BULLET_RE = re.compile(r'^[-•]\s*')


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


def _format_status_buckets(text):
    if not text:
        return text
    lines = [line.strip() for line in text.splitlines()]
    header_positions = [i for i, line in enumerate(lines) if line in STATUS_BUCKET_HEADERS]
    if (
        len(header_positions) < len(STATUS_BUCKET_HEADERS)
        or [lines[i] for i in header_positions[:3]] != list(STATUS_BUCKET_HEADERS)
    ):
        return _autolink_jira(text)

    header_positions = header_positions[:3]
    html = []
    for idx, pos in enumerate(header_positions):
        header = lines[pos]
        end = header_positions[idx + 1] if idx + 1 < len(header_positions) else len(lines)
        bullets = [
            STATUS_BUCKET_BULLET_RE.sub('', line)
            for line in lines[pos + 1:end]
            if line
        ]
        html.append(f'<div class="status-bucket {STATUS_BUCKET_CSS_CLASS[header]}">')
        html.append(f'<div class="status-bucket-label">{escape(header)}</div>')
        if len(bullets) == 1 and bullets[0].strip().lower() == 'none':
            html.append('<div class="status-bucket-none">None</div>')
        else:
            html.append('<ul class="status-bucket-list">')
            html.extend(f'<li>{_autolink_jira(bullet)}</li>' for bullet in bullets)
            html.append('</ul>')
        html.append('</div>')
    return Markup(''.join(html))


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
    env.filters['format_status_buckets'] = _format_status_buckets
    return env
