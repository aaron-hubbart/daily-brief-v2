from account_health import (
    classify_health,
    parse_arr,
    parse_renewal,
    parse_owners,
    parse_commercial_tier,
    parse_risks,
    parse_action_items,
    extract_recap_action_items,
    compute_swept_days_ago,
    format_days_ago,
    format_arr_abbreviated,
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
    # Spec's own literal example (docs/.../2026-11-06-portfolio-design.md):
    # two scores disagree -> group by the worse (Yellow beats Green), both
    # signals kept. Neither "C8:" nor "Overall:" contains the word
    # "health" -- the real pattern this must handle.
    group, signals = classify_health("C8: Green, Overall: Yellow")
    assert group == 'watch'
    assert set(signals) == {'Green', 'Yellow'}


def test_classify_health_ignores_unrelated_health_mention():
    # "health check" on "Red Hat" must not false-positive as a Red health
    # signal -- common phrasing in Camunda TAM docs, unrelated to account
    # health.
    assert classify_health("Platform health check on Red Hat OpenShift") == ('no_health_data', [])


def test_classify_health_dedupes_repeated_signal():
    group, signals = classify_health("Health: Yellow\nGainsight health score: Yellow")
    assert group == 'watch'
    assert signals == ['Yellow']


def test_parse_arr_plain_figure():
    r = parse_arr("Current ARR: $256,000.")
    assert r == {'raw': '$256,000', 'value': 256000.0, 'disputed': False, 'note': None}


def test_parse_arr_disputed_figure_flagged():
    r = parse_arr("ARR: $1.2M per Salesforce, $980K per Gainsight — figures conflict and do not reconcile.")
    assert r['disputed'] is True
    assert r['note'] and 'conflict' in r['note'].lower()


def test_parse_arr_not_found():
    assert parse_arr("No commercial figures in this section.") == {'raw': None, 'value': None, 'disputed': False, 'note': None}


def test_parse_arr_ignores_unrelated_dollar_figure_elsewhere_in_doc():
    # A $ figure on an earlier, unrelated line must not win over the real
    # ARR line later in the doc.
    r = parse_arr("PS deal $40K signed.\nCurrent ARR: $310K")
    assert r['raw'] == '$310K'
    assert r['value'] == 310_000.0


def test_parse_arr_amount_not_inflated_by_trailing_word():
    # "$1,200 monthly" must not read the leading "m" of "monthly" as an
    # M-for-million suffix (which would inflate $1,200 into $1.2B).
    r = parse_arr("ARR runs $1,200 monthly per the latest sync.")
    assert r['raw'] == '$1,200'
    assert r['value'] == 1200.0


def test_parse_arr_dispute_words_scoped_to_arr_line():
    # A dispute word elsewhere in the doc, unrelated to ARR, must not
    # falsely flag the ARR figure as disputed.
    r = parse_arr("Scheduling conflict with the QBR.\nCurrent ARR: $500,000.")
    assert r['disputed'] is False
    assert r['note'] is None


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


def test_parse_owners_you_match_on_first_name_only():
    assert parse_owners("TAM: Aaron", current_user_name='Aaron Hubbart')['tam'] == 'You'


def test_parse_owners_you_match_strips_trailing_parenthetical():
    assert parse_owners("TAM: Aaron Hubbart (Camunda)", current_user_name='Aaron Hubbart')['tam'] == 'You'


def test_parse_commercial_tier_found():
    assert parse_commercial_tier("Edition: Enterprise") == 'Enterprise'


def test_parse_commercial_tier_not_found():
    assert parse_commercial_tier("No edition mentioned.") is None


def test_parse_risks_bullet_list_with_source_tag():
    text = "Top open risks:\n- Renewal timeline slipping [Gainsight via Glean, 2026-10-01]\n- No exec sponsor identified"
    risks = parse_risks(text)
    assert risks[0] == {'text': 'Renewal timeline slipping', 'source_tag': 'Gainsight via Glean, 2026-10-01'}
    assert risks[1] == {'text': 'No exec sponsor identified', 'source_tag': None}


def test_parse_risks_alternate_heading():
    text = "Open Risks & Issues:\n- Budget frozen until Q2"
    assert parse_risks(text) == [{'text': 'Budget frozen until Q2', 'source_tag': None}]


def test_parse_risks_no_section_is_empty_list():
    assert parse_risks("Nothing relevant here.") == []


def test_parse_action_items_inline_recommendation():
    text = "Recommendation: Schedule an exec QBR before renewal."
    assert parse_action_items(text) == [
        {'text': 'Schedule an exec QBR before renewal.', 'asana_url': None, 'source': 'context_doc'},
    ]


def test_parse_action_items_none_found_is_empty_list():
    # No generic "go review the doc" fallback -- an empty list is a valid
    # outcome the card renders as its own placeholder.
    assert parse_action_items("No recommendation language in this doc.") == []


def test_parse_action_items_heading_with_bullets():
    text = "Next Steps:\n- Schedule an exec QBR before renewal\n- Confirm budget owner"
    assert parse_action_items(text) == [
        {'text': 'Schedule an exec QBR before renewal', 'asana_url': None, 'source': 'context_doc'},
        {'text': 'Confirm budget owner', 'asana_url': None, 'source': 'context_doc'},
    ]


def test_parse_action_items_caps_at_five():
    text = "Action Items:\n" + "\n".join(f"- Item {i}" for i in range(1, 8))
    items = parse_action_items(text)
    assert len(items) == 5
    assert [i['text'] for i in items] == ['Item 1', 'Item 2', 'Item 3', 'Item 4', 'Item 5']


def test_parse_action_items_asana_gid_tag_becomes_deep_link():
    text = "Next Steps:\n- Confirm budget owner [Asana: 1211234567890]"
    assert parse_action_items(text) == [
        {'text': 'Confirm budget owner', 'asana_url': 'https://app.asana.com/0/0/1211234567890/f', 'source': 'context_doc'},
    ]


def test_parse_action_items_asana_url_tag_used_as_is():
    text = "Next Steps:\n- Confirm budget owner [Asana: https://app.asana.com/0/123/456/f]"
    assert parse_action_items(text) == [
        {'text': 'Confirm budget owner', 'asana_url': 'https://app.asana.com/0/123/456/f', 'source': 'context_doc'},
    ]


def test_parse_action_items_inline_asana_url_without_tag():
    text = "Next Steps:\n- Confirm budget owner, see https://app.asana.com/0/123/456/f"
    items = parse_action_items(text)
    assert items == [
        {'text': 'Confirm budget owner, see https://app.asana.com/0/123/456/f',
         'asana_url': 'https://app.asana.com/0/123/456/f', 'source': 'context_doc'},
    ]


def test_parse_action_items_non_asana_tag_is_not_a_link():
    text = "Next Steps:\n- Confirm budget owner [Gainsight via Glean, 2026-10-01]"
    assert parse_action_items(text) == [
        {'text': 'Confirm budget owner [Gainsight via Glean, 2026-10-01]', 'asana_url': None, 'source': 'context_doc'},
    ]


def test_extract_recap_action_items_maps_title_to_action_items():
    items = [{'title': 'Acme Corp', 'content': {'action_items': ['Follow up on PO', 'Send revised SOW']}}]
    assert extract_recap_action_items(items) == {'Acme Corp': ['Follow up on PO', 'Send revised SOW']}


def test_extract_recap_action_items_skips_malformed_entries():
    items = [
        'not a dict',
        {'title': None, 'content': {'action_items': ['x']}},
        {'title': 'No Content'},
        {'title': 'Bad Content', 'content': 'oops'},
        {'title': 'Bad Items', 'content': {'action_items': 'not a list'}},
        {'title': 'Empty Items', 'content': {'action_items': ['', '   ']}},
        {'title': 'Good Co', 'content': {'action_items': ['Real item']}},
    ]
    assert extract_recap_action_items(items) == {'Good Co': ['Real item']}


def test_extract_recap_action_items_empty_or_none_input():
    assert extract_recap_action_items(None) == {}
    assert extract_recap_action_items([]) == {}


def test_compute_swept_days_ago_from_doc_line():
    from datetime import date
    assert compute_swept_days_ago("Last swept: 2026-11-01", modified_time=None, today=date(2026, 11, 9)) == 8


def test_compute_swept_days_ago_falls_back_to_modified_time():
    from datetime import date
    assert compute_swept_days_ago("No sweep line here.", modified_time="2026-11-05T00:00:00.000Z", today=date(2026, 11, 9)) == 4


def test_compute_swept_days_ago_unknown():
    from datetime import date
    assert compute_swept_days_ago("Nothing here.", modified_time=None, today=date(2026, 11, 9)) is None


def test_compute_swept_days_ago_malformed_doc_date_does_not_crash():
    from datetime import date
    # Falls back to modified_time when the doc's own date is unparseable,
    # rather than raising.
    assert compute_swept_days_ago(
        "Last swept: 2026-02-30", modified_time="2026-11-05T00:00:00.000Z", today=date(2026, 11, 9),
    ) == 4


def test_compute_swept_days_ago_malformed_modified_time_does_not_crash():
    from datetime import date
    assert compute_swept_days_ago("No sweep line here.", modified_time="not-a-date", today=date(2026, 11, 9)) is None


def test_format_days_ago_variants():
    assert format_days_ago(0) == 'swept today'
    assert format_days_ago(3) == 'swept 3d ago'
    assert format_days_ago(None) == 'swept date unknown'


def test_format_arr_abbreviated_variants():
    assert format_arr_abbreviated(256000.0) == '$256K'
    assert format_arr_abbreviated(3470000.0) == '$3.47M'
    assert format_arr_abbreviated(None) == '—'
