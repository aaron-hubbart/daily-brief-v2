from datetime import date

from account_health import build_account_entry, build_page_model


def test_build_account_entry_no_doc_found():
    entry = build_account_entry('Acme Corp', 'primary', 'not_found', current_user_name=None, today=date(2026, 11, 9))
    assert entry['no_doc'] is True
    assert entry['health_group'] == 'no_health_data'
    assert entry['arr']['raw'] is None
    assert entry['renewal'] is None
    assert entry['csm'] is None and entry['ae'] is None and entry['tam'] is None
    assert entry['risks'] == []
    assert entry['next_step'] == "Review this account's Context Doc for next steps"
    assert entry['doc_url'] is None
    assert entry['refresh_query'] == 'refresh the context for Acme Corp'


def test_build_account_entry_none_doc_result_treated_same_as_not_found():
    entry = build_account_entry('Acme Corp', 'primary', None, current_user_name=None, today=date(2026, 11, 9))
    assert entry['no_doc'] is True


SAMPLE_DOC = """
Edition: Enterprise
Last swept: 2026-11-01
Overall health: Yellow
Current ARR: $256,000.
Renewal date: 2027-03-15
CSM: Jane Doe
AE: John Smith
TAM: Aaron Hubbart

Top open risks:
- Renewal timeline slipping [Gainsight via Glean, 2026-10-01]

Recommendation: Schedule an exec QBR before renewal.
"""


def test_build_account_entry_found_doc():
    doc_result = {'text': SAMPLE_DOC, 'doc_url': 'https://docs.google.com/x', 'modified_time': '2026-11-01T00:00:00.000Z'}
    entry = build_account_entry('Acme Corp', 'primary', doc_result, current_user_name='Aaron Hubbart', today=date(2026, 11, 9))
    assert entry['no_doc'] is False
    assert entry['health_group'] == 'watch'
    assert entry['arr']['value'] == 256000.0
    assert entry['renewal'] == '2027-03-15'
    assert entry['tam'] == 'You'
    assert entry['doc_url'] == 'https://docs.google.com/x'
    assert entry['swept_label'] == 'swept 8d ago'


def _fetcher(docs):
    return lambda name: docs.get(name, 'not_found')


def test_build_page_model_groups_in_fixed_order_with_subtotals():
    accounts_config = [
        {'account_name': 'Red Co', 'tier': 'primary'},
        {'account_name': 'Green Co', 'tier': 'primary'},
        {'account_name': 'Unknown Co', 'tier': 'secondary'},
    ]
    docs = {
        'Red Co': {'text': 'Health: Red\nCurrent ARR: $100,000.', 'doc_url': 'u1', 'modified_time': None},
        'Green Co': {'text': 'Health: Green\nCurrent ARR: $200,000.', 'doc_url': 'u2', 'modified_time': None},
    }
    model = build_page_model(accounts_config, _fetcher(docs), current_user_name=None, today=date(2026, 11, 9))
    keys = [g['key'] for g in model['groups']]
    assert keys == ['needs_attention', 'watch', 'healthy', 'no_health_data']
    needs_attention = next(g for g in model['groups'] if g['key'] == 'needs_attention')
    assert needs_attention['count'] == 1
    assert needs_attention['arr_subtotal_raw'] == '$100K'
    no_health = next(g for g in model['groups'] if g['key'] == 'no_health_data')
    assert no_health['count'] == 1
    assert no_health['accounts'][0]['account_name'] == 'Unknown Co'


def test_build_page_model_stat_tiles():
    accounts_config = [{'account_name': 'A'}, {'account_name': 'B'}]
    docs = {
        'A': {'text': 'Health: Red\nARR: $1.2M vs $900K, figures conflict.', 'doc_url': 'u', 'modified_time': None},
        'B': {'text': 'Health: Green\nCurrent ARR: $500,000.', 'doc_url': 'u', 'modified_time': None},
    }
    model = build_page_model(accounts_config, _fetcher(docs), current_user_name=None, today=date(2026, 11, 9))
    tiles = model['stat_tiles']
    assert tiles['accounts_count'] == 2
    assert tiles['needs_attention_count'] == 1
    assert tiles['combined_arr_disputed_count'] == 1


def test_build_page_model_stale_count_ignores_unknown_staleness():
    accounts_config = [{'account_name': 'Old'}, {'account_name': 'Fresh'}, {'account_name': 'Unknown'}]
    docs = {
        # 45 days before the fixed `today` below -> stale
        'Old': {'text': 'Health: Green\nLast swept: 2026-09-25', 'doc_url': 'u', 'modified_time': None},
        # 2 days before -> not stale
        'Fresh': {'text': 'Health: Green\nLast swept: 2026-11-07', 'doc_url': 'u', 'modified_time': None},
        # no sweep line, no modified_time -> staleness unknown, must NOT count as stale
        'Unknown': {'text': 'Health: Green', 'doc_url': 'u', 'modified_time': None},
    }
    model = build_page_model(accounts_config, _fetcher(docs), current_user_name=None, today=date(2026, 11, 9))
    assert model['stat_tiles']['stale_count'] == 1


def test_build_page_model_missing_account_name_key_does_not_crash():
    # account-config.json entries have used both 'account_name' and 'name' historically
    accounts_config = [{'name': 'Legacy Co', 'tier': 'primary'}]
    model = build_page_model(accounts_config, _fetcher({}), current_user_name=None, today=date(2026, 11, 9))
    assert model['groups'][-1]['accounts'][0]['account_name'] == 'Legacy Co'
