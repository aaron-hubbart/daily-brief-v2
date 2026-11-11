from template_test_utils import make_env


def render_brief_fragment():
    env = make_env()
    env.globals['url_for'] = lambda endpoint, **kwargs: (
        '/' + endpoint + ('?' + '&'.join(f'{k}={v}' for k, v in kwargs.items()) if kwargs else '')
    )
    template = env.get_template('brief_fragment.html')
    return template.render(
        brief_date='2026-09-15', brief_date_label='Tuesday, September 15',
        brief_type='morning', checkable_count=0, sections=[], items_by_section={},
        action_subsections=[], asana_pat_configured=False, today_iso='2026-09-15',
        progressive=False,
    )


def test_toolbar_has_account_health_link():
    html = render_brief_fragment()
    assert 'Account Health' in html
    assert 'href="/account_health_page"' in html
