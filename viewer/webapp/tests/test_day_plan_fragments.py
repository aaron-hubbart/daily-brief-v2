from template_test_utils import make_env


def render_morning(available=True, **kwargs):
    env = make_env()
    template = env.get_template('morning_plan_fragment.html')
    defaults = dict(
        available=available, stats={}, recommendations=[], schedule=[],
        quick_actions={}, critical_path=[],
    )
    defaults.update(kwargs)
    return template.render(**defaults)


def render_evening(available=True, **kwargs):
    env = make_env()
    template = env.get_template('evening_wrapup_fragment.html')
    defaults = dict(
        available=available, stats={}, completed=[], carried_over=[],
        key_wins=[], still_blocking=[], tomorrows_focus=[],
    )
    defaults.update(kwargs)
    return template.render(**defaults)


def test_morning_not_available_shows_placeholder():
    html = render_morning(available=False)
    assert 'not generated yet' in html.lower()


def test_morning_renders_recommendations_and_schedule():
    html = render_morning(
        recommendations=[{'time_range': '8–10 AM', 'text': 'Block this for ESUP.'}],
        schedule=[{'time': '10:00 AM', 'title': 'Micah 1:1', 'meeting_prep_link': None}],
    )
    assert '8–10 AM' in html
    assert 'Block this for ESUP.' in html
    assert 'Micah 1:1' in html


def test_morning_renders_meeting_prep_link_when_present():
    html = render_morning(schedule=[{'time': '10:00 AM', 'title': 'Micah 1:1', 'meeting_prep_link': 'claude://x'}])
    assert 'claude://x' in html


def test_morning_renders_quick_action_column_even_for_unrecognized_category_name():
    html = render_morning(quick_actions={'Some Deleted Category': [{'text': 'Old leftover item'}]})
    assert 'Some Deleted Category' in html
    assert 'Old leftover item' in html


def test_morning_renders_critical_path_cards():
    html = render_morning(critical_path=[{'title': 'Extended 8.7 Support Decision', 'detail': 'x', 'amount': '$2.28M', 'due': None}])
    assert 'Extended 8.7 Support Decision' in html
    assert '$2.28M' in html


def test_evening_not_available_shows_placeholder():
    html = render_evening(available=False)
    assert 'not generated yet' in html.lower()


def test_evening_renders_day_score():
    html = render_evening(stats={'meetings': 6, 'completed': 3, 'carried_over': 2, 'day_score': 8})
    assert '8' in html


def test_evening_renders_completed_carried_over_wins_and_blocking():
    html = render_evening(
        completed=[{'title': 'Finalized ESUP proposal', 'detail': 'Unblocked'}],
        carried_over=[{'title': 'Define Big Rocks', 'detail': 'Tomorrow'}],
        key_wins=['ESUP blocking path cleared'],
        still_blocking=[{'title': 'Extended 8.7 support decision', 'detail': '$2.28M'}],
    )
    assert 'Finalized ESUP proposal' in html
    assert 'Define Big Rocks' in html
    assert 'ESUP blocking path cleared' in html
    assert 'Extended 8.7 support decision' in html


def test_evening_renders_tomorrows_focus():
    html = render_evening(tomorrows_focus=[{'time_range': '8–10 AM', 'text': 'Define Big Rocks'}])
    assert 'Define Big Rocks' in html
