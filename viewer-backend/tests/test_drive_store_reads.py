from unittest.mock import call


BRIEFS_ROOT = 'briefs-root-id'
DATE_FOLDER = 'date-folder-id'
CONFIG_ROOT = 'config-root-id'


def _child(id_, name, created='2026-07-21T08:00:00.000Z'):
    return {'id': id_, 'name': name, 'createdTime': created}


def test_list_active_briefs_reads_manifests_newest_first(mocker):
    import drive_store

    def fake_find_child(tok, parent, name):
        if name == 'briefs':
            return _child('briefs-folder', 'briefs')
        elif name == 'manifest.json':
            if parent == 'date-2026-07-21':
                return _child('manifest-2026-07-21', 'manifest.json')
            elif parent == 'date-2026-07-20':
                return _child('manifest-2026-07-20', 'manifest.json')
        return None

    mocker.patch('drive_store._find_child', side_effect=fake_find_child)
    mocker.patch('drive_store._list_children', return_value=[
        _child('date-2026-07-21', '2026-07-21'),
        _child('date-2026-07-20', '2026-07-20'),
    ])
    manifests = {
        'manifest-2026-07-21': {'brief_date': '2026-07-21', 'brief_type': 'morning', 'generated_at': '2026-07-21T12:00:00Z'},
        'manifest-2026-07-20': {'brief_date': '2026-07-20', 'brief_type': 'evening', 'generated_at': '2026-07-20T22:00:00Z'},
    }

    def fake_download(tok, file_id):
        return manifests.get(file_id, {})

    mocker.patch('drive_store._download_json', side_effect=fake_download)
    result = drive_store.list_active_briefs('tok', 'root-folder')
    assert [d['brief_date'] for d in result] == ['2026-07-21', '2026-07-20']


def test_get_brief_day_returns_none_when_date_folder_missing(mocker):
    import drive_store

    mocker.patch('drive_store._find_child', return_value=None)
    assert drive_store.get_brief_day('tok', 'root-folder', '2026-07-19') is None


def test_get_items_for_day_flattens_sections_and_applies_state_overrides(mocker):
    import drive_store

    def fake_find_child(tok, parent, name):
        return _child(f'id-{name}', name)

    mocker.patch('drive_store._find_child', side_effect=fake_find_child)

    def fake_download(tok, file_id):
        if file_id == 'id-briefs':
            return None
        return {
            'id-2026-07-21': None,
            'id-meetings.json': [
                {'item_key': 'ym-0900-bofa', 'item_type': 'checkable', 'title': 'BofA Sync',
                 'subtitle': None, 'badge': None, 'links': [], 'content': {}, 'checked': False,
                 'display_order': 0, 'generated_at': '2026-07-21T08:00:00Z'},
            ],
            'id-today.json': [],
            'id-action-items.json': [
                {'item_key': 'action-999', 'item_type': 'checkable', 'title': 'Follow up',
                 'subtitle': None, 'badge': None, 'links': [], 'content': {'due_on': '2026-07-22', 'is_new': True, 'project_name': None},
                 'checked': False, 'display_order': 0, 'generated_at': '2026-07-21T08:00:00Z'},
            ],
            'id-fyi.json': [],
            'id-manager-update.json': {'item_key': 'mgr-update', 'item_type': 'text-block', 'title': 'Manager Update',
                                        'subtitle': None, 'badge': None, 'links': [], 'content': {'textarea': 'x'},
                                        'checked': None, 'display_order': 0, 'generated_at': '2026-07-21T08:00:00Z'},
            'id-2026-07-21.json': {
                'yesterday-meetings:ym-0900-bofa': {'checked': True, 'due_on_override': None},
                'action-items:action-999': {'checked': None, 'due_on_override': '2026-07-25'},
            },
        }.get(file_id, [])

    mocker.patch('drive_store._download_json', side_effect=fake_download)
    mocker.patch('drive_store._list_children', return_value=[])

    items = drive_store.get_items_for_day('tok', 'root-folder', '2026-07-21')
    by_key = {f"{it['section']}:{it['item_key']}": it for it in items}

    assert by_key['yesterday-meetings:ym-0900-bofa']['checked'] is True
    assert by_key['action-items:action-999']['content']['due_on'] == '2026-07-25'


def test_get_account_projects_reads_config_file(mocker):
    import drive_store

    mocker.patch('drive_store._find_child', side_effect=lambda tok, parent, name: (
        _child('config-file', 'account-config.json') if name == 'account-config.json' else _child('config-folder', 'config')
    ))
    mocker.patch('drive_store._download_json', return_value={
        'accounts': [
            {'account_name': 'Bank of America', 'project_gid': '111', 'slack_channel_id': 'C0395GFC4PR'},
        ]
    })

    result = drive_store.get_account_projects('tok', 'root-folder')
    assert result == [{'account_name': 'Bank of America', 'project_gid': '111'}]
