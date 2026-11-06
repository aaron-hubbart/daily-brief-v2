from gdrive_briefs import _FILE_TO_SECTION


def test_morning_plan_and_evening_wrapup_slugs_registered():
    assert _FILE_TO_SECTION['morning-plan.json'] == 'morning-plan'
    assert _FILE_TO_SECTION['evening-wrapup.json'] == 'evening-wrapup'
