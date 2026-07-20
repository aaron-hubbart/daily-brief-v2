"""
Daily Brief Viewer — hosted app (Kubernetes deployment).

Auth model: this app does the OAuth 2.0 authorization code flow itself,
using MSAL against Camunda's existing Azure AD tenant and app registration:

  1. /login redirects to Azure AD's authorize endpoint.
  2. Azure AD redirects back to /auth/callback with an authorization code.
  3. This app exchanges that code for tokens server-side (MSAL handles the
     exchange and signature/issuer/audience validation).
  4. Only the minimal identity claims we need (name, email, oid, tenant id)
     go into a signed Flask session cookie — never the access token itself,
     since this app doesn't call Graph or any other API on the user's
     behalf. There's nothing to refresh and nothing sensitive to leak if a
     cookie were ever exposed beyond the session identity itself.

Any user in the configured tenant can sign in — Azure AD enforces the
tenant boundary because the app registration is single-tenant and MSAL is
configured with a tenant-specific authority (not "common"). There's no
additional allowlist right now; ALLOWED_GROUPS below is a marked, inactive
extension point for later if this needs to narrow to a specific group.

Path-prefix aware: this app is deployed alongside an existing app on the
same host, reachable at a sub-path (e.g. dashboard.es-sandbox.com/daily-brief/)
via an nginx-ingress Ingress rather than at a domain root. See
k8s/ingress.yaml and DEPLOYMENT.md for the reverse-proxy config this depends
on (X-Forwarded-Prefix, X-Forwarded-Proto).

Per-user data isolation: each signed-in user gets their own data/{slug}/
folder, derived from their verified session identity, never from anything
client-supplied.
"""
import json
import os
import re
import secrets
from functools import wraps
from pathlib import Path

import msal
from flask import Flask, Response, abort, jsonify, redirect, request, send_from_directory, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

APP_DIR = Path(__file__).resolve().parent
# In the VM deployment, app.py lives at viewer/webapp/app.py and the shared
# daily-brief-viewer.html sits one level up at viewer/. The container image
# flattens both into /app/ directly (see Dockerfile), so this is overridable
# rather than hardcoded to the VM's directory nesting.
VIEWER_HTML_DIR = Path(os.environ.get('VIEWER_HTML_DIR', str(APP_DIR.parent)))
DATA_ROOT = APP_DIR / 'data'      # data/{user-slug}/Daily Brief_*.html

BRIEF_RE = re.compile(r'^Daily Brief_\d{4}-\d{2}-\d{2}', re.IGNORECASE)

# ── Required configuration — fail loudly at startup rather than running insecurely ──

def _require_env(name):
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f'{name} is not set. See DEPLOYMENT.md for the full list of required '
            'environment variables and where each one comes from.'
        )
    return val

FLASK_SECRET_KEY = _require_env('FLASK_SECRET_KEY')
AZURE_TENANT_ID = _require_env('AZURE_TENANT_ID')
AZURE_CLIENT_ID = _require_env('AZURE_CLIENT_ID')
AZURE_CLIENT_SECRET = _require_env('AZURE_CLIENT_SECRET')
# Full callback URL Azure AD redirects back to, e.g.
# https://dashboard.es-sandbox.com/daily-brief/auth/callback — must exactly
# match a Redirect URI registered on the app registration in the Portal.
AZURE_REDIRECT_URI = _require_env('AZURE_REDIRECT_URI')

# Optional, inactive by default — comma-separated Azure AD group object IDs.
# If set, sign-in additionally requires the user's token to include one of
# these group IDs in its `groups` claim (requires enabling group claims on
# the app registration's token configuration). Leave unset for "any Camunda
# tenant user," which is what this test rollout uses.
_allowed_groups_raw = os.environ.get('ALLOWED_GROUPS', '').strip()
ALLOWED_GROUPS = {g.strip() for g in _allowed_groups_raw.split(',') if g.strip()} if _allowed_groups_raw else None

AZURE_AUTHORITY = f'https://login.microsoftonline.com/{AZURE_TENANT_ID}'
GRAPH_SCOPES = []  # no Graph calls made — sign-in identity only, nothing to scope

try:
    _UPLOAD_TOKENS = json.loads(os.environ.get('UPLOAD_TOKENS', '{}'))
except json.JSONDecodeError:
    _UPLOAD_TOKENS = {}

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PREFERRED_URL_SCHEME='https',
)

# Trust nginx's forwarded headers for scheme, host, and path prefix — required
# for url_for() and the OAuth redirect_uri to come out correct when this app
# is mounted at a sub-path behind a reverse proxy rather than at a domain root.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)


def _msal_app():
    return msal.ConfidentialClientApplication(
        AZURE_CLIENT_ID,
        authority=AZURE_AUTHORITY,
        client_credential=AZURE_CLIENT_SECRET,
    )


def slugify_user(principal_name: str) -> str:
    """Turn an email/UPN into a filesystem-safe folder name."""
    return re.sub(r'[^a-z0-9]+', '-', principal_name.lower()).strip('-') or 'unknown-user'


def current_user():
    """Reads the identity stored in the session by /auth/callback. Returns
    None if there's no session or it's missing required fields — never
    trusts anything from the request itself for identity."""
    u = session.get('user')
    if not u or not u.get('email') or not u.get('oid'):
        return None
    return u


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            session['post_login_redirect'] = request.path
            return redirect(url_for('login'))
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


# ── Auth routes ──────────────────────────────────────────────────────────

@app.route('/login')
def login():
    state = secrets.token_urlsafe(24)
    session['oauth_state'] = state
    auth_url = _msal_app().get_authorization_request_url(
        GRAPH_SCOPES,
        state=state,
        redirect_uri=AZURE_REDIRECT_URI,
    )
    return redirect(auth_url)


@app.route('/auth/callback')
def auth_callback():
    expected_state = session.pop('oauth_state', None)
    if not expected_state or request.args.get('state') != expected_state:
        abort(400, 'Invalid or missing OAuth state — possible CSRF, or an expired sign-in attempt. Try signing in again.')

    if 'error' in request.args:
        abort(401, request.args.get('error_description', 'Sign-in failed.'))

    code = request.args.get('code')
    if not code:
        abort(400, 'No authorization code returned.')

    result = _msal_app().acquire_token_by_authorization_code(
        code,
        scopes=GRAPH_SCOPES,
        redirect_uri=AZURE_REDIRECT_URI,
    )
    if 'error' in result:
        abort(401, result.get('error_description', 'Token exchange failed.'))

    claims = result.get('id_token_claims', {})

    # Defense in depth: MSAL's tenant-specific authority already scopes token
    # acquisition to this tenant, but verify the tid claim explicitly too —
    # cheap, and catches any future authority/config mismatch immediately
    # rather than silently trusting a token from the wrong tenant.
    if claims.get('tid') != AZURE_TENANT_ID:
        abort(403, 'Token issued by an unexpected tenant.')

    if ALLOWED_GROUPS is not None:
        user_groups = set(claims.get('groups', []))
        if not user_groups & ALLOWED_GROUPS:
            abort(403, 'Your account is not in an allowed group for this app.')

    email = claims.get('preferred_username') or claims.get('email') or claims.get('upn')
    if not email:
        abort(401, 'Sign-in succeeded but no usable email/UPN claim was present.')

    session['user'] = {
        'email': email,
        'name': claims.get('name', email),
        'oid': claims.get('oid'),
        'slug': slugify_user(email),
    }

    dest = session.pop('post_login_redirect', None) or url_for('index')
    return redirect(dest)


@app.route('/logout')
def logout():
    session.clear()
    # Also end the Azure AD session itself, not just this app's session —
    # otherwise a fresh /login silently re-signs the person in without a
    # prompt, which is surprising after clicking "logout."
    logout_url = (
        f'{AZURE_AUTHORITY}/oauth2/v2.0/logout'
        f'?post_logout_redirect_uri={url_for("index", _external=True)}'
    )
    return redirect(logout_url)


# ── App routes ────────────────────────────────────────────────────────────

@app.route('/')
@app.route('/index.html')
@login_required
def index():
    return send_from_directory(VIEWER_HTML_DIR, 'daily-brief-viewer.html')


@app.route('/api/whoami')
@login_required
def whoami():
    return jsonify({'name': request.brief_user['name'], 'email': request.brief_user['email']})


@app.route('/api/briefs')
@login_required
def api_briefs():
    return jsonify(list_briefs(request.brief_user))


@app.route('/brief/<path:name>')
@login_required
def serve_brief(name):
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
    Refresh flows) to deliver a generated report directly, in addition to —
    not instead of — uploading to Google Drive. Intentionally NOT behind
    @login_required: the skill has no browser session to complete an
    interactive Azure AD sign-in with. Guarded instead by its own bearer
    token, scoped to exactly one user's folder.
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


@app.route('/healthz')
def healthz():
    # Unauthenticated on purpose — nginx / uptime monitors need a path that
    # doesn't require a sign-in.
    return 'ok', 200


if __name__ == '__main__':
    # Local dev only. In production this runs under gunicorn behind nginx —
    # see DEPLOYMENT.md and gunicorn.conf.py.
    app.run(host='127.0.0.1', port=int(os.environ.get('PORT', 8000)), debug=False)
