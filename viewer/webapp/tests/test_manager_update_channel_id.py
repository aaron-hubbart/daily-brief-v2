from template_test_utils import make_env


def render_manager_update(items):
    env = make_env()
    template = env.get_template('section_fragment.html')
    return template.render(
        section_slug='manager-update',
        section_items=items,
        action_subsections=[],
        asana_pat_configured=False,
        brief_date='2026-09-15',
        today_iso='2026-09-15',
    )


def test_post_to_manager_button_carries_channel_id():
    items = [{
        'item_key': 'mgr-update',
        'item_type': 'text-block',
        'title': 'Manager Update',
        'content': {
            'textarea': 'TAM Weekly Update...',
            'channel_id': 'D0TESTMANAGER',
        },
    }]

    html = render_manager_update(items)

    assert 'data-item-key="mgr-update"' in html
    assert 'data-section="manager-update"' in html
    assert 'value="D0TESTMANAGER"' in html
    assert 'Post to Manager' in html
