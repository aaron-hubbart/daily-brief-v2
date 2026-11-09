from account_health import (
    classify_health,
    parse_arr,
    parse_renewal,
    parse_owners,
    parse_commercial_tier,
)


def test_classify_health_red_is_needs_attention():
    assert classify_health("Health: Red") == ('needs_attention', ['Red'])


def test_classify_health_amber_is_watch():
    assert classify_health("Gainsight health score: Amber") == ('watch', ['Amber'])


def test_classify_health_green_is_healthy():
    assert classify_health("Overall health: Lime Green") == ('healthy', ['Lime Green'])


def test_classify_health_no_signal_is_no_health_data():
    assert classify_health("No health mentions in this document at all.") == ('no_health_data', [])


def test_classify_health_worse_of_two_scores():
    # Two scores disagree -> group by the worse (Yellow beats Green), both signals kept
    group, signals = classify_health("C8: Green, Overall health: Yellow")
    assert group == 'watch'
    assert set(signals) == {'Green', 'Yellow'}


def test_parse_arr_plain_figure():
    r = parse_arr("Current ARR: $256,000.")
    assert r == {'raw': '$256,000', 'value': 256000.0, 'disputed': False, 'note': None}


def test_parse_arr_disputed_figure_flagged():
    r = parse_arr("ARR: $1.2M per Salesforce, $980K per Gainsight — figures conflict and do not reconcile.")
    assert r['disputed'] is True
    assert r['note'] and 'conflict' in r['note'].lower()


def test_parse_arr_not_found():
    assert parse_arr("No commercial figures in this section.") == {'raw': None, 'value': None, 'disputed': False, 'note': None}


def test_parse_renewal_found():
    assert parse_renewal("Renewal date: 2027-03-15") == '2027-03-15'


def test_parse_renewal_not_found():
    assert parse_renewal("No renewal info here.") is None


def test_parse_owners_inline_labels():
    text = "CSM: Jane Doe\nAE: John Smith\nTAM: Aaron Hubbart"
    assert parse_owners(text, current_user_name='Aaron Hubbart') == {'csm': 'Jane Doe', 'ae': 'John Smith', 'tam': 'You'}


def test_parse_owners_table_rows():
    text = "Field, Detail\nCSM, Jane Doe\nAE, John Smith\nTAM, Aaron Hubbart"
    assert parse_owners(text, current_user_name='Aaron Hubbart') == {'csm': 'Jane Doe', 'ae': 'John Smith', 'tam': 'You'}


def test_parse_owners_missing_role_is_none():
    assert parse_owners("CSM: Jane Doe", current_user_name=None) == {'csm': 'Jane Doe', 'ae': None, 'tam': None}


def test_parse_owners_you_match_is_case_insensitive():
    assert parse_owners("TAM: aaron hubbart", current_user_name='Aaron Hubbart')['tam'] == 'You'


def test_parse_commercial_tier_found():
    assert parse_commercial_tier("Edition: Enterprise") == 'Enterprise'


def test_parse_commercial_tier_not_found():
    assert parse_commercial_tier("No edition mentioned.") is None
