# Setup Flow Redesign & Account Finder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the daily-brief skill's three-phase First-Run Setup with a faster minimal→discovery→confirmation flow, and add a reusable "Account Finder" so users can scan for new accounts anytime — fully (email+Slack+Asana) from the skill, Asana-only from the webapp's Customers tab.

**Architecture:** Two independent subsystems that share the same `account-config.json` shape (`references/item-sync.md`) but run in different environments:
- **Skill side** (`SKILL.md` + a new `references/first-run-setup.md`): conversational markdown instructions Claude follows during a chat. Has full MCP connector access (Outlook, Slack, Asana, Google Drive). No automated tests are possible here — verification is manual/conversational, matching this repo's existing testing convention for skill behavior.
- **Webapp side** (`viewer/webapp/`): a new pure-logic module (`asana_discovery.py`), a new Flask route, and a UI addition to `customers.html`. Has only a stored per-user Asana PAT (`db.get_asana_pat`) and Google Drive OAuth — no Slack or Outlook access — so its discovery is Asana-only. The pure-logic piece gets real unit tests; the Flask route and frontend follow this codebase's existing untested-route/untested-JS convention (see Global Constraints).

**Tech Stack:** Python 3 / Flask (existing `viewer/webapp/app.py`), vanilla JS in `customers.html` (existing, no framework), pytest (newly introduced for this plan), Markdown skill instructions (`SKILL.md`, `references/`).

## Global Constraints

- Field names in every `account-config.json` read/write MUST match the existing schema exactly: `account_name`, `tier`, `run_day`, `slack_channel_name`, `slack_channel_id`, `supporting_slack_channel_ids`, `project_gid` (NOT `asana_project_gid`), `asana_board_name`, `gdrive_folder_id`. Top-level `internal_project_gid` lives in `account-config.json`, not `config.json`. Source of truth: `references/item-sync.md` lines 52-76 and the existing `viewer/webapp/templates/customers.html`.
- The webapp has no Slack or Outlook access. Any webapp-side discovery feature is Asana-only — never imply otherwise in UI copy or code comments.
- Nothing is written to Google Drive from the skill's setup flow until the user has confirmed the full account list in chat (see spec's Phase 3/4 split).
- `viewer/webapp/` currently has zero automated tests (verified: no `tests/` directory, no pytest in `requirements.txt`, no test files matching `test_*.py`). This plan introduces pytest for the one new pure-logic module only (`asana_discovery.py`). Do not retrofit tests onto existing untested routes/files as part of this plan — that is out of scope (YAGNI).
- Preserve the existing `customers.html` UX convention: edits (add/edit/remove rows) stage in the in-memory `CONFIG` object and only commit to Drive when the user clicks the existing "Save to Drive" button. The new "Scan for Accounts" flow must follow this same stage-then-save pattern, not introduce a separate immediate-write path.

---

## File Structure

**New files:**
- `viewer/webapp/asana_discovery.py` — pure logic: given a fetch function, a PAT, and the set of already-linked Asana project GIDs, returns unlinked candidate projects.
- `viewer/webapp/tests/__init__.py` — empty, makes the tests directory a package for pytest discovery.
- `viewer/webapp/tests/test_asana_discovery.py` — unit tests for the above, using a fake fetch function (no network, no mocking library needed).
- `viewer/webapp/requirements-dev.txt` — adds `pytest` as a dev-only dependency (kept separate from `requirements.txt` since pytest is not needed in the production container).
- `references/first-run-setup.md` — full setup flow: Phase 1 (minimal), Phase 2 (four-pass discovery), Phase 3 (confirmation table), Phase 4 (write & hand-off), plus the on-demand "find new accounts" flow. Replaces the inline "First-Run Setup" section currently in `SKILL.md`.

**Modified files:**
- `viewer/webapp/app.py` — add `import asana_discovery` and a new `GET /api/customers/discover-asana` route.
- `viewer/webapp/templates/customers.html` — add a "Scan for Accounts" button, a results modal, and JS to stage discovered accounts into the existing `CONFIG.accounts` array.
- `SKILL.md` — replace the inline "First-Run Setup" section (current lines ~71-107) with a short pointer to `references/first-run-setup.md` (matching the existing pointer style used for `references/post-meeting-patch.md` and `references/section-refresh.md`); update the YAML frontmatter trigger list to include "find new accounts" / "scan for customers".
- `README.md` — update the Structure section to list the new reference file; update the "First-Run Setup" summary to reflect the new phased flow.

---

## Task 1: Asana Discovery Logic (pure function, unit tested)

**Files:**
- Create: `viewer/webapp/asana_discovery.py`
- Create: `viewer/webapp/tests/__init__.py`
- Create: `viewer/webapp/tests/test_asana_discovery.py`
- Create: `viewer/webapp/requirements-dev.txt`

**Interfaces:**
- Produces: `find_new_projects(fetch_fn, pat, linked_gids) -> list[dict]` where `fetch_fn` matches `app.py`'s existing `_asana_api_get(pat, path, params) -> dict` signature (Asana's raw `{"data": ...}` JSON shape), `pat: str`, `linked_gids: set[str]`. Returns a list of `{"gid": str, "name": str}` dicts sorted alphabetically by name. Consumed by Task 2's Flask route.

- [ ] **Step 1: Create the tests directory package marker**

Create `viewer/webapp/tests/__init__.py` with empty content (just makes the directory a package so pytest can discover it alongside `app.py`'s imports).

- [ ] **Step 2: Add pytest as a dev dependency**

Create `viewer/webapp/requirements-dev.txt`:

```
-r requirements.txt
pytest==8.3.3
```

- [ ] **Step 3: Write the failing tests**

Create `viewer/webapp/tests/test_asana_discovery.py`:

```python
"""Tests for asana_discovery.find_new_projects — pure logic, no real
Asana calls. fetch_fn is faked so these run with no network access and
no mocking library."""
from asana_discovery import find_new_projects


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
            {'gid': 'p1', 'name': 'Bank of America'},
            {'gid': 'p2', 'name': 'Acme Corp'},
        ]},
    })

    result = find_new_projects(fetch_fn, pat='fake-pat', linked_gids={'p1'})

    assert result == [{'gid': 'p2', 'name': 'Acme Corp'}]


def test_returns_empty_list_when_all_projects_already_linked():
    fetch_fn = _fake_fetch({
        '/users/me': {'data': {'workspaces': [{'gid': 'ws1', 'name': 'Camunda'}]}},
        '/workspaces/ws1/projects': {'data': [
            {'gid': 'p1', 'name': 'Bank of America'},
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
```

- [ ] **Step 4: Run tests to verify they fail**

Run (from `viewer/webapp/`):
```bash
pip install -r requirements-dev.txt
pytest tests/test_asana_discovery.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'asana_discovery'`

- [ ] **Step 5: Write the implementation**

Create `viewer/webapp/asana_discovery.py`:

```python
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
```

- [ ] **Step 6: Run tests to verify they pass**

Run:
```bash
pytest tests/test_asana_discovery.py -v
```
Expected: PASS (6 tests)

- [ ] **Step 7: Commit**

```bash
git add viewer/webapp/asana_discovery.py viewer/webapp/tests/__init__.py viewer/webapp/tests/test_asana_discovery.py viewer/webapp/requirements-dev.txt
git commit -m "feat: add Asana-only account discovery logic with unit tests"
```

---

## Task 2: Discovery API Endpoint

**Files:**
- Modify: `viewer/webapp/app.py` (add import near line 53; add route near line 1004, after the existing `/api/customers/config` PUT route)

**Interfaces:**
- Consumes: `asana_discovery.find_new_projects(fetch_fn, pat, linked_gids)` from Task 1; `db.get_asana_pat(user_id)`, `db.get_google_refresh_token(user_id)`, `db.get_google_drive_folder_id(user_id)`, `gdrive_briefs.read_account_config(token, folder_id)` — all already exist in this file.
- Produces: `GET /api/customers/discover-asana` → `{"candidates": [{"gid": str, "name": str}, ...]}` on success, `{"error": str}` with 400/500/502 on failure. Consumed by Task 3's frontend fetch call.

**Note on testing:** This route is thin glue code over already-existing, already-untested helpers (`db.py`, `gdrive_briefs.py`) that would require substantial DB/OAuth mocking infrastructure this codebase doesn't have (see Global Constraints). Verification here is manual, matching every other route in `app.py` today.

- [ ] **Step 1: Add the import**

In `viewer/webapp/app.py`, find:
```python
import db
import gdrive_briefs
```
Replace with:
```python
import asana_discovery
import db
import gdrive_briefs
```

- [ ] **Step 2: Add the route**

In `viewer/webapp/app.py`, find the end of `api_customers_config_update` (the `/api/customers/config` PUT route):
```python
    result = gdrive_briefs.write_account_config(data, google_token, folder_id)
    if result is not True:
        msg = result if isinstance(result, str) else 'Failed to write account-config.json'
        return jsonify({'error': msg}), 500
    return jsonify({'ok': True})

@app.route('/admin')
```
Replace with:
```python
    result = gdrive_briefs.write_account_config(data, google_token, folder_id)
    if result is not True:
        msg = result if isinstance(result, str) else 'Failed to write account-config.json'
        return jsonify({'error': msg}), 500
    return jsonify({'ok': True})


@app.route('/api/customers/discover-asana')
@login_required
def api_customers_discover_asana():
    """Returns Asana projects not yet linked to any account, for the
    Customers tab's "Scan for Accounts" button. Asana-only: this webapp
    has no Slack or Outlook access, so full multi-source discovery still
    only happens in the skill's own setup flow
    (references/first-run-setup.md)."""
    pat = db.get_asana_pat(request.brief_user['id'])
    if not pat:
        return jsonify({'error': 'No Asana PAT configured — add one from the Account panel first.'}), 400

    google_token = db.get_google_refresh_token(request.brief_user['id'])
    folder_id = db.get_google_drive_folder_id(request.brief_user['id'])
    if not google_token:
        return jsonify({'error': 'Google Drive not connected'}), 400
    config = gdrive_briefs.read_account_config(google_token, folder_id)
    if config is None:
        return jsonify({'error': 'Could not read account-config.json'}), 500

    linked_gids = {
        a.get('project_gid') for a in config.get('accounts', []) if a.get('project_gid')
    }

    try:
        candidates = asana_discovery.find_new_projects(_asana_api_get, pat, linked_gids)
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        return jsonify({'error': f'Asana lookup failed: {e}'}), 502

    return jsonify({'candidates': candidates})


@app.route('/admin')
```

- [ ] **Step 3: Manual verification**

Run the app locally per its existing dev setup (see `viewer/webapp/DEPLOYMENT.md` for env vars), sign in, ensure an Asana PAT is saved for the test account (via the existing Account panel / `POST /api/asana-pat`), then:

```bash
curl -s -b <session-cookie-jar> http://localhost:8080/api/customers/discover-asana | python -m json.tool
```

Expected: `{"candidates": [...]}` listing Asana projects not already present as a `project_gid` in that user's `account-config.json`. Verify:
- A project already linked in `account-config.json` does NOT appear.
- Removing the Asana PAT (`DELETE /api/asana-pat`) and re-calling returns the 400 "No Asana PAT configured" error.

- [ ] **Step 4: Commit**

```bash
git add viewer/webapp/app.py
git commit -m "feat: add /api/customers/discover-asana endpoint"
```

---

## Task 3: Customers Page "Scan for Accounts" UI

**Files:**
- Modify: `viewer/webapp/templates/customers.html`

**Interfaces:**
- Consumes: `GET /api/customers/discover-asana` from Task 2; existing in-page functions `markDirty()`, `render()`, `showToast(text, type, duration)`, `esc(s)`, and the existing `CONFIG.accounts` array (all already defined in this file).
- Produces: no new interfaces for other tasks — this is the final UI layer.

**Note on testing:** This file has no JS test framework (plain inline `<script>`, no build step). Verification is manual, matching the rest of this template.

- [ ] **Step 1: Add the "Scan for Accounts" button**

In `viewer/webapp/templates/customers.html`, find:
```html
  <div class="panel-head">
    <span>Account List</span>
    <button class="btn save" id="save-btn" onclick="saveConfig()" disabled>Save to Drive</button>
  </div>
```
Replace with:
```html
  <div class="panel-head">
    <span>Account List</span>
    <div style="display:flex;gap:8px">
      <button class="btn" id="scan-btn" onclick="scanForAccounts()">Scan for Accounts</button>
      <button class="btn save" id="save-btn" onclick="saveConfig()" disabled>Save to Drive</button>
    </div>
  </div>
```

- [ ] **Step 2: Add modal CSS**

In `viewer/webapp/templates/customers.html`, find:
```css
.toast.out{animation:toast-out .25s ease forwards;}
@keyframes toast-in{to{opacity:1;transform:translateY(0);}}
@keyframes toast-out{from{opacity:1;transform:translateY(0);}to{opacity:0;transform:translateY(-12px);}}
</style>
```
Replace with:
```css
.toast.out{animation:toast-out .25s ease forwards;}
@keyframes toast-in{to{opacity:1;transform:translateY(0);}}
@keyframes toast-out{from{opacity:1;transform:translateY(0);}to{opacity:0;transform:translateY(-12px);}}
.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.4);display:flex;align-items:center;justify-content:center;z-index:1000;}
.modal{background:var(--surface);border-radius:var(--r);max-width:600px;width:90%;max-height:80vh;display:flex;flex-direction:column;overflow:hidden;border:1px solid var(--border-strong);}
.modal-head{padding:12px 16px;background:var(--surface2);font-weight:600;font-size:13px;display:flex;justify-content:space-between;align-items:center;}
.modal-body{padding:14px 16px;overflow-y:auto;flex:1;}
.modal-foot{padding:12px 16px;border-top:1px solid var(--border);display:flex;justify-content:flex-end;gap:8px;}
.scan-row{display:flex;align-items:center;gap:10px;padding:7px 0;border-bottom:.5px solid var(--border);}
.scan-row input[type="text"]{flex:1;}
.scan-row .mono{white-space:nowrap;}
</style>
```

- [ ] **Step 3: Add modal HTML**

In `viewer/webapp/templates/customers.html`, find:
```html
<div class="toast-container" id="toast-container"></div>
```
Replace with:
```html
<div class="toast-container" id="toast-container"></div>

<div class="modal-overlay" id="scan-modal" style="display:none">
  <div class="modal">
    <div class="modal-head">
      <span>Discovered Asana Projects</span>
      <button class="btn" onclick="closeScanModal()">Close</button>
    </div>
    <div class="modal-body" id="scan-body"></div>
    <div class="modal-foot">
      <button class="btn primary" onclick="addScannedAccounts()">Add Selected</button>
    </div>
  </div>
</div>
```

- [ ] **Step 4: Add the scan/render/add JS functions**

In `viewer/webapp/templates/customers.html`, find:
```javascript
function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
```
Replace with:
```javascript
function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

let SCAN_CANDIDATES = [];

async function scanForAccounts() {
  const modal = document.getElementById('scan-modal');
  const body = document.getElementById('scan-body');
  modal.style.display = 'flex';
  body.innerHTML = '<div class="empty">Scanning Asana…</div>';
  try {
    const r = await fetch(`${BASE}api/customers/discover-asana`, {credentials:'include'});
    if (!r.ok) throw new Error((await r.json()).error || r.statusText);
    const data = await r.json();
    SCAN_CANDIDATES = data.candidates || [];
    renderScanResults();
  } catch(e) {
    body.innerHTML = `<div class="empty" style="color:var(--bad-t)">${esc(e.message)}</div>`;
  }
}

function renderScanResults() {
  const body = document.getElementById('scan-body');
  if (!SCAN_CANDIDATES.length) {
    body.innerHTML = '<div class="empty">No new Asana projects found — everything visible to your Asana account is already linked. Note: this only scans Asana; use the skill\'s "find new accounts" to also scan Slack and email.</div>';
    return;
  }
  body.innerHTML = SCAN_CANDIDATES.map((c, i) => `
    <div class="scan-row">
      <input type="checkbox" id="scan-check-${i}" checked>
      <input type="text" id="scan-name-${i}" value="${esc(c.name)}" placeholder="Account name">
      <span class="mono sub">${esc(c.gid)}</span>
    </div>
  `).join('');
}

function closeScanModal() {
  document.getElementById('scan-modal').style.display = 'none';
}

function addScannedAccounts() {
  let added = 0;
  SCAN_CANDIDATES.forEach((c, i) => {
    const checkbox = document.getElementById(`scan-check-${i}`);
    if (!checkbox || !checkbox.checked) return;
    const name = document.getElementById(`scan-name-${i}`).value.trim();
    if (!name) return;
    CONFIG.accounts.push({
      account_name: name, tier: 'primary', run_day: null,
      slack_channel_name: '', slack_channel_id: '', supporting_slack_channel_ids: [],
      asana_board_name: c.name, project_gid: c.gid, gdrive_folder_id: null
    });
    added++;
  });
  CONFIG.accounts.sort((a,b) =>
    (a.account_name||'').localeCompare(b.account_name||'', undefined, {sensitivity:'base'})
  );
  closeScanModal();
  if (added > 0) {
    markDirty();
    render();
    showToast(`Added ${added} account${added===1?'':'s'} — click "Save to Drive" to persist`, 'ok', 5000);
  }
}
```

- [ ] **Step 5: Manual verification**

With the webapp running and an Asana PAT + Google Drive connected for the test account:
1. Open `/customers`, click "Scan for Accounts".
2. Verify the modal shows "Scanning Asana…" then either results or the empty-state message.
3. Uncheck one candidate, edit another's name, click "Add Selected".
4. Verify the modal closes, a toast reads "Added N accounts…", the table shows new rows under the correct Primary/Secondary section, and "Save to Drive" is now enabled.
5. Click "Save to Drive" and verify the toast reads "Configuration saved to Drive" and reloading `/customers` shows the new accounts persisted.
6. Re-open "Scan for Accounts" and verify the just-added project no longer appears (now linked).

- [ ] **Step 6: Commit**

```bash
git add viewer/webapp/templates/customers.html
git commit -m "feat: add Scan for Accounts UI to Customers tab"
```

---

## Task 4: Skill Setup Flow Rewrite

**Files:**
- Create: `references/first-run-setup.md`
- Modify: `SKILL.md` (First-Run Setup section, admin config reference list, YAML frontmatter trigger description)

**Interfaces:**
- Produces: the conversational flow Claude follows for `/daily-brief setup` and for on-demand "find new accounts" / "scan for customers" triggers. No code interfaces — this is skill-instruction content consumed only by Claude at runtime.

**Note on testing:** This is conversational skill content, not code — there is nothing to unit test. Verification is manual: run the actual flow in a Claude conversation against a test Drive folder, Slack workspace, and Asana workspace, and confirm the written files match the schema in `references/item-sync.md`. This matches the existing testing convention documented in this repo's design docs for skill-side behavior.

- [ ] **Step 1: Write the new reference file**

Create `references/first-run-setup.md`:

```markdown
# First-Run Setup & Account Finder

Full detail for the setup flow referenced from `SKILL.md`'s "First-Run
Setup" section. Read this file only when that flow triggers — it is not
needed on a normal brief run.

Runs when the user explicitly asks (`/daily-brief setup`, "set up daily
brief", etc.), and is auto-offered whenever a normal run finds
`CONFIG_FILE_ID` still set to the placeholder. The same discovery engine
(Phase 2 below) also powers the on-demand "find new accounts" flow
(see "On-Demand: Find New Accounts" at the end of this file), triggered
by "find new accounts", "scan for customers", or similar phrasing outside
of full setup.

Setup is **minimal → discovery → confirmation**: gather only the two
essentials up front, auto-discover everything else, then let the user
review and edit before anything is written to Drive.

## Phase 1: Minimal Configuration

Ask for exactly two values, one at a time:

1. **Drive folder ID** — "Where should I save your briefs? Paste the ID
   from your Drive folder's URL (the part after `folders/`)." If the user
   doesn't have one yet, tell them to create an empty Drive folder first.
2. **Slack user ID** — "What's your Slack user ID? (Format `UXXXXXXXXXX`
   — find it in your Slack profile under 'Copy member ID'.)"

Hold both values in the conversation. Do not write anything to Drive yet.

## Phase 2: Automated Discovery

Run this automatically, without asking the user to confirm each pass —
show all results together at the end of Phase 2, then move to Phase 3.

**Pass 1 — Email seed.** Use `Microsoft 365: outlook_email_search` over
the last 30 days, look at the 50 most recent unique sender
organizations. Extract likely account/company names from sender domains
and email subjects (e.g. a sender at `@acmecorp.com` with subject lines
mentioning "Acme" suggests account name "Acme Corp"). Build a candidate
account-name list. If this pass fails or the connector errors, note it
and continue with an empty candidate list — the remaining passes can
still contribute matches for a smaller manually-typed list, or you can
proceed to Phase 3 with zero candidates and let the user type names.

**Pass 2 — Slack channel match.** For each candidate account name, use
the Slack connector's channel search (`Slack: slack_search_channels` or
equivalent) to find channels whose name contains the candidate name
(case-insensitive substring match, ignoring spaces/punctuation — e.g.
"Bank of America" should match `#boa-main`). If multiple channels match
one account, treat the shortest/most-exact-match name as the primary
channel and the rest as `supporting_slack_channel_ids`. If this pass
fails or errors, note it and continue — accounts simply carry no Slack
channel yet, editable in Phase 3.

**Pass 3 — Asana project match.** For each candidate account name, use
`Asana: search` or equivalent to find projects whose name contains the
candidate name. If exactly one matches, link it (`project_gid`,
`asana_board_name`). If multiple match, flag as ambiguous — surface all
matches to the user in Phase 3 and let them pick. If none match, leave
`project_gid` blank — editable in Phase 3. If this pass fails or errors,
note it and continue.

**Pass 4 — Internal board detection.** Search Asana for projects whose
name suggests an internal/non-customer board — look for names containing
"Internal", "Admin", "Team", "General", or "Recurring". If exactly one
strong candidate is found, propose it as `internal_project_gid`. If
multiple candidates are found, list them and ask the user to pick one in
Phase 3. If none are found, leave it blank — the user can paste a GID
directly in Phase 3.

**Confidence ranking.** Sort the candidate account list for Phase 3
presentation: accounts with both a Slack channel AND an Asana project
first (high confidence), then accounts with only one of the two (medium),
then email-seeded-only accounts with neither (low). This ordering is
presentation only — every candidate is still shown, none are dropped for
low confidence.

## Phase 3: User Confirmation & Edit

Present the full discovered list in chat as a reviewable table, grouped
by confidence tier, something like:

```
DISCOVERED ACCOUNTS — Review & Confirm

High confidence:
1. [x] Bank of America — Slack: #boa-main, #boa-support | Asana: Bank of America Engagement (123456)
2. [x] JPMorgan Chase — Slack: #jpmc | Asana: JPMC Banking Platform (789012)

Medium confidence:
3. [x] Acme Corp — Slack: #acme-internal | Asana: (none found — reply with a project name/GID to link one)

Low confidence:
4. [ ] Foo Industries — Slack: (none found) | Asana: Foo Corp - Legacy (555666)

Internal board: Internal Tasks & Recurring (999888) — confirm or reply with a different project?

Key contacts: (reply with names, comma-separated, e.g. "Alice Smith, Bob Chen")
```

Ask the user to reply with corrections: which numbers to exclude, tier
(primary/secondary — and if secondary, which weekday) for each account
they're keeping, any account name corrections, and manually-supplied
Slack channels or Asana projects for gaps. Default every account to
`tier: primary` unless the user says otherwise. Keep iterating on this
single message/reply exchange until the user says the list is correct —
do not write anything to Drive until they explicitly confirm.

## Phase 4: Write & Hand-Off

Once the user confirms:

1. Create `/config/config.json` via `Google Drive: create_file` with:
   `brief_data_folder_id`, `slack_user_id`, `key_contacts`, and empty-string
   placeholders for `meeting_run_log_sheet_id`,
   `recurring_activities_project_gid`, `status_update_cache_file_id` (the
   user can fill these in later, or by re-running setup — see
   `references/item-sync.md` for what these three unlock and how they're
   used).
2. Create `/config/account-config.json` via `Google Drive: create_file`
   with the confirmed `accounts` array and top-level `internal_project_gid`
   — exact field names per `references/item-sync.md`: `account_name`,
   `tier`, `run_day`, `slack_channel_id`, `supporting_slack_channel_ids`,
   `project_gid`, `asana_board_name`, `gdrive_folder_id` (set `null` for
   anything not resolved).
3. Run the Folder Existence Check (see `SKILL.md`) to create `/briefs`,
   `/config`, `/state` under the brief-data folder if they don't already
   exist.
4. Report the new `config.json` file ID and tell the user to paste it
   into `CONFIG_FILE_ID` at the top of their local `SKILL.md` — this is
   the only manual edit.

## On-Demand: Find New Accounts

Triggered by "find new accounts", "scan for customers", or a direct ask
to find more accounts, outside of full setup. Requires an existing valid
`CONFIG_FILE_ID` (if not set, offer full setup instead).

1. Read the current `/config/account-config.json` to know which
   `slack_channel_id`s and `project_gid`s are already in use.
2. Run Phase 2's four-pass discovery as above, but skip any candidate
   whose Slack channel or Asana project is already linked to an existing
   account.
3. Present results using the same Phase 3 table format, scoped to only
   the new candidates found.
4. On confirmation, append the newly-confirmed accounts to the existing
   `accounts` array (read-merge-rewrite — do not touch existing entries)
   and write a new version of `account-config.json` via
   `Google Drive: create_file`.
5. Confirm to the user: "Added N new accounts. They'll appear starting
   with your next brief."
```

- [ ] **Step 2: Update SKILL.md's First-Run Setup section to point at the new file**

In `SKILL.md`, the existing "First-Run Setup" section runs from the
heading `## First-Run Setup` down through the line
`**Re-running setup** loads both existing files first, uses them as the
Phase A/B starting point, re-confirms, and writes a fresh version of each
file once — never a per-key incremental write.` (immediately followed by
a blank line, then `---`, a blank line, `---`, a blank line, then
`## Purpose`). Replace everything from `## First-Run Setup` through that
"Re-running setup" line (inclusive) with:

```markdown
## First-Run Setup

Runs when the user explicitly asks (`/daily-brief setup`, "set up daily brief", etc.), and is auto-offered whenever a normal run finds `CONFIG_FILE_ID` still set to the placeholder (per the config-load step above — offer setup instead of erroring).

Read `references/first-run-setup.md` in full before running this flow — it documents the minimal-configuration phase, the automated discovery pass (email, Slack, Asana, and internal-board detection), the confirmation-and-edit step, and the final write-and-hand-off step. It also documents the on-demand "find new accounts" flow used outside of full setup.

**Re-running setup** loads both existing config files first, uses them as the Phase 1/2 starting point, re-confirms, and writes a fresh version of each file once — never a per-key incremental write.
```

- [ ] **Step 3: Update the trigger list in SKILL.md's YAML frontmatter**

In `SKILL.md`, find:
```yaml
  Also trigger the setup flow on "/daily-brief setup", "set up daily brief", or "configure daily brief" — see the First-Run Setup section.
```
Replace with:
```yaml
  Also trigger the setup flow on "/daily-brief setup", "set up daily brief", or "configure daily brief" — see the First-Run Setup section.

  Also trigger the on-demand account-discovery flow on "find new accounts", "scan for customers", or "find more accounts" — see the "On-Demand: Find New Accounts" section of references/first-run-setup.md.
```

- [ ] **Step 4: Update the reference-file list near the top of SKILL.md**

In `SKILL.md`, find the last bullet of the reference-file list near the
top of the file:
```markdown
- `references/section-refresh.md` — patches a single Customer Update or Manager Update card, or regenerates one of the other five sections in full, when a Refresh button is clicked. Only read when that trigger fires.
```
Replace with:
```markdown
- `references/section-refresh.md` — patches a single Customer Update or Manager Update card, or regenerates one of the other five sections in full, when a Refresh button is clicked. Only read when that trigger fires.
- `references/first-run-setup.md` — the First-Run Setup flow (minimal config, automated discovery, confirmation, write) and the on-demand "find new accounts" flow. Only read when one of those two triggers fires.
```

- [ ] **Step 5: Manual verification**

In a real Claude conversation with the MCP connectors enabled against a
test Drive folder / Slack workspace / Asana workspace:
1. Trigger `/daily-brief setup` and confirm Claude asks only for Drive
   folder ID and Slack user ID before running discovery.
2. Confirm discovery results are presented in the ranked table format
   from Phase 3, and that nothing is written to Drive before you reply
   to confirm.
3. Confirm the written `config.json` and `account-config.json` match the
   schema in `references/item-sync.md` (check field names exactly,
   especially `project_gid` not `asana_project_gid`).
4. Say "find new accounts" in a follow-up message and confirm it does
   not re-ask for Drive folder ID / Slack user ID, runs discovery again,
   and only shows genuinely new (not-yet-linked) candidates.
5. Confirm accepting a new candidate appends to the existing
   `account-config.json` without altering previously-configured accounts.

- [ ] **Step 6: Commit**

```bash
git add references/first-run-setup.md SKILL.md
git commit -m "feat: rewrite skill setup flow with phased discovery and on-demand account finder"
```

---

## Task 5: Update README.md

**Files:**
- Modify: `README.md`

**Interfaces:** None — documentation only.

- [ ] **Step 1: Add the new reference file to the Structure section**

In `README.md`, find:
```markdown
- `references/section-refresh.md` — writes a new version of a single Customer Update or Manager Update card, or a full section (Yesterday's Meetings, Account/Initiative Recap, Today, Action Items, FYI), to Drive when its Refresh button is clicked. Read only when that trigger fires.
```
Replace with:
```markdown
- `references/section-refresh.md` — writes a new version of a single Customer Update or Manager Update card, or a full section (Yesterday's Meetings, Account/Initiative Recap, Today, Action Items, FYI), to Drive when its Refresh button is clicked. Read only when that trigger fires.
- `references/first-run-setup.md` — the First-Run Setup flow (minimal Drive-folder/Slack-ID collection, automated email/Slack/Asana discovery, user confirmation, write) and the on-demand "find new accounts" flow. Read only when setup or account-discovery triggers.
```

- [ ] **Step 2: Update the Google Drive prerequisites note to mention discovery**

In `README.md`, find:
```markdown
- A folder to hold `/briefs` (this skill's own output), `/config` (hand-maintained by you), and `/state` (written by the hosted webapp, not this skill) — its ID is collected by the setup flow and stored in the `brief_data_folder_id` field of `config.json`. See `references/item-sync.md` for the layout.
```
Replace with:
```markdown
- A folder to hold `/briefs` (this skill's own output), `/config` (hand-maintained by you), and `/state` (written by the hosted webapp, not this skill) — its ID is collected by the setup flow and stored in the `brief_data_folder_id` field of `config.json`. See `references/item-sync.md` for the layout.

Setup itself now only asks for this folder ID and your Slack user ID up front — it discovers your customer accounts, their Slack channels, and their Asana projects automatically, then has you review and confirm before writing anything. See `references/first-run-setup.md` for the full flow. You can also run account discovery anytime after setup ("find new accounts"), or use the "Scan for Accounts" button on the hosted webapp's Customers tab (Asana-only there, since the webapp has no Slack access).
```

- [ ] **Step 3: Manual verification**

Read through the updated `README.md` top to bottom and confirm it no longer describes the old three-phase (Phase A/B/C) setup flow anywhere, and accurately points to `references/first-run-setup.md` for detail.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: update README for new setup flow and account finder"
```

---

## Self-Review Notes

**Spec coverage:**
- Phase 1-4 setup flow → Task 4, Step 1 (Phases 1-4 in `first-run-setup.md`)
- Four-pass discovery engine (email, Slack, Asana, internal board) → Task 4, Step 1, Phase 2
- Confirmation/edit UI (skill side, conversational) → Task 4, Step 1, Phase 3
- Data persistence (config.json, account-config.json) → Task 4, Step 1, Phase 4
- Account Finder on-demand (skill side) → Task 4, Step 1, "On-Demand: Find New Accounts"
- Account Finder (webapp, Asana-only per user decision) → Tasks 1-3
- Error handling / edge cases (API failures, ambiguous matches, no matches, duplicates) → covered inline in Task 4 Step 1's Phase 2/3 text, and in Task 2's endpoint (missing PAT, missing Drive token, Asana API failure)
- README updates → Task 5

**Type/field consistency check:** `project_gid` (not `asana_project_gid`) used consistently across Task 1's `find_new_projects`, Task 2's endpoint, Task 3's `addScannedAccounts`, and Task 4's Phase 4 write instructions — matches `references/item-sync.md` and the existing `customers.html`.

**No placeholders:** every step above contains complete file content or exact diffs; no "TODO"/"similar to above" references remain.
