"""
Discovers Asana projects not yet linked to any account in
account-config.json, so the webapp's Customers tab can suggest new
accounts to add via its "Scan for Accounts" button.

Webapp-only discovery: this module only ever talks to Asana. The fuller
four-pass version (email + Slack + Asana + internal-board detection)
lives in the skill's own setup flow (references/first-run-setup.md),
since only the skill has Slack and Outlook MCP connectors — this webapp
has neither, only a stored per-user Asana PAT and Google Drive OAuth.
"""
import re
from difflib import SequenceMatcher
from typing import Callable, Dict, List, Optional, Set

FetchFn = Callable[[str, str, dict], dict]


def find_new_projects(
    fetch_fn: FetchFn,
    pat: str,
    linked_gids: Set[str],
) -> List[Dict[str, str]]:
    """Returns Asana projects visible to this PAT's user that are not
    already referenced by any account's project_gid in account-config.json.

    fetch_fn must match app.py's _asana_api_get(pat, path, params) -> dict
    signature, returning Asana's raw {"data": ...} JSON shape.

    Returns a list of {"gid": str, "name": str} dicts, sorted by name.
    Propagates whatever fetch_fn itself raises on failure (matches
    _asana_api_get's own urllib.error.URLError / json.JSONDecodeError
    contract) — callers are responsible for catching those.
    """
    me = fetch_fn(pat, '/users/me', {'opt_fields': 'workspaces.gid,workspaces.name'})
    workspaces = me.get('data', {}).get('workspaces', [])
    if not workspaces:
        return []

    candidates: List[Dict[str, str]] = []
    seen_gids: Set[str] = set()
    for workspace in workspaces:
        workspace_gid = workspace.get('gid')
        if not workspace_gid:
            continue
        projects = fetch_fn(
            pat, f'/workspaces/{workspace_gid}/projects',
            {'opt_fields': 'name,gid', 'archived': 'false', 'limit': 100},
        )
        for project in projects.get('data', []):
            gid = project.get('gid')
            name = project.get('name')
            if not gid or not name:
                continue
            if gid in linked_gids or gid in seen_gids:
                continue
            seen_gids.add(gid)
            candidates.append({'gid': gid, 'name': name})

    candidates.sort(key=lambda p: p['name'].lower())
    return candidates


def _extract_theater(item: Dict) -> Optional[str]:
    """Returns the display value of whichever of this Asana portfolio
    item's custom_fields is named "Theater" (case-insensitive), or None
    if it has no such field."""
    for field in item.get('custom_fields') or []:
        if (field.get('name') or '').strip().lower() == 'theater':
            return field.get('display_value')
    return None


def get_portfolio_project_names(
    fetch_fn: FetchFn,
    pat: str,
    portfolio_gid: str,
) -> List[Dict[str, Optional[str]]]:
    """Returns {"gid", "name", "theater"} for every project currently in
    the given Asana portfolio, sorted by name (case-insensitive) — used by
    the Environments tab to determine which account-config.json customers
    are in scope (see match_accounts_to_theaters) and to source the Region
    filter's values from each project's Asana "Theater" custom field.

    fetch_fn must match app.py's _asana_api_get(pat, path, params) -> dict
    signature. Propagates whatever fetch_fn itself raises on failure
    (matches _asana_api_get's own urllib.error.URLError /
    json.JSONDecodeError contract) — callers are responsible for catching
    those.
    """
    items = fetch_fn(pat, f'/portfolios/{portfolio_gid}/items', {
        'opt_fields': 'name,custom_fields.name,custom_fields.display_value',
    })
    projects = [
        {'gid': item['gid'], 'name': item['name'], 'theater': _extract_theater(item)}
        for item in items.get('data', [])
        if item.get('gid') and item.get('name')
    ]
    projects.sort(key=lambda p: p['name'].lower())
    return projects


def _normalize_name(name: str) -> str:
    """Lowercases, strips punctuation, and collapses whitespace so names
    like "Acme, Inc." and "Acme Inc" compare as equal or near-equal."""
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', '', name.lower())).strip()


def match_accounts_to_theaters(
    accounts: List[Dict],
    portfolio_items: List[Dict[str, Optional[str]]],
    fuzzy_threshold: float = 0.72,
) -> List[Dict[str, Optional[str]]]:
    """Matches account-config.json's accounts against the Environments
    Asana portfolio's items (as returned by get_portfolio_project_names),
    to determine which customers are in scope for the Environments tab and
    what Asana "Theater" value each one has.

    Matching is exact-first: an account whose 'project_gid' equals one of
    the portfolio item gids is matched to that item regardless of name —
    project_gid is already used elsewhere in this app to identify a
    customer's Asana project, so it doubles as an explicit manual mapping
    here. Any account left unmatched (no project_gid, or one not present in
    this portfolio) is fuzzy-matched by name against whichever portfolio
    items no other account has already claimed, using a normalized
    difflib.SequenceMatcher ratio; the best-scoring available item above
    fuzzy_threshold is claimed. An account with no candidate above the
    threshold is left out of scope entirely (same behavior as today's
    exact-match-only logic, just with better recall).

    Returns [{"name": account_name, "theater": theater_or_none}, ...]
    sorted by name (case-insensitive).
    """
    items_by_gid = {item['gid']: item for item in portfolio_items}
    claimed_gids: Set[str] = set()
    results: List[Dict[str, Optional[str]]] = []
    unmatched_accounts: List[Dict] = []

    for account in accounts:
        name = account.get('account_name')
        if not name:
            continue
        gid = account.get('project_gid')
        if gid and gid in items_by_gid:
            results.append({'name': name, 'theater': items_by_gid[gid].get('theater')})
            claimed_gids.add(gid)
        else:
            unmatched_accounts.append(account)

    for account in sorted(unmatched_accounts, key=lambda a: a['account_name'].lower()):
        name = account['account_name']
        normalized_name = _normalize_name(name)
        best_item = None
        best_score = 0.0
        for item in portfolio_items:
            if item['gid'] in claimed_gids:
                continue
            score = SequenceMatcher(None, normalized_name, _normalize_name(item['name'])).ratio()
            if score > best_score:
                best_score = score
                best_item = item
        if best_item and best_score >= fuzzy_threshold:
            results.append({'name': name, 'theater': best_item.get('theater')})
            claimed_gids.add(best_item['gid'])

    results.sort(key=lambda r: r['name'].lower())
    return results
