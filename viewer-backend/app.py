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
import logging
import os
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from functools import wraps
from pathlib import Path

import msal
from flask import Flask, Response, abort, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

import token_store as db_tokens
import google_oauth
import drive_store

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


ASANA_API_BASE = 'https://app.asana.com/api/1.0'


def _sync_asana_completed(pat, item_key: str, checked: bool):
    """
    Best-effort: mirrors a checkbox toggle on an Action Item to the
    completed state of its linked Asana task. Returns (attempted, ok).
    attempted is False when the item_key isn't an Asana-backed action item
    or the signed-in user has no asana_pat configured, ok is False when it
    was attempted but the Asana API call itself failed — either way the
    Postgres write this accompanies (if any — see the live-item fallback
    in set_item_checked below) has already succeeded and isn't rolled back.
    """
    if not item_key.startswith(ASANA_ACTION_ITEM_PREFIX):
        return False, False
    if not pat:
        return False, False
    gid = item_key[len(ASANA_ACTION_ITEM_PREFIX):]
    if not gid.isdigit():
        return False, False
    req = urllib.request.Request(
        f'{ASANA_API_BASE}/tasks/{gid}',
        data=json.dumps({'data': {'completed': checked}}).encode('utf-8'),
        method='PUT',
        headers={
            'Authorization': f'Bearer {pat}',
            'Content-Type': 'application/json',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            return True, True
    except urllib.error.URLError:
        return True, False


def _sync_asana_due_date(pat, item_key: str, due_on):
    """
    Best-effort: mirrors an Action Items due-date box edit to the linked
    Asana task's due_on field. Same shape and same caveats as
    _sync_asana_completed above — returns (attempted, ok), and a failed
    Asana call never rolls back the Postgres write it accompanies.
    due_on is an ISO date string ('YYYY-MM-DD') or None to clear the date.
    """
    if not item_key.startswith(ASANA_ACTION_ITEM_PREFIX):
        return False, False
    if not pat:
        return False, False
    gid = item_key[len(ASANA_ACTION_ITEM_PREFIX):]
    if not gid.isdigit():
        return False, False
    req = urllib.request.Request(
        f'{ASANA_API_BASE}/tasks/{gid}',
        data=json.dumps({'data': {'due_on': due_on}}).encode('utf-8'),
        method='PUT',
        headers={
            'Authorization': f'Bearer {pat}',
            'Content-Type': 'application/json',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            return True, True
    except urllib.error.URLError:
        return True, False


def _asana_api_get(pat, path, params):
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f'{ASANA_API_BASE}{path}?{query}',
        headers={'Authorization': f'Bearer {pat}'},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode('utf-8'))


def _validate_asana_pat(pat):
    """Used when a person saves a new PAT during setup or from the Account
    panel — calls Asana's own /users/me so a bad token is caught immediately
    with a clear error, rather than silently failing later on the first
    live pull. Returns the Asana user's name/email dict, or None if the
    token is invalid or the call otherwise failed."""
    try:
        data = _asana_api_get(pat, '/users/me', {'opt_fields': 'name,email'})
        return data.get('data')
    except (urllib.error.URLError, json.JSONDecodeError):
        return None


def _fetch_live_action_items(pat, account_projects, exclude_gids):
    """
    Pulls open tasks that are either assigned to the signed-in user or
    unassigned, directly from Asana, for every project GID in
    account_projects, excluding any task GID already tracked in Postgres
    as a New Item (see references/item-sync.md in the skill repo — only
    newly-created tasks are upserted there now). Returns a flat list of
    item dicts shaped like the skill's own action-items rows, so
    _group_action_items can bucket them exactly the same way it already
    does for New Items.

    Unassigned tasks are included on purpose: an unassigned task sitting
    in one of the person's own account projects is still their problem to
    triage, and a live pull that silently hid those would understate what
    actually needs attention.

    Asana's /tasks endpoint rejects a query that specifies both `project`
    and `assignee` — its own API error is "Must specify exactly one of
    project, tag, section, user task list, or assignee + workspace". So
    this queries by `project` alone (every task in the project, done or
    not, hence `completed_since=now` to only get incomplete ones) and
    filters client-side to tasks with no assignee or assigned to the
    signed-in person's own Asana user gid, resolved once per call rather
    than per project.

    Best-effort per project: one project's fetch failing (bad GID, Asana
    outage, rate limit) doesn't block the others — it's just logged and
    skipped, since there's no per-item place in this flat list to surface
    a project-level error.
    """
    try:
        me = _asana_api_get(pat, '/users/me', {'opt_fields': 'gid'})
        me_gid = me.get('data', {}).get('gid')
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        logger.warning('live action items: could not resolve Asana user gid, aborting pull: %s', e)
        return []
    if not me_gid:
        logger.warning('live action items: /users/me returned no gid, aborting pull')
        return []

    items = []
    seen_gids = set(exclude_gids)
    for ap in account_projects:
        gid = ap['project_gid']
        try:
            data = _asana_api_get(pat, '/tasks', {
                'project': gid,
                'completed_since': 'now',
                'opt_fields': 'name,due_on,permalink_url,projects.name,assignee.gid',
                'limit': 100,
            })
        except urllib.error.HTTPError as e:
            body = ''
            try:
                body = e.read().decode('utf-8', errors='replace')[:500]
            except Exception:
                pass
            logger.warning(
                'live action items: Asana /tasks fetch failed for %s (account=%s): HTTP %s %s',
                gid, ap.get('account_name'), e.code, body,
            )
            continue
        except (urllib.error.URLError, json.JSONDecodeError) as e:
            logger.warning(
                'live action items: Asana /tasks fetch failed for %s (account=%s): %s',
                gid, ap.get('account_name'), e,
            )
            continue
        fetched = data.get('data', [])
        mine = [
            t for t in fetched
            if t.get('assignee') is None or (t.get('assignee') or {}).get('gid') == me_gid
        ]
        logger.info(
            'live action items: %s (account=%s) returned %d task(s), %d mine or unassigned',
            gid, ap.get('account_name'), len(fetched), len(mine),
        )
        for task in mine:
            task_gid = task.get('gid')
            if not task_gid or task_gid in seen_gids:
                continue
            seen_gids.add(task_gid)
            projects = task.get('projects') or []
            project_name = ', '.join(p['name'] for p in projects if p.get('name')) or None
            items.append({
                'item_key': f'{ASANA_ACTION_ITEM_PREFIX}{task_gid}',
                'title': task.get('name') or '(untitled task)',
                'subtitle': None,
                'badge': None if task.get('assignee') else {'label': 'unassigned', 'class': 'bwarn'},
                'links': [{
                    'label': 'Open in Asana',
                    'url': task.get('permalink_url') or f'https://app.asana.com/0/0/{task_gid}/f',
                    'class': 'lbtn',
                }],
                'content': {
                    'due_on': task.get('due_on'),
                    'is_new': False,
                    'project_name': project_name,
                },
                'checked': False,
            })
    return items


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

    groups = [
        {**s, 'items': buckets[s['slug']]}
        for s in ACTION_SUBSECTIONS
        if buckets[s['slug']]
    ]

    # No Due Date is further split by board (Asana project name) so a
    # long backlog doesn't read as one undifferentiated pile — a person
    # scanning for "what's sitting in the Wells Fargo board" shouldn't
    # have to read every title to find it. "My Tasks" (content.project_name
    # is null — no configured project GID for that account, or a
    # non-Asana action item) sorts last since it's the catch-all, not a
    # named board a person is likely scanning for specifically. Item order
    # within each board is preserved from the incoming list (display_order
    # for New-Item-shaped rows, upstream ordering for live-pulled ones).
    for group in groups:
        if group['slug'] != 'no-due-date':
            continue
        boards = {}
        for item in group['items']:
            board_name = (item.get('content') or {}).get('project_name') or 'My Tasks'
            boards.setdefault(board_name, []).append(item)
        group['boards'] = [
            {'name': name, 'items': boards[name]}
            for name in sorted(boards, key=lambda n: (n == 'My Tasks', n))
        ]

    return groups


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

AZURE_AUTHORITY = f'https://login.microsoftonline.com/{AZURE_TENANT_ID}'
GRAPH_SCOPES = []  # no Graph calls made — sign-in identity only, nothing to scope

app = Flask(__name__)

logger = logging.getLogger(__name__)
if not logger.handlers:
    # Gunicorn doesn't attach a handler to arbitrary module loggers by
    # default, only to its own 'gunicorn.error'/'gunicorn.access' loggers —
    # without this, logger.info/.warning calls below silently go nowhere
    # even though the process is otherwise logging fine. This mirrors them
    # into gunicorn's own handlers so they land in the same stdout stream
    # `kubectl logs` already shows, instead of requiring a separate log
    # sink or config just for this module.
    gunicorn_logger = logging.getLogger('gunicorn.error')
    logger.handlers = gunicorn_logger.handlers
    logger.setLevel(gunicorn_logger.level or logging.INFO)
app.secret_key = FLASK_SECRET_KEY
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PREFERRED_URL_SCHEME='https',
    # Both this app and the parent dashboard app live on dashboard.es-sandbox.com.
    # Flask's cookie default name ("session") is identical for both, so without
    # overriding it here, whichever app sets its cookie last wins — the other
    # app's session gets silently clobbered. That produced a login loop: this
    # app's session would be overwritten right after auth_callback set it, so
    # login_required immediately treated the user as signed out again and
    # bounced back to /login. A distinct cookie name alone is what keeps the
    # two cookies from colliding (cookie identity is name+domain+path — a
    # unique name means no collision regardless of path).
    #
    # Deliberately NOT also scoping SESSION_COOKIE_PATH to this app's mount
    # point (as a prior revision did): this app is path-prefix-aware (see
    # ForcePrefixMiddleware below) and the actual ingress prefix is subject to
    # change across deployments (v1 is /daily-brief, v2 rolls out at
    # /daily-brief-v2 per the migration plan) -- hardcoding today's prefix into
    # the cookie's Path would silently break session recognition the moment
    # that prefix changes, or whenever a request is exercised directly against
    # this app's own root (e.g. via the test client, or a port-forward) rather
    # than through the reverse proxy at that exact sub-path. Leaving Path at
    # Flask's default ('/') costs nothing given the name is already unique.
    SESSION_COOKIE_NAME='daily_brief_session',
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
    '/daily-brief-v2',
)
app.teardown_appcontext(db_tokens.close_conn)


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
        if request.endpoint not in ('google_login', 'google_callback', 'logout') and not db_tokens.get_google_tokens(user['id']):
            session['post_google_link_redirect'] = request.script_root + request.path
            return redirect(url_for('google_login'))
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


def _drive_context():
    """Every brief-reading/writing route needs both the caller's valid Drive
    access token and their linked brief_data_folder_id. Centralizing the
    lookup here means a route body reads exactly like its db.py-backed
    predecessor, just swapping db.X(user_id, ...) for
    drive_store.X(access_token, folder_id, ...)."""
    user = db_tokens.get_user(request.brief_user['id'])
    if not user or not user['brief_data_folder_id']:
        abort(400, 'No Google Drive folder linked yet — visit the Account panel to link one.')
    access_token = google_oauth.get_valid_access_token(request.brief_user['id'])
    return access_token, user['brief_data_folder_id']


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
    user_row = db_tokens.get_or_create_user(claims.get('oid'), email)
    session['user'] = {
        'email': email,
        'name': claims.get('name', email),
        'oid': claims.get('oid'),
        'slug': slug,
        # Entra's own object id is now the primary key everywhere (token_store,
        # Drive folder linkage) -- simpler than db.py's separate auto-increment
        # id, since Entra already hands us a stable, globally-unique identifier.
        'id': claims.get('oid'),
    }

    dest = session.pop('post_login_redirect', None) or url_for('index')
    return redirect(dest)


@app.route('/auth/google/login')
@login_required
def google_login():
    state = secrets.token_urlsafe(24)
    session['google_oauth_state'] = state
    return redirect(google_oauth.get_authorization_url(state))


@app.route('/auth/google/callback')
@login_required
def google_callback():
    expected_state = session.pop('google_oauth_state', None)
    if not expected_state or request.args.get('state') != expected_state:
        abort(400, 'Invalid or missing OAuth state for the Google consent step.')
    if 'error' in request.args:
        abort(401, request.args.get('error_description', 'Google sign-in failed.'))
    code = request.args.get('code')
    if not code:
        abort(400, 'No authorization code returned from Google.')

    tokens = google_oauth.exchange_code_for_tokens(code)
    # set_google_tokens is an UPDATE keyed on entra_object_id -- it silently
    # affects zero rows if this user's row doesn't exist yet. auth_callback
    # already calls get_or_create_user on every Entra sign-in, so in the
    # normal flow the row is always there by the time a person reaches this
    # step; this call is a cheap, idempotent safety net against that
    # ordering assumption rather than something expected to do real work.
    db_tokens.get_or_create_user(request.brief_user['id'], request.brief_user['email'])
    db_tokens.set_google_tokens(
        request.brief_user['id'], tokens['access_token'], tokens['refresh_token'], tokens['expiry'],
    )
    dest = session.pop('post_google_link_redirect', None) or url_for('index')
    return redirect(dest)


@app.errorhandler(google_oauth.GoogleAuthRequired)
def handle_google_auth_required(error):
    """google_oauth.get_valid_access_token (via _drive_context) and
    exchange_code_for_tokens (via google_callback) both raise this when a
    user's stored Google refresh token is missing or a refresh grant fails
    -- e.g. they revoked access at myaccount.google.com. Without this
    handler, every brief-related route would 500 for that user instead of
    sending them back through the Google consent flow to re-link.

    Sets post_google_link_redirect the same way login_required's own
    not-yet-linked branch does, so re-consenting returns the user to the
    page they were on rather than always landing on index."""
    session['post_google_link_redirect'] = request.script_root + request.path
    session.pop('google_oauth_state', None)
    return redirect(url_for('google_login'))


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
    user = db_tokens.get_user(request.brief_user['id'])
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
    db_tokens.mark_onboarding_complete(request.brief_user['id'])
    return jsonify({'status': 'ok'})


@app.route('/api/client-config')
@login_required
def api_client_config():
    """Values the setup walkthrough and Account panel need. request.host_url
    isn't reliable to derive client-side since this app is deployed at a
    sub-path (see ForcePrefixMiddleware's docstring)."""
    return jsonify({
        'api_base_url': request.host_url.rstrip('/') + request.script_root,
    })


@app.route('/api/asana-pat')
@login_required
def api_asana_pat_status():
    """Presence check only — the PAT itself is never sent back to the
    browser once saved, unlike the daily-brief api_token above. It's a
    third-party credential with write access to the person's own Asana
    account, not something this app minted, so there's less reason to
    ever need to re-display it and more reason not to."""
    pat = db_tokens.get_asana_pat(request.brief_user['id'])
    return jsonify({'configured': bool(pat)})


@app.route('/api/asana-pat', methods=['POST'])
@login_required
def api_asana_pat_save():
    """
    Saves (or replaces) the signed-in user's Asana PAT — called from both
    the setup walkthrough and the Account panel. Validates against Asana's
    own /users/me before saving, so a typo'd or already-revoked token is
    caught immediately with a clear error rather than failing silently on
    the next brief's live pull. Enabling this is what turns on the Overdue
    / Due Next 7 Days / No Due Date Action Items subsections; skipping it
    (or never calling this) leaves only New Items showing.
    """
    body = request.get_json(silent=True) or {}
    pat = (body.get('pat') or '').strip()
    if not pat:
        abort(400, 'pat is required')
    asana_user = _validate_asana_pat(pat)
    if asana_user is None:
        abort(400, 'Could not validate this token against Asana — check that it was copied correctly and hasn\'t been revoked.')
    db_tokens.set_asana_pat(request.brief_user['id'], pat)
    return jsonify({'status': 'ok', 'asana_user': asana_user})


@app.route('/api/asana-pat', methods=['DELETE'])
@login_required
def api_asana_pat_clear():
    """Disconnects Asana — same effect as skipping it during setup. Turns
    off the live pull and the two-way checkbox/due-date sync immediately;
    New Items keeps working as before since that path doesn't need a PAT
    to read (though creating/completing tasks in Asana itself still needs
    the skill's own Asana connector, unrelated to this webapp-side PAT)."""
    db_tokens.clear_asana_pat(request.brief_user['id'])
    return jsonify({'status': 'ok'})


@app.route('/api/drive-folder')
@login_required
def api_drive_folder_status():
    user = db_tokens.get_user(request.brief_user['id'])
    return jsonify({'folder_id': user['brief_data_folder_id'] if user else None})


@app.route('/api/drive-folder', methods=['POST'])
@login_required
def api_drive_folder_save():
    body = request.get_json(silent=True) or {}
    folder_id = (body.get('folder_id') or '').strip()
    if not folder_id:
        abort(400, 'folder_id is required')
    db_tokens.set_brief_data_folder_id(request.brief_user['id'], folder_id)
    return jsonify({'status': 'ok'})


@app.route('/admin')
@login_required
@admin_required
def admin_page():
    return render_template('admin.html', admin_email=request.brief_user['email'])


@app.route('/api/admin/users')
@login_required
@admin_required
def admin_list_users():
    # Drive-era admin panel shows registered users only -- no brief_count/
    # last_active_at columns, since computing those now means listing every
    # user's Drive folder on every admin page load rather than one indexed
    # Postgres query. Deliberately dropped rather than reimplemented at that
    # cost; revisit if the admin panel's user list needs it back.
    return jsonify(db_tokens.list_users())


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
        'users_with_asana_pat': db_tokens.count_users_with_asana_pat(),
    })


@app.route('/api/briefs')
@login_required
def api_briefs():
    access_token, folder_id = _drive_context()
    days = drive_store.list_active_briefs(access_token, folder_id)
    # 'name' and 'label' are what the existing viewer JS actually reads
    # (see daily-brief-viewer.html) — everything else from the old
    # file-listing response (size, mtime) was never used by the frontend,
    # so it's fine that a DB row doesn't have a natural equivalent for them.
    return jsonify([{'name': d['brief_date'], 'label': d['brief_date']} for d in days])


@app.route('/brief/<date_str>')
@login_required
def serve_brief(date_str):
    if not DATE_RE.match(date_str):
        abort(400)
    access_token, folder_id = _drive_context()
    brief_day = drive_store.get_brief_day(access_token, folder_id, date_str)
    if not brief_day:
        abort(404)

    items = drive_store.get_items_for_day(access_token, folder_id, date_str)
    items_by_section = {}
    checkable_count = 0
    for item in items:
        items_by_section.setdefault(item['section'], []).append(item)
        if item['item_type'] in ('checkable', 'fyi') and item['checked'] is not None:
            checkable_count += 1

    # Action Items renders as four fixed subsections (New Items, Overdue,
    # Due Next 7 Days, No Due Date) rather than one flat list. New Items is
    # the only one tracked in Postgres (the skill only upserts action-items
    # rows where content.is_new is true — see references/item-sync.md). The
    # other three are pulled live from Asana on every page render if the
    # signed-in user has an asana_pat configured; if not, they're omitted
    # entirely and only whatever's in Postgres (New Items, plus any stale
    # pre-migration rows from before the skill stopped syncing the rest)
    # renders. "Today" here means the server's own local date; brief_date
    # is the brief's date, which isn't necessarily the same day the person
    # is viewing it on an evening/late run, so we deliberately use
    # wall-clock today for the overdue/due-soon cutoffs rather than
    # brief_date.
    today_iso = date.today().isoformat()
    postgres_action_items = items_by_section.get('action-items', [])
    asana_pat = db_tokens.get_asana_pat(request.brief_user['id'])

    if asana_pat:
        account_projects = drive_store.get_account_projects(access_token, folder_id)
        exclude_gids = {
            it['item_key'][len(ASANA_ACTION_ITEM_PREFIX):]
            for it in postgres_action_items
            if it['item_key'].startswith(ASANA_ACTION_ITEM_PREFIX)
        }
        if not account_projects:
            logger.warning(
                'live action items: user=%s has an asana_pat configured but zero rows in '
                'account_projects — the skill\'s daily_brief_sync_account_projects call may '
                'never have run for this user, or ran against a different user_id',
                request.brief_user['email'],
            )
        live_items = _fetch_live_action_items(asana_pat, account_projects, exclude_gids)
        logger.info(
            'live action items: user=%s account_projects=%d live_items=%d',
            request.brief_user['email'], len(account_projects), len(live_items),
        )
        action_subsections = _group_action_items(postgres_action_items + live_items, today_iso)
    else:
        logger.info(
            'live action items: user=%s has no asana_pat configured, skipping live pull',
            request.brief_user['email'],
        )
        # No Asana connection for this user — only ever show items this
        # brief run itself created and synced to Postgres, never any
        # stale non-new rows a pre-migration skill run may have left
        # behind (those would otherwise show up here as an inconsistent,
        # un-refreshable "Overdue"/"Due Soon" section with no live source).
        new_only = [it for it in postgres_action_items if (it.get('content') or {}).get('is_new')]
        action_subsections = _group_action_items(new_only, today_iso)

    # Count actually displayed, not raw Postgres row counts, for Action
    # Items — the two now diverge on purpose (stale non-new rows get
    # filtered out with no asana_pat; live-pulled items get added in with
    # one). Every other section still has count == what's in Postgres, so
    # only Action Items needs the override.
    action_items_displayed = sum(len(g['items']) for g in action_subsections)

    # '%-d' (day of month, no leading zero) is a glibc/macOS libc strftime
    # extension, not part of the C89 standard '%d' set -- Windows' C runtime
    # raises ValueError('Invalid format string') on it. Building the no-
    # leading-zero day with plain int formatting instead of '%-d' keeps the
    # exact same rendered label ("Tuesday, July 21") on every platform this
    # runs on, whether that's a Windows dev box or the Linux gunicorn
    # deployment.
    brief_date_obj = date.fromisoformat(brief_day['brief_date'])
    brief_date_label = f"{brief_date_obj.strftime('%A, %B')} {brief_date_obj.day}"

    sections = []
    for s in SECTIONS:
        section_items = items_by_section.get(s['slug'], [])
        if s['slug'] == 'action-items':
            count_label = f'{action_items_displayed} items'
        else:
            count_label = _count_label(s['slug'], section_items)
        sections.append({**s, 'count_label': count_label})

    return render_template(
        'brief_fragment.html',
        brief_date=date_str,
        brief_date_label=brief_date_label,
        brief_type=brief_day['brief_type'],
        checkable_count=checkable_count,
        sections=sections,
        items_by_section=items_by_section,
        action_subsections=action_subsections,
        asana_pat_configured=bool(asana_pat),
        today_iso=today_iso,
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
    body = request.get_json(silent=True) or {}
    if 'checked' not in body:
        abort(400, 'checked (bool) is required')
    checked = bool(body['checked'])

    access_token, folder_id = _drive_context()
    brief_day = drive_store.get_brief_day(access_token, folder_id, date_str)
    if not brief_day:
        abort(404)
    drive_store.set_item_checked(access_token, folder_id, date_str, section, item_key, checked)

    pat = db_tokens.get_asana_pat(request.brief_user['id'])
    attempted, ok = _sync_asana_completed(pat, item_key, checked)
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
    body = request.get_json(silent=True) or {}
    if 'due_on' not in body:
        abort(400, 'due_on (YYYY-MM-DD or null) is required')
    due_on = body['due_on']
    if due_on is not None and not DATE_RE.match(due_on):
        abort(400, 'due_on must be YYYY-MM-DD or null')

    access_token, folder_id = _drive_context()
    brief_day = drive_store.get_brief_day(access_token, folder_id, date_str)
    if not brief_day:
        abort(404)
    drive_store.set_item_due_date(access_token, folder_id, date_str, section, item_key, due_on)

    pat = db_tokens.get_asana_pat(request.brief_user['id'])
    attempted, ok = _sync_asana_due_date(pat, item_key, due_on)
    result = {'status': 'ok'}
    if attempted:
        result['asana_synced'] = ok
    return jsonify(result)


@app.route('/healthz')
def healthz():
    # Unauthenticated on purpose — process-liveness only, deliberately does
    # NOT check the token store. A transient SQLite/disk blip shouldn't cause
    # Kubernetes to kill and restart this pod; restarting doesn't fix a
    # storage problem, it just adds a second failure on top of the first.
    # Use /readyz (below) for anything that should depend on token store
    # connectivity.
    return 'ok', 200


@app.route('/readyz')
def readyz():
    """Kubernetes readiness probe: confirms the token_store SQLite file is
    reachable, so a pod that can't read/write it stops receiving traffic
    without being killed and restarted (that's /healthz's job instead)."""
    try:
        with db_tokens.cursor() as cur:
            cur.execute('SELECT 1')
    except Exception as e:
        return f'token store unavailable: {e}', 503
    return 'ok', 200


if __name__ == '__main__':
    # Local dev only. In production this runs under gunicorn behind nginx —
    # see DEPLOYMENT.md and gunicorn.conf.py.
    app.run(host='127.0.0.1', port=int(os.environ.get('PORT', 8000)), debug=False)
