"""Tests for asana_discovery's pure logic (find_new_projects,
get_portfolio_project_names) — no real Asana calls. fetch_fn is faked
so these run with no network access and no mocking library."""
from asana_discovery import find_new_projects, get_portfolio_project_names, match_accounts_to_theaters


def _fake_fetch(responses):
    """Builds a fetch_fn(pat, path, params) that returns responses[path]
    regardless of the pat/params passed in."""
    def fetch_fn(pat, path, params):
        return responses[path]
    return fetch_fn


def test_returns_projects_not_already_linked():
    fetch_fn = _fake_fetch({
        '/users/me': {'data': {'workspaces': [{'gid': 'ws1', 'name': 'Camunda'}]}},
        '/workspaces/ws1/projects': {'data': [
            {'gid': 'p1', 'name': 'Acme Financial'},
            {'gid': 'p2', 'name': 'Acme Corp'},
        ]},
    })

    result = find_new_projects(fetch_fn, pat='fake-pat', linked_gids={'p1'})

    assert result == [{'gid': 'p2', 'name': 'Acme Corp'}]


def test_returns_empty_list_when_all_projects_already_linked():
    fetch_fn = _fake_fetch({
        '/users/me': {'data': {'workspaces': [{'gid': 'ws1', 'name': 'Camunda'}]}},
        '/workspaces/ws1/projects': {'data': [
            {'gid': 'p1', 'name': 'Acme Financial'},
        ]},
    })

    result = find_new_projects(fetch_fn, pat='fake-pat', linked_gids={'p1'})

    assert result == []


def test_returns_empty_list_when_user_has_no_workspaces():
    fetch_fn = _fake_fetch({
        '/users/me': {'data': {'workspaces': []}},
    })

    result = find_new_projects(fetch_fn, pat='fake-pat', linked_gids=set())

    assert result == []


def test_sorts_results_alphabetically_by_name():
    fetch_fn = _fake_fetch({
        '/users/me': {'data': {'workspaces': [{'gid': 'ws1', 'name': 'Camunda'}]}},
        '/workspaces/ws1/projects': {'data': [
            {'gid': 'p1', 'name': 'Zebra Corp'},
            {'gid': 'p2', 'name': 'Acme Corp'},
        ]},
    })

    result = find_new_projects(fetch_fn, pat='fake-pat', linked_gids=set())

    assert [p['name'] for p in result] == ['Acme Corp', 'Zebra Corp']


def test_skips_projects_missing_gid_or_name():
    fetch_fn = _fake_fetch({
        '/users/me': {'data': {'workspaces': [{'gid': 'ws1', 'name': 'Camunda'}]}},
        '/workspaces/ws1/projects': {'data': [
            {'gid': 'p1', 'name': None},
            {'gid': None, 'name': 'No GID Project'},
            {'gid': 'p2', 'name': 'Valid Project'},
        ]},
    })

    result = find_new_projects(fetch_fn, pat='fake-pat', linked_gids=set())

    assert result == [{'gid': 'p2', 'name': 'Valid Project'}]


def test_dedupes_across_multiple_workspaces():
    fetch_fn = _fake_fetch({
        '/users/me': {'data': {'workspaces': [
            {'gid': 'ws1', 'name': 'Camunda'},
            {'gid': 'ws2', 'name': 'Camunda Sandbox'},
        ]}},
        '/workspaces/ws1/projects': {'data': [{'gid': 'p1', 'name': 'Acme Corp'}]},
        '/workspaces/ws2/projects': {'data': [{'gid': 'p1', 'name': 'Acme Corp'}]},
    })

    result = find_new_projects(fetch_fn, pat='fake-pat', linked_gids=set())

    assert result == [{'gid': 'p1', 'name': 'Acme Corp'}]


def test_get_portfolio_project_names_returns_sorted_names():
    fetch_fn = _fake_fetch({
        '/portfolios/999/items': {'data': [
            {'gid': 'p1', 'name': 'Zebra Corp'},
            {'gid': 'p2', 'name': 'Acme Corp'},
        ]},
    })
    result = get_portfolio_project_names(fetch_fn, pat='fake-pat', portfolio_gid='999')
    assert result == [
        {'gid': 'p2', 'name': 'Acme Corp', 'theater': None},
        {'gid': 'p1', 'name': 'Zebra Corp', 'theater': None},
    ]


def test_get_portfolio_project_names_skips_items_missing_name():
    fetch_fn = _fake_fetch({
        '/portfolios/999/items': {'data': [
            {'gid': 'p1', 'name': 'Acme Corp'},
            {'gid': 'p2'},
        ]},
    })
    result = get_portfolio_project_names(fetch_fn, pat='fake-pat', portfolio_gid='999')
    assert result == [{'gid': 'p1', 'name': 'Acme Corp', 'theater': None}]


def test_get_portfolio_project_names_skips_items_missing_gid():
    fetch_fn = _fake_fetch({
        '/portfolios/999/items': {'data': [
            {'name': 'No GID Project'},
            {'gid': 'p2', 'name': 'Valid Project'},
        ]},
    })
    result = get_portfolio_project_names(fetch_fn, pat='fake-pat', portfolio_gid='999')
    assert result == [{'gid': 'p2', 'name': 'Valid Project', 'theater': None}]


def test_get_portfolio_project_names_returns_empty_list_when_portfolio_empty():
    fetch_fn = _fake_fetch({'/portfolios/999/items': {'data': []}})
    result = get_portfolio_project_names(fetch_fn, pat='fake-pat', portfolio_gid='999')
    assert result == []


def test_get_portfolio_project_names_extracts_theater_custom_field():
    fetch_fn = _fake_fetch({
        '/portfolios/999/items': {'data': [
            {'gid': 'p1', 'name': 'Acme Corp', 'custom_fields': [
                {'name': 'Priority', 'display_value': 'High'},
                {'name': 'Theater', 'display_value': 'AMER'},
            ]},
        ]},
    })
    result = get_portfolio_project_names(fetch_fn, pat='fake-pat', portfolio_gid='999')
    assert result == [{'gid': 'p1', 'name': 'Acme Corp', 'theater': 'AMER'}]


def test_get_portfolio_project_names_theater_field_name_is_case_insensitive():
    fetch_fn = _fake_fetch({
        '/portfolios/999/items': {'data': [
            {'gid': 'p1', 'name': 'Acme Corp', 'custom_fields': [
                {'name': 'THEATER', 'display_value': 'EMEA'},
            ]},
        ]},
    })
    result = get_portfolio_project_names(fetch_fn, pat='fake-pat', portfolio_gid='999')
    assert result == [{'gid': 'p1', 'name': 'Acme Corp', 'theater': 'EMEA'}]


def test_get_portfolio_project_names_theater_is_none_without_that_field():
    fetch_fn = _fake_fetch({
        '/portfolios/999/items': {'data': [
            {'gid': 'p1', 'name': 'Acme Corp', 'custom_fields': [
                {'name': 'Priority', 'display_value': 'High'},
            ]},
        ]},
    })
    result = get_portfolio_project_names(fetch_fn, pat='fake-pat', portfolio_gid='999')
    assert result == [{'gid': 'p1', 'name': 'Acme Corp', 'theater': None}]


def test_match_accounts_to_theaters_exact_gid_match_wins_regardless_of_name():
    accounts = [{'account_name': 'Acme Corp', 'project_gid': 'p1'}]
    items = [{'gid': 'p1', 'name': 'Totally Different Name', 'theater': 'AMER'}]
    result = match_accounts_to_theaters(accounts, items)
    assert result == [{'name': 'Acme Corp', 'theater': 'AMER'}]


def test_match_accounts_to_theaters_fuzzy_fallback_without_project_gid():
    accounts = [{'account_name': 'Acme Corp', 'project_gid': None}]
    items = [{'gid': 'p1', 'name': 'Acme Corp.', 'theater': 'EMEA'}]
    result = match_accounts_to_theaters(accounts, items)
    assert result == [{'name': 'Acme Corp', 'theater': 'EMEA'}]


def test_match_accounts_to_theaters_project_gid_not_in_portfolio_falls_back_to_fuzzy():
    accounts = [{'account_name': 'Acme Corp', 'project_gid': 'not-in-portfolio'}]
    items = [{'gid': 'p1', 'name': 'Acme Corp', 'theater': 'APAC'}]
    result = match_accounts_to_theaters(accounts, items)
    assert result == [{'name': 'Acme Corp', 'theater': 'APAC'}]


def test_match_accounts_to_theaters_below_threshold_is_left_out_of_scope():
    accounts = [{'account_name': 'Acme Corp', 'project_gid': None}]
    items = [{'gid': 'p1', 'name': 'Wildly Unrelated Project', 'theater': 'AMER'}]
    result = match_accounts_to_theaters(accounts, items)
    assert result == []


def test_match_accounts_to_theaters_two_accounts_competing_for_one_name_only_best_wins():
    accounts = [
        {'account_name': 'Acme Corp', 'project_gid': None},
        {'account_name': 'Acme Corpor', 'project_gid': None},
    ]
    items = [{'gid': 'p1', 'name': 'Acme Corp', 'theater': 'AMER'}]
    result = match_accounts_to_theaters(accounts, items)
    assert result == [{'name': 'Acme Corp', 'theater': 'AMER'}]


def test_match_accounts_to_theaters_tie_break_uses_global_best_score_not_alphabetical_order():
    # "Alpine Corporation" (0.7778) and "Ardent Corporation" (0.8333) both
    # score above the 0.72 threshold against the single "Widget
    # Corporation" item. Alphabetically, Alpine sorts first, but Ardent
    # is the better match and must win the item — Alpine must be left
    # unmatched rather than greedily grabbed by whichever account is
    # processed first.
    accounts = [
        {'account_name': 'Alpine Corporation', 'project_gid': None},
        {'account_name': 'Ardent Corporation', 'project_gid': None},
    ]
    items = [{'gid': 'p1', 'name': 'Widget Corporation', 'theater': 'AMER'}]
    result = match_accounts_to_theaters(accounts, items)
    assert result == [{'name': 'Ardent Corporation', 'theater': 'AMER'}]


def test_match_accounts_to_theaters_sorted_by_name():
    accounts = [
        {'account_name': 'Zebra Corp', 'project_gid': 'p2'},
        {'account_name': 'Acme Corp', 'project_gid': 'p1'},
    ]
    items = [
        {'gid': 'p1', 'name': 'Acme Corp', 'theater': 'AMER'},
        {'gid': 'p2', 'name': 'Zebra Corp', 'theater': 'EMEA'},
    ]
    result = match_accounts_to_theaters(accounts, items)
    assert [r['name'] for r in result] == ['Acme Corp', 'Zebra Corp']


def test_match_accounts_to_theaters_skips_accounts_without_account_name():
    accounts = [{'account_name': '', 'project_gid': 'p1'}, {'project_gid': 'p2'}]
    items = [
        {'gid': 'p1', 'name': 'Acme Corp', 'theater': 'AMER'},
        {'gid': 'p2', 'name': 'Zebra Corp', 'theater': 'EMEA'},
    ]
    result = match_accounts_to_theaters(accounts, items)
    assert result == []


def test_match_accounts_to_theaters_returns_empty_list_for_no_accounts():
    result = match_accounts_to_theaters([], [{'gid': 'p1', 'name': 'Acme Corp', 'theater': 'AMER'}])
    assert result == []
