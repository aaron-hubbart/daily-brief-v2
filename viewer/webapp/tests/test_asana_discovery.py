"""Tests for asana_discovery's pure logic (find_new_projects,
get_portfolio_project_names) — no real Asana calls. fetch_fn is faked
so these run with no network access and no mocking library."""
from asana_discovery import find_new_projects, get_portfolio_project_names


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
    assert result == ['Acme Corp', 'Zebra Corp']


def test_get_portfolio_project_names_skips_items_missing_name():
    fetch_fn = _fake_fetch({
        '/portfolios/999/items': {'data': [
            {'gid': 'p1', 'name': 'Acme Corp'},
            {'gid': 'p2'},
        ]},
    })
    result = get_portfolio_project_names(fetch_fn, pat='fake-pat', portfolio_gid='999')
    assert result == ['Acme Corp']


def test_get_portfolio_project_names_returns_empty_list_when_portfolio_empty():
    fetch_fn = _fake_fetch({'/portfolios/999/items': {'data': []}})
    result = get_portfolio_project_names(fetch_fn, pat='fake-pat', portfolio_gid='999')
    assert result == []
