import json
from unittest.mock import MagicMock

import pytest


def _fake_response(payload_bytes):
    resp = MagicMock()
    resp.read.return_value = payload_bytes
    resp.__enter__.return_value = resp
    return resp


def test_find_child_returns_first_match_or_none(mocker):
    import drive_store

    mocker.patch('urllib.request.urlopen', return_value=_fake_response(json.dumps({
        'files': [{'id': 'file-1', 'name': 'manifest.json', 'createdTime': '2026-07-21T08:00:00.000Z'}]
    }).encode('utf-8')))
    found = drive_store._find_child('tok', 'folder-1', 'manifest.json')
    assert found == {'id': 'file-1', 'name': 'manifest.json', 'createdTime': '2026-07-21T08:00:00.000Z'}

    mocker.patch('urllib.request.urlopen', return_value=_fake_response(json.dumps({'files': []}).encode('utf-8')))
    assert drive_store._find_child('tok', 'folder-1', 'missing.json') is None


def test_list_children_sorted_newest_first(mocker):
    import drive_store

    mocker.patch('urllib.request.urlopen', return_value=_fake_response(json.dumps({
        'files': [
            {'id': 'f1', 'name': 'today.json', 'createdTime': '2026-07-21T08:00:00.000Z'},
            {'id': 'f2', 'name': 'today.json', 'createdTime': '2026-07-21T09:30:00.000Z'},
        ]
    }).encode('utf-8')))
    files = drive_store._list_children('tok', 'folder-1', 'today.json')
    assert [f['id'] for f in files] == ['f2', 'f1']


def test_download_json_parses_media_body(mocker):
    import drive_store

    mocker.patch('urllib.request.urlopen', return_value=_fake_response(
        json.dumps({'hello': 'world'}).encode('utf-8')
    ))
    assert drive_store._download_json('tok', 'file-1') == {'hello': 'world'}


def test_upload_json_update_sends_patch_with_media_body(mocker):
    import drive_store

    mock_urlopen = mocker.patch('urllib.request.urlopen', return_value=_fake_response(b'{}'))
    drive_store._upload_json_update('tok', 'file-1', {'checked': True})

    request_obj = mock_urlopen.call_args[0][0]
    assert request_obj.get_method() == 'PATCH'
    assert '/upload/drive/v3/files/file-1' in request_obj.full_url
    assert json.loads(request_obj.data.decode('utf-8')) == {'checked': True}


def test_create_json_file_sends_multipart_post(mocker):
    import drive_store

    mock_urlopen = mocker.patch('urllib.request.urlopen', return_value=_fake_response(
        json.dumps({'id': 'new-file-1', 'name': 'state.json'}).encode('utf-8')
    ))
    result = drive_store._create_json_file('tok', 'folder-1', 'state.json', {'a': 1})

    assert result == {'id': 'new-file-1', 'name': 'state.json'}
    request_obj = mock_urlopen.call_args[0][0]
    assert request_obj.get_method() == 'POST'
    assert '/upload/drive/v3/files' in request_obj.full_url
    assert b'"a": 1' in request_obj.data or b'"a":1' in request_obj.data
    assert b'folder-1' in request_obj.data


def test_create_folder_sends_plain_post_with_folder_mimetype(mocker):
    import drive_store

    mock_urlopen = mocker.patch('urllib.request.urlopen', return_value=_fake_response(
        json.dumps({'id': 'new-folder-1', 'name': 'state'}).encode('utf-8')
    ))
    result = drive_store._create_folder('tok', 'parent-1', 'state')

    assert result == {'id': 'new-folder-1', 'name': 'state'}
    request_obj = mock_urlopen.call_args[0][0]
    assert request_obj.get_method() == 'POST'
    assert request_obj.full_url == 'https://www.googleapis.com/drive/v3/files'
    assert '/upload/' not in request_obj.full_url
    body = json.loads(request_obj.data.decode('utf-8'))
    assert body['mimeType'] == 'application/vnd.google-apps.folder'
    assert body['name'] == 'state'
    assert body['parents'] == ['parent-1']


def test_trash_file_sends_patch_trashed_true(mocker):
    import drive_store

    mock_urlopen = mocker.patch('urllib.request.urlopen', return_value=_fake_response(b'{}'))
    drive_store._trash_file('tok', 'file-1')

    request_obj = mock_urlopen.call_args[0][0]
    assert request_obj.get_method() == 'PATCH'
    assert '/drive/v3/files/file-1' in request_obj.full_url
    assert json.loads(request_obj.data.decode('utf-8')) == {'trashed': True}
