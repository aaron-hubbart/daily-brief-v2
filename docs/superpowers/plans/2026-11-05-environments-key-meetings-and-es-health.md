# Environments Tab — Key Meetings & ES Health Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-team ES meeting tracking and a Green/Yellow/Red health signal to the existing Environments tab, surfaced through three drill-down views (Portfolio → Customer → Team).

**Architecture:** Health scoring and the meeting catalog live in one new pure-Python module (`es_health.py`) with no Flask dependency, so the scoring logic is unit-testable directly — the same "testable pure function" pattern `asana_discovery.py` already uses. `app.py`'s existing per-account GET/PUT routes grow two new JSON arrays (`meetings`, `es_activities`) and the GET route annotates its response with computed health via `es_health`, so the Drive JSON file itself never stores a stale score. A new portfolio-rollup route fans out to every in-scope customer's file and reuses the same `es_health` functions. The existing `environments.html` single-page app gains new render functions following its established patterns (`.panel`, caret-collapse, `markDirty()`/`saveAll()`) rather than a new page or framework.

**Tech Stack:** Python 3 / Flask (existing), pytest (existing, `viewer/webapp/tests/`), vanilla JS single-page app (existing, `environments.html`), Google Drive JSON storage via `gdrive_briefs.py` (existing) — no new dependencies.

**Spec:** [docs/superpowers/specs/2026-11-05-environments-key-meetings-and-es-health-design.md](../specs/2026-11-05-environments-key-meetings-and-es-health-design.md)

## Global Constraints

- No live Jira/Salesforce/Gainsight integration in this plan — sentiment and open-issue counts are manually entered fields; a Glean-refresh skill is an explicit future follow-up, not built here.
- No ingestion of the full Lamppost ES playbook catalog — only the 10 catalog entries in the spec's table; ES Activities stays a free-text checklist, not a synced catalog.
- No enforced data-entry ordering for the one-time onboarding sequence — a TAM can record any step in any order; only the *scoring* uses catalog order (see Task 1).
- No calendar integration — `standing_schedule` and `last_held_date` are TAM-entered text/dates, not real calendar events.
- No automated test exists today for any Environments Flask route or any function in `environments.html` (`app.py` needs live env vars + Postgres to import; the JS has no test harness) — this is a documented, accepted gap this plan does not close. Only `es_health.py` (new, dependency-free) gets automated tests; routes and JS are verified manually, per task.
- Never overwrite a populated field with a blank/failed lookup (existing discovery-skill discipline) — relevant once the future Glean-refresh skill exists, not exercised by this plan's manual-entry fields.

## Review Focus

- A team marked `exempt: true` must be fully excluded from health/rollup even if it still has old `meetings`/`es_activities` rows from before it was marked exempt (data isn't deleted, just ignored) — covered in Task 1.
- A customer with zero teams, or every team exempt, must roll up to a clean "Green / no tracked teams" result, not crash or default to Red — covered in Task 1.
- An `optional`/`conditional` catalog entry (e.g. Executive Meeting, Platform Best Practices) must never contribute to the Red/Yellow count regardless of its own overdue state, whether or not it's been marked inapplicable — covered in Task 1.
- The one-time sequence's "only the earliest incomplete step counts" rule must re-target correctly once that step is marked `occurred` — fixing step 1 while step 2 is still outstanding must make step 2 the one cited, not silently clear all issues or double-count both — covered in Task 1.
- One customer's unreadable/missing Drive file (a 404 string or `None` from a per-account read) in the portfolio rollup must not take down the whole Portfolio view — that customer renders as an error row while the rest still load — covered in Task 1 (`build_portfolio_rollup`, tested with a hand-rolled fake reader) and exercised live in Task 3.

---

## File Structure

**Create:**
- `viewer/webapp/es_health.py` — meeting catalog constant + all health-scoring logic (pure functions, no Flask import).
- `viewer/webapp/tests/test_es_health.py` — unit tests for the above.

**Modify:**
- `viewer/webapp/gdrive_briefs.py` — `_EMPTY_ACCOUNT_ENVIRONMENTS` (line 635) gains `meetings`/`es_activities`.
- `viewer/webapp/app.py` — environments routes (lines 1337–1419) accept/return the new fields and annotate health; two new routes (meeting catalog, portfolio rollup).
- `viewer/webapp/templates/environments.html` — new JS functions for meeting-catalog loading, team health badges, the Team detail view, and the Portfolio landing view, following the file's existing patterns. (This file is already ~1200 lines; this plan adds functions alongside the existing ones rather than restructuring it — a future split into multiple `<script>`/include files is reasonable but out of scope here, same "don't unilaterally restructure" call the spec makes for scoring.)

---

### Task 1: Meeting catalog & health-scoring logic

**Files:**
- Create: `viewer/webapp/es_health.py`
- Test: `viewer/webapp/tests/test_es_health.py`

**Interfaces:**
- Produces:
  - `MEETING_CATALOG: List[Dict]` — 10 entries, each `{"id": str, "name": str, "category": "one_time"|"recurring", "default_cadence": str|None, "default_requirement": "required"|"optional"|"conditional"}`, in the exact order from the spec's table (order matters — it's the one-time sequence's dependency order).
  - `compute_team_health(team: dict, meetings: List[dict], es_activities: List[dict], today: Optional[date] = None) -> Dict` — `meetings`/`es_activities` are already filtered to this team's `team_id` by the caller. Returns `{"level": "Green"|"Yellow"|"Red"|"Exempt", "reasons": List[str], "overdue_count": int, "stale_count": int}`.
  - `compute_account_health(data: Dict, today: Optional[date] = None) -> Dict` — takes the raw `{teams, environments, use_cases, meetings, es_activities}` dict (as read from Drive), mutates each entry in `data["teams"]` to add a `"health"` key (via `compute_team_health`), adds `data["rollup"]` (see below), and returns `data`.
  - `compute_customer_rollup(team_healths: List[Tuple[dict, dict]]) -> Dict` — takes `(team, health)` pairs for **non-exempt teams only** (caller filters). Returns `{"level": "Green"|"Yellow"|"Red", "team_count": int, "overdue_count": int, "sentiment_level": str, "open_issues_total": int}`. Empty input returns `{"level": "Green", "team_count": 0, "overdue_count": 0, "sentiment_level": "", "open_issues_total": 0}`.
  - `build_portfolio_rollup(customers: List[Dict], read_fn: Callable[[str], Union[dict, str, None]], today: Optional[date] = None) -> List[Dict]` — `customers` is `[{"name": str, "theater": str|None}, ...]`. For each, calls `read_fn(name)` (the caller supplies e.g. `lambda name: gdrive_briefs.read_account_environments(token, name)`, same injectable-callable pattern `asana_discovery.py` already uses, so this is testable with a hand-rolled fake and no network/mocking library). If `read_fn` returns a `dict`, runs `compute_account_health` and emits `{"name", "theater", "error": None, **rollup}`; if it returns a `str` or `None`, emits `{"name", "theater", "level": "Green", "team_count": 0, "overdue_count": 0, "sentiment_level": "", "open_issues_total": 0, "error": <the string, or a generic message for None>}`. One customer's failure never raises — the loop always produces one entry per input customer. Result is sorted by `name` case-insensitively.

**Constants (exact values — pin these, don't re-derive):**
```python
RECURRING_CADENCE_DAYS = {
    'monthly': 30, 'quarterly': 91, 'yearly': 365,
    'periodic': 91,   # ES105.03 Technical Roadmap Review — spec treats "periodic" as quarterly by default
    'ongoing': None,  # ES301 — never overdue; it's also never `required`, so this never matters for scoring
}
ES_ACTIVITY_STALE_GRACE_DAYS = 14   # guess — not_done activity must be at least this old to count as stale
OPEN_ISSUES_YELLOW_THRESHOLD = 10   # guess — placeholder per spec, trivially tunable later
```

**Rules to implement (exact, from the spec):**
- One-time entry status: `"not_scheduled"` (or no row) / `"scheduled"` / `"occurred"`. Overdue iff: no row, or `status != "occurred"` and (`status != "scheduled"` or `scheduled_date` is in the past). `scheduled_date` in the future with `status == "scheduled"` is **not** overdue.
- Recurring entry: overdue iff no row / no `last_held_date`, or `today > last_held_date + RECURRING_CADENCE_DAYS[default_cadence]` days (cadence `None` ⇒ never overdue).
- ES activity: stale iff `status == "not_done"` and (`last_updated` empty or `today - last_updated > ES_ACTIVITY_STALE_GRACE_DAYS` days). `status == "done"` is never stale.
- Applicability: a catalog entry is applicable to a team unless (a) `default_requirement in ("optional", "conditional")` **and** its `id` is in `team.get("inapplicable_meeting_types", [])`. `"required"` entries are always applicable (short of full-team `exempt`).
- Only `default_requirement == "required"` entries can ever appear in `overdue_count`/`reasons` — optional/conditional ones are never counted, applicable or not.
- One-time sequence: among applicable required one-time entries in `MEETING_CATALOG` order, only the **first** one that isn't `occurred` counts as overdue; later ones in the sequence are not separately counted even if also not `occurred`.
- Recurring: every applicable required recurring entry that's overdue counts independently (no "first only" rule — that's one-time-only).
- `level`: `"Exempt"` if `team.get("exempt")` (short-circuits everything else — no reasons computed). Else: `"Red"` if `sentiment == "Red"` or `(overdue_count + stale_count) >= 2`; `"Yellow"` if `sentiment == "Yellow"` or `(overdue_count + stale_count) == 1` or (`open_issues` is not `None` and `open_issues > OPEN_ISSUES_YELLOW_THRESHOLD`); else `"Green"`.
- `compute_customer_rollup` level is the worst level among the given teams (`Red` > `Yellow` > `Green`), `Green` if the list is empty. `overdue_count` sums each team's `overdue_count + stale_count`. `sentiment_level` is the worst non-empty `team["sentiment"]` among them (`""` if none set). `open_issues_total` sums each team's `open_issues`, treating `None` as `0`.

- [ ] **Step 1: Write failing tests for `compute_team_health`**

```python
from datetime import date
from es_health import compute_team_health, MEETING_CATALOG

TODAY = date(2026, 11, 5)

def test_exempt_team_returns_exempt_level_ignoring_bad_data():
    team = {"id": "t1", "exempt": True, "sentiment": "Red", "open_issues": 999}
    stale_activity = [{"team_id": "t1", "status": "not_done", "last_updated": "2020-01-01"}]
    result = compute_team_health(team, meetings=[], es_activities=stale_activity, today=TODAY)
    assert result == {"level": "Exempt", "reasons": [], "overdue_count": 0, "stale_count": 0}

def test_no_data_at_all_is_overdue_not_unknown():
    team = {"id": "t1"}
    result = compute_team_health(team, meetings=[], es_activities=[], today=TODAY)
    assert result["level"] in ("Yellow", "Red")
    assert result["overdue_count"] >= 1

def test_one_time_sequence_only_cites_earliest_incomplete_step():
    first_id = MEETING_CATALOG[0]["id"]      # es101-01-handover
    second_name = MEETING_CATALOG[1]["name"]  # "CS Introduction"
    team = {"id": "t1"}
    meetings = [{"team_id": "t1", "meeting_type_id": first_id, "status": "occurred", "occurred_date": "2026-01-01"}]
    result = compute_team_health(team, meetings, es_activities=[], today=TODAY)
    # first step is done, so only the second step counts — not both, not neither
    assert result["overdue_count"] == 1
    assert any(second_name in r for r in result["reasons"])

def test_optional_meeting_never_counts_even_when_overdue_and_applicable():
    exec_id = next(m["id"] for m in MEETING_CATALOG if m["default_requirement"] == "optional")
    team = {"id": "t1"}
    # no row for the exec meeting at all (maximally "overdue"), but it's optional
    result = compute_team_health(team, meetings=[], es_activities=[], today=TODAY)
    # confirm by checking that marking it inapplicable changes nothing about overdue_count
    result_marked = compute_team_health({"id": "t1", "inapplicable_meeting_types": [exec_id]}, meetings=[], es_activities=[], today=TODAY)
    assert result["overdue_count"] == result_marked["overdue_count"]

def test_sentiment_red_forces_red_even_with_no_other_issues():
    recurring_ids = [m["id"] for m in MEETING_CATALOG if m["category"] == "recurring" and m["default_requirement"] == "required"]
    one_time_ids = [m["id"] for m in MEETING_CATALOG if m["category"] == "one_time"]
    meetings = [{"team_id": "t1", "meeting_type_id": mid, "status": "occurred", "occurred_date": "2026-01-01"} for mid in one_time_ids]
    meetings += [{"team_id": "t1", "meeting_type_id": mid, "last_held_date": "2026-11-01"} for mid in recurring_ids]
    team = {"id": "t1", "sentiment": "Red"}
    result = compute_team_health(team, meetings, es_activities=[], today=TODAY)
    assert result["level"] == "Red"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd viewer/webapp && python -m pytest tests/test_es_health.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'es_health'`)

- [ ] **Step 3: Implement `MEETING_CATALOG` and `compute_team_health` in `viewer/webapp/es_health.py`**

Use the exact 10 catalog rows and rules above. `reasons` strings are free-form but must be human-readable (e.g. `f"{entry['name']} is overdue"` / `f"{entry['name']} has not been scheduled"` / `f"{activity['label']} hasn't been updated recently"` / `f"Sentiment: {team['sentiment']}"` / `f"Open issues: {open_issues} (over threshold {OPEN_ISSUES_YELLOW_THRESHOLD})"`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd viewer/webapp && python -m pytest tests/test_es_health.py -v`
Expected: PASS

- [ ] **Step 5: Write failing tests for `compute_customer_rollup` and `compute_account_health`**

```python
from es_health import compute_customer_rollup, compute_account_health

def test_rollup_of_no_teams_is_green_and_empty():
    assert compute_customer_rollup([]) == {
        "level": "Green", "team_count": 0, "overdue_count": 0,
        "sentiment_level": "", "open_issues_total": 0,
    }

def test_rollup_takes_worst_level_and_sums_issues():
    teams = [
        ({"id": "a", "sentiment": "Yellow"}, {"level": "Yellow", "reasons": [], "overdue_count": 1, "stale_count": 0}),
        ({"id": "b", "sentiment": "Red", "open_issues": 5}, {"level": "Red", "reasons": [], "overdue_count": 2, "stale_count": 0}),
    ]
    result = compute_customer_rollup(teams)
    assert result["level"] == "Red"
    assert result["team_count"] == 2
    assert result["overdue_count"] == 3
    assert result["sentiment_level"] == "Red"
    assert result["open_issues_total"] == 5

def test_compute_account_health_annotates_teams_and_excludes_exempt_from_rollup():
    data = {
        "teams": [
            {"id": "a", "exempt": True, "sentiment": "Red"},
            {"id": "b"},
        ],
        "meetings": [], "es_activities": [], "environments": [], "use_cases": [],
    }
    result = compute_account_health(data, today=TODAY)
    assert result["teams"][0]["health"]["level"] == "Exempt"
    assert "health" in result["teams"][1]
    assert result["rollup"]["team_count"] == 1  # exempt team excluded
```

- [ ] **Step 6: Run tests to verify they fail, then implement `compute_customer_rollup` and `compute_account_health`, then run tests to verify they pass**

Run: `cd viewer/webapp && python -m pytest tests/test_es_health.py -v` before and after implementing.
Expected: FAIL then PASS.

- [ ] **Step 7: Write a failing test for `build_portfolio_rollup`'s partial-failure behavior**

```python
from es_health import build_portfolio_rollup

def test_build_portfolio_rollup_isolates_one_customers_read_failure():
    customers = [{"name": "Acme", "theater": "AMER"}, {"name": "Globex", "theater": "EMEA"}]

    def fake_read(name):
        if name == "Acme":
            return {"teams": [{"id": "a"}], "meetings": [], "es_activities": [], "environments": [], "use_cases": []}
        return "No Drive folder found for 'Globex'"  # simulates the 404 string case

    result = build_portfolio_rollup(customers, fake_read, today=TODAY)

    assert len(result) == 2
    acme = next(c for c in result if c["name"] == "Acme")
    globex = next(c for c in result if c["name"] == "Globex")
    assert acme["error"] is None
    assert acme["team_count"] == 1
    assert globex["error"] == "No Drive folder found for 'Globex'"
    assert globex["team_count"] == 0
    assert globex["level"] == "Green"  # placeholder, not a crash
```

- [ ] **Step 8: Run test to verify it fails, implement `build_portfolio_rollup`, run test to verify it passes**

Run: `cd viewer/webapp && python -m pytest tests/test_es_health.py -v` before and after implementing.
Expected: FAIL then PASS.

- [ ] **Step 9: Commit**

```bash
git add viewer/webapp/es_health.py viewer/webapp/tests/test_es_health.py
git commit -m "feat(environments): add ES meeting catalog and health-scoring logic"
```

---

### Task 2: Data model plumbing & per-account API

**Files:**
- Modify: `viewer/webapp/gdrive_briefs.py:635` (`_EMPTY_ACCOUNT_ENVIRONMENTS`)
- Modify: `viewer/webapp/app.py:1345-1419` (existing environments routes), plus one new route

**Interfaces:**
- Consumes: `es_health.compute_account_health(data, today=None)` and `es_health.MEETING_CATALOG` from Task 1.
- Produces: `GET /api/environments/meeting-catalog` → `{"meeting_catalog": MEETING_CATALOG}`. `GET /api/environments/config/<account_name>` response now includes `meetings`, `es_activities`, per-team `health`, and top-level `rollup`. `PUT /api/environments/config/<account_name>` accepts optional `meetings`/`es_activities` arrays in the request body.

- [ ] **Step 1: Update `_EMPTY_ACCOUNT_ENVIRONMENTS`**

In `gdrive_briefs.py:635`, change to:
```python
_EMPTY_ACCOUNT_ENVIRONMENTS: Dict = {'teams': [], 'environments': [], 'use_cases': [], 'meetings': [], 'es_activities': []}
```

- [ ] **Step 2: Add `GET /api/environments/meeting-catalog` in `app.py`**

Add directly after the `/api/environments/config` route (~line 1377):
```python
@app.route('/api/environments/meeting-catalog')
@login_required
def api_environments_meeting_catalog():
    """Static catalog of ES playbook meeting types — see es_health.py."""
    return jsonify({'meeting_catalog': es_health.MEETING_CATALOG})
```
Add `import es_health` near the top of `app.py` alongside the other local module imports (find the existing `import gdrive_briefs` / `import asana_discovery` line and add `import es_health` next to it).

- [ ] **Step 3: Annotate the GET route's response with health**

In `api_environments_account` (`app.py:1379-1393`), after the existing `isinstance(result, str)` 404 check and before `return jsonify(result)`, add:
```python
result = es_health.compute_account_health(result)
```

- [ ] **Step 4: Accept `meetings`/`es_activities` in the PUT route**

In `api_environments_account_update` (`app.py:1396-1419`), mirror the existing `use_cases` validation (lines 1408-1410) for the two new fields, and add them to the dict passed to `write_account_environments`:
```python
meetings = data.get('meetings', [])
if not isinstance(meetings, list):
    return jsonify({'error': 'Invalid payload — meetings must be an array'}), 400
es_activities = data.get('es_activities', [])
if not isinstance(es_activities, list):
    return jsonify({'error': 'Invalid payload — es_activities must be an array'}), 400
```
and extend the `write_account_environments(...)` call's dict literal with `'meetings': meetings, 'es_activities': es_activities`.

- [ ] **Step 5: Manual verification**

Start the Flask app locally (or reuse the existing dev-server workflow for this repo) and, with a real or stubbed account:
- `GET /api/environments/meeting-catalog` returns the 10-entry catalog.
- `GET /api/environments/config/<account>` for an account with no existing file returns `teams: [], meetings: [], es_activities: [], rollup: {level: "Green", team_count: 0, ...}`.
- `PUT` with a `meetings` array round-trips correctly on the next `GET`.
- `PUT` without `meetings`/`es_activities` keys at all (old client) still succeeds, defaulting both to `[]`.

- [ ] **Step 6: Commit**

```bash
git add viewer/webapp/gdrive_briefs.py viewer/webapp/app.py
git commit -m "feat(environments): wire meetings/es_activities into the per-account API"
```

---

### Task 3: Portfolio rollup endpoint

**Files:**
- Modify: `viewer/webapp/app.py` (new route; minor refactor of the in-scope-customer lookup already in `api_environments_config`)

**Interfaces:**
- Consumes: `es_health.build_portfolio_rollup` (Task 1), `gdrive_briefs.read_account_environments` (existing).
- Produces: `GET /api/environments/portfolio-health` → `{"customers": [{"name": str, "theater": str|None, "level": str, "team_count": int, "overdue_count": int, "sentiment_level": str, "open_issues_total": int, "error": str|None}, ...]}`, sorted by name. An entry with `error` set has every other numeric field as `0`/`"Green"`/`""` placeholders and the UI (Task 7) shows it distinctly.

- [ ] **Step 1: Extract the in-scope-customer lookup into a helper**

In `app.py`, factor the body of `api_environments_config` (`app.py:1347-1376`, the Asana-portfolio fetch + error branches) into `_load_in_scope_customers(request) -> Dict` returning the exact same shape that route already returns (`{'in_scope_customers': ...}` / `{'in_scope_customers': None, 'needs_pat': True}` / `{'in_scope_customers': None, 'error': ...}`). `api_environments_config` becomes `return jsonify(_load_in_scope_customers(request))`. No behavior change — existing manual verification of that route (customer list loads, PAT-missing and Asana-error branches) should be re-checked after this refactor since there's no automated test for it.

- [ ] **Step 2: Add the portfolio-health route**

```python
@app.route('/api/environments/portfolio-health')
@login_required
def api_environments_portfolio_health():
    """Rolls up every in-scope customer's health for the Portfolio view.
    Fans out to one Drive read per customer, unlike every other route in
    this module — short TTL cache below, not the "no caching" precedent
    the single-file routes follow."""
    cached = _portfolio_health_cache_get(request.brief_user['id'])
    if cached is not None:
        return jsonify(cached)

    scope = _load_in_scope_customers(request)
    if scope.get('in_scope_customers') is None:
        return jsonify({'customers': []})  # needs_pat / error — Portfolio view just shows empty, same as today's customer dropdown

    google_token = db.get_google_refresh_token(request.brief_user['id'])
    read_fn = (lambda name: gdrive_briefs.read_account_environments(google_token, name)) if google_token else (lambda name: None)
    customers = es_health.build_portfolio_rollup(scope['in_scope_customers'], read_fn)

    payload = {'customers': customers}
    _portfolio_health_cache_set(request.brief_user['id'], payload)
    return jsonify(payload)
```

- [ ] **Step 3: Implement the TTL cache helpers**

Add near the top of the environments section in `app.py`:
```python
_portfolio_health_cache: Dict[int, Tuple[float, Dict]] = {}
_portfolio_health_cache_lock = threading.Lock()
PORTFOLIO_HEALTH_CACHE_TTL_SECONDS = 180  # short — this fans out to N Drive reads per request

def _portfolio_health_cache_get(user_id):
    with _portfolio_health_cache_lock:
        entry = _portfolio_health_cache.get(user_id)
        if entry and entry[0] > time.monotonic():
            return entry[1]
        return None

def _portfolio_health_cache_set(user_id, payload):
    with _portfolio_health_cache_lock:
        _portfolio_health_cache[user_id] = (time.monotonic() + PORTFOLIO_HEALTH_CACHE_TTL_SECONDS, payload)
```
(`threading` and `time` are near-certainly already imported in `app.py`; add them if not.)

- [ ] **Step 4: Manual verification**

The partial-failure logic itself is already covered by Task 1's `test_build_portfolio_rollup_isolates_one_customers_read_failure` — `api_environments_portfolio_health` is a thin Flask wrapper around it and follows this module's existing "no automated test for routes" precedent (it needs live env vars + Postgres to import `app.py` at all). With at least two in-scope customers, one with a valid environments file and one whose account folder doesn't exist in Drive (or temporarily rename it): confirm `GET /api/environments/portfolio-health` returns both customers, the broken one with `error` set and placeholder zeros, the good one with real rollup numbers, and the endpoint doesn't 500. Confirm a second request within 3 minutes returns the cached result (check Drive API call count/logs) and a request after 3 minutes refreshes.

- [ ] **Step 5: Commit**

```bash
git add viewer/webapp/app.py
git commit -m "feat(environments): add portfolio-wide health rollup endpoint"
```

---

### Task 4: JS data layer — catalog loading & normalization

**Files:**
- Modify: `viewer/webapp/templates/environments.html`

**Interfaces:**
- Consumes: `GET /api/environments/meeting-catalog` (Task 2), the `meetings`/`es_activities`/`health`/`rollup` fields now present on `GET /api/environments/config/<account>` (Task 2).
- Produces: `STATE.meeting_catalog` (array, loaded once), `normalizeMeeting(m)`, `normalizeEsActivity(a)`, updated `normalizeTeam(team)`, updated `ensureCustomer(name)`.

- [ ] **Step 1: Load the meeting catalog in `load()`**

In `load()` (`environments.html:324-345`), add a third parallel fetch alongside the existing two:
```js
const [envResp, custResp, catalogResp] = await Promise.all([
  fetch(`${BASE}api/environments/config`, {credentials:'include'}),
  fetch(`${BASE}api/customers/config`, {credentials:'include'}).catch(() => null),
  fetch(`${BASE}api/environments/meeting-catalog`, {credentials:'include'}).catch(() => null),
]);
```
and after `STATE = await envResp.json();`, add:
```js
STATE.meeting_catalog = (catalogResp && catalogResp.ok) ? (await catalogResp.json()).meeting_catalog : [];
```

- [ ] **Step 2: Extend `normalizeTeam`**

In `normalizeTeam` (`environments.html:263-268`), add defaults for every new field from the spec's data model:
```js
function normalizeTeam(team) {
  team.id = team.id || nextFallbackId('team');
  team.notes = team.notes || '';
  team.members = team.members || [];
  team.exempt = team.exempt || false;
  team.sentiment = team.sentiment || '';
  team.sentiment_updated = team.sentiment_updated || '';
  team.open_issues = (team.open_issues === undefined) ? null : team.open_issues;
  team.open_issues_updated = team.open_issues_updated || '';
  team.inapplicable_meeting_types = team.inapplicable_meeting_types || [];
  team.onboarding_date = team.onboarding_date || '';
  team.renewal_date = team.renewal_date || '';
  return team;
}
```
`team.health`/customer-level `rollup` are server-computed and read-only on the client — normalize functions don't touch them, but must not strip them either (they're plain extra keys on objects already being spread/preserved as-is elsewhere in this file, so no action needed beyond not deleting them).

- [ ] **Step 3: Add `normalizeMeeting` and `normalizeEsActivity`**

```js
function normalizeMeeting(m) {
  m.id = m.id || nextFallbackId('mtg');
  m.team_id = m.team_id || '';
  m.meeting_type_id = m.meeting_type_id || '';
  m.status = m.status || 'not_scheduled';
  m.scheduled_date = m.scheduled_date || '';
  m.occurred_date = m.occurred_date || '';
  m.last_held_date = m.last_held_date || '';
  m.standing_schedule = m.standing_schedule || '';
  m.notes = m.notes || '';
  return m;
}

function normalizeEsActivity(a) {
  a.id = a.id || nextFallbackId('act');
  a.team_id = a.team_id || '';
  a.label = a.label || '';
  a.status = a.status || 'not_done';
  a.last_updated = a.last_updated || '';
  a.notes = a.notes || '';
  return a;
}
```

- [ ] **Step 4: Wire both into `ensureCustomer`**

In `ensureCustomer` (`environments.html:475-483`), update the default-object literal and add two more `.map()` calls:
```js
function ensureCustomer(name) {
  if (!STATE.customers[name]) {
    STATE.customers[name] = {teams: [], environments: [], use_cases: [], meetings: [], es_activities: []};
  }
  const c = STATE.customers[name];
  c.teams = (c.teams || []).map(normalizeTeam);
  c.environments = (c.environments || []).map(normalizeEnvironment);
  c.use_cases = (c.use_cases || []).map(normalizeUseCase);
  c.meetings = (c.meetings || []).map(normalizeMeeting);
  c.es_activities = (c.es_activities || []).map(normalizeEsActivity);
}
```

- [ ] **Step 5: Manual verification**

Open the Environments tab in a browser, select a customer, open the browser console, and confirm `STATE.meeting_catalog.length === 10` and `STATE.customers[CURRENT].meetings`/`.es_activities` are `[]` (or normalized arrays) with no console errors. Confirm the existing Teams/Environments/Use Cases panels still render unchanged (regression check).

- [ ] **Step 6: Commit**

```bash
git add viewer/webapp/templates/environments.html
git commit -m "feat(environments): load meeting catalog and normalize meeting/activity data"
```

---

### Task 5: JS — team health badges & customer rollup strip

**Files:**
- Modify: `viewer/webapp/templates/environments.html`

**Interfaces:**
- Consumes: Task 4's normalize functions; `team.health` and `c.rollup` from the API response (Task 2).
- Produces: `healthBadgeHtml(health)`, updated `teamCardHtml(team, idx)` (adds exempt checkbox, sentiment select, open-issues number input, health badge), `rollupStripHtml(c)`, updated `renderCustomer()`.

- [ ] **Step 1: Add `healthBadgeHtml`**

```js
const HEALTH_COLORS = {Green: '#2e7d32', Yellow: '#f9a825', Red: '#c62828', Exempt: '#888'};
function healthBadgeHtml(health) {
  if (!health) return '';
  const color = HEALTH_COLORS[health.level] || '#888';
  return `<span class="health-badge" style="color:${color};font-weight:700;">${esc(health.level)}</span>`;
}
```

- [ ] **Step 2: Add exempt/sentiment/open-issues controls and the health badge to `teamCardHtml`**

Inside the team card head (`environments.html` around line 538-539, alongside the existing caret and name input), add: the health badge (`healthBadgeHtml(team.health)`), an "Exempt" checkbox bound to `team.exempt` via a new `updateTeamField(idx, 'exempt', checked)` call (reuse the existing `updateTeamField` function at `environments.html:716-719` — it already does `c.teams[idx][field] = value; markDirty();`, so no change needed there, just wire a new `<input type="checkbox">` to it), a sentiment `<select>` with options `["", "Green", "Yellow", "Red"]` bound to `team.sentiment` via `updateTeamField`, and a number `<input>` bound to `team.open_issues` via `updateTeamField`. When `team.exempt` is true, render the rest of the card's meeting-related content (the new "View meetings & health" link added in Task 6) as absent/disabled, but keep name/notes/members editable (exempt teams are still real teams for membership purposes per the spec).

- [ ] **Step 3: Add `rollupStripHtml` and wire it into `renderCustomer`**

```js
function rollupStripHtml(c) {
  const r = c.rollup || {level: 'Green', team_count: 0, overdue_count: 0, sentiment_level: '', open_issues_total: 0};
  return `
    <div class="rollup-strip" style="display:flex;gap:16px;margin-bottom:12px;">
      <div>Health: ${healthBadgeHtml({level: r.level})}</div>
      <div>${r.team_count} team${r.team_count === 1 ? '' : 's'}</div>
      <div>${r.overdue_count} overdue</div>
      <div>Sentiment: ${esc(r.sentiment_level || '—')}</div>
      <div>Open issues: ${r.open_issues_total}</div>
    </div>`;
}
```
In `renderCustomer()` (`environments.html:485-513`), insert `${rollupStripHtml(c)}` immediately before the Teams `.panel` div in the template literal.

- [ ] **Step 4: Manual verification**

For a customer with 2+ teams, mark one team `exempt`, set another's sentiment to `Red`: confirm the rollup strip's level reflects only the non-exempt team, the exempt team's card shows an "Exempt" badge and greyed meeting content, and `team.health`/`c.rollup` update correctly after `saveAll()` + reload (since health is server-computed on GET, toggling exempt and saving, then reloading the customer, should reflect the new health).

- [ ] **Step 5: Commit**

```bash
git add viewer/webapp/templates/environments.html
git commit -m "feat(environments): show team health badges and customer rollup strip"
```

---

### Task 6: JS — Team detail view (meetings & ES activities)

**Files:**
- Modify: `viewer/webapp/templates/environments.html`

**Interfaces:**
- Consumes: `STATE.meeting_catalog`, `normalizeMeeting`/`normalizeEsActivity` (Task 4), `team.health` (Task 2/5), `caretHtml`/`isExpanded`/`toggleExpanded`/`markDirty`/`esc`/`escAttr`/`nextFallbackId` (existing).
- Produces: `renderTeamDetail(teamId)`, `getOrCreateMeetingRow(teamId, meetingTypeId)`, `updateMeetingField(teamId, meetingTypeId, field, value)`, `toggleMeetingApplicable(teamId, meetingTypeId, inapplicable)`, `addEsActivity(teamId)`, `updateEsActivityField(activityId, field, value)`, `removeEsActivity(activityId)`. A new `VIEW` global (`'customer'` | `'team'`) and `CURRENT_TEAM_ID` global tracking which team is being viewed.

- [ ] **Step 1: Add view-state globals and a "View meetings & health" entry point**

Near the other globals (`environments.html:138-139`):
```js
let VIEW = 'customer';
let CURRENT_TEAM_ID = null;
```
In `teamCardHtml` (extended in Task 5), add a button: `<button type="button" onclick="renderTeamDetail('${escAttr(team.id)}')">View meetings &amp; health</button>` (omit/disable when `team.exempt`).

- [ ] **Step 2: Implement `getOrCreateMeetingRow`**

```js
function getOrCreateMeetingRow(teamId, meetingTypeId) {
  const c = STATE.customers[CURRENT];
  let row = c.meetings.find(m => m.team_id === teamId && m.meeting_type_id === meetingTypeId);
  if (!row) {
    row = normalizeMeeting({team_id: teamId, meeting_type_id: meetingTypeId});
    c.meetings.push(row);
  }
  return row;
}
```

- [ ] **Step 3: Implement `updateMeetingField`, `toggleMeetingApplicable`, and the ES-activity CRUD functions**

```js
function updateMeetingField(teamId, meetingTypeId, field, value) {
  const row = getOrCreateMeetingRow(teamId, meetingTypeId);
  row[field] = value;
  markDirty();
  renderTeamDetail(teamId);
}

function toggleMeetingApplicable(teamId, meetingTypeId, inapplicable) {
  const team = STATE.customers[CURRENT].teams.find(t => t.id === teamId);
  const set = new Set(team.inapplicable_meeting_types);
  if (inapplicable) set.add(meetingTypeId); else set.delete(meetingTypeId);
  team.inapplicable_meeting_types = Array.from(set);
  markDirty();
  renderTeamDetail(teamId);
}

function addEsActivity(teamId) {
  const activity = normalizeEsActivity({team_id: teamId, label: 'New activity'});
  STATE.customers[CURRENT].es_activities.push(activity);
  markDirty();
  renderTeamDetail(teamId);
}

function updateEsActivityField(activityId, field, value) {
  const activity = STATE.customers[CURRENT].es_activities.find(a => a.id === activityId);
  activity[field] = value;
  markDirty();
  renderTeamDetail(CURRENT_TEAM_ID);
}

function removeEsActivity(activityId) {
  const c = STATE.customers[CURRENT];
  c.es_activities = c.es_activities.filter(a => a.id !== activityId);
  markDirty();
  renderTeamDetail(CURRENT_TEAM_ID);
}
```

- [ ] **Step 4: Implement `renderTeamDetail(teamId)`**

Sets `VIEW = 'team'`, `CURRENT_TEAM_ID = teamId`, resolves `const idx = STATE.customers[CURRENT].teams.findIndex(t => t.id === teamId)` (needed because the existing `updateTeamField(idx, field, value)` is index-based, not id-based), and replaces `#content`'s innerHTML with (in order): a back link (`onclick="VIEW='customer'; renderCustomer();"`), the team name + `onboarding_date`/`renewal_date` `<input type="date">` fields (bound via `updateTeamField(idx, 'onboarding_date', value)` / `updateTeamField(idx, 'renewal_date', value)`), the health breakdown box (`team.health.level` + a `<ul>` of `team.health.reasons`), a One-time Meetings `.env-subsection` iterating `MEETING_CATALOG.filter(m => m.category === 'one_time')` in catalog order (each row: name, a `<select>` for `status`, `scheduled_date`/`occurred_date` date inputs, calling `getOrCreateMeetingRow`/`updateMeetingField`), a Recurring Meetings `.env-subsection` iterating `category === 'recurring'` entries (each row: name, requirement badge, an "applicable" checkbox for `optional`/`conditional` entries only via `toggleMeetingApplicable`, `standing_schedule` text input, `last_held_date` date input), and an ES Activities `.env-subsection` listing `c.es_activities.filter(a => a.team_id === teamId)` with add/remove/edit wired to the Step 3 functions. Call `wireCarets()` at the end if any new collapsible sections are added (optional for this view — plain always-expanded subsections are acceptable for v1, following the "visual details are a builder call" note in the spec).

- [ ] **Step 5: Manual verification**

For a team: mark the first one-time entry `occurred` and confirm the health box now cites the second entry, not the first; set a recurring entry's `last_held_date` to 6 months ago and confirm it's cited as overdue; toggle Executive Meeting's "applicable" checkbox off and confirm it never affects the health level either way; add and remove an ES activity; confirm `saveAll()` persists all of the above and a reload of the customer still shows it correctly (including re-entering the team detail view).

- [ ] **Step 6: Commit**

```bash
git add viewer/webapp/templates/environments.html
git commit -m "feat(environments): add team detail view for meetings and ES activities"
```

---

### Task 7: JS — Portfolio landing view

**Files:**
- Modify: `viewer/webapp/templates/environments.html`

**Interfaces:**
- Consumes: `GET /api/environments/portfolio-health` (Task 3), `selectCustomer(name)` (existing, `environments.html:438`), `VIEW` global (Task 6).
- Produces: `renderPortfolio()`, updated `load()` (shows Portfolio first instead of auto-selecting a customer), a `VIEW = 'portfolio'` state, a "← Portfolio" link shown from Customer/Team views.

- [ ] **Step 1: Implement `renderPortfolio()`**

```js
async function renderPortfolio() {
  VIEW = 'portfolio';
  const content = document.getElementById('content');
  content.innerHTML = '<div class="empty">Loading&hellip;</div>';
  try {
    const r = await fetch(`${BASE}api/environments/portfolio-health`, {credentials:'include'});
    const body = await r.json();
    if (!r.ok) throw new Error(body.error || r.statusText);
    const rows = body.customers.map(c => `
      <tr style="cursor:pointer;" onclick="onCustomerChange_fromPortfolio('${escAttr(c.name)}')">
        <td>${esc(c.name)}</td>
        <td>${c.error ? `<span style="color:var(--bad-t)">${esc(c.error)}</span>` : healthBadgeHtml({level: c.level})}</td>
        <td>${c.team_count}</td>
        <td>${c.overdue_count} overdue</td>
        <td>${esc(c.sentiment_level || '—')}</td>
        <td>${c.open_issues_total}</td>
      </tr>`).join('');
    content.innerHTML = `
      <table class="portfolio-table">
        <thead><tr><th>Customer</th><th>Health</th><th>Teams</th><th>Meetings</th><th>Sentiment</th><th>Open issues</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  } catch(e) {
    content.innerHTML = `<div class="empty" style="color:var(--bad-t)">Failed to load portfolio: ${esc(e.message)}</div>`;
  }
}

function onCustomerChange_fromPortfolio(name) {
  VIEW = 'customer';
  document.getElementById('customer-select').value = name;
  selectCustomer(name);
}
```

- [ ] **Step 2: Change the initial view and add a back-to-Portfolio link**

In `renderCustomerSelect()` (`environments.html:379-425`), replace the final two lines:
```js
if (!CURRENT || !names.includes(CURRENT)) CURRENT = names[0];
selectCustomer(CURRENT);
```
with:
```js
if (!CURRENT || !names.includes(CURRENT)) CURRENT = names[0];
if (VIEW === 'portfolio') {
  renderPortfolio();
} else {
  selectCustomer(CURRENT);
}
```
so the dropdown is still populated either way, but `load()`'s initial `renderCustomerSelect()` call (with the default `VIEW = 'portfolio'`) shows the Portfolio table instead of auto-opening the first customer. In `onCustomerChange()` (`environments.html:427-436`), add `VIEW = 'customer';` as its first line, so picking a customer from the dropdown — including after a later region/My-Customers filter change re-triggers `renderCustomerSelect()` — stays on that customer instead of bouncing back to Portfolio. Add a small `<a onclick="renderPortfolio()">← Portfolio</a>` link at the top of `renderCustomer()`'s template literal (`environments.html:490`) and `renderTeamDetail`'s output (Task 6), so both lower views can navigate back up.

- [ ] **Step 3: Manual verification**

Load `/environments` fresh: confirm the Portfolio table is the first thing shown (not an auto-selected customer), with every in-scope customer as a row and correct health/team-count/overdue/sentiment/issues columns. Click a row: confirm it opens that customer's existing Teams/Environments/Use Cases view with the "← Portfolio" link visible. From there, open a team's detail view and confirm "← Portfolio" still returns to the table (not just back one level). Confirm the existing customer `<select>` dropdown still works as a direct way to jump to a customer without going through the Portfolio table first.

- [ ] **Step 4: Commit**

```bash
git add viewer/webapp/templates/environments.html
git commit -m "feat(environments): add Portfolio landing view as the new default Environments entry point"
```

---

## Post-plan follow-ups (explicitly out of scope here)

- The Glean-based `open_issues` refresh skill (deep-link button + skill, mirroring `account-environments-discovery`).
- Tuning the grace-period/threshold constants once real usage data exists.
- Possibly splitting `environments.html`'s script into multiple files if it keeps growing.
