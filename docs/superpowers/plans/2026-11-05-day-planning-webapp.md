# Day Planning (webapp half) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone Day Planning page (morning plan / evening wrap-up) to the daily-brief-v2 viewer, backed by two new per-date Drive files the skill will generate, plus a Settings UI for managing the quick-action categories those files are sorted into.

**Architecture:** Follows this repo's existing per-date-section pattern exactly: two new filename↔slug entries in `gdrive_briefs.py` make the existing `read_section` helper work for the new data for free; two new Jinja fragment templates render that data server-side (mirroring `tasks_fragment.html`); a thin page (`day_plan.html`, mirroring `tasks.html`) fetches and injects those fragments client-side; and category management reuses the existing `config.json` read/write + Settings-modal-tab pattern that Key Contacts already uses.

**Tech Stack:** Flask, Jinja2, vanilla JS (no build step), pytest.

**Spec:** [docs/superpowers/specs/2026-11-05-day-planning-design.md](../specs/2026-11-05-day-planning-design.md) — this plan implements §§2–7, 9–10 only (the webapp half); §8 (the actora skill's JSON-generation contract) is out of scope here.

## Global Constraints

- Quick-action categories: 1–3 entries (`MAX_DAY_PLANNING_CATEGORIES = 3`), each with a non-empty, trimmed `name` and `description`; names unique case-insensitively.
- Categories live in `config.json` under the key `day_planning_categories`.
- Day Score is rendered as a fixed integer **0–10** scale.
- New per-date Drive files: `morning-plan.json`, `evening-wrapup.json` — each a single JSON object (not an `{"items": [...]}` wrapper), matching the spec's §8.1/§8.2 schemas.
- Day Planning's default view: **today** uses the time-of-day split (local hour `< 12` → morning, `>= 12` → evening); **any other date** always defaults to evening.
- The toolbar entry point is a plain page link (not a `claude://` trigger) placed in `brief_fragment.html`'s `.toolbar`, next to "Weekly Time Tracking," threading the currently-viewed `brief_date`.
- No Google token at all → `400 {"error": "Google Drive not connected"}` for every new route (matches the existing Settings-route precedent, not `serve_brief`'s `403`).
- Quick-action columns render whatever keys are present in the fetched JSON for that date — never filtered or relabeled against the *current* `day_planning_categories` config (historical snapshot, same as every other section).

## Review Focus

- Saving a 4th category (UI bug or a direct API call bypassing the client) — `PUT /api/settings/day-planning-categories` must reject it with 400, not silently truncate to 3 or accept it.
- Two categories whose names differ only by case/whitespace ("Strategic" vs. "strategic ") — must be rejected as a duplicate at save time, since the skill keys `quick_actions` by name and a collision would silently drop a category's items weeks later.
- Requesting `/api/day-plan/<date>/morning` (or `/evening`) for a date the skill has never generated a file for — must return a graceful `{"available": false}`, not a 500 or an exception.
- A `morning-plan.json` whose `quick_actions` keys don't match any *currently* configured category (renamed/deleted since generation) — the fragment must still render that stale key as its own column, not drop the data or error.
- Loading `/day-plan` for today right at the noon boundary — the default-view logic must resolve deterministically (local hour `>= 12` is evening; anything earlier is morning), not leave an ambiguous tie.

---

## Task 1: Register the two new section slugs

**Files:**
- Modify: `viewer/webapp/gdrive_briefs.py` (`_FILE_TO_SECTION`, ~line 58)
- Test: `viewer/webapp/tests/test_day_planning_sections.py`

**Interfaces:**
- Produces: `gdrive_briefs._FILE_TO_SECTION` gains `'morning-plan.json': 'morning-plan'` and `'evening-wrapup.json': 'evening-wrapup'`. This makes `gdrive_briefs.read_section(date, 'morning-plan', token, folder_id)` and `read_section(date, 'evening-wrapup', ...)` work immediately (the module derives `_SLUG_TO_FILE` from this dict at call time). Per `_extract_items`'s existing behavior, a missing file reads back as `[]`, and a present single-object file reads back as `[the_dict]` — same handling `manager-update.json` already gets. Task 6 relies on this.

- [ ] **Step 1: Write the failing test**

```python
from gdrive_briefs import _FILE_TO_SECTION


def test_morning_plan_and_evening_wrapup_slugs_registered():
    assert _FILE_TO_SECTION['morning-plan.json'] == 'morning-plan'
    assert _FILE_TO_SECTION['evening-wrapup.json'] == 'evening-wrapup'
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `viewer/webapp`): `pytest tests/test_day_planning_sections.py -v`
Expected: FAIL with `KeyError`

- [ ] **Step 3: Add the two entries to `_FILE_TO_SECTION` in `gdrive_briefs.py`**

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_day_planning_sections.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add viewer/webapp/gdrive_briefs.py viewer/webapp/tests/test_day_planning_sections.py
git commit -m "feat: register morning-plan/evening-wrapup Drive section slugs"
```

---

## Task 2: Category validation helper

**Files:**
- Modify: `viewer/webapp/gdrive_briefs.py` (new constant + function, near `clamp_max_briefs_to_load`)
- Test: `viewer/webapp/tests/test_day_planning_categories_validation.py`

**Interfaces:**
- Consumes: nothing (pure function).
- Produces: `gdrive_briefs.MAX_DAY_PLANNING_CATEGORIES: int = 3` and
  `gdrive_briefs.validate_day_planning_categories(categories: list) -> Tuple[Optional[List[Dict]], Optional[str]]`
  — returns `(cleaned_categories, None)` on success (each entry `{'name': str, 'description': str}`, trimmed) or `(None, error_message)` on failure. Consumed by Task 3's `PUT` route.

- [ ] **Step 1: Write the failing tests**

```python
from gdrive_briefs import validate_day_planning_categories, MAX_DAY_PLANNING_CATEGORIES


def test_accepts_one_to_three_valid_categories():
    cats = [{'name': 'Strategic', 'description': 'Big Rocks planning'}]
    cleaned, error = validate_day_planning_categories(cats)
    assert error is None
    assert cleaned == [{'name': 'Strategic', 'description': 'Big Rocks planning'}]


def test_trims_whitespace_in_name_and_description():
    cats = [{'name': '  Strategic  ', 'description': '  Big Rocks  '}]
    cleaned, error = validate_day_planning_categories(cats)
    assert error is None
    assert cleaned == [{'name': 'Strategic', 'description': 'Big Rocks'}]


def test_rejects_empty_list():
    cleaned, error = validate_day_planning_categories([])
    assert cleaned is None
    assert error is not None


def test_rejects_non_list_input():
    assert validate_day_planning_categories(None)[0] is None
    assert validate_day_planning_categories('not a list')[0] is None


def test_rejects_non_dict_entries():
    cleaned, error = validate_day_planning_categories(['just a string'])
    assert cleaned is None
    assert error is not None


def test_rejects_more_than_max_categories():
    assert MAX_DAY_PLANNING_CATEGORIES == 3
    cats = [{'name': f'Cat{i}', 'description': 'desc'} for i in range(4)]
    cleaned, error = validate_day_planning_categories(cats)
    assert cleaned is None
    assert error is not None


def test_rejects_missing_or_blank_name_or_description():
    assert validate_day_planning_categories([{'name': '', 'description': 'x'}])[0] is None
    assert validate_day_planning_categories([{'name': 'x', 'description': '   '}])[0] is None
    assert validate_day_planning_categories([{'description': 'x'}])[0] is None


def test_rejects_case_and_whitespace_insensitive_duplicate_names():
    cats = [
        {'name': 'Strategic', 'description': 'a'},
        {'name': ' strategic ', 'description': 'b'},
    ]
    cleaned, error = validate_day_planning_categories(cats)
    assert cleaned is None
    assert error is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_day_planning_categories_validation.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `validate_day_planning_categories(categories) -> Tuple[Optional[List[Dict]], Optional[str]]` and `MAX_DAY_PLANNING_CATEGORIES = 3` in `gdrive_briefs.py`**

Validate in this order: not a non-empty list → error; more than `MAX_DAY_PLANNING_CATEGORIES` entries → error; then per-entry, trim `name`/`description` and reject blank; track lowercased names seen so far and reject a repeat. Return the trimmed, cleaned list only if every entry passes.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_day_planning_categories_validation.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add viewer/webapp/gdrive_briefs.py viewer/webapp/tests/test_day_planning_categories_validation.py
git commit -m "feat: add day-planning category validation helper"
```

---

## Task 3: Category settings API routes

**Files:**
- Modify: `viewer/webapp/app.py` (new routes, near the `/api/key-contacts` routes)

**Interfaces:**
- Consumes: `gdrive_briefs.read_config`, `gdrive_briefs.write_config`, `gdrive_briefs.validate_day_planning_categories` (Task 2), `db.get_google_refresh_token`, `db.get_google_drive_folder_id` (all existing).
- Produces: `GET /api/settings/day-planning-categories` → `{"day_planning_categories": [...]}`; `PUT /api/settings/day-planning-categories` → `{"ok": true, "day_planning_categories": [...]}` or `400` with `{"error": ...}`. Consumed by Task 4's Settings-tab JS.

This task has no dedicated automated test, matching this codebase's existing convention for thin route wrappers around already-tested logic (e.g. `api_key_contacts`/`api_key_contacts_update` have none either; `app.py` can't be imported under pytest without the full Flask/Postgres/Azure env per `tests/template_test_utils.py`'s docstring). The validation behavior itself is already covered by Task 2's tests.

- [ ] **Step 1: Add `GET /api/settings/day-planning-categories`**

Mirror `api_key_contacts` (app.py:1299) exactly: `@login_required`; `400 {"error": "Google Drive not connected"}` when there's no Google token; otherwise `gdrive_briefs.read_config(...)`, `500` if `None`, else `jsonify({'day_planning_categories': config.get('day_planning_categories', [])})`.

- [ ] **Step 2: Add `PUT /api/settings/day-planning-categories`**

Mirror `api_key_contacts_update` (app.py:1315), but validate the body's `day_planning_categories` list with `gdrive_briefs.validate_day_planning_categories` instead of the key-contacts inline check; `400` with its error message on failure; on success, `gdrive_briefs.write_config({'day_planning_categories': cleaned}, ...)`, `500` on a write failure, else `jsonify({'ok': True, 'day_planning_categories': cleaned})`.

- [ ] **Step 3: Manually verify against a real Drive-connected account**

Start the app locally, open Settings (added in Task 4) once it exists, or `curl`/Postman the two routes directly with a valid session cookie: confirm `GET` returns `[]` before anything is saved, and `PUT` with an invalid payload (4 categories, or a duplicate name) returns `400` with the expected message.

- [ ] **Step 4: Commit**

```bash
git add viewer/webapp/app.py
git commit -m "feat: add day-planning category settings API routes"
```

---

## Task 4: Settings UI — "Day Planning" tab

**Files:**
- Modify: `viewer/daily-brief-viewer.html` (new settings tab button + panel + JS, modeled on the existing "Key Contacts" sub-panel at ~line 453 and its JS at ~line 2069)

**Interfaces:**
- Consumes: Task 3's `GET`/`PUT /api/settings/day-planning-categories`.
- Produces: a working Settings-modal tab; no interface other tasks depend on.

No automated test — this codebase has no test coverage for `daily-brief-viewer.html`'s inline `<script>` (it's exercised manually, same as the rest of the Settings modal).

- [ ] **Step 1: Add the tab button**

In `#settings-tabs` (line ~292-297), add a `Day Planning` button between `Customers` and `Admin`: `<button class="settings-tab" data-tab="day-planning" onclick="switchSettingsTab('day-planning')">Day Planning</button>`.

- [ ] **Step 2: Add the tab panel**

New `<div class="tab-panel" id="tab-day-planning">` (place it after `#tab-customers`), containing a table (`Name | Description | Actions` columns, `<tbody id="dpc-body">`), an add-row (`#dpc-new-name` text input, `#dpc-new-description` text input, an "Add category" button calling `addDayPlanningCategory()`), a `Save to Drive` button (`#dpc-save-btn`, `onclick="saveDayPlanningCategories()"`, `disabled` by default), and a message div `#dpc-msg` — same structure as the Key Contacts panel, with an extra column.

- [ ] **Step 3: Add the JS — load and render**

Add `DAY_PLANNING_CATEGORIES` (array) and `dpcDirty` (bool) module-level state, plus `loadDayPlanningCategories()` (fetches `api/settings/day-planning-categories`, populates `DAY_PLANNING_CATEGORIES`, calls `renderDayPlanningCategories()`) and `renderDayPlanningCategories()` (renders the table rows; shows "No categories configured" when empty; hides/disables the add-row's inputs and button once `DAY_PLANNING_CATEGORIES.length >= 3`) — mirror `loadKeyContacts`/`renderKeyContacts` (lines 2072–2099).

- [ ] **Step 4: Add the JS — add/remove/save**

`addDayPlanningCategory()` (reads the two add-row inputs, trims, no-ops if either is blank or if already at 3, case-insensitive-dedupes against existing names, else pushes and re-renders — mirror `addKeyContact`), `removeDayPlanningCategory(idx)` (mirror `removeKeyContact`, with a confirm prompt), `markDayPlanningCategoriesDirty()` (mirror `markKeyContactsDirty`), and `saveDayPlanningCategories()` (PUT the full `DAY_PLANNING_CATEGORIES` array, surface the server's `error` message in `#dpc-msg` on a non-200 response rather than a generic toast, since the 400 messages from Task 3 are specific and useful — mirror `saveKeyContacts` but show the real error text).

- [ ] **Step 5: Wire the load call into tab switching**

In `switchSettingsTab` (~line 1661), call `loadDayPlanningCategories()` the first time the `day-planning` tab is opened (mirror however `customers`/`account` already lazy-load on first switch).

- [ ] **Step 6: Manually verify**

Open Settings → Day Planning: add a category, confirm the 4th add attempt is blocked in the UI, save, reload the page, confirm it persisted. Try saving two categories with names differing only by case and confirm the server's 400 message surfaces in `#dpc-msg`.

- [ ] **Step 7: Commit**

```bash
git add viewer/daily-brief-viewer.html
git commit -m "feat: add Day Planning categories tab to Settings"
```

---

## Task 5: Morning/evening fragment templates

**Files:**
- Create: `viewer/webapp/templates/morning_plan_fragment.html`
- Create: `viewer/webapp/templates/evening_wrapup_fragment.html`
- Test: `viewer/webapp/tests/test_day_plan_fragments.py`

**Interfaces:**
- Consumes: nothing (pure template rendering).
- Produces: two templates, each accepting `available: bool` plus (when `available` is true) the fields from the spec's §8.1/§8.2 schemas — `morning_plan_fragment.html` takes `stats` (dict), `recommendations` (list of `{time_range, text}`), `schedule` (list of `{time, title, meeting_prep_link}`), `quick_actions` (dict of category-name → list of `{text}`), `critical_path` (list of `{title, detail, amount, due}`); `evening_wrapup_fragment.html` takes `stats`, `completed` (list of `{title, detail}`), `carried_over` (list of `{title, detail}`), `key_wins` (list of strings), `still_blocking` (list of `{title, detail}`), `tomorrows_focus` (list of `{time_range, text}`). Consumed by Task 6's routes via `render_template(...)`.

- [ ] **Step 1: Write the failing tests**

```python
from template_test_utils import make_env


def render_morning(available=True, **kwargs):
    env = make_env()
    template = env.get_template('morning_plan_fragment.html')
    defaults = dict(
        available=available, stats={}, recommendations=[], schedule=[],
        quick_actions={}, critical_path=[],
    )
    defaults.update(kwargs)
    return template.render(**defaults)


def render_evening(available=True, **kwargs):
    env = make_env()
    template = env.get_template('evening_wrapup_fragment.html')
    defaults = dict(
        available=available, stats={}, completed=[], carried_over=[],
        key_wins=[], still_blocking=[], tomorrows_focus=[],
    )
    defaults.update(kwargs)
    return template.render(**defaults)


def test_morning_not_available_shows_placeholder():
    html = render_morning(available=False)
    assert 'not generated yet' in html.lower()


def test_morning_renders_recommendations_and_schedule():
    html = render_morning(
        recommendations=[{'time_range': '8–10 AM', 'text': 'Block this for ESUP.'}],
        schedule=[{'time': '10:00 AM', 'title': 'Micah 1:1', 'meeting_prep_link': None}],
    )
    assert '8–10 AM' in html
    assert 'Block this for ESUP.' in html
    assert 'Micah 1:1' in html


def test_morning_renders_meeting_prep_link_when_present():
    html = render_morning(schedule=[{'time': '10:00 AM', 'title': 'Micah 1:1', 'meeting_prep_link': 'claude://x'}])
    assert 'claude://x' in html


def test_morning_renders_quick_action_column_even_for_unrecognized_category_name():
    html = render_morning(quick_actions={'Some Deleted Category': [{'text': 'Old leftover item'}]})
    assert 'Some Deleted Category' in html
    assert 'Old leftover item' in html


def test_morning_renders_critical_path_cards():
    html = render_morning(critical_path=[{'title': 'Extended 8.7 Support Decision', 'detail': 'x', 'amount': '$2.28M', 'due': None}])
    assert 'Extended 8.7 Support Decision' in html
    assert '$2.28M' in html


def test_evening_not_available_shows_placeholder():
    html = render_evening(available=False)
    assert 'not generated yet' in html.lower()


def test_evening_renders_day_score():
    html = render_evening(stats={'meetings': 6, 'completed': 3, 'carried_over': 2, 'day_score': 8})
    assert '8' in html


def test_evening_renders_completed_carried_over_wins_and_blocking():
    html = render_evening(
        completed=[{'title': 'Finalized ESUP proposal', 'detail': 'Unblocked'}],
        carried_over=[{'title': 'Define Big Rocks', 'detail': 'Tomorrow'}],
        key_wins=['ESUP blocking path cleared'],
        still_blocking=[{'title': 'Extended 8.7 support decision', 'detail': '$2.28M'}],
    )
    assert 'Finalized ESUP proposal' in html
    assert 'Define Big Rocks' in html
    assert 'ESUP blocking path cleared' in html
    assert 'Extended 8.7 support decision' in html


def test_evening_renders_tomorrows_focus():
    html = render_evening(tomorrows_focus=[{'time_range': '8–10 AM', 'text': 'Define Big Rocks'}])
    assert 'Define Big Rocks' in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_day_plan_fragments.py -v`
Expected: FAIL with `TemplateNotFound`

- [ ] **Step 3: Write `morning_plan_fragment.html`**

An `{% if not available %}` placeholder branch ("Not generated yet" + hint text), else: a stats row from `stats`, a `Recommendations`-style callout looping `recommendations` (time_range + text), a schedule list looping `schedule` (time, title, and — only `{% if item.meeting_prep_link %}` — a prep link), a quick-actions row looping `quick_actions.items()` (one column per key, regardless of whether it matches any current config), and a critical-path row looping `critical_path` (title, detail, amount, due). Reuse `brief_fragment.html`'s CSS custom properties/class conventions rather than inventing new ones.

- [ ] **Step 4: Write `evening_wrapup_fragment.html`**

Same `{% if not available %}` placeholder branch; else: a stats row including `stats.day_score`, a "What Got Done Today" list from `completed`, a "Carried Over to Tomorrow" list from `carried_over`, side-by-side `key_wins` / `still_blocking` lists, and a "Tomorrow's Focus" callout from `tomorrows_focus` (same time_range/text shape as `recommendations`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_day_plan_fragments.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add viewer/webapp/templates/morning_plan_fragment.html viewer/webapp/templates/evening_wrapup_fragment.html viewer/webapp/tests/test_day_plan_fragments.py
git commit -m "feat: add morning-plan and evening-wrapup fragment templates"
```

---

## Task 6: Day Plan page and API routes

**Files:**
- Create: `viewer/webapp/templates/day_plan.html`
- Modify: `viewer/webapp/app.py` (new routes + one small pure helper)
- Test: `viewer/webapp/tests/test_day_plan_payload.py`

**Interfaces:**
- Consumes: `gdrive_briefs.read_section` (Task 1's new slugs), `morning_plan_fragment.html` / `evening_wrapup_fragment.html` (Task 5).
- Produces: route endpoint `day_plan_page` (`GET /day-plan`, accepting `?date=`), `GET /api/day-plan/<date_str>/morning`, `GET /api/day-plan/<date_str>/evening` (each returning `{"available": false}` or `{"available": true, "html": "..."}`). Consumed by Task 7's toolbar link (`url_for('day_plan_page', date=...)`).

- [ ] **Step 1: Write the failing test for the payload-shaping helper**

`app.py` can't be imported directly under pytest (needs Flask/Azure/Postgres env — see `tests/test_validate_asana_pat.py`'s `_load_validator` for the established workaround: extract the function's AST node and `exec` it in isolation). Follow that exact pattern for the new helper:

```python
import ast
from pathlib import Path


def _load_day_plan_payload():
    src = (Path(__file__).resolve().parent.parent / 'app.py').read_text(encoding='utf-8')
    node = next(n for n in ast.parse(src).body
                if isinstance(n, ast.FunctionDef) and n.name == '_day_plan_payload')
    ns = {}
    exec(compile(ast.Module([node], []), 'app.py', 'exec'), ns)
    return ns['_day_plan_payload']


_day_plan_payload = _load_day_plan_payload()


def test_no_sections_means_not_available():
    assert _day_plan_payload([]) == (False, None)


def test_drive_error_means_not_available():
    assert _day_plan_payload(None) == (False, None)


def test_populated_sections_returns_the_single_dict():
    data = {'stats': {}, 'recommendations': []}
    assert _day_plan_payload([data]) == (True, data)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_day_plan_payload.py -v`
Expected: FAIL with `StopIteration` (function doesn't exist yet)

- [ ] **Step 3: Implement `_day_plan_payload(sections) -> Tuple[bool, Optional[dict]]` in `app.py`**

`sections` is `gdrive_briefs.read_section`'s return value for a day-plan slug: `None` on a Drive error, `[]` when the skill hasn't generated that date's file yet, or `[data]` once it has. Both `None` and `[]` mean "not available" — the route surfaces a `{"available": false}` placeholder either way rather than distinguishing a Drive hiccup from "not generated yet" to the client.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_day_plan_payload.py -v`
Expected: PASS

- [ ] **Step 5: Add `GET /day-plan` → `day_plan_page`**

`@login_required`, `render_template('day_plan.html', user_email=request.brief_user['email'])` — mirror `tasks_page` (app.py:1651) exactly.

- [ ] **Step 6: Add `GET /api/day-plan/<date_str>/morning`**

`@login_required`; `400` when no Google token (Global Constraints); else `sections = gdrive_briefs.read_section(date_str, 'morning-plan', google_token, folder_id)`; `available, data = _day_plan_payload(sections)`; if not `available`, `jsonify({'available': False})`; else `jsonify({'available': True, 'html': render_template('morning_plan_fragment.html', available=True, **data)})`.

- [ ] **Step 7: Add `GET /api/day-plan/<date_str>/evening`**

Same as Step 6, for slug `'evening-wrapup'` and `evening_wrapup_fragment.html`.

- [ ] **Step 8: Write `day_plan.html`**

Mirror `tasks.html`'s shell (back link, title, `user_email` sub-line, same inline CSS variables). Add a two-button toggle ("Morning" / "Evening") and a content container. Client JS: read `?date=` from the URL (default to today, local date); compute the default view — if the viewed date is today, `new Date().getHours() >= 12 ? 'evening' : 'morning'`, else always `'evening'` (Global Constraints); fetch `api/day-plan/<date>/<view>`, inject `data.html` into the container (showing a "not generated yet" message when `data.available` is false — the fragment templates already render that copy, so this is just for a fetch failure); clicking the toggle re-fetches the other view without reloading the page.

- [ ] **Step 9: Manually verify**

Start the app locally, visit `/day-plan`, confirm it loads (as "not generated yet" is fine, since the skill hasn't run), toggle between Morning/Evening, and visit `/day-plan?date=<a past date with no data>` to confirm the evening-only default and the placeholder both work.

- [ ] **Step 10: Commit**

```bash
git add viewer/webapp/app.py viewer/webapp/templates/day_plan.html viewer/webapp/tests/test_day_plan_payload.py
git commit -m "feat: add Day Plan page and API routes"
```

---

## Task 7: Toolbar entry point

**Files:**
- Modify: `viewer/webapp/templates/brief_fragment.html` (`.toolbar`, ~line 125)
- Test: `viewer/webapp/tests/test_toolbar_day_plan_link.py`

**Interfaces:**
- Consumes: Task 6's `day_plan_page` endpoint name (referenced via `url_for`, which this template's tests stub out — see Step 1).
- Produces: nothing further consumed by other tasks (final task).

- [ ] **Step 1: Write the failing test**

Mirror `tests/test_toolbar_time_tracking_link.py` exactly (same `render_brief_fragment()` helper and `url_for` stub):

```python
from template_test_utils import make_env


def render_brief_fragment():
    env = make_env()
    env.globals['url_for'] = lambda endpoint, **kwargs: '#'
    template = env.get_template('brief_fragment.html')
    return template.render(
        brief_date='2026-09-15', brief_date_label='Tuesday, September 15',
        brief_type='morning', checkable_count=0, sections=[], items_by_section={},
        action_subsections=[], asana_pat_configured=False, today_iso='2026-09-15',
        progressive=False,
    )


def test_toolbar_has_day_plan_link():
    html = render_brief_fragment()
    assert 'Day Plan' in html
    assert 'class="toolbtn"' in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_toolbar_day_plan_link.py -v`
Expected: FAIL (`'Day Plan' in html` is False)

- [ ] **Step 3: Add the link to `brief_fragment.html`'s `.toolbar`**

```html
<a class="toolbtn" href="{{ url_for('day_plan_page', date=brief_date) }}">Day Plan</a>
```

Placed after the existing "Weekly Time Tracking" link (Global Constraints).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_toolbar_day_plan_link.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add viewer/webapp/templates/brief_fragment.html viewer/webapp/tests/test_toolbar_day_plan_link.py
git commit -m "feat: add Day Plan link to the brief toolbar"
```
