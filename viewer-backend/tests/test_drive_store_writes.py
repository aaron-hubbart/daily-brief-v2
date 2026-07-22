def test_set_item_checked_updates_existing_state_file(mocker):
    import drive_store

    mocker.patch('drive_store._find_child', side_effect=lambda tok, parent, name: (
        {'id': 'state-root'} if name == 'state' else
        {'id': 'state-file'} if name == '2026-07-21.json' else None
    ))
    mocker.patch('drive_store._download_json', return_value={
        'yesterday-meetings:ym-0900-acmefin': {'checked': False, 'due_on_override': None},
    })
    update_spy = mocker.patch('drive_store._upload_json_update')
    create_spy = mocker.patch('drive_store._create_json_file')

    drive_store.set_item_checked('tok', 'root-folder', '2026-07-21', 'yesterday-meetings', 'ym-0900-acmefin', True)

    update_spy.assert_called_once()
    create_spy.assert_not_called()
    written_state = update_spy.call_args[0][2]
    assert written_state['yesterday-meetings:ym-0900-acmefin']['checked'] is True


def test_set_item_checked_creates_state_file_and_folder_when_absent(mocker):
    import drive_store

    mocker.patch('drive_store._find_child', return_value=None)
    create_folder_spy = mocker.patch('drive_store._create_folder', return_value={
        'id': 'new-state-root', 'name': 'state',
    })
    create_file_spy = mocker.patch('drive_store._create_json_file', return_value={
        'id': 'new-state-file', 'name': '2026-07-21.json',
    })
    update_spy = mocker.patch('drive_store._upload_json_update')

    drive_store.set_item_checked('tok', 'root-folder', '2026-07-21', 'today', 'today-0900-zebra-financial', False)

    create_folder_spy.assert_called_once_with('tok', 'root-folder', 'state')
    create_file_spy.assert_called_once()
    assert create_file_spy.call_args[0][0] == 'tok'
    assert create_file_spy.call_args[0][1] == 'new-state-root'
    assert create_file_spy.call_args[0][2] == '2026-07-21.json'
    update_spy.assert_not_called()


def test_set_item_due_date_preserves_checked_value(mocker):
    import drive_store

    mocker.patch('drive_store._find_child', side_effect=lambda tok, parent, name: (
        {'id': 'state-root'} if name == 'state' else
        {'id': 'state-file'} if name == '2026-07-21.json' else None
    ))
    mocker.patch('drive_store._download_json', return_value={
        'action-items:action-999': {'checked': True, 'due_on_override': None},
    })
    update_spy = mocker.patch('drive_store._upload_json_update')

    drive_store.set_item_due_date('tok', 'root-folder', '2026-07-21', 'action-items', 'action-999', '2026-07-30')

    written_state = update_spy.call_args[0][2]
    entry = written_state['action-items:action-999']
    assert entry['due_on_override'] == '2026-07-30'
    assert entry['checked'] is True


def test_run_retention_cleanup_trashes_only_old_folders(mocker):
    import drive_store
    from datetime import date, timedelta

    today = date(2026, 7, 21)
    old_date = (today - timedelta(days=20)).isoformat()
    recent_date = (today - timedelta(days=2)).isoformat()

    mocker.patch('drive_store._find_child', return_value={'id': 'briefs-root'})
    mocker.patch('drive_store._list_children', return_value=[
        {'id': 'old-folder', 'name': old_date, 'createdTime': f'{old_date}T08:00:00.000Z'},
        {'id': 'recent-folder', 'name': recent_date, 'createdTime': f'{recent_date}T08:00:00.000Z'},
    ])
    trash_spy = mocker.patch('drive_store._trash_file')

    result = drive_store.run_retention_cleanup('tok', 'root-folder', active_days=14, today=today)

    trash_spy.assert_called_once_with('tok', 'old-folder')
    assert result == {'trashed': [old_date], 'skipped': [recent_date]}
