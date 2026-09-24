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
same host, reachable at a sub-path (e.g. dashboard.es-sandbox.com/daily-brief-v2/)
via an nginx-ingress Ingress rather than at a domain root. See
k8s/ingress.yaml and DEPLOYMENT.md for the reverse-proxy config this depends
on (X-Forwarded-Prefix, X-Forwarded-Proto).

Per-user data isolation: each signed-in user's brief days and items are
scoped to their own row in Postgres by user_id — every query filters on the
current session's verified identity, never anything client-supplied. See
db.py and db/README.md for the storage model.
"""
import hmac
import json
import logging
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from functools import wraps
from pathlib import Path

import msal
from flask import Flask, Response, abort, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from markupsafe import Markup, escape
from werkzeug.middleware.proxy_fix import ProxyFix

import asana_discovery
import db
import gdrive_briefs
from action_items import group_action_items

APP_DIR = Path(__file__).resolve().parent
# In the VM deployment, app.py lives at viewer/webapp/app.py and the shared
# daily-brief-viewer.html sits one level up at viewer/. The container image
# flattens both into /app/ directly (see Dockerfile), so this is overridable
# rather than hardcoded to the VM's directory nesting.
VIEWER_HTML_DIR = Path(os.environ.get('VIEWER_HTML_DIR', str(APP_DIR.parent)))

DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')

# Matches standard Jira ticket keys: 2+ uppercase letters, a dash, then one or
# more digits (e.g. SUPPORT-33741, CAM-12345, OPT-678). Used by the
# autolink_jira template filter below.
JIRA_TICKET_RE = re.compile(r'\b([A-Z]{2,}-\d+)\b')

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

SLACK_API_BASE = 'https://slack.com/api'

# Verify this against a real GET /portfolios/{gid}/items call before
# relying on it — see the Environments tab design spec's "Customer list
# scope" section. One project per customer in this portfolio; a customer
# is in scope if their account_name matches a project name in it.
ENVIRONMENTS_PORTFOLIO_GID = os.environ.get('ASANA_ENVIRONMENTS_PORTFOLIO_GID', '1209916881329688')


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


def _post_to_slack(channel_id: str, text: str):
    """
    Posts a message to Slack via chat.postMessage, authenticated as the
    workspace's shared bot (SLACK_BOT_TOKEN) rather than the signed-in user.
    Slack's API returns HTTP 200 even for a rejected call (e.g. the bot
    isn't in a private channel, or the channel id is wrong), so success is
    read from the JSON body's "ok" field, not the status code. Returns
    (ok, error) — error is None on success, otherwise Slack's own error
    code, or 'request_failed' if the HTTP call itself didn't complete.
    """
    req = urllib.request.Request(
        f'{SLACK_API_BASE}/chat.postMessage',
        data=json.dumps({'channel': channel_id, 'text': text}).encode('utf-8'),
        method='POST',
        headers={
            'Authorization': f'Bearer {SLACK_BOT_TOKEN}',
            'Content-Type': 'application/json; charset=utf-8',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        logger.warning('Slack chat.postMessage request failed: %s', e)
        return False, 'request_failed'
    if not data.get('ok'):
        return False, data.get('error', 'unknown_error')
    return True, None


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
    Pulls open tasks directly from Asana as the union of two sources,
    excluding any task GID already tracked in Postgres as a New Item (see
    references/item-sync.md in the skill repo — only newly-created tasks
    are upserted there now). Returns a flat list of item dicts shaped like
    the skill's own action-items rows, so _group_action_items can bucket
    them exactly the same way it already does for New Items.

    1. Every open task in each project GID in account_projects (already
       filtered to primary-tier accounts by
       gdrive_briefs.get_account_projects — secondary accounts never reach
       this function). Assignee is irrelevant here: a primary account's
       board is fully in scope, whoever a given task happens to be
       assigned to.
    2. Every open task assigned to the signed-in user anywhere in their
       Asana workspace, regardless of project. This is what surfaces the
       person's own work even when it lives on a secondary-account board
       or a project with no account-config mapping at all.

    A task can land in both sources (e.g. a primary-account task assigned
    to the signed-in user) — de-duplicated by GID via seen_gids, first
    source wins.

    Asana's /tasks endpoint rejects a query that specifies both `project`
    and `assignee` — its own API error is "Must specify exactly one of
    project, tag, section, user task list, or assignee + workspace". So
    source 1 queries by `project` alone and source 2 by `assignee` +
    `workspace` — two separate calls rather than one filtered call.
    `completed_since=now` on both queries limits results to incomplete
    tasks.

    Best-effort per project/query: one project's fetch failing (bad GID,
    Asana outage, rate limit) doesn't block the others — it's just logged
    and skipped, since there's no per-item place in this flat list to
    surface a project-level error.
    """
    try:
        me = _asana_api_get(pat, '/users/me', {'opt_fields': 'gid,workspaces.gid'})
        me_data = me.get('data', {})
        me_gid = me_data.get('gid')
        workspaces = me_data.get('workspaces') or []
        workspace_gid = workspaces[0].get('gid') if workspaces else None
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        logger.warning('live action items: could not resolve Asana user gid, aborting pull: %s', e)
        return []
    if not me_gid:
        logger.warning('live action items: /users/me returned no gid, aborting pull')
        return []

    items = []
    seen_gids = set(exclude_gids)

    def _add_task(task):
        task_gid = task.get('gid')
        if not task_gid or task_gid in seen_gids:
            return
        seen_gids.add(task_gid)
        projects = task.get('projects') or []
        project_name = ', '.join(p['name'] for p in projects if p.get('name')) or None
        assignee = task.get('assignee') or {}
        if not assignee:
            badge = {'label': 'unassigned', 'class': 'bwarn'}
        elif assignee.get('gid') != me_gid:
            badge = {'label': f"assigned to {assignee.get('name')}" if assignee.get('name') else 'assigned to someone else', 'class': 'bwarn'}
        else:
            badge = None
        items.append({
            'item_key': f'{ASANA_ACTION_ITEM_PREFIX}{task_gid}',
            'title': task.get('name') or '(untitled task)',
            'subtitle': None,
            'badge': badge,
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

    opt_fields = 'name,due_on,permalink_url,projects.name,assignee.gid,assignee.name'

    # Source 1: every open task in each primary-tier account project.
    for ap in account_projects:
        gid = ap['project_gid']
        try:
            data = _asana_api_get(pat, '/tasks', {
                'project': gid,
                'completed_since': 'now',
                'opt_fields': opt_fields,
                'limit': 100,
            })
        except urllib.error.HTTPError as e:
            body = ''
            try:
                body = e.read().decode('utf-8', errors='replace')[:500]
            except Exception:
                pass
            logger.warning(
                'live action items: Asana /tasks fetch failed for project %s (account=%s): HTTP %s %s',
                gid, ap.get('account_name'), e.code, body,
            )
            continue
        except (urllib.error.URLError, json.JSONDecodeError) as e:
            logger.warning(
                'live action items: Asana /tasks fetch failed for project %s (account=%s): %s',
                gid, ap.get('account_name'), e,
            )
            continue
        fetched = data.get('data', [])
        logger.info(
            'live action items: project %s (account=%s) returned %d task(s)',
            gid, ap.get('account_name'), len(fetched),
        )
        for task in fetched:
            _add_task(task)

    # Source 2: every open task assigned to the signed-in user, regardless of project.
    if workspace_gid:
        try:
            data = _asana_api_get(pat, '/tasks', {
                'assignee': me_gid,
                'workspace': workspace_gid,
                'completed_since': 'now',
                'opt_fields': opt_fields,
                'limit': 100,
            })
            fetched = data.get('data', [])
            logger.info('live action items: assignee=me across workspace returned %d task(s)', len(fetched))
            for task in fetched:
                _add_task(task)
        except urllib.error.HTTPError as e:
            body = ''
            try:
                body = e.read().decode('utf-8', errors='replace')[:500]
            except Exception:
                pass
            logger.warning('live action items: Asana /tasks assignee=me fetch failed: HTTP %s %s', e.code, body)
        except (urllib.error.URLError, json.JSONDecodeError) as e:
            logger.warning('live action items: Asana /tasks assignee=me fetch failed: %s', e)
    else:
        logger.warning('live action items: no workspace gid resolved on /users/me, skipping assignee=me pull')

    return items



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
# Optional — if set, read briefs from Google Drive instead of database
GOOGLE_DRIVE_BRIEFS_FOLDER_ID = os.environ.get('GOOGLE_DRIVE_BRIEFS_FOLDER_ID')
# If DATABASE_URL is not set, operate in read-only mode from Google Drive
DATABASE_URL = os.environ.get('DATABASE_URL')
# Full callback URL Azure AD redirects back to, e.g.
# https://dashboard.es-sandbox.com/daily-brief-v2/auth/callback — must exactly
# match a Redirect URI registered on the app registration in the Portal.
AZURE_REDIRECT_URI = _require_env('AZURE_REDIRECT_URI')

# Google Drive OAuth credentials (from secrets, optional)
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')

# Bot User OAuth Token (xoxb-...) for the workspace's shared Slack app —
# lets Post to Slack/Post to Manager call chat.postMessage directly instead
# of just deep-linking into the Slack client. One token for the whole app,
# not per-user: messages post as the app's bot identity, not as whoever
# clicked the button. Optional — if unset, api_post_item_to_slack below
# 503s instead of the app failing to start, since this is an add-on feature
# rather than something the rest of the app depends on.
SLACK_BOT_TOKEN = os.environ.get('SLACK_BOT_TOKEN')

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

# Optional, inactive unless set — enables the shared cross-app SSO cookie
# (see db.create_sso_session) so another app on the same host can recognize
# a signed-in user via /internal/sso/verify. Leave both unset to run this
# app standalone with no cross-app coupling (e.g. local dev): no cookie is
# set, and the verify endpoint always 404s. Domain must NOT be path-scoped
# — it needs to reach every path on the host, not just this app's own
# /daily-brief-v2 mount point, unlike SESSION_COOKIE_PATH above.
SSO_COOKIE_DOMAIN = os.environ.get('SSO_COOKIE_DOMAIN', '').strip() or None
SSO_COOKIE_NAME = 'dashboard_sso'
# Shared secret the calling app must present (X-Internal-Auth header) to
# use /internal/sso/verify — this endpoint resolves an opaque token to a
# real identity, so it can't be left open to anyone who can reach the host.
INTERNAL_SSO_SECRET = os.environ.get('INTERNAL_SSO_SECRET', '').strip() or None

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
    # Flask's cookie defaults (name "session", path "/") are identical for both,
    # so without overriding them here, whichever app sets its cookie last wins —
    # the other app's session gets silently clobbered. That produced a login
    # loop: this app's session would be overwritten right after auth_callback
    # set it, so login_required immediately treated the user as signed out
    # again and bounced back to /login. Scoping both name and path to this
    # app's mount point keeps the two cookies distinct.
    SESSION_COOKIE_NAME='daily_brief_session',
    SESSION_COOKIE_PATH=os.environ.get('APP_PATH_PREFIX', '/daily-brief-v2'),
)

class ForcePrefixMiddleware:
    """Hardcodes SCRIPT_NAME instead of trusting X-Forwarded-Prefix.

    The plan was for nginx (via the ingress's proxy-set-headers annotation +
    the daily-brief-proxy-headers ConfigMap) to inject X-Forwarded-Prefix,
    and for ProxyFix(x_prefix=1) to turn that into SCRIPT_NAME so url_for()
    and login_required's redirect(url_for('login')) would come out as
    /daily-brief-v2/login. In practice that annotation is only a documented
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
_app_path_prefix = os.environ.get('APP_PATH_PREFIX', '/daily-brief-v2')
app.wsgi_app = ForcePrefixMiddleware(
    ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1),
    _app_path_prefix,
)
app.teardown_appcontext(db.close_conn)


JIRA_BASE_URL = os.environ.get('JIRA_BASE_URL', 'https://jira.camunda.com/browse').rstrip('/')


@app.template_filter('autolink_jira')
def autolink_jira(text):
    """Jinja2 filter: converts Jira ticket keys (e.g. SUPPORT-33741) in plain
    text into clickable links pointing at the configured Jira instance. The
    rest of the text is HTML-escaped first so this is safe to use with |safe
    in the template."""
    if not text:
        return text
    safe_text = str(escape(text))
    def _replace(m):
        key = m.group(1)
        return f'<a class="lbtn" href="{JIRA_BASE_URL}/{key}" target="_blank">{key}</a>'
    return Markup(JIRA_TICKET_RE.sub(_replace, safe_text))


@app.template_filter('resolve_link_url')
def resolve_link_url(url):
    """Jinja2 filter for link href values: if the URL is a bare Jira ticket
    key (e.g. 'SUPPORT-33741') rather than a full URL, prefix it with the
    Jira browse base so it doesn't resolve as a relative path against the
    current page. Full URLs (http://, https://, claude://) pass through
    unchanged."""
    if not url:
        return url
    if url.startswith(('http://', 'https://', 'claude://', '//', '/')):
        return url
    if JIRA_TICKET_RE.fullmatch(url):
        return f'{JIRA_BASE_URL}/{url}'
    return url


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
    
    # Validate that 'id' is an integer, not a UUID string (old session format).
    # If it's a UUID string, the session is stale — clear it and force re-login.
    user_id = u.get('id')
    if isinstance(user_id, str) and '-' in user_id:
        # Looks like a UUID (old format) — invalidate the session
        session.clear()
        return None
    
    return u


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            # request.path alone is the path AFTER nginx has already
            # stripped the /daily-brief-v2 prefix (that's the whole point of
            # the Ingress rewrite-target) — it's just "/" for the viewer's
            # root, with no prefix on it. request.script_root is where
            # ForcePrefixMiddleware put that prefix back (hardcoded, not
            # from a forwarded header — see its docstring). Unlike
            # url_for(), a plain redirect(dest) does NOT automatically
            # prepend script_root to a literal string — skipping this here
            # sent people back to the domain root after sign-in instead of
            # back under /daily-brief-v2.
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
    # the row, no admin step required.
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
    response = redirect(dest)
    if SSO_COOKIE_DOMAIN:
        sso_token = db.create_sso_session(user_row['id'])
        response.set_cookie(
            SSO_COOKIE_NAME, sso_token,
            domain=SSO_COOKIE_DOMAIN, path='/',
            secure=True, httponly=True, samesite='Lax',
            max_age=8 * 60 * 60,
        )
    return response


@app.route('/logout')
def logout():
    session.clear()
    sso_token = request.cookies.get(SSO_COOKIE_NAME)
    if sso_token:
        db.invalidate_sso_session(sso_token)
    # Also end the Azure AD session itself, not just this app's session —
    # otherwise a fresh /login silently re-signs the person in without a
    # prompt, which is surprising after clicking "logout."
    logout_url = (
        f'{AZURE_AUTHORITY}/oauth2/v2.0/logout'
        f'?post_logout_redirect_uri={url_for("index", _external=True)}'
    )
    response = redirect(logout_url)
    if SSO_COOKIE_DOMAIN:
        response.delete_cookie(SSO_COOKIE_NAME, domain=SSO_COOKIE_DOMAIN, path='/')
    return response


@app.route('/internal/sso/verify')
def internal_sso_verify():
    """Lets another app on the same host (the TAM Dashboard's Express proxy)
    resolve the shared SSO cookie to a real identity, without ever handing
    that app a Postgres connection of its own. Gated by a shared secret
    rather than login_required — the caller is a backend service, not a
    signed-in browser session reaching this route directly."""
    if not INTERNAL_SSO_SECRET:
        abort(404)
    presented = request.headers.get('X-Internal-Auth', '')
    if not hmac.compare_digest(presented, INTERNAL_SSO_SECRET):
        abort(403)
    token = request.args.get('token', '')
    user = db.get_user_by_sso_token(token) if token else None
    if not user:
        return jsonify({'authenticated': False})
    return jsonify({'authenticated': True, 'user': {
        'id': user['id'], 'email': user['email'], 'slug': user['slug'],
    }})


# ── Google Drive OAuth ────────────────────────────────────────────────────────

@app.route('/auth/google')
@login_required
def auth_google():
    """Initiate Google OAuth 2.0 flow for Drive access."""
    try:
        from google_auth_oauthlib.flow import Flow
    except ImportError:
        return 'Google OAuth library not available', 500
    
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return 'Google OAuth not configured', 500
    
    # Store the redirect URI
    redirect_uri = url_for('auth_google_callback', _external=True)
    
    # Create OAuth 2.0 flow with proper web app config
    flow = Flow.from_client_config(
        {
            'web': {
                'client_id': GOOGLE_CLIENT_ID,
                'client_secret': GOOGLE_CLIENT_SECRET,
                'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
                'token_uri': 'https://oauth2.googleapis.com/token',
                'redirect_uris': [redirect_uri],
            }
        },
        scopes=['https://www.googleapis.com/auth/drive'],
        redirect_uri=redirect_uri,
    )
    
    # Generate authorization URL
    auth_url, state = flow.authorization_url(access_type='offline', prompt='consent')
    session['google_oauth_state'] = state
    
    return redirect(auth_url)


@app.route('/auth/google/callback')
@login_required
def auth_google_callback():
    """Handle Google OAuth 2.0 callback."""
    try:
        from google_auth_oauthlib.flow import Flow
    except ImportError:
        return 'Google OAuth library not available', 500
    
    # Verify state
    state = request.args.get('state')
    if state != session.get('google_oauth_state'):
        return 'Invalid OAuth state', 400
    
    # Get authorization code
    code = request.args.get('code')
    if not code:
        error = request.args.get('error', 'unknown')
        return f'Google auth failed: {error}', 400
    
    try:
        # Create flow again with same config
        redirect_uri = url_for('auth_google_callback', _external=True)
        flow = Flow.from_client_config(
            {
                'web': {
                    'client_id': GOOGLE_CLIENT_ID,
                    'client_secret': GOOGLE_CLIENT_SECRET,
                    'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
                    'token_uri': 'https://oauth2.googleapis.com/token',
                    'redirect_uris': [redirect_uri],
                }
            },
            scopes=['https://www.googleapis.com/auth/drive'],
            redirect_uri=redirect_uri,
        )
        
        # Exchange code for token
        flow.fetch_token(authorization_response=request.url)
        credentials = flow.credentials
        refresh_token = credentials.refresh_token
        
        if not refresh_token:
            return 'No refresh token received from Google', 400
        
        # Store refresh token for this user
        if not db.set_google_refresh_token(request.brief_user['id'], refresh_token):
            return 'Failed to store Google token', 500
        
        logger.info(f'Stored Google refresh token for user {request.brief_user["email"]}')
        
        # Redirect back to index
        session.pop('google_oauth_state', None)
        return redirect(url_for('index'))
    
    except Exception as e:
        logger.error(f'Google OAuth callback failed: {e}', exc_info=True)
        return f'Google auth failed: {e}', 500


@app.route('/api/google-token/status')
@login_required
def google_token_status():
    """Check if user has connected Google Drive."""
    has_token = bool(db.get_google_refresh_token(request.brief_user['id']))
    return jsonify({'connected': has_token})


@app.route('/api/google-token', methods=['DELETE'])
@login_required
def delete_google_token():
    """Disconnect user's Google Drive."""
    try:
        if db.set_google_refresh_token(request.brief_user['id'], None):
            logger.info(f'Removed Google token for user {request.brief_user["email"]}')
            return jsonify({'success': True})
        else:
            return jsonify({'error': 'Failed to remove token'}), 500
    except Exception as e:
        logger.error(f'Failed to delete Google token: {e}', exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/google-drive/folder-id', methods=['GET'])
@login_required
def get_folder_id():
    """Get user's current Google Drive folder ID."""
    folder_id = db.get_google_drive_folder_id(request.brief_user['id'])
    return jsonify({'folder_id': folder_id})


@app.route('/api/google-drive/folder-id', methods=['POST'])
@login_required
def set_folder_id():
    """Set user's Google Drive folder ID."""
    data = request.get_json() or {}
    folder_id = data.get('folder_id')
    
    if not folder_id:
        return jsonify({'error': 'folder_id is required'}), 400
    
    try:
        if db.set_google_drive_folder_id(request.brief_user['id'], folder_id):
            logger.info(f'Set Google Drive folder ID for user {request.brief_user["email"]}')
            return jsonify({'success': True})
        else:
            return jsonify({'error': 'Failed to set folder ID'}), 500
    except Exception as e:
        logger.error(f'Failed to set folder ID: {e}', exc_info=True)
        return jsonify({'error': str(e)}), 500


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
    original = session.get('admin_original_user')
    response = {
        'name': request.brief_user['name'],
        'email': request.brief_user['email'],
        'onboarding_completed': bool(user and user['onboarding_completed_at']),
        'impersonating': bool(original),
        'is_admin': bool(ADMIN_EMAILS and request.brief_user['email'].lower() in ADMIN_EMAILS),
    }
    if original:
        response['real_admin_email'] = original['email']
    return jsonify(response)


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
    """Values the setup walkthrough needs to render correct copy-paste
    instructions, computed server-side rather than guessed from
    window.location (this app is deployed at a sub-path)."""
    return jsonify({
        # request.script_root is where ForcePrefixMiddleware put the
        # /daily-brief-v2 prefix back (see its docstring).
        'api_base_url': request.host_url.rstrip('/') + request.script_root,
    })


@app.route('/api/asana-pat')
@login_required
def api_asana_pat_status():
    """Presence check only — the PAT itself is never sent back to the
    browser once saved. It's a third-party credential with write access to
    the person's own Asana account, not something this app minted, so
    there's less reason to ever need to re-display it and more reason not
    to."""
    pat = db.get_asana_pat(request.brief_user['id'])
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
    db.set_asana_pat(request.brief_user['id'], pat)
    return jsonify({'status': 'ok', 'asana_user': asana_user})


@app.route('/api/asana-pat', methods=['DELETE'])
@login_required
def api_asana_pat_clear():
    """Disconnects Asana — same effect as skipping it during setup. Turns
    off the live pull and the two-way checkbox/due-date sync immediately;
    New Items keeps working as before since that path doesn't need a PAT
    to read (though creating/completing tasks in Asana itself still needs
    the skill's own Asana connector, unrelated to this webapp-side PAT)."""
    db.clear_asana_pat(request.brief_user['id'])
    return jsonify({'status': 'ok'})


@app.route('/api/notification-prefs')
@login_required
def api_notification_prefs():
    """Returns the signed-in user's Slack notification preferences, for
    the Account panel to pre-fill its notification settings form."""
    prefs = db.get_notification_prefs(request.brief_user['id'])
    return jsonify({
        'slack_notify_enabled': prefs.get('slack_notify_enabled', False),
        'slack_notify_channel_id': prefs.get('slack_notify_channel_id'),
    })


@app.route('/api/notification-prefs', methods=['PATCH'])
@login_required
def api_notification_prefs_update():
    """Saves the signed-in user's Slack notification preferences from the
    Account panel."""
    body = request.get_json(silent=True) or {}
    enabled = bool(body.get('slack_notify_enabled', False))
    channel_id = (body.get('slack_notify_channel_id') or '').strip() or None
    db.set_notification_prefs(request.brief_user['id'], enabled, channel_id)
    return jsonify({'status': 'ok'})


@app.route('/api/settings/missing-transcript-asana-task')
@login_required
def api_missing_transcript_asana_task_status():
    """Returns whether the skill should create an Asana task when it can't
    find a recording/transcript for a meeting (SKILL.md's Yesterday's
    Meetings checklist, item 4). Read from config.json on Drive — this is a
    skill behavior toggle, not a webapp-only preference, so it lives
    alongside the skill's other settings rather than in Postgres. Defaults
    to enabled (True) when the field has never been set, matching the
    skill's existing behavior before this toggle existed."""
    google_token = db.get_google_refresh_token(request.brief_user['id'])
    folder_id = db.get_google_drive_folder_id(request.brief_user['id'])
    if not google_token:
        return jsonify({'error': 'Google Drive not connected'}), 400
    config = gdrive_briefs.read_config(google_token, folder_id)
    if config is None:
        return jsonify({'error': 'Could not read config.json'}), 500
    return jsonify({
        'missing_transcript_asana_task_enabled': config.get('missing_transcript_asana_task_enabled', True),
    })


@app.route('/api/settings/missing-transcript-asana-task', methods=['PATCH'])
@login_required
def api_missing_transcript_asana_task_update():
    """Saves the missing-transcript Asana task toggle back to config.json."""
    google_token = db.get_google_refresh_token(request.brief_user['id'])
    folder_id = db.get_google_drive_folder_id(request.brief_user['id'])
    if not google_token:
        return jsonify({'error': 'Google Drive not connected'}), 400
    body = request.get_json(silent=True) or {}
    if 'missing_transcript_asana_task_enabled' not in body:
        return jsonify({'error': 'missing_transcript_asana_task_enabled (bool) is required'}), 400
    enabled = bool(body['missing_transcript_asana_task_enabled'])
    result = gdrive_briefs.write_config(
        {'missing_transcript_asana_task_enabled': enabled}, google_token, folder_id,
    )
    if result is not True:
        msg = result if isinstance(result, str) else 'Failed to write config.json'
        return jsonify({'error': msg}), 500
    return jsonify({'ok': True, 'missing_transcript_asana_task_enabled': enabled})


# ── Customer list management ─────────────────────────────────────────

@app.route('/customers')
@login_required
def customers_page():
    return render_template('customers.html', user_email=request.brief_user['email'])


@app.route('/api/customers/config')
@login_required
def api_customers_config():
    """Return the raw account-config.json for the management UI."""
    google_token = db.get_google_refresh_token(request.brief_user['id'])
    folder_id = db.get_google_drive_folder_id(request.brief_user['id'])
    if not google_token:
        return jsonify({'error': 'Google Drive not connected'}), 400
    config = gdrive_briefs.read_account_config(google_token, folder_id)
    if config is None:
        return jsonify({'error': 'Could not read account-config.json'}), 500
    return jsonify(config)


@app.route('/api/customers/config', methods=['PUT'])
@login_required
def api_customers_config_update():
    """Write updated account-config.json back to Drive."""
    google_token = db.get_google_refresh_token(request.brief_user['id'])
    folder_id = db.get_google_drive_folder_id(request.brief_user['id'])
    if not google_token:
        return jsonify({'error': 'Google Drive not connected'}), 400
    data = request.get_json(silent=True)
    if not data or 'accounts' not in data:
        return jsonify({'error': 'Invalid payload — must include accounts array'}), 400
    result = gdrive_briefs.write_account_config(data, google_token, folder_id)
    if result is not True:
        msg = result if isinstance(result, str) else 'Failed to write account-config.json'
        return jsonify({'error': msg}), 500
    return jsonify({'ok': True})


@app.route('/api/customers/discover-asana')
@login_required
def api_customers_discover_asana():
    """Returns Asana projects not yet linked to any account, for the
    Customers tab's "Scan for Accounts" button. Asana-only: this webapp
    has no Slack or Outlook access, so full multi-source discovery still
    only happens in the skill's own setup flow
    (references/first-run-setup.md)."""
    pat = db.get_asana_pat(request.brief_user['id'])
    if not pat:
        return jsonify({'error': 'No Asana PAT configured — add one from the Account panel first.'}), 400

    google_token = db.get_google_refresh_token(request.brief_user['id'])
    folder_id = db.get_google_drive_folder_id(request.brief_user['id'])
    if not google_token:
        return jsonify({'error': 'Google Drive not connected'}), 400
    config = gdrive_briefs.read_account_config(google_token, folder_id)
    if config is None:
        return jsonify({'error': 'Could not read account-config.json'}), 500

    linked_gids = {
        a.get('project_gid') for a in config.get('accounts', []) if a.get('project_gid')
    }
    if config.get('internal_project_gid'):
        linked_gids.add(config['internal_project_gid'])

    try:
        candidates = asana_discovery.find_new_projects(_asana_api_get, pat, linked_gids)
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        return jsonify({'error': f'Asana lookup failed: {e}'}), 502

    return jsonify({'candidates': candidates})


# ── Environments management ──────────────────────────────────────────

@app.route('/environments')
@login_required
def environments_page():
    return render_template('environments.html', user_email=request.brief_user['email'])


@app.route('/api/environments/config')
@login_required
def api_environments_config():
    """Returns saved environments-config.json data plus the current
    in-scope customer name list (from the Asana portfolio)."""
    google_token = db.get_google_refresh_token(request.brief_user['id'])
    folder_id = db.get_google_drive_folder_id(request.brief_user['id'])
    if not google_token:
        return jsonify({'error': 'Google Drive not connected'}), 400
    config = gdrive_briefs.read_environments_config(google_token, folder_id)
    if config is None:
        return jsonify({'error': 'Could not read environments-config.json'}), 500

    pat = db.get_asana_pat(request.brief_user['id'])
    if not pat:
        return jsonify({'customers': config, 'in_scope_names': None, 'needs_pat': True})

    try:
        in_scope_names = asana_discovery.get_portfolio_project_names(
            _asana_api_get, pat, ENVIRONMENTS_PORTFOLIO_GID,
        )
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        return jsonify({
            'customers': config, 'in_scope_names': None,
            'error': f'Could not load customer list from Asana: {e}',
        })

    return jsonify({'customers': config, 'in_scope_names': in_scope_names})


@app.route('/api/environments/config', methods=['PUT'])
@login_required
def api_environments_config_update():
    """Writes the full customers dict (teams + environments per customer)
    back to environments-config.json."""
    google_token = db.get_google_refresh_token(request.brief_user['id'])
    folder_id = db.get_google_drive_folder_id(request.brief_user['id'])
    if not google_token:
        return jsonify({'error': 'Google Drive not connected'}), 400
    data = request.get_json(silent=True)
    if not data or 'customers' not in data or not isinstance(data['customers'], dict):
        return jsonify({'error': 'Invalid payload — must include a customers object'}), 400
    result = gdrive_briefs.write_environments_config(data['customers'], google_token, folder_id)
    if result is not True:
        msg = result if isinstance(result, str) else 'Failed to write environments-config.json'
        return jsonify({'error': msg}), 500
    return jsonify({'ok': True})


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


@app.route('/api/admin/test-users', methods=['GET'])
@login_required
@admin_required
def admin_list_test_users():
    return jsonify(db.list_test_users())


@app.route('/api/admin/test-users', methods=['POST'])
@login_required
@admin_required
def admin_create_test_user():
    body = request.get_json(silent=True) or {}
    user = db.create_test_user(body.get('label'))
    return jsonify(user), 201


@app.route('/api/admin/test-users/<int:user_id>', methods=['DELETE'])
@login_required
@admin_required
def admin_delete_test_user(user_id):
    deleted = db.delete_test_user(user_id)
    if not deleted:
        abort(404, 'Not a test user, or already deleted.')
    return jsonify({'status': 'ok'})


@app.route('/api/admin/impersonate/<int:user_id>/start', methods=['POST'])
@login_required
@admin_required
def admin_impersonate_start(user_id):
    """Switches the current session to view as a throwaway test user.
    Guarded twice: @admin_required above, and the is_test check here — this
    route can never target a real user's account, even via a crafted ID."""
    if not db.is_test_user(user_id):
        abort(404, 'Can only impersonate a test user.')
    if session.get('admin_original_user'):
        abort(400, 'Already impersonating — stop first.')
    test_user = db.get_user_by_id(user_id)
    if not test_user:
        abort(404)
    session['admin_original_user'] = session['user']
    session['user'] = {
        'email': test_user['email'],
        'name': test_user['email'],
        'oid': f"test-{test_user['id']}",
        'slug': test_user['slug'],
        'id': test_user['id'],
    }
    return jsonify({'status': 'ok', 'email': test_user['email']})


@app.route('/api/admin/impersonate/stop', methods=['POST'])
@login_required
def admin_impersonate_stop():
    """Ends impersonation and restores the real admin's session. Not
    admin-gated: by construction only someone who started an impersonation
    can have admin_original_user set, and they must always be able to end
    it even if ADMIN_EMAILS changes mid-session."""
    original = session.pop('admin_original_user', None)
    if original:
        session['user'] = original
    return jsonify({'status': 'ok'})


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
        'users_with_asana_pat': db.count_users_with_asana_pat(),
    })


@app.route('/api/briefs')
@login_required
def api_briefs():
    # Get user's Google refresh token and folder ID from database
    google_token = db.get_google_refresh_token(request.brief_user['id'])
    folder_id = db.get_google_drive_folder_id(request.brief_user['id'])
    
    if not google_token:
        # User hasn't connected Google Drive yet
        return jsonify([])
    
    # List briefs from Google Drive using user's token and folder ID
    days = gdrive_briefs.list_available_briefs(google_token, folder_id)
    return jsonify([
        {'name': d, 'label': d}
        for d in days
    ])


@app.route('/brief/<date_str>')
@login_required
def serve_brief(date_str):
    if not DATE_RE.match(date_str):
        abort(400)

    t0 = time.monotonic()

    google_token = db.get_google_refresh_token(request.brief_user['id'])
    folder_id = db.get_google_drive_folder_id(request.brief_user['id'])

    if not google_token:
        abort(403)

    # Only read manifest + folder listing (no section file downloads).
    # Section content is loaded progressively via /api/brief/<date>/section/<slug>.
    meta = gdrive_briefs.read_brief_metadata(date_str, google_token, folder_id)
    t_meta = time.monotonic()

    if not meta:
        abort(404)

    asana_pat = db.get_asana_pat(request.brief_user['id'])
    available = set(meta.get('available_sections', []))

    sections = []
    for s in SECTIONS:
        if s['slug'] in available or s['slug'] == 'action-items':
            sections.append({**s, 'count_label': 'loading\u2026'})

    logger.info('serve_brief: date=%s meta=%.1fs sections=%d total=%.1fs',
                date_str, t_meta - t0, len(sections), time.monotonic() - t0)

    return render_template(
        'brief_fragment.html',
        brief_date=date_str,
        brief_date_label=date.fromisoformat(date_str).strftime('%A, %B %-d'),
        brief_type=meta.get('brief_type', 'default'),
        checkable_count=0,
        sections=sections,
        items_by_section={},
        action_subsections=[],
        asana_pat_configured=bool(asana_pat),
        today_iso=date.today().isoformat(),
        progressive=True,
    )


@app.route('/api/brief/<date_str>/live-action-items')
@login_required
def api_live_action_items(date_str):
    """Async endpoint called by the client after the action-items section
    renders. Does the Asana live pull, groups the results with the brief-file
    items, and returns rendered HTML for all action item subsections."""
    if not DATE_RE.match(date_str):
        abort(400)

    t0 = time.monotonic()
    asana_pat = db.get_asana_pat(request.brief_user['id'])
    if not asana_pat:
        return jsonify({'html': '', 'count': 0})

    today_iso = date.today().isoformat()

    # Read just the action-items section (not the entire brief) to build
    # the exclude list so New Items aren't duplicated in the live pull.
    google_token = db.get_google_refresh_token(request.brief_user['id'])
    folder_id = db.get_google_drive_folder_id(request.brief_user['id'])
    brief_action_items = []
    if google_token:
        brief_action_items = gdrive_briefs.read_section(
            date_str, 'action-items', google_token, folder_id,
        ) or []
    t_gdrive = time.monotonic()

    account_projects = (
        gdrive_briefs.get_account_projects(google_token, folder_id)
        if google_token
        else []
    )
    exclude_gids = {
        it['item_key'][len(ASANA_ACTION_ITEM_PREFIX):]
        for it in brief_action_items
        if it.get('item_key', '').startswith(ASANA_ACTION_ITEM_PREFIX)
    }
    live_items = _fetch_live_action_items(asana_pat, account_projects, exclude_gids)
    t_asana = time.monotonic()

    all_items = brief_action_items + live_items
    action_subsections = group_action_items(all_items, today_iso)
    total_count = sum(len(g['items']) for g in action_subsections)

    html = render_template(
        'action_items_fragment.html',
        action_subsections=action_subsections,
        asana_pat_configured=True,
        brief_date=date_str,
        today_iso=today_iso,
    )
    t_render = time.monotonic()

    logger.info(
        'api_live_action_items: date=%s gdrive=%.1fs asana=%.1fs render=%.1fs total=%.1fs items=%d',
        date_str, t_gdrive - t0, t_asana - t_gdrive, t_render - t_asana, t_render - t0, total_count,
    )
    return jsonify({'html': html, 'count': total_count})


@app.route('/tasks')
@login_required
def tasks_page():
    return render_template('tasks.html', user_email=request.brief_user['email'])


@app.route('/api/tasks')
@login_required
def api_tasks():
    """Standalone, cross-day view of every open Asana task relevant to the
    signed-in user — everything api_live_action_items pulls for one brief
    day, but with nothing excluded (there's no specific day's stored items
    to de-duplicate against here)."""
    asana_pat = db.get_asana_pat(request.brief_user['id'])
    if not asana_pat:
        html = render_template('tasks_fragment.html', action_subsections=[], asana_pat_configured=False)
        return jsonify({'html': html, 'count': 0, 'needs_pat': True})

    google_token = db.get_google_refresh_token(request.brief_user['id'])
    folder_id = db.get_google_drive_folder_id(request.brief_user['id'])
    account_projects = (
        gdrive_briefs.get_account_projects(google_token, folder_id)
        if google_token
        else []
    )
    live_items = _fetch_live_action_items(asana_pat, account_projects, set())
    today_iso = date.today().isoformat()
    action_subsections = group_action_items(live_items, today_iso)
    total_count = sum(len(g['items']) for g in action_subsections)

    html = render_template(
        'tasks_fragment.html', action_subsections=action_subsections,
        asana_pat_configured=True, today_iso=today_iso,
    )
    return jsonify({'html': html, 'count': total_count})


@app.route('/api/tasks/<item_key>/checked', methods=['PATCH'])
@login_required
def set_task_checked(item_key):
    """Marks an open task complete/incomplete directly in Asana. Unlike
    /api/items/<section>/<item_key>/checked, there's no Postgres row
    backing this up — these items are never persisted (see
    api_tasks/_fetch_live_action_items) — so a failed Asana write has
    nothing else to fall back on; the client surfaces asana_synced=false
    as an error rather than treating the checkbox as settled."""
    body = request.get_json(silent=True) or {}
    if 'checked' not in body:
        abort(400, 'checked (bool) is required')
    checked = bool(body['checked'])
    pat = db.get_asana_pat(request.brief_user['id'])
    attempted, ok = _sync_asana_completed(pat, item_key, checked)
    if not attempted:
        abort(404)
    return jsonify({'status': 'ok', 'asana_synced': ok})


@app.route('/api/tasks/<item_key>/due-date', methods=['PATCH'])
@login_required
def set_task_due_date(item_key):
    """Sets the due date on an open task directly in Asana. Same
    no-Postgres-row situation as set_task_checked above — these items are
    the live, unpersisted Asana pull (see api_tasks) — so this always
    writes straight to Asana rather than going through the brief's
    Postgres-backed /api/items/<section>/<item_key>/due-date route. Mirrors
    the Action Items due-date box: the four shortcut buttons and the raw
    date input both funnel through here."""
    body = request.get_json(silent=True) or {}
    if 'due_on' not in body:
        abort(400, 'due_on (YYYY-MM-DD or null) is required')
    due_on = body['due_on']
    if due_on is not None and not DATE_RE.match(due_on):
        abort(400, 'due_on must be YYYY-MM-DD or null')
    pat = db.get_asana_pat(request.brief_user['id'])
    attempted, ok = _sync_asana_due_date(pat, item_key, due_on)
    if not attempted:
        abort(404)
    return jsonify({'status': 'ok', 'asana_synced': ok})


@app.route('/api/brief/<date_str>/section/<slug>')
@login_required
def api_section(date_str, slug):
    """Returns pre-rendered HTML for a single brief section. Called by the
    client-side progressive loader which fires parallel fetches for each
    section, so sections appear on the page as their individual Drive
    downloads complete rather than waiting for all of them."""
    if not DATE_RE.match(date_str):
        abort(400)
    valid_slugs = {s['slug'] for s in SECTIONS}
    if slug not in valid_slugs:
        abort(404)

    t0 = time.monotonic()
    google_token = db.get_google_refresh_token(request.brief_user['id'])
    folder_id = db.get_google_drive_folder_id(request.brief_user['id'])
    if not google_token:
        return jsonify({'html': '', 'count': 0})

    items = gdrive_briefs.read_section(date_str, slug, google_token, folder_id) or []
    if slug == 'customer-updates':
        items.sort(key=lambda x: (x.get('title') or '').lower())
    t_read = time.monotonic()

    today_iso = date.today().isoformat()

    # Action Items gets special handling — the brief-file items render
    # immediately; the live Asana pull is a separate async call.
    if slug == 'action-items':
        asana_pat = db.get_asana_pat(request.brief_user['id'])
        new_only = [it for it in items if (it.get('content') or {}).get('is_new')]
        action_subsections = group_action_items(new_only, today_iso)
        html = render_template(
            'section_fragment.html',
            section_slug=slug,
            section_items=items,
            action_subsections=action_subsections,
            asana_pat_configured=bool(asana_pat),
            brief_date=date_str,
            today_iso=today_iso,
        )
        count = sum(len(g['items']) for g in action_subsections)
    else:
        html = render_template(
            'section_fragment.html',
            section_slug=slug,
            section_items=items,
            action_subsections=[],
            asana_pat_configured=False,
            brief_date=date_str,
            today_iso=today_iso,
        )
        count = len(items)

    elapsed = time.monotonic() - t0
    logger.info('api_section: date=%s slug=%s read=%.1fs total=%.1fs items=%d',
                date_str, slug, t_read - t0, elapsed, count)
    return jsonify({'html': html, 'count': count})


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
    pat = db.get_asana_pat(request.brief_user['id'])

    brief_day = db.get_brief_day(request.brief_user['id'], date_str)
    found = db.set_item_checked(brief_day['id'], section, item_key, checked) if brief_day else False

    if not found:
        # No Postgres row for this item — it's one of the live-pulled
        # Overdue/Due Next 7 Days/No Due Date items (see
        # _fetch_live_action_items), which are never persisted here.
        # Write straight to Asana instead of 404ing; these only ever
        # render when a pat is configured, so this should always be
        # attempted successfully unless the pat was just revoked.
        attempted, ok = _sync_asana_completed(pat, item_key, checked)
        if not attempted:
            abort(404)
        return jsonify({'status': 'ok', 'asana_synced': ok})

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
    pat = db.get_asana_pat(request.brief_user['id'])

    brief_day = db.get_brief_day(request.brief_user['id'], date_str)
    found = db.set_item_due_date(brief_day['id'], section, item_key, due_on) if brief_day else False

    if not found:
        # Same live-item fallback as set_item_checked above — no Postgres
        # row exists for this one, so write straight to Asana.
        attempted, ok = _sync_asana_due_date(pat, item_key, due_on)
        if not attempted:
            abort(404)
        return jsonify({'status': 'ok', 'asana_synced': ok})

    attempted, ok = _sync_asana_due_date(pat, item_key, due_on)
    result = {'status': 'ok'}
    if attempted:
        result['asana_synced'] = ok
    return jsonify(result)


@app.route('/api/items/<section>/<item_key>/post-to-slack', methods=['POST'])
@login_required
def post_item_to_slack(section, item_key):
    """
    Called by the Post to Slack / Post to Manager buttons. Posts whatever
    is currently in the item's textarea — including edits the person made
    but never saved anywhere, since this app doesn't persist that draft
    text server-side — to the given channel via chat.postMessage. channel_id
    and text both come from the request body (what's on screen right now),
    not looked up from Postgres, so an in-progress edit posts exactly what
    the person sees.
    """
    if not SLACK_BOT_TOKEN:
        # jsonify, not abort() — this route's whole contract is JSON
        # responses, and abort() renders Werkzeug's default HTML error page,
        # which breaks the frontend's response.json() call with a
        # confusing "Unexpected token '<'" parse error instead of the real
        # "not configured" message.
        return jsonify({'status': 'error', 'error': 'not_configured'}), 503
    body = request.get_json(silent=True) or {}
    channel_id = (body.get('channel_id') or '').strip()
    text = (body.get('text') or '').strip()
    if not channel_id:
        return jsonify({'status': 'error', 'error': 'channel_id is required'}), 400
    if not text:
        return jsonify({'status': 'error', 'error': 'text is required'}), 400

    ok, error = _post_to_slack(channel_id, text)
    if not ok:
        logger.warning('post_item_to_slack failed: section=%s item_key=%s error=%s', section, item_key, error)
        return jsonify({'status': 'error', 'error': error}), 502
    return jsonify({'status': 'ok'})


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
