"""
Google Drive-backed replacement for db.py. Reads brief content that the
daily-brief-v2 skill wrote via its own native Drive connector, and owns the
two things this webapp itself writes: per-item checked/due-date state and
retention cleanup -- both using the signed-in user's own OAuth access token
(full `drive` scope; see google_oauth.py), never a service account.

Every public function in this module takes access_token as an explicit
argument rather than fetching it itself, so callers (app.py) are the only
place that decides *whose* token is in play, and this module stays testable
without mocking OAuth at all.

Hand-rolled via urllib against the Drive v3 REST API, matching the existing
Asana-call style in app.py, rather than adding google-api-python-client as a
dependency.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
import uuid

DRIVE_API_BASE = 'https://www.googleapis.com/drive/v3'
DRIVE_UPLOAD_BASE = 'https://www.googleapis.com/upload/drive/v3'


class DriveApiError(Exception):
    """A Google Drive REST call returned an HTTP error status. Carries the
    status code, a short machine reason parsed from the response, and the raw
    body -- so callers can surface *why* Drive refused (insufficient
    permissions, API not enabled, folder not found) instead of letting the
    error collapse into an opaque 500 with no detail."""

    def __init__(self, status, reason, body):
        self.status = status
        self.reason = reason
        self.body = body
        super().__init__(f'Drive API {status}: {reason or (body[:200] if body else "")}')


def _extract_drive_reason(body):
    """Pull a short 'reason: message' string out of a Drive v3 JSON error
    body (shape: {"error": {"message": ..., "errors": [{"reason": ...}]}}).
    Returns '' if the body isn't the expected shape."""
    try:
        err = json.loads(body)['error']
        message = err.get('message', '')
        errors = err.get('errors') or []
        reason = errors[0].get('reason', '') if errors else ''
        return f'{reason}: {message}' if reason else message
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        return ''


def _drive_request(access_token, method, url, body_bytes=None, content_type=None):
    headers = {'Authorization': f'Bearer {access_token}'}
    if content_type:
        headers['Content-Type'] = content_type
    req = urllib.request.Request(url, data=body_bytes, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode('utf-8', 'replace')
        except Exception:
            body = ''
        raise DriveApiError(e.code, _extract_drive_reason(body), body) from e


def _list_children(access_token, parent_id, name=None):
    q = f"'{parent_id}' in parents and trashed = false"
    if name:
        q += f" and name = '{name}'"
    params = urllib.parse.urlencode({
        'q': q,
        'fields': 'files(id,name,createdTime)',
        'orderBy': 'createdTime desc',
        'pageSize': 100,
    })
    raw = _drive_request(access_token, 'GET', f'{DRIVE_API_BASE}/files?{params}')
    files = json.loads(raw.decode('utf-8')).get('files', [])
    # Sort by createdTime descending (newest first) to ensure consistent ordering
    return sorted(files, key=lambda f: f['createdTime'], reverse=True)


def _find_child(access_token, parent_id, name):
    matches = _list_children(access_token, parent_id, name=name)
    return matches[0] if matches else None


def _download_json(access_token, file_id):
    raw = _drive_request(access_token, 'GET', f'{DRIVE_API_BASE}/files/{file_id}?alt=media')
    return json.loads(raw.decode('utf-8'))


def _upload_json_update(access_token, file_id, content):
    body = json.dumps(content).encode('utf-8')
    _drive_request(
        access_token, 'PATCH', f'{DRIVE_UPLOAD_BASE}/files/{file_id}?uploadType=media',
        body_bytes=body, content_type='application/json',
    )


def _create_folder(access_token, parent_id, name):
    body = json.dumps({
        'name': name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [parent_id],
    }).encode('utf-8')
    raw = _drive_request(
        access_token, 'POST', f'{DRIVE_API_BASE}/files',
        body_bytes=body, content_type='application/json',
    )
    data = json.loads(raw.decode('utf-8'))
    return {'id': data['id'], 'name': data['name']}


def _create_json_file(access_token, parent_id, name, content):
    boundary = uuid.uuid4().hex
    metadata = json.dumps({'name': name, 'parents': [parent_id]})
    payload = (
        f'--{boundary}\r\n'
        'Content-Type: application/json; charset=UTF-8\r\n\r\n'
        f'{metadata}\r\n'
        f'--{boundary}\r\n'
        'Content-Type: application/json\r\n\r\n'
        f'{json.dumps(content)}\r\n'
        f'--{boundary}--'
    ).encode('utf-8')
    raw = _drive_request(
        access_token, 'POST', f'{DRIVE_UPLOAD_BASE}/files?uploadType=multipart',
        body_bytes=payload, content_type=f'multipart/related; boundary={boundary}',
    )
    data = json.loads(raw.decode('utf-8'))
    return {'id': data['id'], 'name': data['name']}


def _trash_file(access_token, file_id):
    body = json.dumps({'trashed': True}).encode('utf-8')
    _drive_request(
        access_token, 'PATCH', f'{DRIVE_API_BASE}/files/{file_id}',
        body_bytes=body, content_type='application/json',
    )


SECTION_FILES = [
    ('meetings.json', 'yesterday-meetings'),
    ('today.json', 'today'),
    ('action-items.json', 'action-items'),
    ('fyi.json', 'fyi'),
]
SECTION_SUBFOLDERS = [
    ('accounts', 'account-recap'),
    ('updates', 'customer-updates'),
]


def _briefs_root(access_token, brief_data_folder_id):
    return _find_child(access_token, brief_data_folder_id, 'briefs')


def _date_folder(access_token, brief_data_folder_id, brief_date):
    root = _briefs_root(access_token, brief_data_folder_id)
    if not root:
        return None
    return _find_child(access_token, root['id'], brief_date)


def list_active_briefs(access_token, brief_data_folder_id):
    root = _briefs_root(access_token, brief_data_folder_id)
    if not root:
        return []
    results = []
    for date_folder in _list_children(access_token, root['id']):
        manifest_file = _find_child(access_token, date_folder['id'], 'manifest.json')
        if not manifest_file:
            continue
        manifest = _download_json(access_token, manifest_file['id'])
        results.append({
            'brief_date': manifest['brief_date'],
            'brief_type': manifest.get('brief_type'),
            'last_updated_at': manifest.get('generated_at'),
        })
    results.sort(key=lambda d: d['brief_date'], reverse=True)
    return results


def get_brief_day(access_token, brief_data_folder_id, brief_date):
    date_folder = _date_folder(access_token, brief_data_folder_id, brief_date)
    if not date_folder:
        return None
    manifest_file = _find_child(access_token, date_folder['id'], 'manifest.json')
    if not manifest_file:
        return None
    manifest = _download_json(access_token, manifest_file['id'])
    manifest['folder_id'] = date_folder['id']
    return manifest


def _read_section_file(access_token, folder_id, filename):
    f = _find_child(access_token, folder_id, filename)
    if not f:
        return []
    data = _download_json(access_token, f['id'])
    return data if isinstance(data, list) else ([data] if data else [])


def _read_section_subfolder(access_token, folder_id, subfolder_name):
    sub = _find_child(access_token, folder_id, subfolder_name)
    if not sub:
        return []
    items = []
    for child in _list_children(access_token, sub['id']):
        data = _download_json(access_token, child['id'])
        items.append(data)
    return items


def _read_state(access_token, brief_data_folder_id, brief_date):
    state_root = _find_child(access_token, brief_data_folder_id, 'state')
    if not state_root:
        return {}
    state_file = _find_child(access_token, state_root['id'], f'{brief_date}.json')
    if not state_file:
        return {}
    return _download_json(access_token, state_file['id'])


def get_items_for_day(access_token, brief_data_folder_id, brief_date):
    date_folder = _date_folder(access_token, brief_data_folder_id, brief_date)
    if not date_folder:
        return []

    items = []
    for filename, section_slug in SECTION_FILES:
        for item in _read_section_file(access_token, date_folder['id'], filename):
            items.append({**item, 'section': section_slug})

    for subfolder_name, section_slug in SECTION_SUBFOLDERS:
        for item in _read_section_subfolder(access_token, date_folder['id'], subfolder_name):
            items.append({**item, 'section': section_slug})

    manager_update_file = _find_child(access_token, date_folder['id'], 'manager-update.json')
    if manager_update_file:
        item = _download_json(access_token, manager_update_file['id'])
        items.append({**item, 'section': 'manager-update'})

    state = _read_state(access_token, brief_data_folder_id, brief_date)
    for item in items:
        key = f"{item['section']}:{item['item_key']}"
        override = state.get(key)
        if not override:
            continue
        if override.get('checked') is not None:
            item['checked'] = override['checked']
        if override.get('due_on_override') is not None:
            item.setdefault('content', {})['due_on'] = override['due_on_override']

    return items


def get_account_projects(access_token, brief_data_folder_id):
    config_folder = _find_child(access_token, brief_data_folder_id, 'config')
    if not config_folder:
        return []
    config_file = _find_child(access_token, config_folder['id'], 'account-config.json')
    if not config_file:
        return []
    config = _download_json(access_token, config_file['id'])
    return [
        {'account_name': a['account_name'], 'project_gid': a['project_gid']}
        for a in config.get('accounts', [])
        if a.get('project_gid')
    ]


from datetime import date as _date


def _update_state_entry(access_token, brief_data_folder_id, brief_date, section, item_key, **fields):
    """
    Shared read-modify-write for both set_item_checked and
    set_item_due_date: 'state' is a real Drive folder (created via
    _create_folder) that acts as a container of per-date state files, one
    per active brief-date per user. It must be an actual folder -- not a
    JSON file -- because Drive's `parents` field on the per-date files
    requires a real folder id; a file cannot be the parent of another file.

    fields is exactly one of {checked: bool} or {due_on_override: str|None}
    -- whichever the caller didn't pass stays untouched on the existing
    entry, which is what lets a due-date edit preserve a prior checked
    value and vice versa.
    """
    state_root = _find_child(access_token, brief_data_folder_id, 'state')
    state = {}
    state_file = None
    if state_root:
        state_file = _find_child(access_token, state_root['id'], f'{brief_date}.json')
        if state_file:
            state = _download_json(access_token, state_file['id'])

    key = f'{section}:{item_key}'
    entry = state.get(key, {'checked': None, 'due_on_override': None})
    entry.update(fields)
    state[key] = entry

    if state_file:
        _upload_json_update(access_token, state_file['id'], state)
    else:
        if not state_root:
            state_root = _create_folder(access_token, brief_data_folder_id, 'state')
        _create_json_file(access_token, state_root['id'], f'{brief_date}.json', state)


def set_item_checked(access_token, brief_data_folder_id, brief_date, section, item_key, checked):
    _update_state_entry(access_token, brief_data_folder_id, brief_date, section, item_key, checked=checked)


def set_item_due_date(access_token, brief_data_folder_id, brief_date, section, item_key, due_on):
    _update_state_entry(access_token, brief_data_folder_id, brief_date, section, item_key, due_on_override=due_on)


def run_retention_cleanup(access_token, brief_data_folder_id, active_days=14, hard_delete_days=30, today=None):
    """
    Trashes /briefs/{date} folders older than active_days. hard_delete_days
    is accepted for interface parity with the old 14/30-day Postgres model
    but not separately implemented: Drive auto-empties Trash after 30 days
    on its own, so a single trash call already produces the same two-stage
    effect without this module needing a second destructive delete call.

    NOT YET WIRED UP: nothing in app.py, the k8s manifests, or any
    scheduler currently invokes this function, so in the real deployment
    briefs will accumulate in Drive indefinitely until something calls it.
    This is a known, deliberately-deferred follow-up rather than a silent
    gap -- wiring it up (e.g. via a k8s CronJob invoking a small script that
    calls this function per user, or via an authenticated admin-only route)
    is left to a future task.
    """
    today = today or _date.today()
    root = _find_child(access_token, brief_data_folder_id, 'briefs')
    if not root:
        return {'trashed': [], 'skipped': []}

    trashed, skipped = [], []
    for folder in _list_children(access_token, root['id']):
        try:
            folder_date = _date.fromisoformat(folder['name'])
        except ValueError:
            continue
        if (today - folder_date).days > active_days:
            _trash_file(access_token, folder['id'])
            trashed.append(folder['name'])
        else:
            skipped.append(folder['name'])
    return {'trashed': trashed, 'skipped': skipped}
