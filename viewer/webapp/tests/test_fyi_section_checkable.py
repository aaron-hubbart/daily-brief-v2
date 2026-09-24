from template_test_utils import make_env


def render_fyi(items):
    env = make_env()
    template = env.get_template('section_fragment.html')
    return template.render(
        section_slug='fyi',
        section_items=items,
        action_subsections=[],
        asana_pat_configured=False,
        brief_date='2026-09-15',
        today_iso='2026-09-15',
    )


def test_fyi_item_renders_as_checkable():
    items = [{
        'item_key': 'fyi-1',
        'item_type': 'checkable',
        'title': 'Post-meeting summary generated',
        'subtitle': 'Acme, Inc. Sync — summary posted to Drive',
        'checked': False,
        'content': {},
    }]

    html = render_fyi(items)

    assert 'Post-meeting summary generated' in html
    assert 'Acme, Inc. Sync — summary posted to Drive' in html
    assert 'type="checkbox"' in html
    assert 'data-id="fyi-1"' in html
    # No longer the old, non-interactive fyi-item/fyi-dot markup
    assert 'fyi-item' not in html
    assert 'fyi-dot' not in html


def test_fyi_item_checked_state_renders_done_class_and_checked_attr():
    items = [{
        'item_key': 'fyi-1',
        'item_type': 'checkable',
        'title': 'Recurring task spawned',
        'checked': True,
        'content': {},
    }]

    html = render_fyi(items)

    assert 'done' in html
    assert 'checked' in html
