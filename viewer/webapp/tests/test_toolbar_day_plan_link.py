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


def test_toolbar_has_day_plan_link():
    html = render_brief_fragment()
    assert 'Day Plan' in html
    assert 'class="toolbtn"' in html


def test_day_plan_link_threads_the_viewed_date():
    html = render_brief_fragment()
    assert 'href="/day_plan_page?date=2026-09-15"' in html
