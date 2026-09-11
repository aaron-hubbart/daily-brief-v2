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
from typing import Callable, Dict, List, Set

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
            {'opt_fields': 'name,gid', 'archived': 'false'},
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
