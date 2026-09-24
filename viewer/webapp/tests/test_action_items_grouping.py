"""Tests for action_items.group_action_items — pure logic, no Flask/DB/
network. Mirrors test_asana_discovery.py's style: hand-rolled fixtures,
no mocking library."""
from action_items import ACTION_SUBSECTIONS, group_action_items


def _item(item_key, due_on=None, is_new=False, project_name=None):
    return {
        'item_key': item_key,
        'title': item_key,
        'subtitle': None,
        'badge': None,
        'links': [],
        'content': {'due_on': due_on, 'is_new': is_new, 'project_name': project_name},
        'checked': False,
    }


def test_new_item_takes_priority_over_due_date():
    items = [_item('a', due_on='2020-01-01', is_new=True)]
    groups = group_action_items(items, today_iso='2026-01-15')
    assert [g['slug'] for g in groups] == ['new']
    assert groups[0]['items'] == items


def test_overdue_item_before_today():
    items = [_item('a', due_on='2026-01-10')]
    groups = group_action_items(items, today_iso='2026-01-15')
    assert [g['slug'] for g in groups] == ['overdue']


def test_item_due_within_next_7_days_is_due_soon():
    items = [_item('a', due_on='2026-01-20')]
    groups = group_action_items(items, today_iso='2026-01-15')
    assert [g['slug'] for g in groups] == ['due-soon']


def test_item_with_no_due_date_or_far_future_is_no_due_date():
    items = [_item('a', due_on=None), _item('b', due_on='2026-03-01')]
    groups = group_action_items(items, today_iso='2026-01-15')
    assert [g['slug'] for g in groups] == ['no-due-date']
    assert len(groups[0]['items']) == 2


def test_empty_groups_are_omitted():
    items = [_item('a', due_on='2026-01-10')]
    groups = group_action_items(items, today_iso='2026-01-15')
    assert [g['slug'] for g in groups] == ['overdue']


def test_overdue_and_due_soon_sorted_by_due_date_ascending():
    items = [
        _item('later', due_on='2026-01-12'),
        _item('earlier', due_on='2026-01-10'),
    ]
    groups = group_action_items(items, today_iso='2026-01-15')
    assert [it['item_key'] for it in groups[0]['items']] == ['earlier', 'later']


def test_items_grouped_into_boards_by_project_name_with_my_tasks_last():
    items = [
        _item('a', due_on='2026-01-10', project_name='Acme'),
        _item('b', due_on='2026-01-10', project_name=None),
        _item('c', due_on='2026-01-10', project_name='Zeta'),
    ]
    groups = group_action_items(items, today_iso='2026-01-15')
    board_names = [b['name'] for b in groups[0]['boards']]
    assert board_names == ['Acme', 'Zeta', 'My Tasks']


def test_item_due_exactly_today_is_due_today_not_due_soon():
    items = [_item('a', due_on='2026-01-15')]
    groups = group_action_items(items, today_iso='2026-01-15')
    assert [g['slug'] for g in groups] == ['due-today']


def test_item_due_tomorrow_is_still_due_soon():
    items = [_item('a', due_on='2026-01-16')]
    groups = group_action_items(items, today_iso='2026-01-15')
    assert [g['slug'] for g in groups] == ['due-soon']


def test_action_subsections_defines_five_fixed_slugs():
    assert [s['slug'] for s in ACTION_SUBSECTIONS] == [
        'new', 'overdue', 'due-today', 'due-soon', 'no-due-date',
    ]
