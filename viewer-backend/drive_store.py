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
