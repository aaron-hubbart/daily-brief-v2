# Environments Theater/Region Matching & Collapsible UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Source the Environments tab's Region filter from Asana's per-project "Theater" custom field, make the in-scope customer match robust (exact via existing `project_gid`, fuzzy fallback by name), and restructure the page's Teams/Environments UI to be collapsible and grouped by team, with save status moved off the bottom of the page.

**Architecture:** Backend: `asana_discovery.py` gains Theater extraction on `get_portfolio_project_names` and a new pure `match_accounts_to_theaters` function; `app.py`'s `/api/environments/config` wires both together using the already-loaded `account-config.json`. Frontend: `environments.html`'s JS switches its data model from a bare name list to `{name, theater}` objects, adds a small generic collapsible/persistence mechanism reused by three UI pieces (teams, environment groups, individual environment cards), and moves save-status text next to the Save button.

**Tech Stack:** Python 3.12 / Flask (backend), vanilla JS in a Jinja template (frontend, no build step, no JS test framework — matches this codebase throughout). `difflib.SequenceMatcher` (stdlib) for fuzzy matching — no new dependency.

## Global Constraints

- Fuzzy-match threshold is `0.72` on a normalized (lowercased, punctuation-stripped, whitespace-collapsed) `difflib.SequenceMatcher.ratio()`.
- An account's `project_gid` (already stored in `account-config.json`, already used elsewhere for Asana task fetching) is the exact-match key — it is the "manual override," no new mapping schema or UI is introduced.
- The per-environment `deployment.region` free-text field (infra region, e.g. `us-east-1`) is untouched — it is a separate concept from the Asana Theater value the Region filter now uses.
- No native `<details>/<summary>` for collapsibility — team/environment headers contain editable inputs and buttons that would conflict with `<summary>`'s click-to-toggle. Use an explicit caret button instead.
- Default collapse state (no localStorage entry yet) is **collapsed**. Expanded state is persisted per-customer in `localStorage` under key `env-tab:expanded:<customer name>`.
- An environment linked to multiple teams renders under every one of its teams' groups, always via the same real index into `c.environments` — never a per-group copy — so editing it anywhere edits the same object.
- No automated tests exist (or are added) for Flask routes, `gdrive_briefs.py`, or the JS in `environments.html` — this matches the existing, consistent coverage level of this whole codebase (confirmed in the prior Environments Tab plan's own Global Constraints). Only the pure-logic functions in `asana_discovery.py` get real `pytest` tests, following its existing injectable-`fetch_fn` pattern.
- Response field rename: `in_scope_names: string[]` → `in_scope_customers: {name: string, theater: string|null}[]` in the `/api/environments/config` GET response.

---

### Task 1: Extract the Asana "Theater" custom field in `get_portfolio_project_names`

**Files:**
- Modify: `viewer/webapp/asana_discovery.py`
- Test: `viewer/webapp/tests/test_asana_discovery.py`

**Interfaces:**
- Consumes: nothing new — same `FetchFn` type already defined in this module.
- Produces: `get_portfolio_project_names(fetch_fn, pat, portfolio_gid) -> List[Dict]`, each dict `{"gid": str, "name": str, "theater": Optional[str]}`, sorted by `name` (case-insensitive). **Breaking change** from the current `List[str]` return — Task 3 depends on this new shape.

This is a pure function change with real tests (no network, no mocking library — `fetch_fn` is faked), same pattern as every other function in this module.

- [ ] **Step 1: Write the failing tests**

Replace the three existing `get_portfolio_project_names` tests in `viewer/webapp/tests/test_asana_discovery.py` (currently the last three tests in the file, `test_get_portfolio_project_names_returns_sorted_names` through `test_get_portfolio_project_names_returns_empty_list_when_portfolio_empty`) with:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd viewer/webapp
python -m pytest tests/test_asana_discovery.py -v -k get_portfolio_project_names
```

Expected: FAIL — either `AssertionError` (return shape is still `List[str]`) since the implementation hasn't changed yet.

- [ ] **Step 3: Implement the Theater extraction and new return shape**

In `viewer/webapp/asana_discovery.py`, replace the `get_portfolio_project_names` function (currently the last function in the file) with:

```python
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
```

Also update the module's import line (currently `from typing import Callable, Dict, List, Set`) to add `Optional`:

```python
from typing import Callable, Dict, List, Optional, Set
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_asana_discovery.py -v -k get_portfolio_project_names
```

Expected: 7 passed (the updated 3 + 4 new).

- [ ] **Step 5: Run the full test file to confirm nothing else broke**

```bash
python -m pytest tests/test_asana_discovery.py -v
```

Expected: all tests pass (the 6 `find_new_projects` tests are untouched, plus the 7 from this task).

- [ ] **Step 6: Commit**

```bash
git add viewer/webapp/asana_discovery.py viewer/webapp/tests/test_asana_discovery.py
git commit -m "Extract Asana Theater custom field in get_portfolio_project_names"
```

---

### Task 2: `match_accounts_to_theaters` — exact `project_gid` match with fuzzy fallback

**Files:**
- Modify: `viewer/webapp/asana_discovery.py`
- Test: `viewer/webapp/tests/test_asana_discovery.py`

**Interfaces:**
- Consumes: `get_portfolio_project_names`'s output shape from Task 1 (`List[{"gid", "name", "theater"}]`), and `account-config.json`'s `accounts` list shape (`List[{"account_name": str, "project_gid": Optional[str], ...}]`, per `gdrive_briefs.read_account_config`).
- Produces: `match_accounts_to_theaters(accounts, portfolio_items, fuzzy_threshold=0.72) -> List[Dict]`, each `{"name": str, "theater": Optional[str]}`, sorted by `name` (case-insensitive). Task 3 depends on this exact function name and signature.

- [ ] **Step 1: Write the failing tests**

Add to the end of `viewer/webapp/tests/test_asana_discovery.py`:

```python
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
```

Also update the module's import line at the top of the test file (currently `from asana_discovery import find_new_projects, get_portfolio_project_names`):

```python
from asana_discovery import find_new_projects, get_portfolio_project_names, match_accounts_to_theaters
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_asana_discovery.py -v -k match_accounts_to_theaters
```

Expected: FAIL with `ImportError: cannot import name 'match_accounts_to_theaters'`.

- [ ] **Step 3: Implement `match_accounts_to_theaters`**

In `viewer/webapp/asana_discovery.py`, add near the top (after the `FetchFn` type alias) the two new imports the module now needs:

```python
import re
from difflib import SequenceMatcher
```

Then add this function at the end of the file (after `get_portfolio_project_names` / `_extract_theater` from Task 1):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_asana_discovery.py -v -k match_accounts_to_theaters
```

Expected: 8 passed.

- [ ] **Step 5: Run the full test file**

```bash
python -m pytest tests/test_asana_discovery.py -v
```

Expected: all 21 tests pass (6 `find_new_projects` + 7 `get_portfolio_project_names` + 8 `match_accounts_to_theaters`).

- [ ] **Step 6: Commit**

```bash
git add viewer/webapp/asana_discovery.py viewer/webapp/tests/test_asana_discovery.py
git commit -m "Add match_accounts_to_theaters: exact project_gid match with fuzzy name fallback"
```

---

### Task 3: Wire `/api/environments/config` to the new matching logic

**Files:**
- Modify: `viewer/webapp/app.py:1131-1158`

**Interfaces:**
- Consumes: `asana_discovery.get_portfolio_project_names` (Task 1) and `asana_discovery.match_accounts_to_theaters` (Task 2); `gdrive_briefs.read_account_config(refresh_token, folder_id) -> Optional[Dict]` (already exists, returns a dict with an `accounts` key).
- Produces: `GET /api/environments/config` now returns `in_scope_customers` (list of `{name, theater}`) instead of `in_scope_names` (list of `str`). Task 4 depends on this new field name and shape.

No automated test for this route (see Global Constraints) — verified by a syntax check here and manually in Task 8.

- [ ] **Step 1: Replace the route implementation**

In `viewer/webapp/app.py`, replace the `api_environments_config` function:

```python
@app.route('/api/environments/config')
@login_required
def api_environments_config():
    """Returns saved environments-config.json data plus the current
    in-scope customer name list (from the Asana portfolio)."""
    google_token = db.get_google_refresh_token(request.brief_user['id'])
    folder_id = db.get_google_drive_folder_id(request.brief_user['id'])
    if not google_token:
        return jsonify({'error': 'Google Drive not connected'}), 400
    config = gdrive_briefs.read_environments_config(google_token, folder_id)
    if config is None:
        return jsonify({'error': 'Could not read environments-config.json'}), 500

    pat = db.get_asana_pat(request.brief_user['id'])
    if not pat:
        return jsonify({'customers': config, 'in_scope_names': None, 'needs_pat': True})

    try:
        in_scope_names = asana_discovery.get_portfolio_project_names(
            _asana_api_get, pat, ENVIRONMENTS_PORTFOLIO_GID,
        )
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        return jsonify({
            'customers': config, 'in_scope_names': None,
            'error': f'Could not load customer list from Asana: {e}',
        })

    return jsonify({'customers': config, 'in_scope_names': in_scope_names})
```

with:

```python
@app.route('/api/environments/config')
@login_required
def api_environments_config():
    """Returns saved environments-config.json data plus the current
    in-scope customer list (name + Asana Theater), matched against
    account-config.json via project_gid (exact) or a fuzzy name match —
    see asana_discovery.match_accounts_to_theaters."""
    google_token = db.get_google_refresh_token(request.brief_user['id'])
    folder_id = db.get_google_drive_folder_id(request.brief_user['id'])
    if not google_token:
        return jsonify({'error': 'Google Drive not connected'}), 400
    config = gdrive_briefs.read_environments_config(google_token, folder_id)
    if config is None:
        return jsonify({'error': 'Could not read environments-config.json'}), 500

    pat = db.get_asana_pat(request.brief_user['id'])
    if not pat:
        return jsonify({'customers': config, 'in_scope_customers': None, 'needs_pat': True})

    try:
        portfolio_items = asana_discovery.get_portfolio_project_names(
            _asana_api_get, pat, ENVIRONMENTS_PORTFOLIO_GID,
        )
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        return jsonify({
            'customers': config, 'in_scope_customers': None,
            'error': f'Could not load customer list from Asana: {e}',
        })

    account_config = gdrive_briefs.read_account_config(google_token, folder_id)
    accounts = (account_config or {}).get('accounts', [])
    in_scope_customers = asana_discovery.match_accounts_to_theaters(accounts, portfolio_items)

    return jsonify({'customers': config, 'in_scope_customers': in_scope_customers})
```

- [ ] **Step 2: Syntax-check the file**

```bash
python -c "import ast; ast.parse(open('viewer/webapp/app.py').read())"
```

Expected: no output (no `SyntaxError`).

- [ ] **Step 3: Commit**

```bash
git add viewer/webapp/app.py
git commit -m "Wire /api/environments/config to Theater-based matching"
```

---

### Task 4: Frontend — Region filter driven by Theater, `in_scope_customers` rename

**Files:**
- Modify: `viewer/webapp/templates/environments.html`

**Interfaces:**
- Consumes: `GET /api/environments/config`'s new `in_scope_customers: {name, theater}[]` field (Task 3).
- Produces: the Region toolbar dropdown now lists distinct Theater values; selecting one filters the customer `<select>` by that customer's own Theater. No change to any function name/signature other functions in this file rely on (`visibleCustomerNames()` keeps its name and no-arg signature; `allRegions()`/`customerHasRegion()` are removed and have no other callers).

- [ ] **Step 1: Replace `allRegions()` and `customerHasRegion()`**

In `viewer/webapp/templates/environments.html`, replace:

```javascript
function allRegions() {
  const regions = new Set();
  Object.values(STATE.customers || {}).forEach(c => {
    (c.environments || []).forEach(env => {
      const region = (env.deployment || {}).region;
      if (region) regions.add(region);
    });
  });
  return Array.from(regions).sort();
}

function customerHasRegion(name, region) {
  const c = STATE.customers[name];
  if (!c) return false;
  return (c.environments || []).some(env => (env.deployment || {}).region === region);
}
```

with:

```javascript
function allRegions() {
  const regions = new Set();
  (STATE.in_scope_customers || []).forEach(c => {
    if (c.theater) regions.add(c.theater);
  });
  return Array.from(regions).sort();
}

function customerTheater(name) {
  const match = (STATE.in_scope_customers || []).find(c => c.name === name);
  return match ? match.theater : null;
}
```

- [ ] **Step 2: Update `visibleCustomerNames()`**

Replace:

```javascript
function visibleCustomerNames() {
  let names = STATE.in_scope_names || [];
  if (filterMyCustomers) names = names.filter(n => MY_CUSTOMER_NAMES.has(n));
  if (filterRegion) names = names.filter(n => customerHasRegion(n, filterRegion));
  return names;
}
```

with:

```javascript
function visibleCustomerNames() {
  let names = (STATE.in_scope_customers || []).map(c => c.name);
  if (filterMyCustomers) names = names.filter(n => MY_CUSTOMER_NAMES.has(n));
  if (filterRegion) names = names.filter(n => customerTheater(n) === filterRegion);
  return names;
}
```

- [ ] **Step 3: Update `renderCustomerSelect()`'s two `in_scope_names` checks**

Replace:

```javascript
  if (STATE.in_scope_names === null) {
    select.innerHTML = '<option value="">—</option>';
    content.innerHTML = `<div class="hint" style="color:var(--bad-t)">${esc(STATE.error || 'Could not determine the customer list.')}</div>`;
    return;
  }
  if (!STATE.in_scope_names.length) {
    select.innerHTML = '<option value="">—</option>';
    content.innerHTML = '<div class="empty">No customers found in the Environments portfolio.</div>';
    return;
  }
```

with:

```javascript
  if (STATE.in_scope_customers === null) {
    select.innerHTML = '<option value="">—</option>';
    content.innerHTML = `<div class="hint" style="color:var(--bad-t)">${esc(STATE.error || 'Could not determine the customer list.')}</div>`;
    return;
  }
  if (!STATE.in_scope_customers.length) {
    select.innerHTML = '<option value="">—</option>';
    content.innerHTML = '<div class="empty">No customers found in the Environments portfolio.</div>';
    return;
  }
```

- [ ] **Step 4: Manual spot-check**

No JS test harness exists for this file (see Global Constraints) — this is a quick sanity check, not the full walkthrough (that's Task 8). Open the file and confirm by reading it that no other reference to `in_scope_names`, `allRegions`, or `customerHasRegion` remains:

```bash
grep -n "in_scope_names\|customerHasRegion" viewer/webapp/templates/environments.html
```

Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add viewer/webapp/templates/environments.html
git commit -m "Drive Environments Region filter from Asana Theater instead of infra region"
```

---

### Task 5: Frontend — collapsible mechanism + Teams panel

**Files:**
- Modify: `viewer/webapp/templates/environments.html`

**Interfaces:**
- Produces: `isExpanded(id)`, `toggleExpanded(id)`, `caretHtml(id)`, `wireCarets()`, `loadExpandedIds(name)` — reused by Task 6 for environment groups/cards. `collapsible-body` / `collapsed` CSS classes — reused by Task 6.

- [ ] **Step 1: Add collapsible CSS**

In `viewer/webapp/templates/environments.html`, in the `<style>` block, immediately after the existing `.team-card-body{padding:10px 12px;}` rule, add:

```css
.caret-btn{border:none;background:none;cursor:pointer;font-size:11px;color:var(--t3);padding:2px 4px;line-height:1;}
.caret-btn:hover{color:var(--t1);}
.collapsible-body.collapsed{display:none;}
```

- [ ] **Step 2: Add the collapse-state helpers**

Immediately after the existing `let addTeamDraft = {existingEnvIds: new Set(), newEnvs: []};` line, add:

```javascript
let expandedIds = new Set();

function expandedStorageKey(name) {
  return `env-tab:expanded:${name}`;
}

function loadExpandedIds(name) {
  try {
    const raw = localStorage.getItem(expandedStorageKey(name));
    expandedIds = new Set(raw ? JSON.parse(raw) : []);
  } catch(e) {
    expandedIds = new Set();
  }
}

function saveExpandedIds() {
  try {
    localStorage.setItem(expandedStorageKey(CURRENT), JSON.stringify(Array.from(expandedIds)));
  } catch(e) { /* localStorage unavailable — collapse state just won't persist */ }
}

function isExpanded(id) {
  return expandedIds.has(id);
}

function toggleExpanded(id) {
  if (expandedIds.has(id)) expandedIds.delete(id);
  else expandedIds.add(id);
  saveExpandedIds();
  renderCustomer();
}

function caretHtml(id) {
  return `<button type="button" class="caret-btn" data-toggle-id="${escAttr(id)}" aria-label="Toggle">${isExpanded(id) ? '▾' : '▸'}</button>`;
}

function wireCarets() {
  document.querySelectorAll('.caret-btn').forEach(btn => {
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      toggleExpanded(this.dataset.toggleId);
    });
  });
}
```

(`▾`/`▸` are ▾/▸ — written as escapes here so the plan file itself stays plain ASCII; write the literal ▾/▸ characters, or the escapes, either works in a JS string.)

- [ ] **Step 3: Load expanded ids and wire carets on every render**

In `renderCustomer()`, add a first line and one more call at the end. Replace:

```javascript
function renderCustomer() {
  addTeamDraft = {existingEnvIds: new Set(), newEnvs: []};
  const c = STATE.customers[CURRENT];
  const content = document.getElementById('content');
  content.innerHTML = `
    <div class="panel">
      <div class="panel-head"><span>Teams</span></div>
      <div class="panel-body" id="teams-body">${teamCardsHtml(c)}</div>
    </div>
    <div class="panel">
      <div class="panel-head">
        <span>Environments</span>
        <button class="btn primary" onclick="addEnvironment()">Add environment</button>
      </div>
      <div class="panel-body" id="envs-body">${environmentsHtml(c)}</div>
    </div>
  `;
  wireTeamCheckboxes();
  wireNewEnvSelect();
}
```

with:

```javascript
function renderCustomer() {
  loadExpandedIds(CURRENT);
  addTeamDraft = {existingEnvIds: new Set(), newEnvs: []};
  const c = STATE.customers[CURRENT];
  const content = document.getElementById('content');
  content.innerHTML = `
    <div class="panel">
      <div class="panel-head"><span>Teams</span></div>
      <div class="panel-body" id="teams-body">${teamCardsHtml(c)}</div>
    </div>
    <div class="panel">
      <div class="panel-head">
        <span>Environments</span>
        <button class="btn primary" onclick="addEnvironment()">Add environment</button>
      </div>
      <div class="panel-body" id="envs-body">${environmentsHtml(c)}</div>
    </div>
  `;
  wireTeamCheckboxes();
  wireNewEnvSelect();
  wireCarets();
}
```

- [ ] **Step 4: Make team cards collapsible**

Replace:

```javascript
function teamCardHtml(team, idx) {
  return `
    <div class="team-card">
      <div class="team-card-head">
        <input type="text" value="${escAttr(team.name)}" onchange="updateTeamField(${idx}, 'name', this.value)">
        <button class="btn danger" onclick="removeTeam(${idx})">Remove</button>
      </div>
      <div class="team-card-body">
        <div class="field"><label>Notes</label><textarea onchange="updateTeamField(${idx}, 'notes', this.value)">${esc(team.notes || '')}</textarea></div>
        <div class="field">
          <label>Members</label>
          ${memberRowsHtml(idx, team.members)}
        </div>
      </div>
    </div>
  `;
}
```

with:

```javascript
function teamCardHtml(team, idx) {
  const collapsed = isExpanded(team.id) ? '' : 'collapsed';
  return `
    <div class="team-card">
      <div class="team-card-head">
        ${caretHtml(team.id)}
        <input type="text" value="${escAttr(team.name)}" onchange="updateTeamField(${idx}, 'name', this.value)">
        <button class="btn danger" onclick="removeTeam(${idx})">Remove</button>
      </div>
      <div class="team-card-body collapsible-body ${collapsed}">
        <div class="field"><label>Notes</label><textarea onchange="updateTeamField(${idx}, 'notes', this.value)">${esc(team.notes || '')}</textarea></div>
        <div class="field">
          <label>Members</label>
          ${memberRowsHtml(idx, team.members)}
        </div>
      </div>
    </div>
  `;
}
```

- [ ] **Step 5: Manual spot-check**

Start the dev server (see Task 8 Step 1 for the exact command) and confirm in the browser: each team card shows a caret, clicking it toggles its body, and the state (expanded/collapsed) survives a page reload for that customer. Stop the server afterward.

- [ ] **Step 6: Commit**

```bash
git add viewer/webapp/templates/environments.html
git commit -m "Add collapsible mechanism and make Teams panel collapsible"
```

---

### Task 6: Frontend — Environments grouped by team, collapsible

**Files:**
- Modify: `viewer/webapp/templates/environments.html`

**Interfaces:**
- Consumes: `isExpanded`, `caretHtml`, `wireCarets` from Task 5.
- Produces: `environmentsHtml(c)` keeps its existing name/signature (called from `renderCustomer()`, unchanged call site) but now groups its output by team; `environmentGroupHtml(group, teams)` is new and only used internally by `environmentsHtml`.

- [ ] **Step 1: Add group CSS**

In the `<style>` block, immediately after `.env-card-body{padding:10px 12px;}`, add:

```css
.env-group{border:1px solid var(--border);border-radius:var(--r);margin-bottom:12px;overflow:hidden;}
.group-head{padding:8px 12px;background:var(--surface2);display:flex;align-items:center;gap:6px;font-size:11px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:var(--t3);}
.group-body{padding:10px 12px;}
```

- [ ] **Step 2: Group `environmentsHtml` by team**

Replace:

```javascript
function environmentsHtml(c) {
  if (!c.environments.length) return '<div class="empty">No environments yet</div>';
  return c.environments.map((env, i) => environmentCardHtml(env, i, c.teams)).join('');
}
```

with:

```javascript
function environmentsHtml(c) {
  if (!c.environments.length) return '<div class="empty">No environments yet</div>';

  const indexed = c.environments.map((env, idx) => ({env, idx}));
  const groups = c.teams.map(team => ({
    id: 'group-' + team.id,
    label: team.name,
    entries: indexed.filter(({env}) => (env.team_ids || []).includes(team.id)),
  }));

  const validTeamIds = new Set(c.teams.map(t => t.id));
  const unassigned = indexed.filter(
    ({env}) => !(env.team_ids || []).some(id => validTeamIds.has(id))
  );
  groups.push({id: 'group-unassigned', label: 'Unassigned', entries: unassigned});

  return groups
    .filter(g => g.entries.length)
    .map(g => environmentGroupHtml(g, c.teams))
    .join('');
}

function environmentGroupHtml(group, teams) {
  const collapsed = isExpanded(group.id) ? '' : 'collapsed';
  const cards = group.entries.map(({env, idx}) => environmentCardHtml(env, idx, teams)).join('');
  return `
    <div class="env-group">
      <div class="group-head">
        ${caretHtml(group.id)}
        <span>${esc(group.label)} (${group.entries.length})</span>
      </div>
      <div class="group-body collapsible-body ${collapsed}">${cards}</div>
    </div>
  `;
}
```

- [ ] **Step 3: Make individual environment cards collapsible**

Replace the opening of `environmentCardHtml` (the `<div class="env-card">` block — the `teamChecks`/`componentChecks` computation above it and the rest of the card body below are unchanged):

```javascript
  return `
    <div class="env-card">
      <div class="env-card-head">
        <input type="text" value="${escAttr(env.label)}" onchange="updateEnvField(${idx}, 'label', this.value)" style="font-weight:600;font-size:12.5px;">
        <button class="btn danger" onclick="removeEnvironment(${idx})">Remove</button>
      </div>
      <div class="env-card-body">
```

with:

```javascript
  const collapsed = isExpanded(env.id) ? '' : 'collapsed';
  return `
    <div class="env-card">
      <div class="env-card-head">
        ${caretHtml(env.id)}
        <input type="text" value="${escAttr(env.label)}" onchange="updateEnvField(${idx}, 'label', this.value)" style="font-weight:600;font-size:12.5px;">
        <button class="btn danger" onclick="removeEnvironment(${idx})">Remove</button>
      </div>
      <div class="env-card-body collapsible-body ${collapsed}">
```

(The card's closing `</div></div>\`;\n}\`` at the end of `environmentCardHtml` needs no change — only the two opening lines shown above change.)

- [ ] **Step 4: Manual spot-check**

Start the dev server (Task 8 Step 1) and confirm: environments render grouped under each team's name with a count, plus a trailing "Unassigned" group for environments with no team; checking a second team's checkbox on an environment makes it appear in both groups; editing a field in either copy updates the same environment (reflected in both places after the next render); each group and each environment card collapses independently and that state survives reload. Stop the server afterward.

- [ ] **Step 5: Commit**

```bash
git add viewer/webapp/templates/environments.html
git commit -m "Group Environments panel by team, made collapsible"
```

---

### Task 7: Frontend — move save confirmation next to the Save button

**Files:**
- Modify: `viewer/webapp/templates/environments.html`

**Interfaces:**
- Produces: no new functions; `markDirty()` and `saveAll()` keep their existing names/signatures (called from many existing `onchange` handlers and `onclick="saveAll()"` — unchanged call sites).

- [ ] **Step 1: Replace the header markup and remove the bottom message div**

Replace:

```html
<div class="head">
  <div>
    <a class="back" href="{{ url_for('index') }}">&larr; Back to briefs</a>
    <h1>Environments</h1>
    <div class="sub">Signed in as {{ user_email }}</div>
  </div>
  <button class="btn save" id="save-btn" onclick="saveAll()" disabled>Save to Drive</button>
</div>
```

with:

```html
<div class="head">
  <div>
    <a class="back" href="{{ url_for('index') }}">&larr; Back to briefs</a>
    <h1>Environments</h1>
    <div class="sub">Signed in as {{ user_email }}</div>
  </div>
  <div style="display:flex;align-items:center;gap:8px;">
    <span class="save-status" id="save-status"></span>
    <button class="btn save" id="save-btn" onclick="saveAll()" disabled>Save to Drive</button>
  </div>
</div>
```

Replace:

```html
<div id="content"><div class="empty">Loading&hellip;</div></div>
<div class="msg" id="msg"></div>
```

with:

```html
<div id="content"><div class="empty">Loading&hellip;</div></div>
```

- [ ] **Step 2: Add the status span's CSS**

In the `<style>` block, immediately after the existing `.msg{font-size:11.5px;color:var(--t3);margin-top:10px;min-height:1.2em;}` rule, replace that whole rule with:

```css
.save-status{font-size:11.5px;color:var(--t3);}
```

- [ ] **Step 3: Update `markDirty()`**

Replace:

```javascript
function markDirty() {
  dirty = true;
  document.getElementById('save-btn').disabled = false;
  document.getElementById('msg').textContent = 'Unsaved changes';
}
```

with:

```javascript
function markDirty() {
  dirty = true;
  document.getElementById('save-btn').disabled = false;
  document.getElementById('save-status').textContent = 'Unsaved changes';
}
```

- [ ] **Step 4: Update `saveAll()`**

Replace:

```javascript
async function saveAll() {
  const btn = document.getElementById('save-btn');
  const msg = document.getElementById('msg');
  btn.disabled = true;
  msg.textContent = 'Saving…';
  try {
    const r = await fetch(`${BASE}api/environments/config`, {
      method: 'PUT', credentials: 'include',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({customers: STATE.customers}),
    });
    if (!r.ok) throw new Error((await r.json()).error || r.statusText);
    dirty = false;
    msg.textContent = '';
    showToast('Saved to Drive', 'ok', 4000);
  } catch(e) {
    showToast('Save failed: ' + e.message, 'err', 5000);
    btn.disabled = false;
  }
}
```

with:

```javascript
async function saveAll() {
  const btn = document.getElementById('save-btn');
  const status = document.getElementById('save-status');
  btn.disabled = true;
  status.textContent = 'Saving…';
  try {
    const r = await fetch(`${BASE}api/environments/config`, {
      method: 'PUT', credentials: 'include',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({customers: STATE.customers}),
    });
    if (!r.ok) throw new Error((await r.json()).error || r.statusText);
    dirty = false;
    status.textContent = '';
    showToast('Saved to Drive', 'ok', 4000);
  } catch(e) {
    showToast('Save failed: ' + e.message, 'err', 5000);
    status.textContent = 'Unsaved changes';
    btn.disabled = false;
  }
}
```

- [ ] **Step 5: Manual spot-check**

```bash
grep -n "id=\"msg\"\|getElementById('msg')" viewer/webapp/templates/environments.html
```

Expected: no output (no remaining reference to the removed `#msg` element).

- [ ] **Step 6: Commit**

```bash
git add viewer/webapp/templates/environments.html
git commit -m "Move Environments save status next to the Save button"
```

---

### Task 8: End-to-end manual verification

No further code changes. Confirms Tasks 1–7 work together, to the same standard of coverage every other route/page in this app gets (see Global Constraints).

- [ ] **Step 1: Automated portion — full test suite and route auth-gating**

```bash
cd viewer/webapp
python -m pytest tests/ -v
```

Expected: all tests pass, including all 21 `test_asana_discovery.py` tests from Tasks 1–2.

Start the dev server with placeholder secrets (no real Azure AD or Postgres needed for this check):

```bash
FLASK_SECRET_KEY=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcd AZURE_TENANT_ID=00000000-0000-0000-0000-000000000000 AZURE_CLIENT_ID=00000000-0000-0000-0000-000000000000 AZURE_CLIENT_SECRET=placeholder AZURE_REDIRECT_URI=http://localhost:8000/auth/callback python app.py
```

In another terminal:

```bash
curl -s -D - -o /dev/null http://127.0.0.1:8000/environments | grep -i location
curl -s -D - -o /dev/null http://127.0.0.1:8000/api/environments/config | grep -i location
```

Expected: both print `Location: /login` — confirming `/api/environments/config` still enforces `@login_required` after the route body changed. Stop the server afterward.

- [ ] **Step 2: Manual portion — needs a real sign-in, Asana PAT, and Google Drive connection**

These require your own Camunda Azure AD credentials and cannot be done by an agent:

1. Sign in, open Environments. Confirm the Region dropdown now lists Asana Theater values (e.g. AMER/EMEA/APAC) instead of being empty/"All regions"-only.
2. Pick a customer whose `account-config.json` entry has a `project_gid` matching one of the Environments portfolio's projects. Confirm they appear in scope with the correct Theater, even if their Asana project's name doesn't exactly match their `account_name`.
3. If you have a customer whose `account_name` is a close-but-not-exact match to an Asana project name (and no `project_gid` set), confirm they're now picked up via fuzzy matching. If you don't have such a case handy, temporarily rename one customer's `account_name` slightly (via the Customers tab) to test this, then revert it.
4. For a customer, expand a team, expand an environment. Reload the page — confirm the same expand/collapse state comes back. Collapse it again — confirm it's remembered too.
5. Link one environment to two teams (via its team checkboxes). Confirm it now shows up under both teams' groups in the Environments panel, and editing a field (e.g. Notes) in one copy shows the updated value in the other after the panel re-renders.
6. Remove an environment's only team link (uncheck all its teams). Confirm it moves to the "Unassigned" group.
7. Make an edit, confirm "Unsaved changes" appears next to the Save button (not at the bottom of the page). Click "Save to Drive" — confirm it briefly shows "Saving…" next to the button, then clears, and the existing top-center toast shows "Saved to Drive".
8. Reload the page. Confirm every value you touched in steps 5–7 round-tripped through `environments-config.json` in Drive correctly.
