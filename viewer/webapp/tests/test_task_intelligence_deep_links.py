"""Tests for action_items.task_intelligence_deep_links — pure logic, no
Flask/DB/network. Mirrors test_action_items_grouping.py's style."""
from urllib.parse import unquote

from action_items import group_action_items, task_intelligence_deep_links


def test_returns_two_lbtn_links_with_claude_deep_link_scheme():
    links = task_intelligence_deep_links('Renew SSO cert', '123456789')
    assert len(links) == 2
    assert [l['label'] for l in links] == ['Check for updates', 'Research']
    for link in links:
        assert link['class'] == 'lbtn'
        assert link['url'].startswith('claude://claude.ai/new?q=')


def test_prompts_reference_task_title_and_gid_and_correct_method():
    links = task_intelligence_deep_links('Renew SSO cert', '123456789')
    check_prompt = unquote(links[0]['url'].split('q=', 1)[1])
    research_prompt = unquote(links[1]['url'].split('q=', 1)[1])

    assert '/task-intelligence-sync' in check_prompt
    assert 'Method A' in check_prompt
    assert 'Renew SSO cert (GID: 123456789)' in check_prompt

    assert '/task-intelligence-sync' in research_prompt
    assert 'Method B' in research_prompt
    assert 'Renew SSO cert (GID: 123456789)' in research_prompt


def test_url_encodes_special_characters_in_title():
    links = task_intelligence_deep_links('Fix & verify "auth" flow', '42')
    for link in links:
        assert ' ' not in link['url'].split('q=', 1)[1]
        assert '&' not in link['url'].split('q=', 1)[1].replace('%26', '')


def _new_item(item_key, title='Some task', links=None):
    return {
        'item_key': item_key,
        'title': title,
        'subtitle': None,
        'badge': None,
        'links': links if links is not None else [],
        'content': {'due_on': None, 'is_new': True, 'project_name': None},
        'checked': False,
    }


def test_new_item_with_no_links_gets_both_deep_links_backfilled():
    items = [_new_item('action-123', links=[])]
    groups = group_action_items(items, today_iso='2026-01-15')
    labels = [l['label'] for l in groups[0]['items'][0]['links']]
    assert labels == ['Check for updates', 'Research']


def test_new_item_with_asana_permalink_keeps_it_and_adds_deep_links():
    permalink = {'label': 'Open in Asana', 'url': 'https://app.asana.com/0/0/123/f', 'class': 'lbtn'}
    items = [_new_item('action-123', links=[permalink])]
    groups = group_action_items(items, today_iso='2026-01-15')
    labels = [l['label'] for l in groups[0]['items'][0]['links']]
    assert labels == ['Open in Asana', 'Check for updates', 'Research']


def test_already_backfilled_item_is_not_duplicated():
    existing = task_intelligence_deep_links('Some task', '123')
    items = [_new_item('action-123', links=list(existing))]
    groups = group_action_items(items, today_iso='2026-01-15')
    labels = [l['label'] for l in groups[0]['items'][0]['links']]
    assert labels == ['Check for updates', 'Research']


def test_non_asana_item_key_is_left_untouched():
    items = [_new_item('fyi-1', links=[])]
    groups = group_action_items(items, today_iso='2026-01-15')
    assert groups[0]['items'][0]['links'] == []
