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


def _drive_request(access_token, method, url, body_bytes=None, content_type=None):
    headers = {'Authorization': f'Bearer {access_token}'}
    if content_type:
        headers['Content-Type'] = content_type
    req = urllib.request.Request(url, data=body_bytes, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read()


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
