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

Per-user data isolation: each signed-in user's brief days and items are
scoped to their own row in Postgres by user_id — every query filters on the
current session's verified identity, never anything client-supplied. See
db.py and db/README.md for the storage model.
"""
import json
import os
import re
import secrets
import urllib.error
import urllib.request
from datetime import date
from functools import wraps
from pathlib import Path

import msal
from flask import Flask, Response, abort, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

import db

APP_DIR = Path(__file__).resolve().parent
# In the VM deployment, app.py lives at viewer/webapp/app.py and the shared
# daily-brief-viewer.html sits one level up at viewer/. The container image
# flattens both into /app/ directly (see Dockerfile), so this is overridable
# rather than hardcoded to the VM's directory nesting.
VIEWER_HTML_DIR = Path(os.environ.get('VIEWER_HTML_DIR', str(APP_DIR.parent)))

DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')

# Fixed section slugs/labels/open-by-default, in the order they render.
# Matches the daily-brief skill's existing section conventions.
SECTIONS = [
    {'slug': 'yesterday-meetings', 'label': "Yesterday's Meetings", 'open_default': True},
    {'slug': 'account-recap', 'label': 'Account / Initiative Recap', 'open_default': True},
    {'slug': 'today', 'label': 'Today', 'open_default': True},
    {'slug': 'action-items', 'label': 'Action Items', 'open_default': True},
    {'slug': 'fyi', 'label': 'FYI', 'open_default': True},
    {'slug': 'customer-updates', 'label': 'Customer Updates', 'open_default': False},
    {'slug': 'manager-update', 'label': 'Manager / Leadership Update', 'open_default': False},
]


ASANA_ACTION_ITEM_PREFIX = 'action-'


def _sync_asana_completed(item_key: str, checked: bool):
    """
    Best-effort: mirrors a checkbox toggle on an Action Item to the
    completed state of its linked Asana task. Returns (attempted, ok).
    attempted is False when the item_key isn't an Asana-backed action item
    or ASANA_PAT isn't configured, ok is False when it was attempted but
    the Asana API call itself failed — either way the Postgres write this
    accompanies has already succeeded and isn't rolled back.
    """
    if not item_key.startswith(ASANA_ACTION_ITEM_PREFIX):
        return False, False
    if not ASANA_PAT:
        return False, False
    gid = item_key[len(ASANA_ACTION_ITEM_PREFIX):]
    if not gid.isdigit():
        return False, False
    req = urllib.request.Request(
        f'https://app.asana.com/api/1.0/tasks/{gid}',
        data=json.dumps({'data': {'completed': checked}}).encode('utf-8'),
        method='PUT',
        headers={
            'Authorization': f'Bearer {ASANA_PAT}',
            'Content-Type': 'application/json',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            return True, True
    except urllib.error.URLError:
        return True, False


def _sync_asana_due_date(item_key: str, due_on):
    """
    Best-effort: mirrors an Action Items due-date box edit to the linked
    Asana task's due_on field. Same shape and same caveats as
    _sync_asana_completed above — returns (attempted, ok), and a failed
    Asana call never rolls back the Postgres write it accompanies.
    due_on is an ISO date string ('YYYY-MM-DD') or None to clear the date.
    """
    if not item_key.startswith(ASANA_ACTION_ITEM_PREFIX):
        return False, False
    if not ASANA_PAT:
        return False, False
    gid = item_key[len(ASANA_ACTION_ITEM_PREFIX):]
    if not gid.isdigit():
        return False, False
    req = urllib.request.Request(
        f'https://app.asana.com/api/1.0/tasks/{gid}',
        data=json.dumps({'data': {'due_on': due_on}}).encode('utf-8'),
        method='PUT',
        headers={
            'Authorization': f'Bearer {ASANA_PAT}',
            'Content-Type': 'application/json',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            return True, True
    except urllib.error.URLError:
        return True, False


# Fixed order and labels for the Action Items subsections (see
# _group_action_items below). "New Items" always renders first regardless
# of due date so a freshly created task doesn't get buried under overdue
# items from prior days.
ACTION_SUBSECTIONS = [
    {'slug': 'new', 'label': 'New Items'},
    {'slug': 'overdue', 'label': 'Overdue'},
    {'slug': 'due-soon', 'label': 'Due Next 7 Days'},
    {'slug': 'no-due-date', 'label': 'No Due Date'},
]


def _group_action_items(items, today_iso: str):
    """
    Splits the flat Action Items list into the four fixed subsections the
    template renders. Membership is exclusive — an item lands in exactly
    one group, checked in this priority order:

      1. is_new  — content.is_new is true (this brief run created the
         Asana task itself; see references/item-sync.md). Takes priority
         over the date-based groups below so a brand-new overdue-looking
         task still shows up under "New Items", not "Overdue".
      2. overdue — content.due_on is set and before today.
      3. due-soon — content.due_on is set and within the next 7 days
         (inclusive of today).
      4. no-due-date — everything else: no due_on at all, or a non-Asana
         action item with no natural date.

    Items are sorted by due_on ascending within groups 2 and 3; group 4
    keeps upstream display_order (already priority-ordered by the skill)
    since there's no date to sort on, and group 1 does the same.
    Returns a list of {slug, label, items} dicts, omitting empty groups —
    the template skips rendering a subsection header with nothing under it.
    """
    from datetime import date, timedelta

    today = date.fromisoformat(today_iso)
    week_out = today + timedelta(days=7)
    buckets = {s['slug']: [] for s in ACTION_SUBSECTIONS}

    for item in items:
        content = item.get('content') or {}
        due_on = content.get('due_on')
        if content.get('is_new'):
            buckets['new'].append(item)
            continue
        if due_on:
            try:
                due_date = date.fromisoformat(due_on)
            except ValueError:
                due_date = None
        else:
            due_date = None
        if due_date is not None and due_date < today:
            buckets['overdue'].append(item)
        elif due_date is not None and due_date <= week_out:
            buckets['due-soon'].append(item)
        else:
            buckets['no-due-date'].append(item)

    for slug in ('overdue', 'due-soon'):
        buckets[slug].sort(key=lambda it: (it.get('content') or {}).get('due_on') or '')

    return [
        {**s, 'items': buckets[s['slug']]}
        for s in ACTION_SUBSECTIONS
        if buckets[s['slug']]
    ]


def _count_label(slug, items):
    if slug == 'customer-updates':
        return f'Expand — {len(items)} assigned accounts'
    if slug == 'manager-update':
        return 'Expand'
    return f'{len(items)} items'

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
# postgresql://user:password@host:5432/dbname — see DEPLOYMENT.md / db/README.md
_require_env('DATABASE_URL')
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

# Optional, inactive unless set — comma-separated emails allowed to reach
# /admin and its API. Same shape as ALLOWED_GROUPS: leave unset and the
# admin routes 404 for everyone rather than silently exposing an empty
# panel. Case-insensitive since Azure AD UPNs aren't guaranteed one case.
_admin_emails_raw = os.environ.get('ADMIN_EMAILS', '').strip()
ADMIN_EMAILS = {e.strip().lower() for e in _admin_emails_raw.split(',') if e.strip()} if _admin_emails_raw else None

# Optional, inactive unless set — a single Asana Personal Access Token used
# to keep Action Items in sync with their linked Asana task's completed
# state. Action item keys are minted as `action-{asana_gid}` (see
# references/item-sync.md in the skill repo), so the GID needed for the
# Asana API call comes straight out of the item_key with no extra lookup.
# Leave unset and checkbox toggles on action items still persist to
# Postgres, they just don't reach Asana.
ASANA_PAT = os.environ.get('ASANA_PAT', '').strip() or None

# Optional, display-only — the daily-brief-mcp-server connector's public
# URL (e.g. https://mcp.dashboard.es-sandbox.com/mcp), shown verbatim in
# the in-app setup walkthrough so people don't have to go find it
# themselves. Not used for anything security-relevant by this app itself.
MCP_CONNECTOR_URL = os.environ.get('MCP_CONNECTOR_URL', '').strip() or None

AZURE_AUTHORITY = f'https://login.microsoftonline.com/{AZURE_TENANT_ID}'
GRAPH_SCOPES = []  # no Graph calls made — sign-in identity only, nothing to scope

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PREFERRED_URL_SCHEME='https',
    # Both this app and the parent dashboard app live on dashboard.es-sandbox.com.
    # Flask's cookie defaults (name "session", path "/") are identical for both,
    # so without overriding them here, whichever app sets its cookie last wins —
    # the other app's session gets silently clobbered. That produced a login
    # loop: this app's session would be overwritten right after auth_callback
    # set it, so login_required immediately treated the user as signed out
    # again and bounced back to /login. Scoping both name and path to this
    # app's mount point keeps the two cookies distinct.
    SESSION_COOKIE_NAME='daily_brief_session',
    SESSION_COOKIE_PATH='/daily-brief',
)

class ForcePrefixMiddleware:
    """Hardcodes SCRIPT_NAME instead of trusting X-Forwarded-Prefix.

    The plan was for nginx (via the ingress's proxy-set-headers annotation +
    the daily-brief-proxy-headers ConfigMap) to inject X-Forwarded-Prefix,
    and for ProxyFix(x_prefix=1) to turn that into SCRIPT_NAME so url_for()
    and login_required's redirect(url_for('login')) would come out as
    /daily-brief/login. In practice that annotation is only a documented
    *global* ingress-nginx-controller ConfigMap key, not a per-Ingress one —
    confirmed by dumping the controller's rendered nginx.conf, which has no
    proxy_set_header for X-Forwarded-Prefix anywhere in this app's location
    block. The header never arrived, so SCRIPT_NAME stayed empty, redirects
    came out as bare /login (outside this app's ingress path entirely), and
    people fell into the dashboard app's own sign-in instead of ours.

    This app is always mounted at exactly one fixed prefix, so there's
    nothing to "discover" from a header — just set it.
    """
    def __init__(self, wsgi_app, prefix):
        self.wsgi_app = wsgi_app
        self.prefix = prefix

    def __call__(self, environ, start_response):
        environ['SCRIPT_NAME'] = self.prefix
        return self.wsgi_app(environ, start_response)


# Trust nginx's forwarded headers for scheme, host, and client IP; the path
# prefix is hardcoded above instead of trusted from a header (see
# ForcePrefixMiddleware) since nginx never actually sends one for this app.
app.wsgi_app = ForcePrefixMiddleware(
    ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1),
    '/daily-brief',
)
app.teardown_appcontext(db.close_conn)


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
    if not u or not u.get('email') or not u.get('oid') or not u.get('id'):
        return None
    return u


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            # request.path alone is the path AFTER nginx has already
            # stripped the /daily-brief prefix (that's the whole point of
            # the Ingress rewrite-target) — it's just "/" for the viewer's
            # root, with no prefix on it. request.script_root is where
            # ForcePrefixMiddleware put that prefix back (hardcoded, not
            # from a forwarded header — see its docstring). Unlike
            # url_for(), a plain redirect(dest) does NOT automatically
            # prepend script_root to a literal string — skipping this here
            # sent people back to the domain root after sign-in instead of
            # back under /daily-brief.
            session['post_login_redirect'] = request.script_root + request.path
            return redirect(url_for('login'))
        request.brief_user = user
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    """Stacks on top of login_required (apply login_required first/outer).
    If ADMIN_EMAILS is unset, every admin route 404s for everyone — there's
    no "admin panel open to any signed-in user" fallback state."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if ADMIN_EMAILS is None or request.brief_user['email'].lower() not in ADMIN_EMAILS:
            abort(404)
        return view(*args, **kwargs)
    return wrapped


def ensure_upload_context():
    """Shared bearer-token check for the skill-facing item endpoints.
    Returns the resolved user_id. Tokens are auto-assigned per user at
    first sign-in (db.get_or_create_user) — there's no admin-managed token
    list to keep in sync anymore."""
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        abort(401)
    token = auth[len('Bearer '):].strip()
    user = db.get_user_by_token(token)
    if not user:
        abort(403)
    return user['id']


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

    slug = slugify_user(email)
    # This is what makes new-user setup automatic — first sign-in creates
    # the row and assigns an api_token in the same call, no admin step.
    user_row = db.get_or_create_user(email, slug)
    session['user'] = {
        'email': email,
        'name': claims.get('name', email),
        'oid': claims.get('oid'),
        'slug': slug,
        # Resolved once at login and cached in the session — every later
        # request in this session reuses it rather than re-querying users
        # on every page load.
        'id': user_row['id'],
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
    user = db.get_user_by_id(request.brief_user['id'])
    return jsonify({
        'name': request.brief_user['name'],
        'email': request.brief_user['email'],
        'onboarding_completed': bool(user and user['onboarding_completed_at']),
    })


@app.route('/api/onboarding/complete', methods=['POST'])
@login_required
def api_onboarding_complete():
    """Called once the person finishes (or dismisses) the in-app setup
    walkthrough, so it doesn't auto-open again on their next sign-in.
    They can still reopen it manually any time from the Account panel."""
    db.mark_onboarding_complete(request.brief_user['id'])
    return jsonify({'status': 'ok'})


@app.route('/api/client-config')
@login_required
def api_client_config():
    """Values the setup walkthrough and Account panel need to render
    correct copy-paste instructions, computed server-side rather than
    guessed from window.location (this app is deployed at a sub-path, and
    the MCP connector lives on an entirely different subdomain that the
    browser has no way to derive on its own)."""
    return jsonify({
        # request.script_root is where ForcePrefixMiddleware put the
        # /daily-brief prefix back (see its docstring) — same value this
        # deployment's DAILY_BRIEF_API_BASE_URL is set to.
        'api_base_url': request.host_url.rstrip('/') + request.script_root,
        'mcp_connector_url': MCP_CONNECTOR_URL,
    })


@app.route('/api/token')
@login_required
def api_token():
    """
    Lets a signed-in person retrieve their own api_token — this is the
    self-service half of automatic setup. There's no admin step between
    "person signs in for the first time" and "person has a token they can
    put in their own daily-brief skill's Admin Config": db.get_or_create_user
    already assigned one at sign-in time (see /auth/callback); this just
    surfaces it.
    """
    token = db.get_user_token(request.brief_user['id'])
    return jsonify({'token': token, 'email': request.brief_user['email']})


@app.route('/api/token/rotate', methods=['POST'])
@login_required
def api_token_rotate():
    """Invalidates the current token and issues a new one — for when a
    token leaks or someone just wants a fresh one. The old value stops
    working immediately; whatever skill config used it needs updating."""
    new_token = db.rotate_user_token(request.brief_user['id'])
    return jsonify({'token': new_token})


@app.route('/admin')
@login_required
@admin_required
def admin_page():
    return render_template('admin.html', admin_email=request.brief_user['email'])


@app.route('/api/admin/users')
@login_required
@admin_required
def admin_list_users():
    return jsonify(db.list_users_with_stats())


@app.route('/api/admin/users/<int:user_id>/rotate-token', methods=['POST'])
@login_required
@admin_required
def admin_rotate_user_token(user_id):
    """Rotates another user's token from the admin panel — for troubleshooting
    a stuck sync (401/403 from the skill) without asking the person to find
    and revisit /api/token themselves. Whoever's token this is needs their
    skill's Admin Config (DAILY_BRIEF_API_TOKEN_FILE_ID's Drive file) updated
    with the new value before their next brief run — this only invalidates
    the old one, it doesn't push the new one anywhere."""
    user = db.get_user_by_id(user_id)
    if not user:
        abort(404)
    new_token = db.rotate_user_token(user_id)
    return jsonify({'email': user['email'], 'token': new_token})


@app.route('/api/admin/config')
@login_required
@admin_required
def admin_config_status():
    """Presence checks only — never the actual secret values — so an admin
    can confirm a deployment's env vars are wired up without this becoming
    a way to read secrets out of the running pod."""
    return jsonify({
        'azure_tenant_id_set': bool(AZURE_TENANT_ID),
        'azure_client_id_set': bool(AZURE_CLIENT_ID),
        'azure_redirect_uri': AZURE_REDIRECT_URI,
        'allowed_groups_active': ALLOWED_GROUPS is not None,
        'allowed_groups_count': len(ALLOWED_GROUPS) if ALLOWED_GROUPS else 0,
        'admin_emails_count': len(ADMIN_EMAILS) if ADMIN_EMAILS else 0,
        'asana_pat_set': bool(ASANA_PAT),
    })


@app.route('/api/briefs')
@login_required
def api_briefs():
    days = db.list_active_briefs(request.brief_user['id'])
    # 'name' and 'label' are what the existing viewer JS actually reads
    # (see daily-brief-viewer.html) — everything else from the old
    # file-listing response (size, mtime) was never used by the frontend,
    # so it's fine that a DB row doesn't have a natural equivalent for them.
    return jsonify([
        {'name': d['brief_date'].isoformat(), 'label': d['brief_date'].isoformat()}
        for d in days
    ])


@app.route('/brief/<date_str>')
@login_required
def serve_brief(date_str):
    if not DATE_RE.match(date_str):
        abort(400)
    brief_day = db.get_brief_day(request.brief_user['id'], date_str)
    if not brief_day:
        abort(404)

    items = db.get_items_for_day(brief_day['id'])
    items_by_section = {}
    checkable_count = 0
    for item in items:
        items_by_section.setdefault(item['section'], []).append(item)
        if item['item_type'] in ('checkable', 'fyi') and item['checked'] is not None:
            checkable_count += 1

    sections = []
    for s in SECTIONS:
        section_items = items_by_section.get(s['slug'], [])
        sections.append({**s, 'count_label': _count_label(s['slug'], section_items)})

    # Action Items renders as four fixed subsections (New Items, Overdue,
    # Due Next 7 Days, No Due Date) rather than one flat list — see
    # _group_action_items for the grouping rules. "Today" here means the
    # server's own local date; brief_date is the brief's date, which isn't
    # necessarily the same day the person is viewing it on an evening/late
    # run, so we deliberately use wall-clock today for the overdue/due-soon
    # cutoffs rather than brief_date.
    action_subsections = _group_action_items(
        items_by_section.get('action-items', []),
        date.today().isoformat(),
    )

    return render_template(
        'brief_fragment.html',
        brief_date=date_str,
        brief_date_label=brief_day['brief_date'].strftime('%A, %B %-d'),
        brief_type=brief_day['brief_type'],
        checkable_count=checkable_count,
        sections=sections,
        items_by_section=items_by_section,
        action_subsections=action_subsections,
        today_iso=date.today().isoformat(),
    )


@app.route('/api/items/<section>/<item_key>/checked', methods=['PATCH'])
@login_required
def set_item_checked(section, item_key):
    """
    Called by the viewer frontend on every checkbox toggle (see
    daily-brief-viewer.html's toggle()) — checked state persists to
    Postgres so it survives across devices, replacing the old
    localStorage-only model. For Action Items specifically (item_key
    formatted as action-{asana_gid}), this also mirrors the toggle onto
    the linked Asana task's completed field via _sync_asana_completed;
    checking the box completes the task, unchecking it reopens it. The
    Asana call is best-effort and never blocks or rolls back the Postgres
    write — see 'asana_synced' in the response for its outcome.
    """
    date_str = request.args.get('date', '')
    if not DATE_RE.match(date_str):
        abort(400, 'date query param (YYYY-MM-DD) is required')
    brief_day = db.get_brief_day(request.brief_user['id'], date_str)
    if not brief_day:
        abort(404)
    body = request.get_json(silent=True) or {}
    if 'checked' not in body:
        abort(400, 'checked (bool) is required')
    checked = bool(body['checked'])
    found = db.set_item_checked(brief_day['id'], section, item_key, checked)
    if not found:
        abort(404)
    attempted, ok = _sync_asana_completed(item_key, checked)
    result = {'status': 'ok'}
    if attempted:
        result['asana_synced'] = ok
    return jsonify(result)


@app.route('/api/items/<section>/<item_key>/due-date', methods=['PATCH'])
@login_required
def set_item_due_date(section, item_key):
    """
    Called by the Action Items due-date box (input or one of the four
    shortcut buttons — Today/Tomorrow/Next week/Next month) on every edit.
    Same bidirectional shape as set_item_checked above: the Postgres write
    is the source of truth for what the box displays after a refresh, and
    a best-effort Asana sync (_sync_asana_due_date) mirrors the new date
    onto the linked task so editing it in the brief and editing it in
    Asana directly both converge on the same value either way.
    """
    date_str = request.args.get('date', '')
    if not DATE_RE.match(date_str):
        abort(400, 'date query param (YYYY-MM-DD) is required')
    brief_day = db.get_brief_day(request.brief_user['id'], date_str)
    if not brief_day:
        abort(404)
    body = request.get_json(silent=True) or {}
    if 'due_on' not in body:
        abort(400, 'due_on (YYYY-MM-DD or null) is required')
    due_on = body['due_on']
    if due_on is not None and not DATE_RE.match(due_on):
        abort(400, 'due_on must be YYYY-MM-DD or null')
    found = db.set_item_due_date(brief_day['id'], section, item_key, due_on)
    if not found:
        abort(404)
    attempted, ok = _sync_asana_due_date(item_key, due_on)
    result = {'status': 'ok'}
    if attempted:
        result['asana_synced'] = ok
    return jsonify(result)


@app.route('/api/items/upsert', methods=['POST'])
def api_items_upsert():
    """
    Called by the daily-brief skill to create or refresh one item. This is
    the single operation for both "generate a brand-new day's brief" (call
    once per item) and "refresh one thing later" (call again for just that
    item_key) — the old file-based model needed a whole separate patch flow
    (references/section-refresh.md in the skill repo) for the second case;
    an upsert doesn't need that distinction.

    Not behind @login_required: the skill runs headless and has no browser
    session for an interactive Azure AD sign-in. Guarded by its own bearer
    token instead, scoped to exactly one user.

    Body: {brief_date, brief_type?, section, item_key, item_type?, title?,
           subtitle?, badge?, links?, content?, checked?, display_order?}
    """
    user_id = ensure_upload_context()
    body = request.get_json(silent=True) or {}

    brief_date = body.get('brief_date', '')
    if not DATE_RE.match(brief_date):
        abort(400, 'brief_date must be YYYY-MM-DD')
    if not body.get('section') or not body.get('item_key'):
        abort(400, 'section and item_key are required')

    brief_day_id = db.upsert_brief_day(user_id, brief_date, body.get('brief_type'))
    db.upsert_item(brief_day_id, body)
    return jsonify({'status': 'ok'}), 201


@app.route('/api/items/batch-upsert', methods=['POST'])
def api_items_batch_upsert():
    """
    Same as /api/items/upsert but for a whole day's worth of items in one
    call — what a full brief-generation run should use, rather than one
    HTTP round trip per item. Body: {brief_date, brief_type?, items: [...]}
    where each entry in items is the same shape as the single-upsert body
    (minus brief_date/brief_type, which apply to the whole batch).
    """
    user_id = ensure_upload_context()
    body = request.get_json(silent=True) or {}

    brief_date = body.get('brief_date', '')
    if not DATE_RE.match(brief_date):
        abort(400, 'brief_date must be YYYY-MM-DD')
    items = body.get('items')
    if not isinstance(items, list) or not items:
        abort(400, 'items must be a non-empty array')
    for item in items:
        if not item.get('section') or not item.get('item_key'):
            abort(400, 'every item needs section and item_key')

    brief_day_id = db.upsert_brief_day(user_id, brief_date, body.get('brief_type'))
    for item in items:
        db.upsert_item(brief_day_id, item)
    return jsonify({'status': 'ok', 'count': len(items)}), 201


@app.route('/healthz')
def healthz():
    # Unauthenticated on purpose — process-liveness only, deliberately does
    # NOT check the database. A transient Postgres blip shouldn't cause
    # Kubernetes to kill and restart this pod; restarting doesn't fix a DB
    # problem, it just adds a second failure on top of the first. Use
    # /readyz (below) for anything that should depend on DB connectivity.
    return 'ok', 200


@app.route('/readyz')
def readyz():
    # Readiness should depend on the DB — if Postgres is unreachable this
    # pod can't actually serve a real request, and Kubernetes should stop
    # routing traffic to it (via the Service) until it's back, without
    # killing/restarting the pod itself (that's what /healthz is for).
    try:
        with db.cursor() as cur:
            cur.execute('SELECT 1')
    except Exception as e:
        return f'db unavailable: {e}', 503
    return 'ok', 200


if __name__ == '__main__':
    # Local dev only. In production this runs under gunicorn behind nginx —
    # see DEPLOYMENT.md and gunicorn.conf.py.
    app.run(host='127.0.0.1', port=int(os.environ.get('PORT', 8000)), debug=False)
