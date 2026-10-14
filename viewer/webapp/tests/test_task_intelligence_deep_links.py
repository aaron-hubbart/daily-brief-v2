"""Tests for action_items.task_intelligence_deep_links — pure logic, no
Flask/DB/network. Mirrors test_action_items_grouping.py's style."""
from urllib.parse import unquote

from action_items import task_intelligence_deep_links


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
