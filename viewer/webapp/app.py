"""
Daily Brief Viewer — hosted app.

Design note: this app does NOT talk to Azure AD directly and does not handle
tokens for the human-facing side. It's built to run behind Azure App
Service's built-in Authentication ("Easy Auth") pointed at Azure AD / Entra
ID. App Service does the OAuth dance, verifies the sign-in, and injects the
signed-in user's identity as request headers before the request ever reaches
this app. That's a much smaller, more auditable surface than hand-rolling
MSAL token exchange here — see ../AZURE_SETUP.md for how to configure that
in the Azure Portal.

If you deploy this somewhere other than App Service (a plain VM, a
container host without Easy Auth in front of it), current_user() below is
the one function you need to replace with real Azure AD token validation —
everything else (routing, per-user data isolation) stays the same.

Per-user data isolation: each signed-in user gets their own subfolder under
data/, named by a slug derived from their principal name (email). One user
can never see another user's briefs — every route re-derives the folder
from the current request's identity, never from a client-supplied value.

Getting reports onto the server: the daily-brief skill runs headless inside
a Claude conversation, so it can't go through an interactive Azure AD sign-in
to deliver a report — Easy Auth is for the human viewing side only. Instead,
/api/upload takes a separate bearer token per user (see UPLOAD_TOKENS below)
that the skill sends with each generated brief. This is a second, narrower
auth mechanism by design: a long-lived machine credential for one write-only
endpoint, not a substitute for the Azure AD login that guards everything else.
"""
import json
import os
import re
from functools import wraps
from pathlib import Path

from flask import Flask, Response, abort, jsonify, redirect, request, send_from_directory

APP_DIR = Path(__file__).resolve().parent
VIEWER_HTML_DIR = APP_DIR.parent  # viewer/daily-brief-viewer.html — reused as-is
DATA_ROOT = APP_DIR / 'data'      # data/{user-slug}/Daily Brief_*.html

BRIEF_RE = re.compile(r'^Daily Brief_\d{4}-\d{2}-\d{2}', re.IGNORECASE)

app = Flask(__name__)

# Fail loudly at startup rather than silently running with an insecure default.
_secret = os.environ.get('FLASK_SECRET_KEY')
if not _secret:
    raise RuntimeError(
        'FLASK_SECRET_KEY is not set. Generate one (e.g. python -c "import secrets; '
        'print(secrets.token_hex(32))") and set it as an App Service application '
        'setting before deploying — never hardcode it here.'
    )
app.secret_key = _secret

# Maps a per-user upload token to that user's data-folder slug, e.g.:
#   {"a1b2c3...": "aaron-hubbart"}
# Set as the UPLOAD_TOKENS app setting (a JSON string) in the Azure Portal —
# generate each token the same way as FLASK_SECRET_KEY, one per person who
# needs to push reports in. Rotate by changing the app setting; no redeploy
# needed since it's read at process start.
try:
    _UPLOAD_TOKENS = json.loads(os.environ.get('UPLOAD_TOKENS', '{}'))
except json.JSONDecodeError:
    _UPLOAD_TOKENS = {}


def slugify_user(principal_name: str) -> str:
    """Turn an email/UPN into a filesystem-safe folder name."""
    return re.sub(r'[^a-z0-9]+', '-', principal_name.lower()).strip('-') or 'unknown-user'


def current_user():
    """
    Reads the identity App Service Easy Auth already verified. Returns None
    if the headers are absent, which — with "Require authentication" turned
    on for this app in the Azure Portal — should only happen if Easy Auth
    itself isn't configured in front of this app (a deploy-time misconfig,
    not something a request can forge its way around).
    """
    principal_name = request.headers.get('X-MS-CLIENT-PRINCIPAL-NAME')
    principal_id = request.headers.get('X-MS-CLIENT-PRINCIPAL-ID')
    if not principal_name or not principal_id:
        return None
    return {'name': principal_name, 'id': principal_id, 'slug': slugify_user(principal_name)}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            # Defensive fallback only — Easy Auth should intercept this before
            # it ever reaches the app when "Require authentication" is on.
            return redirect('/.auth/login/aad?post_login_redirect_uri=' + request.path)
        request.brief_user = user
        return view(*args, **kwargs)
    return wrapped


def user_data_dir(user) -> Path:
    d = DATA_ROOT / user['slug']
    d.mkdir(parents=True, exist_ok=True)
    return d


def make_label(name: str) -> str:
    m = re.match(r'Daily Brief_(\d{4}-\d{2}-\d{2})(?:_(\d{2})-(\d{2}))?', name, re.IGNORECASE)
    if not m:
        return name
    date_part = m.group(1)
    hour, minute = m.group(2), m.group(3)
    if hour and minute:
        return date_part + ' ' + hour + ':' + minute
    return date_part


def list_briefs(user) -> list:
    d = user_data_dir(user)
    files = []
    for name in os.listdir(d):
        if BRIEF_RE.match(name) and name.lower().endswith('.html'):
            path = d / name
            files.append({
                'name': name,
                'label': make_label(name),
                'size': path.stat().st_size,
                'mtime': path.stat().st_mtime,
            })
    files.sort(key=lambda f: f['name'], reverse=True)
    return files


@app.route('/')
@app.route('/index.html')
@login_required
def index():
    return send_from_directory(VIEWER_HTML_DIR, 'daily-brief-viewer.html')


@app.route('/api/whoami')
@login_required
def whoami():
    return jsonify({'name': request.brief_user['name']})


@app.route('/api/briefs')
@login_required
def api_briefs():
    return jsonify(list_briefs(request.brief_user))


@app.route('/brief/<path:name>')
@login_required
def serve_brief(name):
    # Same defense-in-depth check as the local server.py: reject anything that
    # isn't a bare filename matching the expected pattern before it ever
    # touches the filesystem.
    if not BRIEF_RE.match(name) or '/' in name or '\\' in name or '..' in name:
        abort(400)
    fpath = user_data_dir(request.brief_user) / name
    if not fpath.is_file():
        abort(404)
    return Response(fpath.read_text(encoding='utf-8'), mimetype='text/html; charset=utf-8')


@app.route('/api/upload', methods=['POST'])
def api_upload():
    """
    Called by the daily-brief skill (or the Post-Meeting Patch / Section
    Refresh flows) to deliver a generated report directly, as an addition to
    — not a replacement for — uploading to Google Drive. This route is
    intentionally NOT behind @login_required / Easy Auth: the skill has no
    browser session to complete an interactive Azure AD sign-in with. It's
    guarded instead by its own bearer token, scoped to exactly one user's
    folder and nothing else.
    """
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        abort(401)
    token = auth[len('Bearer '):].strip()
    slug = _UPLOAD_TOKENS.get(token)
    if not slug:
        abort(403)

    body = request.get_json(silent=True) or {}
    name = body.get('filename', '')
    html = body.get('html', '')
    if not BRIEF_RE.match(name) or not name.lower().endswith('.html') or '/' in name or '\\' in name or '..' in name:
        abort(400, 'filename must match "Daily Brief_YYYY-MM-DD..." with no path components')
    if not html:
        abort(400, 'html body is required')

    d = DATA_ROOT / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(html, encoding='utf-8')
    return jsonify({'status': 'ok', 'saved': name}), 201


@app.route('/logout')
def logout():
    return redirect('/.auth/logout?post_logout_redirect_uri=/')


@app.route('/healthz')
def healthz():
    # Unauthenticated on purpose — App Service health checks and uptime
    # monitors need a path that doesn't require a sign-in.
    return 'ok', 200


if __name__ == '__main__':
    # Local dev only. In production, App Service runs this via gunicorn
    # (see startup.sh) with Easy Auth sitting in front of it.
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8000)), debug=False)
