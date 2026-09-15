from urllib.parse import unquote

from template_test_utils import make_env


def render_today(items):
    env = make_env()
    template = env.get_template('section_fragment.html')
    return template.render(
        section_slug='today',
        section_items=items,
        action_subsections=[],
        asana_pat_configured=False,
        brief_date='2026-09-15',
        today_iso='2026-09-15',
    )


def test_standup_card_renders_textarea_and_post_to_slack_link():
    items = [{
        'item_key': 'today-standup',
        'item_type': 'card',
        'title': 'Team Standup Update',
        'content': {
            'textarea': 'Customer\n- Acme, Inc. — renewal call prep',
            'channel_id': 'D0TESTGEEKBOT',
        },
    }]

    html = render_today(items)

    assert 'Team Standup Update' in html
    assert 'Customer\n- Acme, Inc. — renewal call prep' in html
    assert 'https://slack.com/app_redirect?channel=D0TESTGEEKBOT' in html
    assert 'Post to Slack' in html


def test_standup_card_refresh_link_targets_today_item():
    items = [{
        'item_key': 'today-standup',
        'item_type': 'card',
        'title': 'Team Standup Update',
        'content': {'textarea': '...', 'channel_id': 'D0TESTGEEKBOT'},
    }]

    html = render_today(items)
    decoded = unquote(html)

    assert '/daily-brief Refresh section:today date:2026-09-15 item:today-standup' in decoded


def test_checkable_meeting_items_still_render_normally():
    items = [{
        'item_key': 'today-0900-acme-sync',
        'item_type': 'checkable',
        'title': 'Acme, Inc. Sync',
        'subtitle': '9:00 AM with a colleague',
        'checked': False,
        'content': {'time': '9:00 AM'},
    }]

    html = render_today(items)

    assert 'Acme, Inc. Sync' in html
    assert '9:00 AM with a colleague' in html
    assert 'type="checkbox"' in html


def test_card_and_checkable_items_render_together():
    items = [
        {
            'item_key': 'today-standup',
            'item_type': 'card',
            'title': 'Team Standup Update',
            'content': {'textarea': 'Customer\n- Acme, Inc.', 'channel_id': 'D0TESTGEEKBOT'},
        },
        {
            'item_key': 'today-0900-acme-sync',
            'item_type': 'checkable',
            'title': 'Acme, Inc. Sync',
            'checked': False,
            'content': {},
        },
    ]

    html = render_today(items)

    assert 'Team Standup Update' in html
    assert 'Acme, Inc. Sync' in html
