# Environments Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone `/environments` page tracking, per in-scope customer, a small set of named teams and one or more Camunda deployment environments (deployment basics, version info, links, notes, and dated diagnostic-report/Helm-values history) — Phase 1 of the Environments feature: data model plus manual entry, per `docs/superpowers/specs/2026-09-23-environments-tab-design.md`.

**Architecture:** A new `environments-config.json` file in Drive's `/config` folder, read/written with the exact same pattern `account-config.json` and `config.json` already use in `gdrive_briefs.py`. Customer scope (which accounts show up at all) comes from Asana portfolio membership — a new `asana_discovery.get_portfolio_project_names` function, called with the signed-in user's existing stored PAT, the same way `asana_discovery.find_new_projects` already works. A new standalone page (`templates/environments.html`, styled like `customers.html`, same "edit everything client-side, one Save button writes it all back" model) is reached via a new topbar button.

**Tech Stack:** Flask, Jinja2 templates (page shell only — no server-side fragment rendering, unlike the Tasks tab), vanilla JS (no framework), pytest (hand-rolled fakes, no mocking library) for the one new pure-logic function.

## Global Constraints

- No `Co-Authored-By` commit trailer — this repo's CLAUDE.md (#2078) forbids it unless `.claude/settings.json` sets `attribution.commit`, which it does not.
- Windows/PowerShell environment — commands use `venv\Scripts\python`/`venv\Scripts\pytest`, not Unix `venv/bin/...`.
- **No automated tests for `read_environments_config`/`write_environments_config` (gdrive_briefs.py) or for any of the new Flask routes.** Their three existing siblings (`read_account_config`/`write_account_config`, `read_config`/`write_config`) have no tests either — there's no stubbed-Drive-client pattern anywhere in this codebase to extend — and no route in this app has an automated test (importing `app.py` needs live env vars and Postgres). This is the existing, consistent level of coverage for this whole category of code, not a gap this feature introduces. The one new pure-logic function (`get_portfolio_project_names`) *does* get real tests, following `asana_discovery.find_new_projects`'s existing injectable-`fetch_fn` pattern.
- **Customer scope comes from an Asana portfolio, not Salesforce.** An earlier draft of the spec proposed a Salesforce `Success Tier` lookup; that's been replaced. A customer is in scope if their `account-config.json` `account_name` matches the name of a project currently in Asana portfolio GID `1209916881329688` (verify this GID against a real `GET /portfolios/{gid}/items` call before relying on it — Asana portfolio URLs aren't fully standardized, and this is a one-line constant to correct if wrong).
- No caching on the portfolio lookup — no other Asana API call in this app is cached (only Drive folder-GID lookups are), so this follows that precedent rather than introducing a new caching layer.
- The environments-config.json schema is deliberately minimal for this first cut — do not add fields beyond what's specified below.

---

### Task 1: `get_portfolio_project_names` in `asana_discovery.py`

**Files:**
- Modify: `viewer/webapp/asana_discovery.py`
- Test: `viewer/webapp/tests/test_asana_discovery.py`

**Interfaces:**
- Consumes: nothing new — same `FetchFn` type already defined in this module (`Callable[[str, str, dict], dict]`, matching `app.py`'s `_asana_api_get(pat, path, params) -> dict`).
- Produces: `get_portfolio_project_names(fetch_fn: FetchFn, pat: str, portfolio_gid: str) -> List[str]` — sorted (case-insensitive) list of project names currently in the given Asana portfolio. Task 3's `/api/environments/config` route is the only caller.

- [ ] **Step 1: Write the failing tests**

Add to `viewer/webapp/tests/test_asana_discovery.py` (it already has a `_fake_fetch` helper and imports from `asana_discovery` — add the new import and these three test functions):

```python
from asana_discovery import find_new_projects, get_portfolio_project_names
```

(Replace the existing `from asana_discovery import find_new_projects` line with the one above.)

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd viewer/webapp
venv\Scripts\pytest tests/test_asana_discovery.py -v
```

Expected: the three new tests FAIL with `ImportError` (`get_portfolio_project_names` doesn't exist yet); the existing `find_new_projects` tests still PASS.

- [ ] **Step 3: Implement the function**

Add to `viewer/webapp/asana_discovery.py`, after `find_new_projects`:

```python
def get_portfolio_project_names(
    fetch_fn: FetchFn,
    pat: str,
    portfolio_gid: str,
) -> List[str]:
    """Returns the names of every project currently in the given Asana
    portfolio, sorted alphabetically (case-insensitive) — used by the
    Environments tab to determine which account-config.json customers are
    in scope (a customer is in scope if their account_name matches one of
    these names).

    fetch_fn must match app.py's _asana_api_get(pat, path, params) -> dict
    signature. Propagates whatever fetch_fn itself raises on failure
    (matches _asana_api_get's own urllib.error.URLError /
    json.JSONDecodeError contract) — callers are responsible for catching
    those.
    """
    items = fetch_fn(pat, f'/portfolios/{portfolio_gid}/items', {'opt_fields': 'name'})
    names = [item['name'] for item in items.get('data', []) if item.get('name')]
    names.sort(key=str.lower)
    return names
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd viewer/webapp
venv\Scripts\pytest tests/test_asana_discovery.py -v
```

Expected: all tests PASS (existing `find_new_projects` tests plus the 3 new ones).

- [ ] **Step 5: Commit**

```bash
git add viewer/webapp/asana_discovery.py viewer/webapp/tests/test_asana_discovery.py
git commit -m "Add get_portfolio_project_names for Environments tab customer scoping"
```

---

### Task 2: `read_environments_config`/`write_environments_config` in `gdrive_briefs.py`

**Files:**
- Modify: `viewer/webapp/gdrive_briefs.py`

**Interfaces:**
- Consumes: `_get_drive_service`, `_find_folder_cached`, `_download_json`, `_cache_lock`, `_folder_cache`, `_FOLDER_TTL`, `BRIEFS_FOLDER_ID` (all existing, unchanged — same helpers `read_account_config`/`write_account_config` already use).
- Produces: `read_environments_config(refresh_token, folder_id=None) -> Optional[Dict]` and `write_environments_config(config_data: Dict, refresh_token, folder_id=None) -> Union[bool, str]`. Task 3's routes are the only callers. The dict shape is `{"<customer name>": {"teams": [...], "environments": [...]}, ...}` per the design spec — this task doesn't validate that shape, it just persists whatever dict it's given (same looseness as `write_account_config`).

No automated test for this task (see Global Constraints).

- [ ] **Step 1: Add the functions**

Add to `viewer/webapp/gdrive_briefs.py`, directly after `write_account_config` (so the three "config JSON in Drive" pairs stay grouped):

```python
_EMPTY_ENVIRONMENTS_CONFIG: Dict = {}


def read_environments_config(refresh_token: str, folder_id: Optional[str] = None) -> Optional[Dict]:
    """Read the raw environments-config.json from Drive's /config
    subfolder. Returns the parsed JSON dict, keyed by customer name (see
    docs/superpowers/specs/2026-09-23-environments-tab-design.md for the
    shape). A missing /config folder or environments-config.json is not an
    error — it just means no customer has saved one yet, so an empty dict
    is returned so the management UI can bootstrap it. Returns None only
    on an actual Drive/auth failure."""
    parent_folder = folder_id or BRIEFS_FOLDER_ID
    if not parent_folder or not refresh_token:
        return None

    try:
        drive = _get_drive_service(refresh_token)
        if not drive:
            return None

        config_folder_id = _find_folder_cached(drive, parent_folder, 'config')
        if not config_folder_id:
            logger.info('read_environments_config: no /config folder found — returning empty config')
            return dict(_EMPTY_ENVIRONMENTS_CONFIG)

        query = (
            f"parents='{config_folder_id}' "
            f"and name='environments-config.json' "
            f"and trashed=false"
        )
        results = drive.files().list(
            q=query, spaces='drive', pageSize=1, fields='files(id)',
        ).execute()
        files = results.get('files', [])
        if not files:
            logger.info('read_environments_config: environments-config.json not found — returning empty config')
            return dict(_EMPTY_ENVIRONMENTS_CONFIG)

        return _download_json(drive, files[0]['id'])

    except Exception as e:
        logger.error('read_environments_config: %s', e, exc_info=True)
        return None


def write_environments_config(config_data: Dict, refresh_token: str,
                               folder_id: Optional[str] = None) -> Union[bool, str]:
    """Write environments-config.json back to Drive. Creates the /config
    folder and/or the environments-config.json file if either doesn't
    exist yet. Returns True on success, or an error string on failure."""
    parent_folder = folder_id or BRIEFS_FOLDER_ID
    if not parent_folder:
        return 'No Drive folder configured'
    if not refresh_token:
        return 'No Google refresh token — re-link Google Drive'

    try:
        from io import BytesIO
        from googleapiclient.http import MediaIoBaseUpload

        drive = _get_drive_service(refresh_token)
        if not drive:
            return 'Could not authenticate with Google Drive — re-link Google Drive'

        config_folder_id = _find_folder_cached(drive, parent_folder, 'config')
        if not config_folder_id:
            logger.info('write_environments_config: no /config folder found — creating it')
            folder_metadata = {
                'name': 'config',
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [parent_folder],
            }
            created_folder = drive.files().create(body=folder_metadata, fields='id').execute()
            config_folder_id = created_folder['id']
            with _cache_lock:
                _folder_cache[f'{parent_folder}/config'] = (config_folder_id, time.monotonic() + _FOLDER_TTL)

        query = (
            f"parents='{config_folder_id}' "
            f"and name='environments-config.json' "
            f"and trashed=false"
        )
        results = drive.files().list(
            q=query, spaces='drive', pageSize=1, fields='files(id)',
        ).execute()
        files = results.get('files', [])

        payload = json.dumps(config_data, indent=2).encode('utf-8')
        media = MediaIoBaseUpload(BytesIO(payload), mimetype='application/json', resumable=False)

        if not files:
            logger.info('write_environments_config: environments-config.json not found — creating it')
            file_metadata = {'name': 'environments-config.json', 'parents': [config_folder_id]}
            created_file = drive.files().create(body=file_metadata, media_body=media, fields='id').execute()
            file_id = created_file['id']
        else:
            file_id = files[0]['id']
            drive.files().update(fileId=file_id, media_body=media).execute()

        logger.info('write_environments_config: saved environments-config.json (file_id=%s)', file_id)
        return True

    except Exception as e:
        logger.error('write_environments_config: %s', e, exc_info=True)
        return f'Drive API error: {e}'
```

- [ ] **Step 2: Syntax-check and commit**

```bash
cd viewer/webapp
venv\Scripts\python -c "import ast; ast.parse(open('gdrive_briefs.py').read())"
git add viewer/webapp/gdrive_briefs.py
git commit -m "Add environments-config.json read/write to gdrive_briefs"
```

---

### Task 3: Routes — `/environments`, `GET/PUT /api/environments/config`

**Files:**
- Modify: `viewer/webapp/app.py`

**Interfaces:**
- Consumes: `gdrive_briefs.read_environments_config`/`write_environments_config` (Task 2), `asana_discovery.get_portfolio_project_names` (Task 1), `db.get_google_refresh_token`, `db.get_google_drive_folder_id`, `db.get_asana_pat`, `_asana_api_get` (all existing except the two named above).
- Produces:
  - `GET /environments` — page shell.
  - `GET /api/environments/config` — `{"customers": {...}, "in_scope_names": [...] | null, "needs_pat"?: true, "error"?: str}`. `in_scope_names` is `null` whenever it couldn't be determined (no PAT, or an Asana error) — Task 4's client always checks for that before rendering a customer list, rather than treating `null` as "nobody in scope."
  - `PUT /api/environments/config` — body `{"customers": {...}}`, returns `{"ok": true}` or `{"error": str}`.

No automated test for this task (see Global Constraints).

- [ ] **Step 1: Add the module-level portfolio GID constant**

In `viewer/webapp/app.py`, add near the other module-level constants (e.g. near `ASANA_API_BASE`):

```python
# Verify this against a real GET /portfolios/{gid}/items call before
# relying on it — see the Environments tab design spec's "Customer list
# scope" section. One project per customer in this portfolio; a customer
# is in scope if their account_name matches a project name in it.
ENVIRONMENTS_PORTFOLIO_GID = '1209916881329688'
```

- [ ] **Step 2: Add the routes**

Add to `viewer/webapp/app.py`, near the `/customers` routes:

```python
@app.route('/environments')
@login_required
def environments_page():
    return render_template('environments.html', user_email=request.brief_user['email'])


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


@app.route('/api/environments/config', methods=['PUT'])
@login_required
def api_environments_config_update():
    """Writes the full customers dict (teams + environments per customer)
    back to environments-config.json."""
    google_token = db.get_google_refresh_token(request.brief_user['id'])
    folder_id = db.get_google_drive_folder_id(request.brief_user['id'])
    if not google_token:
        return jsonify({'error': 'Google Drive not connected'}), 400
    data = request.get_json(silent=True)
    if not data or 'customers' not in data or not isinstance(data['customers'], dict):
        return jsonify({'error': 'Invalid payload — must include a customers object'}), 400
    result = gdrive_briefs.write_environments_config(data['customers'], google_token, folder_id)
    if result is not True:
        msg = result if isinstance(result, str) else 'Failed to write environments-config.json'
        return jsonify({'error': msg}), 500
    return jsonify({'ok': True})
```

- [ ] **Step 3: Syntax-check and commit**

```bash
cd viewer/webapp
venv\Scripts\python -c "import ast; ast.parse(open('app.py').read())"
git add viewer/webapp/app.py
git commit -m "Add GET /environments and GET/PUT /api/environments/config routes"
```

---

### Task 4: Standalone `environments.html` page

**Files:**
- Create: `viewer/webapp/templates/environments.html`

**Interfaces:**
- Consumes: `GET /api/environments/config` and `PUT /api/environments/config` (Task 3).
- Produces: the page rendered at `/environments`. Task 5's topbar button is the only thing that links here.

Client-side data model: one JS object `STATE = {customers: {...}, in_scope_names: [...]}`, edited entirely in memory (checkboxes/inputs mutate `STATE.customers[name]` directly), with a single "Save to Drive" button that `PUT`s `{customers: STATE.customers}` — same "edit client-side, one Save button writes it all back" model `customers.html` already uses, not per-field auto-save.

- [ ] **Step 1: Create the page**

Create `viewer/webapp/templates/environments.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Daily Brief · Environments</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg:#f5f4f1; --surface:#fff; --surface2:#f0efe9; --border:#e2e0d8; --border-strong:#c8c6bc;
  --t1:#1a1916; --t2:#5a5850; --t3:#9a9890;
  --accent:#1a5ca0; --accent-bg:#eef3fb; --accent-t:#1a5ca0;
  --good-bg:#eef7ee; --good-t:#2a7a34; --bad-bg:#fef1f0; --bad-t:#b02520;
  --font:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
  --mono:ui-monospace,"SF Mono","Cascadia Code",monospace; --r:5px;
}
@media(prefers-color-scheme:dark){:root{
  --bg:#18181b; --surface:#1e1e22; --surface2:#26262c; --border:#2c2c32; --border-strong:#3c3c44;
  --t1:#e6e4de; --t2:#9a9890; --t3:#5a5850;
  --accent:#5a9de0; --accent-bg:#0f2140; --accent-t:#6aade8;
  --good-bg:#122415; --good-t:#5cc26a; --bad-bg:#280e0e; --bad-t:#e06868;
}}
html{font-size:14px;}
body{font-family:var(--font);background:var(--bg);color:var(--t1);line-height:1.5;padding:24px 16px 60px;max-width:900px;margin:0 auto;}
.head{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:1.25rem;padding-bottom:1rem;border-bottom:1.5px solid var(--border-strong);}
.head h1{font-size:19px;font-weight:600;letter-spacing:-.025em;}
.head .sub{font-size:12px;color:var(--t3);}
a.back{font-size:12px;color:var(--accent-t);text-decoration:none;}
a.back:hover{text-decoration:underline;}
.hint{font-size:12.5px;color:var(--t3);padding:12px 0;}
.empty{color:var(--t3);font-size:12px;padding:16px 0;text-align:center;}
select,input[type="text"],input[type="date"],textarea{font-family:var(--font);font-size:12px;padding:4px 8px;border:1px solid var(--border-strong);border-radius:var(--r);background:var(--surface);color:var(--t1);}
textarea{width:100%;min-height:52px;resize:vertical;}
.btn{font-size:11px;font-weight:500;padding:4px 10px;border-radius:var(--r);border:.5px solid var(--border-strong);background:var(--surface);color:var(--t2);cursor:pointer;}
.btn:hover{filter:brightness(.95);}
.btn.primary{background:var(--accent-bg);border-color:var(--accent);color:var(--accent-t);}
.btn.danger{border-color:var(--bad-t);color:var(--bad-t);background:var(--bad-bg);}
.btn.save{background:var(--good-bg);border-color:var(--good-t);color:var(--good-t);}
.btn:disabled{opacity:.4;cursor:default;}
.toolbar{display:flex;gap:8px;align-items:center;margin-bottom:14px;}
.customer-select{min-width:260px;}
.panel{border:1px solid var(--border);border-radius:var(--r);background:var(--surface);margin-bottom:16px;overflow:hidden;}
.panel-head{padding:10px 14px;background:var(--surface2);font-size:11px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:var(--t3);display:flex;justify-content:space-between;align-items:center;}
.panel-body{padding:12px 14px;}
table{width:100%;border-collapse:collapse;font-size:12.5px;}
th{text-align:left;font-size:10px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--t3);padding:6px 8px;border-bottom:1px solid var(--border-strong);}
td{padding:7px 8px;border-bottom:.5px solid var(--border);vertical-align:top;}
tr:last-child td{border-bottom:none;}
.add-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:10px;padding-top:10px;border-top:1px solid var(--border);}
.add-row input{flex:1;min-width:120px;}
.env-card{border:1px solid var(--border);border-radius:var(--r);margin-bottom:12px;overflow:hidden;}
.env-card-head{padding:8px 12px;background:var(--surface2);display:flex;justify-content:space-between;align-items:center;font-size:12.5px;font-weight:600;}
.env-card-body{padding:10px 12px;}
.field-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px;}
.field-grid label,.field label{display:block;font-size:10px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--t3);margin-bottom:3px;}
.field-grid input,.field-grid select{width:100%;}
.field{margin-bottom:10px;}
.team-checks label{display:inline-flex;align-items:center;gap:4px;font-size:11.5px;font-weight:500;text-transform:none;letter-spacing:0;color:var(--t1);margin-right:12px;margin-bottom:4px;}
.dated-list-row{display:flex;gap:6px;align-items:center;margin-bottom:6px;}
.dated-list-row input{flex:1;}
.dated-list-row input.date-input{flex:0 0 130px;}
.dated-list-row input.ticket-input{flex:0 0 110px;}
.msg{font-size:11.5px;color:var(--t3);margin-top:10px;min-height:1.2em;}
.toast-container{position:fixed;top:16px;left:50%;transform:translateX(-50%);z-index:9999;pointer-events:none;}
.toast{padding:10px 20px;border-radius:var(--r);font-size:13px;font-weight:500;pointer-events:auto;
  opacity:0;transform:translateY(-12px);animation:toast-in .25s ease forwards;}
.toast.ok{background:var(--good-bg);color:var(--good-t);border:1px solid var(--good-t);}
.toast.err{background:var(--bad-bg);color:var(--bad-t);border:1px solid var(--bad-t);}
.toast.out{animation:toast-out .25s ease forwards;}
@keyframes toast-in{to{opacity:1;transform:translateY(0);}}
@keyframes toast-out{from{opacity:1;transform:translateY(0);}to{opacity:0;transform:translateY(-12px);}}
</style>
</head>
<body>
<div class="toast-container" id="toast-container"></div>

<div class="head">
  <div>
    <a class="back" href="{{ url_for('index') }}">&larr; Back to briefs</a>
    <h1>Environments</h1>
    <div class="sub">Signed in as {{ user_email }}</div>
  </div>
  <button class="btn save" id="save-btn" onclick="saveAll()" disabled>Save to Drive</button>
</div>

<div class="toolbar">
  <label for="customer-select" style="font-size:12px;font-weight:500;">Customer:</label>
  <select class="customer-select" id="customer-select" onchange="onCustomerChange()">
    <option value="">Loading…</option>
  </select>
</div>

<div id="content"><div class="empty">Loading&hellip;</div></div>
<div class="msg" id="msg"></div>

<script>
const BASE = document.querySelector('base')?.href || '';
let STATE = null;
let CURRENT = null;
let dirty = false;

const COMPONENT_OPTIONS = ['Zeebe', 'Operate', 'Tasklist', 'Optimize', 'Connectors'];

async function load() {
  try {
    const r = await fetch(`${BASE}api/environments/config`, {credentials:'include'});
    if (!r.ok) throw new Error(r.statusText);
    STATE = await r.json();
    renderCustomerSelect();
  } catch(e) {
    document.getElementById('content').innerHTML =
      `<div class="empty" style="color:var(--bad-t)">Failed to load: ${e.message}</div>`;
  }
}

function renderCustomerSelect() {
  const select = document.getElementById('customer-select');
  const content = document.getElementById('content');

  if (STATE.needs_pat) {
    select.innerHTML = '<option value="">—</option>';
    content.innerHTML = '<div class="hint">Add your Asana PAT in Settings to load the customer list.</div>';
    return;
  }
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

  select.innerHTML = STATE.in_scope_names.map(name =>
    `<option value="${escAttr(name)}">${esc(name)}</option>`
  ).join('');
  CURRENT = STATE.in_scope_names[0];
  select.value = CURRENT;
  ensureCustomer(CURRENT);
  renderCustomer();
}

function onCustomerChange() {
  CURRENT = document.getElementById('customer-select').value;
  ensureCustomer(CURRENT);
  renderCustomer();
}

function ensureCustomer(name) {
  if (!STATE.customers[name]) {
    STATE.customers[name] = {teams: [], environments: []};
  }
}

function renderCustomer() {
  const c = STATE.customers[CURRENT];
  const content = document.getElementById('content');
  content.innerHTML = `
    <div class="panel">
      <div class="panel-head"><span>Teams</span></div>
      <div class="panel-body">
        <table>
          <thead><tr><th>Name</th><th>Notes</th><th></th></tr></thead>
          <tbody id="teams-body">${teamsRowsHtml(c.teams)}</tbody>
        </table>
        <div class="add-row">
          <input type="text" id="new-team-name" placeholder="Team name">
          <input type="text" id="new-team-notes" placeholder="Notes (optional)">
          <button class="btn primary" onclick="addTeam()">Add team</button>
        </div>
      </div>
    </div>
    <div class="panel">
      <div class="panel-head">
        <span>Environments</span>
        <button class="btn primary" onclick="addEnvironment()">Add environment</button>
      </div>
      <div class="panel-body" id="envs-body">${environmentsHtml(c)}</div>
    </div>
  `;
}

function teamsRowsHtml(teams) {
  if (!teams.length) return '<tr><td colspan="3" class="empty">No teams yet</td></tr>';
  return teams.map((t, i) => `
    <tr>
      <td><input type="text" value="${escAttr(t.name)}" onchange="updateTeamField(${i}, 'name', this.value)"></td>
      <td><input type="text" value="${escAttr(t.notes || '')}" onchange="updateTeamField(${i}, 'notes', this.value)" style="width:100%"></td>
      <td><button class="btn danger" onclick="removeTeam(${i})">Remove</button></td>
    </tr>
  `).join('');
}

function addTeam() {
  const nameInput = document.getElementById('new-team-name');
  const notesInput = document.getElementById('new-team-notes');
  const name = nameInput.value.trim();
  if (!name) return;
  const id = 'team-' + name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '') + '-' + Date.now();
  STATE.customers[CURRENT].teams.push({id, name, notes: notesInput.value.trim()});
  nameInput.value = '';
  notesInput.value = '';
  markDirty();
  renderCustomer();
}

function updateTeamField(idx, field, value) {
  STATE.customers[CURRENT].teams[idx][field] = value;
  markDirty();
}

function removeTeam(idx) {
  const team = STATE.customers[CURRENT].teams[idx];
  if (!confirm(`Remove team "${team.name}"? It will also be unlinked from any environment.`)) return;
  STATE.customers[CURRENT].teams.splice(idx, 1);
  STATE.customers[CURRENT].environments.forEach(env => {
    env.team_ids = (env.team_ids || []).filter(id => id !== team.id);
  });
  markDirty();
  renderCustomer();
}

function environmentsHtml(c) {
  if (!c.environments.length) return '<div class="empty">No environments yet</div>';
  return c.environments.map((env, i) => environmentCardHtml(env, i, c.teams)).join('');
}

function environmentCardHtml(env, idx, teams) {
  const teamChecks = teams.map(t => `
    <label><input type="checkbox" ${((env.team_ids||[]).includes(t.id)) ? 'checked' : ''}
      onchange="toggleEnvTeam(${idx}, '${t.id}', this.checked)"> ${esc(t.name)}</label>
  `).join('') || '<span class="hint" style="padding:0">No teams defined yet</span>';

  const componentChecks = COMPONENT_OPTIONS.map(comp => `
    <label><input type="checkbox" ${((env.versions.components||[]).includes(comp)) ? 'checked' : ''}
      onchange="toggleEnvComponent(${idx}, '${comp}', this.checked)"> ${comp}</label>
  `).join('');

  return `
    <div class="env-card">
      <div class="env-card-head">
        <input type="text" value="${escAttr(env.label)}" onchange="updateEnvField(${idx}, 'label', this.value)" style="font-weight:600;font-size:12.5px;">
        <button class="btn danger" onclick="removeEnvironment(${idx})">Remove</button>
      </div>
      <div class="env-card-body">
        <div class="field"><label>Teams</label><div class="team-checks">${teamChecks}</div></div>
        <div class="field-grid">
          <div><label>Deployment model</label>
            <select onchange="updateEnvNested(${idx}, 'deployment', 'model', this.value)">
              <option value="SaaS" ${env.deployment.model==='SaaS'?'selected':''}>SaaS</option>
              <option value="Self-Managed" ${env.deployment.model==='Self-Managed'?'selected':''}>Self-Managed</option>
            </select>
          </div>
          <div><label>Install method</label><input type="text" value="${escAttr(env.deployment.install_method)}" onchange="updateEnvNested(${idx}, 'deployment', 'install_method', this.value)"></div>
          <div><label>Region</label><input type="text" value="${escAttr(env.deployment.region)}" onchange="updateEnvNested(${idx}, 'deployment', 'region', this.value)"></div>
          <div><label>Multi-tenancy</label><input type="text" value="${escAttr(env.deployment.multi_tenancy)}" onchange="updateEnvNested(${idx}, 'deployment', 'multi_tenancy', this.value)"></div>
          <div><label>Sizing</label><input type="text" value="${escAttr(env.deployment.sizing)}" onchange="updateEnvNested(${idx}, 'deployment', 'sizing', this.value)"></div>
          <div><label>Camunda version</label><input type="text" value="${escAttr(env.versions.camunda_version)}" onchange="updateEnvNested(${idx}, 'versions', 'camunda_version', this.value)"></div>
        </div>
        <div class="field"><label>Components</label><div class="team-checks">${componentChecks}</div></div>
        <div class="field-grid">
          <div><label>Console URL</label><input type="text" value="${escAttr(env.links.console_url)}" onchange="updateEnvNested(${idx}, 'links', 'console_url', this.value)"></div>
          <div><label>Support plan</label><input type="text" value="${escAttr(env.links.support_plan)}" onchange="updateEnvNested(${idx}, 'links', 'support_plan', this.value)"></div>
        </div>
        <div class="field"><label>Cluster URLs (one per line)</label><textarea onchange="updateEnvListField(${idx}, 'links', 'cluster_urls', this.value)">${esc((env.links.cluster_urls||[]).join('\n'))}</textarea></div>
        <div class="field"><label>Runbook links (one per line)</label><textarea onchange="updateEnvListField(${idx}, 'links', 'runbook_links', this.value)">${esc((env.links.runbook_links||[]).join('\n'))}</textarea></div>
        <div class="field"><label>Notes</label><textarea onchange="updateEnvField(${idx}, 'notes', this.value)">${esc(env.notes || '')}</textarea></div>
        <div class="field"><label>Diagnostic reports</label>${datedListHtml(idx, 'diagnostic_reports', env.diagnostic_reports, true)}</div>
        <div class="field"><label>Helm values.yaml history</label>${datedListHtml(idx, 'helm_values', env.helm_values, false)}</div>
      </div>
    </div>
  `;
}

function datedListHtml(envIdx, key, rows, withTicket) {
  const rowsHtml = (rows || []).map((row, rowIdx) => `
    <div class="dated-list-row">
      <input type="text" placeholder="Link" value="${escAttr(row.link || '')}" onchange="updateDatedListField(${envIdx}, '${key}', ${rowIdx}, 'link', this.value)">
      <input type="date" class="date-input" value="${escAttr(row.date || row.generated_date || '')}" onchange="updateDatedListField(${envIdx}, '${key}', ${rowIdx}, '${withTicket ? 'generated_date' : 'date'}', this.value)">
      ${withTicket ? `<input type="text" class="ticket-input" placeholder="Ticket" value="${escAttr(row.ticket || '')}" onchange="updateDatedListField(${envIdx}, '${key}', ${rowIdx}, 'ticket', this.value)">` : ''}
      <button class="btn danger" onclick="removeDatedListRow(${envIdx}, '${key}', ${rowIdx})">Remove</button>
    </div>
  `).join('');
  return rowsHtml + `<button class="btn" onclick="addDatedListRow(${envIdx}, '${key}', ${withTicket})">Add</button>`;
}

function addEnvironment() {
  const label = prompt('Environment label (e.g. Production, Staging):');
  if (!label || !label.trim()) return;
  STATE.customers[CURRENT].environments.push({
    id: 'env-' + Date.now(),
    label: label.trim(),
    team_ids: [],
    deployment: {model: 'SaaS', install_method: '', region: '', multi_tenancy: '', sizing: ''},
    versions: {camunda_version: '', components: []},
    links: {console_url: '', cluster_urls: [], support_plan: '', runbook_links: []},
    notes: '',
    diagnostic_reports: [],
    helm_values: [],
  });
  markDirty();
  renderCustomer();
}

function removeEnvironment(idx) {
  const env = STATE.customers[CURRENT].environments[idx];
  if (!confirm(`Remove environment "${env.label}"?`)) return;
  STATE.customers[CURRENT].environments.splice(idx, 1);
  markDirty();
  renderCustomer();
}

function updateEnvField(idx, field, value) {
  STATE.customers[CURRENT].environments[idx][field] = value;
  markDirty();
}

function updateEnvNested(idx, group, field, value) {
  STATE.customers[CURRENT].environments[idx][group][field] = value;
  markDirty();
}

function updateEnvListField(idx, group, field, textareaValue) {
  STATE.customers[CURRENT].environments[idx][group][field] =
    textareaValue.split('\n').map(s => s.trim()).filter(Boolean);
  markDirty();
}

function toggleEnvTeam(idx, teamId, checked) {
  const env = STATE.customers[CURRENT].environments[idx];
  env.team_ids = env.team_ids || [];
  if (checked) {
    if (!env.team_ids.includes(teamId)) env.team_ids.push(teamId);
  } else {
    env.team_ids = env.team_ids.filter(id => id !== teamId);
  }
  markDirty();
}

function toggleEnvComponent(idx, comp, checked) {
  const env = STATE.customers[CURRENT].environments[idx];
  env.versions.components = env.versions.components || [];
  if (checked) {
    if (!env.versions.components.includes(comp)) env.versions.components.push(comp);
  } else {
    env.versions.components = env.versions.components.filter(c => c !== comp);
  }
  markDirty();
}

function addDatedListRow(envIdx, key, withTicket) {
  const env = STATE.customers[CURRENT].environments[envIdx];
  env[key] = env[key] || [];
  env[key].push(withTicket ? {link: '', generated_date: '', ticket: ''} : {link: '', date: ''});
  markDirty();
  renderCustomer();
}

function removeDatedListRow(envIdx, key, rowIdx) {
  STATE.customers[CURRENT].environments[envIdx][key].splice(rowIdx, 1);
  markDirty();
  renderCustomer();
}

function updateDatedListField(envIdx, key, rowIdx, field, value) {
  STATE.customers[CURRENT].environments[envIdx][key][rowIdx][field] = value;
  markDirty();
}

function markDirty() {
  dirty = true;
  document.getElementById('save-btn').disabled = false;
  document.getElementById('msg').textContent = 'Unsaved changes';
}

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

function showToast(text, type, duration) {
  const container = document.getElementById('toast-container');
  const el = document.createElement('div');
  el.className = 'toast ' + type;
  el.textContent = text;
  container.appendChild(el);
  setTimeout(() => {
    el.classList.add('out');
    el.addEventListener('animationend', () => el.remove());
  }, duration);
}

function esc(s) { const d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }
function escAttr(s) { return esc(s).replace(/"/g, '&quot;'); }

window.addEventListener('beforeunload', e => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });

load();
</script>
</body>
</html>
```

- [ ] **Step 2: Sanity-check the page**

Run a JS syntax check on the inline script and a Jinja render check, same approach used for `tasks.html`:

```bash
cd viewer/webapp
venv\Scripts\python -c "
import re
content = open('templates/environments.html', encoding='utf-8').read()
m = re.search(r'<script>(.*?)</script>', content, re.S)
open('_env_script_check.js', 'w', encoding='utf-8').write(m.group(1))
"
node --check _env_script_check.js
```

Expected: no output (exit 0). Then remove the temp file:

```bash
rm _env_script_check.js
```

```bash
venv\Scripts\python -c "
import sys
sys.path.insert(0, 'tests')
from template_test_utils import make_env
env = make_env()
env.globals['url_for'] = lambda name: '/'
template = env.get_template('environments.html')
html = template.render(user_email='test@example.com')
assert '<h1>Environments</h1>' in html
assert 'id=\"customer-select\"' in html
print('TEMPLATE RENDER OK, length:', len(html))
"
```

Expected: `TEMPLATE RENDER OK, length: <some number>` with no exception.

- [ ] **Step 3: Commit**

```bash
git add viewer/webapp/templates/environments.html
git commit -m "Add standalone Environments page"
```

---

### Task 5: Add an "Environments" topbar link

**Files:**
- Modify: `viewer/daily-brief-viewer.html`

**Interfaces:**
- Consumes: `GET /environments` (Task 4).

Same reasoning as the Tasks tab's topbar link: this file is served via `send_from_directory`, not Jinja-rendered, so use a plain relative `href` with no leading slash — every existing fetch/link in this file already does this to stay correct under the app's nginx sub-path deployment.

- [ ] **Step 1: Add the link**

In `viewer/daily-brief-viewer.html`, find the topbar's button group (the "Tasks" link added by the prior plan should already be there; if not, find the "Connect Google Drive" button):

```html
  <a class="icon-btn" href="tasks" style="text-decoration:none;display:inline-flex;align-items:center;">Tasks</a>
```

Add a second link directly after it:

```html
  <a class="icon-btn" href="tasks" style="text-decoration:none;display:inline-flex;align-items:center;">Tasks</a>
  <a class="icon-btn" href="environments" style="text-decoration:none;display:inline-flex;align-items:center;">Environments</a>
```

(If the Tasks link isn't present yet in this checkout, add the Environments link directly after the "Connect Google Drive" button instead, using the same styling.)

- [ ] **Step 2: Commit**

```bash
git add viewer/daily-brief-viewer.html
git commit -m "Add Environments link to the topbar"
```

---

### Task 6: End-to-end manual verification

No further code changes. Confirms Tasks 1–5 work together, to the same standard of coverage every other route in this app gets (see Global Constraints).

- [ ] **Step 1: Automated portion — server boot and route auth-gating**

```bash
cd viewer/webapp
venv\Scripts\python -m pytest tests/ -v
```

Expected: all tests pass, including the 3 new `get_portfolio_project_names` tests.

Start the dev server with placeholder secrets (no real Azure AD or Postgres needed for this check — same approach used for the Tasks tab's equivalent verification):

```bash
FLASK_SECRET_KEY=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcd AZURE_TENANT_ID=00000000-0000-0000-0000-000000000000 AZURE_CLIENT_ID=00000000-0000-0000-0000-000000000000 AZURE_CLIENT_SECRET=placeholder AZURE_REDIRECT_URI=http://localhost:8000/auth/callback venv/Scripts/python app.py
```

In another terminal:

```bash
curl -s -D - -o /dev/null http://127.0.0.1:8000/environments | grep -i location
curl -s -D - -o /dev/null http://127.0.0.1:8000/api/environments/config | grep -i location
```

Expected: both print `Location: /login` — confirming the new routes correctly enforce `@login_required`, matching every other protected route.

Stop the server afterward.

- [ ] **Step 2: Manual portion — needs a real sign-in, Asana PAT, and Google Drive connection**

These require your own Camunda Azure AD credentials and cannot be done by an agent:

1. Sign in and confirm an "Environments" button now shows in the topbar next to "Tasks".
2. Click it. If no Asana PAT is saved, confirm it shows "Add your Asana PAT in Settings" rather than an error.
3. Add a PAT. Confirm the customer dropdown populates from the Asana portfolio (`https://app.asana.com/0/portfolio/1209916881329688/1209923685916686`) — if it errors, the portfolio GID constant (`ENVIRONMENTS_PORTFOLIO_GID` in `app.py`) likely needs correcting; check the error message against a manual `GET /portfolios/{gid}/items` call.
4. For a customer, add a team, add an environment, fill in a few fields, add a diagnostic report row and a Helm values row, then click "Save to Drive". Confirm the toast shows success.
5. Reload the page. Confirm everything you entered is still there (round-tripped through `environments-config.json` in Drive).
6. Remove a team that's linked to an environment. Confirm the environment's team checkbox for it disappears without breaking anything else, and save again.
