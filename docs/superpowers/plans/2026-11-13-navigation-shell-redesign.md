# Navigation & Shell Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the topbar + four standalone full-page areas (Environments, Tasks, Day Plan, Account Health) with one persistent left sidebar and a true single-page shell where switching areas never reloads the browser.

**Architecture:** `viewer/daily-brief-viewer.html` is served as a **static file** via `send_from_directory` (it is not a Jinja template — it lives outside `viewer/webapp/templates/` and contains no `{{ }}`/`{% %}` syntax). It becomes the one and only page: a sidebar + one `#area-content` container, with each area's markup stashed in an inert `<template>` element inside this same file and cloned into `#area-content` on mount. Each area's existing JS (today scattered across `tasks.html`, `day_plan.html`, `environments.html`, `account_health.html`) moves into this file's own `<script>`, wrapped so it runs on mount instead of at parse time. The four areas' own data-fetching endpoints (`/api/tasks`, `/api/day-plan/<date>/morning|evening`, `/api/environments/*`, `/api/account-health/<date>`) are untouched — only how their HTML shell is delivered changes.

**Tech Stack:** Flask + Jinja (`viewer/webapp/app.py`, `viewer/webapp/templates/`), vanilla JS + `fetch` (no framework, no build step), `history.pushState`/`popstate` for client routing, pytest + a template-only Jinja harness (`viewer/webapp/tests/template_test_utils.py`) for the parts that are Jinja templates.

**Spec:** `docs/superpowers/specs/2026-11-13-navigation-redesign-design.md`

## Global Constraints

- No frontend framework, no build step — stay in vanilla JS + server-rendered Jinja fragments (spec Anti-goals).
- No visual redesign of content *within* a page beyond what's needed for the shell (spec Non-goals).
- No new auth/permissions model; Admin tab visibility logic is unchanged (spec Non-goals).
- Old URLs (`/tasks`, `/environments`, `/day-plan`, `/account-health`) are **not** required to render their old full-page markup — only to keep working as entry points into the new shell (spec Anti-goals, as amended).
- `/` with no deep link always lands on Brief (spec Decision 8).
- Broad, non-technical user base — no behavior that only makes sense if you know the old layout (spec Constraints).

## Review Focus

- **Stale area after a failed fetch.** If an area's data fetch (`/api/tasks`, `/api/account-health/<date>`, etc.) fails or 401s mid-mount, the user should see that area's own error state, not the previous area's content left on screen or a silent blank panel. Covered in Task 1's `mount()` contract and exercised per-area in Tasks 3–6.
- **Rapid sidebar clicking.** Clicking a second sidebar item before the first area's fetch resolves must not let the stale response land in `#area-content` after the new area has already mounted. Covered in Task 1 (mount tokens) and re-used by every area task.
- **Direct load of a non-root path.** Loading `/tasks` (or any of the four) fresh, not via a sidebar click, must land on that area, not bounce to Brief — the pathname-based bootstrap (Task 1) is what makes this work; verified per-route in Task 2.
- **Settings tabs left dangling after relocation.** Once Customers/Day Planning content moves out of Settings (Tasks 4 & 6), nothing in the Settings modal's markup, `switchSettingsTab`, or the `?openSettings=` query-param opener should still reference the removed tabs. Covered in Task 7.
- **Name collisions when merging four scripts into one.** `load()` is defined four separate times today (`tasks.html`, `environments.html`, `account_health.html`, and the shell's own Customers-tab loader) and would silently shadow on merge. Each area task below gives the exact rename; Task 9's regression pass greps for any remaining bare `function load(`.

---

## Research notes (ground truth, so no task has to re-derive this)

- `viewer/daily-brief-viewer.html` (2555 lines): static file, served by `app.py:1035-1039`'s `index()` view via `send_from_directory`. Existing bootstrap at the bottom: `loadBriefList();` (line 2549). Settings modal JS: `openSettings(tab)` (1687), `closeSettings()` (1692), `switchSettingsTab(tab)` (1696) — tab list driven by `.settings-tab[data-tab]` buttons and `.tab-panel` divs in the HTML (lines ~296-301, ~404-557 for the Customers/Day Planning/Admin panels). Customers-tab JS: `load()` (1854), `render()` (1872), `editRow/saveRow/addAccount/removeRow/markDirty/showToast/saveConfig/esc/escAttr/scanForAccounts/renderScanResults/closeScanModal/addScannedAccounts` (1911-2106), plus Key Contacts: `loadKeyContacts..saveKeyContacts` (2108-2200). Day-Planning-categories JS: `loadDayPlanningCategories..saveDayPlanningCategories` (2201-2349). Admin JS: `fmtDate..copyField` (2350-2510).
- `viewer/webapp/app.py`: `/` and `/index.html` → static shell (1035). `/environments` (1425) and `/tasks` (1785) and `/day-plan` (2087) and `/account-health` (2135) each currently `render_template()` their own full page with only `user_email` (or none) as context — no data-bearing template variables, so collapsing them loses nothing. `/customers` (line ~1250) redirects to `url_for('index', openSettings='customers')`.
- `viewer/webapp/templates/tasks.html` (197 lines): bootstraps via bare `load();` (line 194) which fetches `/api/tasks` → injects `tasks_fragment.html` HTML.
- `viewer/webapp/templates/day_plan.html` (142 lines): bootstraps via `setView(currentView);` (line 139); `setView(view)` (118) fetches `/api/day-plan/<date>/morning` or `/evening`.
- `viewer/webapp/templates/environments.html` (1489 lines): bootstraps via bare `load();` (line 1486); fetches `/api/environments/config`, `/api/customers/config`, `/api/environments/meeting-catalog` and renders client-side with `renderCustomerSelect/renderPortfolio/...`.
- `viewer/webapp/templates/account_health.html` (341 lines): bootstraps via bare `load();` (line 338); fetches `/api/account-health/<date>` and renders client-side with `renderStatTiles/renderCallout/renderGroups/renderCard`.
- No existing test imports `app.py` (it needs Azure/DB env vars the test env doesn't have — see `template_test_utils.py`'s module docstring) and no JS test harness exists. Route-level and shell-JS behavior in this plan is verified by **running the dev server and checking in a browser** — stated explicitly per task rather than inventing a new test harness.
- Jinja-template-level changes (anything still rendered via `render_template` from `viewer/webapp/templates/`) are testable with the existing `make_env()` harness (`viewer/webapp/tests/template_test_utils.py`), the same way `tests/test_toolbar_account_health_link.py` does it.
- **Pre-existing, unrelated failures found during research:** `tests/test_toolbar_account_health_link.py` and `tests/test_toolbar_day_plan_link.py` (2 of its 2 tests) already fail on `main`, before this plan's changes — they expect an "Account Health"/"Day Plan" link inside `brief_fragment.html` that does not exist in the current template. This plan does not touch that toolbar's link set and does not fix these — flag to the user as a pre-existing issue, don't let it block Task 9's regression pass (run the suite with `-k 'not test_toolbar_has_account_health_link and not test_toolbar_has_day_plan_link and not test_day_plan_link_threads_the_viewed_date'` when checking for new regressions, or simply confirm no *new* failures appear beyond these 3).

---

### Task 1: Sidebar shell skeleton + client router (Brief wired, others stubbed)

**Files:**
- Modify: `viewer/daily-brief-viewer.html`

**Interfaces:**
- Produces: `AREAS` registry object `{ [areaSlug]: { mount(signal), unmount() } }` for slugs `'brief' | 'environments' | 'tasks' | 'day-plan' | 'account-health'`. `mount(signal)` is called with an `AbortController.signal`; an area's fetch calls must pass this signal and bail out silently if `signal.aborted` by the time the response arrives (this is the fix for "rapid sidebar clicking" in Review Focus).
- Produces: `navigateTo(areaSlug, { push = true } = {})` — unmounts the current area (if it defines `unmount()`), clones `#tpl-<areaSlug>`'s content into `#area-content`, sets the sidebar's active item, calls `AREAS[areaSlug].mount(signal)`, and (if `push`) calls `history.pushState({area: areaSlug}, '', areaSlug === 'brief' ? '/' : '/' + areaSlug)`.
- Consumes (later tasks fill these in): `AREAS.tasks`, `AREAS['day-plan']`, `AREAS.environments`, `AREAS['account-health']` — this task registers them as no-op stubs (`mount` renders a `<p>Coming soon</p>` placeholder) so the sidebar is fully clickable without errors before Tasks 3–6 land.

- [ ] **Step 1: Add the sidebar markup and CSS**

  Replace the four `<a class="icon-btn" href="...">` nav links in `.topbar` (environments/tasks/day-plan/account-health) with a new `<nav id="sidebar">` containing five `<button class="sidebar-item" data-area="...">` entries (Brief, Environments, Tasks, Day Plan, Account Health) and a `<button id="sidebar-settings" class="sidebar-item">⚙ Settings</button>` pinned to the bottom via `margin-top:auto` on a flex column. Wrap the existing `.topbar` + `.timeline-bar` + `.viewer-wrap` in a new `<div id="shell-body" style="display:flex;">` so the sidebar sits to the left of them. Add a `<div id="area-content"></div>` placeholder — for now it's unused by Brief (Brief keeps using `#viewer-wrap` directly); Tasks 3–6 will route their areas' content into it. Give `.sidebar-item.active` the same visual treatment `.brief-select`'s focus state uses today (`border-color:var(--accent)`) so "you are here" is obvious.

- [ ] **Step 2: Add four empty `<template>` stubs**

  Add `<template id="tpl-environments"><p>Coming soon</p></template>`, `<template id="tpl-tasks">`, `<template id="tpl-day-plan">`, `<template id="tpl-account-health">` (same placeholder) right before the closing `</body>`.

- [ ] **Step 3: Implement the router**

  Add, in the existing `<script>` block:
  ```js
  const AREAS = {
    brief: { mount() { document.getElementById('viewer-wrap').style.display = ''; } , unmount() { document.getElementById('viewer-wrap').style.display = 'none'; } },
    environments: { mount(signal) { /* Task 5 fills this in */ } },
    tasks: { mount(signal) { /* Task 3 fills this in */ } },
    'day-plan': { mount(signal) { /* Task 4 fills this in */ } },
    'account-health': { mount(signal) { /* Task 6 fills this in */ } },
  };
  let currentArea = null, currentAbort = null;
  function navigateTo(areaSlug, { push = true } = {}) { /* per Interfaces above */ }
  function areaFromPathname(pathname) {
    const map = { '/': 'brief', '/index.html': 'brief', '/environments': 'environments', '/tasks': 'tasks', '/day-plan': 'day-plan', '/account-health': 'account-health' };
    return map[pathname] || 'brief';
  }
  window.addEventListener('popstate', () => navigateTo(areaFromPathname(location.pathname), { push: false }));
  document.querySelectorAll('.sidebar-item[data-area]').forEach(btn =>
    btn.addEventListener('click', () => navigateTo(btn.dataset.area)));
  document.getElementById('sidebar-settings').addEventListener('click', () => openSettings('setup'));
  navigateTo(areaFromPathname(location.pathname), { push: false });
  ```
  Remove the old unconditional `loadBriefList();` bootstrap call and instead call it only from inside `AREAS.brief.mount()`, guarded so it only runs the first time Brief mounts (`if (!briefLoadedOnce) { briefLoadedOnce = true; loadBriefList(); }`) — otherwise flipping back to Brief after visiting another area would re-fetch the whole brief list every time.

- [ ] **Step 4: Manual verification**

  Run the dev server (see the project's `run` setup) and in a browser: confirm Brief still loads and works exactly as before; confirm clicking Environments/Tasks/Day Plan/Account Health shows the "Coming soon" placeholder and highlights the right sidebar item; confirm the browser back button after two sidebar clicks returns to the previous area; confirm loading `http://localhost:<port>/tasks` directly (typed in the address bar) lands on the Tasks placeholder, not Brief.

- [ ] **Step 5: Commit**

  ```bash
  git add viewer/daily-brief-viewer.html
  git commit -m "feat(viewer): add sidebar shell and client-side area router"
  ```

---

### Task 2: Flask route consolidation

**Files:**
- Modify: `viewer/webapp/app.py:1035-1039` (the `index()` view), `:1425-1428` (`environments()`), `:1785-1789` (`tasks_page()` — confirm exact name at that line), `:2087-2091` (`day_plan_page()`), `:2135-2139` (`account_health_page()`), `:~1250` (`/customers` redirect)

**Interfaces:**
- Produces: a single view function (keep the name `index`) decorated with `@app.route('/')`, `@app.route('/index.html')`, `@app.route('/environments')`, `@app.route('/tasks')`, `@app.route('/day-plan')`, `@app.route('/account-health')`, all `@login_required`, all returning the same `send_from_directory(VIEWER_HTML_DIR, 'daily-brief-viewer.html')`.
- Consumes: nothing new — the four areas' own `/api/*` data routes are untouched.

- [ ] **Step 1: Collapse the five routes onto one view**

  Delete the four separate view functions `environments()`, the `/tasks` page view, `day_plan_page()`, `account_health_page()` (keep their companion `/api/...` routes exactly as they are — only the page-serving view goes away). Add their four `@app.route(...)` decorators to `index()` alongside its existing two.

- [ ] **Step 2: Retarget the `/customers` redirect**

  Change `return redirect(url_for('index', openSettings='customers'))` to `return redirect(url_for('index', area='account-health'))` (Customers config now lives on the Account Health page as of Task 6 — this redirect's query param is read by `openSettingsFromQuery()` today; Task 7 updates/removes that reader once Settings no longer has a Customers tab, so for now just change the destination; the `area=` param isn't consumed by anything until Task 6's mount reads it — note it as a loose end Task 6 must close).

- [ ] **Step 3: Delete the now-orphaned templates**

  Delete `viewer/webapp/templates/environments.html`, `tasks.html`, `day_plan.html`, `account_health.html` — **wait until Tasks 3–6 have copied their markup/JS out**, so do this step last, once per-area, inside each of Tasks 3–6 rather than here. (This step intentionally left as a no-op in Task 2; see Tasks 3–6 Step "Delete the old template".)

- [ ] **Step 4: Manual verification**

  With the dev server running, visit `/`, `/environments`, `/tasks`, `/day-plan`, `/account-health` directly — each must return 200 and the shell (confirmed by Task 1's placeholder behavior). Visit `/customers` and confirm it redirects to `/account-health` (still a placeholder until Task 6).

- [ ] **Step 5: Run the existing test suite to confirm no regressions**

  Run: `pytest viewer/webapp/tests -v`
  Expected: same failures as the pre-existing baseline noted in Research notes above (the 3 toolbar-link tests) and nothing else newly broken — these route changes don't touch anything `make_env()`-rendered.

- [ ] **Step 6: Commit**

  ```bash
  git add viewer/webapp/app.py
  git commit -m "feat(viewer): serve the shell for every top-level area route"
  ```

---

### Task 3: Migrate Tasks into the shell

**Files:**
- Modify: `viewer/daily-brief-viewer.html`
- Delete: `viewer/webapp/templates/tasks.html`

**Interfaces:**
- Consumes: `AREAS.tasks` stub from Task 1 (replace its body); existing `/api/tasks` (unchanged), `tasks_fragment.html` (unchanged).
- Produces: `loadTasks()` (renamed from `tasks.html`'s `load()`) — the only renamed symbol from this file; its other helpers' names are untouched per the Research notes since they don't collide.

- [ ] **Step 1: Copy `tasks.html`'s body scaffold into `<template id="tpl-tasks">`**

  Everything inside `tasks.html`'s `<body>` except the `<script>` tag. Drop the `{{ user_email }}` Jinja expression's containing element (or replace with an empty span the JS fills from the already-available `/api/whoami` response the Account-tab code already fetches) since this file is static now.

- [ ] **Step 2: Move `tasks.html`'s `<script>` body into the shell's `<script>`**

  Rename the bare `function load()` to `function loadTasks()`. Wrap the whole thing so nothing executes at parse time — delete the bottom-of-file `load();` call. Set `AREAS.tasks.mount(signal) { loadTasks(signal); }` (thread the abort signal into `loadTasks`'s `fetch('/api/tasks', { signal })` call per Task 1's Review Focus fix).

- [ ] **Step 3: Move `tasks.html`'s page-specific CSS into the shell's `<style>`**

  Scope every selector that isn't already covered by an existing shell class under `#area-content` (e.g. `.toggle-btn` if Tasks has one — check for name collisions against the shell's existing CSS class names before copying verbatim; rename on collision).

- [ ] **Step 4: Delete the old template**

  ```bash
  git rm viewer/webapp/templates/tasks.html
  ```

- [ ] **Step 5: Manual verification**

  Dev server; click Tasks in the sidebar — same content and checkbox/due-date behavior as the old `/tasks` page. Toggle a task's checkbox and its due date; confirm both still persist (same `/api/tasks/<item_key>/checked` and `/due-date` endpoints, untouched). Click away to another area mid-fetch (throttle network in devtools) and confirm no stale Tasks content flashes into a different area's panel.

- [ ] **Step 6: Commit**

  ```bash
  git add viewer/daily-brief-viewer.html
  git commit -m "feat(viewer): migrate Tasks into the shell as a mounted area"
  ```

---

### Task 4: Migrate Day Plan into the shell (+ relocate Day Planning categories)

**Files:**
- Modify: `viewer/daily-brief-viewer.html`
- Delete: `viewer/webapp/templates/day_plan.html`

**Interfaces:**
- Consumes: `AREAS['day-plan']` stub; existing `/api/day-plan/<date>/morning` and `/evening` (unchanged); Settings' existing Day-Planning-categories JS (`loadDayPlanningCategories`..`saveDayPlanningCategories`, lines 2201-2349 per Research notes) and markup (`#tab-day-planning` panel, lines ~481-504).
- Produces: `mountDayPlan()` (renamed from `day_plan.html`'s implicit bootstrap); the Day Planning categories panel now lives inside `<template id="tpl-day-plan">` instead of inside the Settings modal.

- [ ] **Step 1: Copy `day_plan.html`'s body scaffold (Morning/Evening toggle + containers) into `<template id="tpl-day-plan">`**, dropping its `{{ user_email }}` usage same as Task 3.

- [ ] **Step 2: Move the Day Planning categories panel**

  Cut the `#tab-day-planning` `<div class="tab-panel">` markup (Settings modal, ~lines 481-504) and append it into `<template id="tpl-day-plan">` below the toggle/schedule content, under its own `<h2>Quick Action Categories</h2>` heading (dropping the "Save to Drive" framing that made sense inside a modal — keep the button, just restyle as a normal page panel, not a `cust-panel` inside a settings tab).

- [ ] **Step 3: Move the Day Planning categories JS and `day_plan.html`'s own script into the shell's `<script>`**

  No renames needed for the categories functions (`loadDayPlanningCategories` etc. don't collide with anything). `day_plan.html`'s own script defines `setView(view)` as its bootstrap — check it against the shell's existing global names for a collision (the shell doesn't define `setView` today, per the function inventory in Research notes, so no rename needed) — wrap it as `mountDayPlan(signal)` which calls `setView(currentView)` internally, and also calls `loadDayPlanningCategories()` once.

- [ ] **Step 4: Remove the now-empty Settings tab**

  Delete the `<button class="settings-tab" data-tab="day-planning">` nav button and the `dayPlanningLoaded` guard's branch in `switchSettingsTab` (Settings modal still has Setup/Account/Customers/Admin at this point — Customers goes away in Task 6, the full trim happens in Task 7).

- [ ] **Step 5: Delete the old template**

  ```bash
  git rm viewer/webapp/templates/day_plan.html
  ```

- [ ] **Step 6: Manual verification**

  Dev server; click Day Plan — Morning/Evening toggle and schedule still work via the unchanged API; the Quick Action Categories panel is now visible directly on the page (not behind Settings) and add/edit/remove/save still round-trips to `/api/settings/day-planning-categories`.

- [ ] **Step 7: Commit**

  ```bash
  git add viewer/daily-brief-viewer.html
  git commit -m "feat(viewer): migrate Day Plan into the shell, move categories config onto the page"
  ```

---

### Task 5: Migrate Environments into the shell

**Files:**
- Modify: `viewer/daily-brief-viewer.html`
- Delete: `viewer/webapp/templates/environments.html`

**Interfaces:**
- Consumes: `AREAS.environments` stub; existing `/api/environments/config`, `/api/environments/meeting-catalog`, `/api/customers/config` (unchanged).
- Produces: `loadEnvironments()` (renamed from `environments.html`'s `load()` — this one collides with Task 3's `loadTasks` source name and the shell's own pre-existing `load()`, per Review Focus; this is the rename that resolves it for this area).

- [ ] **Step 1: Copy `environments.html`'s body scaffold into `<template id="tpl-environments">`**, same `user_email` handling as prior tasks. This file is large (1489 lines) — copy its structure as-is; this task is a relocation, not a rewrite (per spec Non-goals, no visual redesign beyond shell support).

- [ ] **Step 2: Move its `<script>` into the shell's `<script>`, renaming `load()` → `loadEnvironments()`**

  Check every other top-level function name defined in this script against the full name inventory in Research notes (the shell's own functions plus Tasks 3-4's additions so far) before merging; rename any other collision found the same way (prefix with `Environments`).

- [ ] **Step 3: Move its page-specific CSS into the shell's `<style>`**, scoped under `#area-content`, resolving any class-name collision against the shell's existing CSS (same check as Task 3 Step 3).

- [ ] **Step 4: Delete the old template**

  ```bash
  git rm viewer/webapp/templates/environments.html
  ```

- [ ] **Step 5: Manual verification**

  Dev server; click Environments — customer select, region filter, portfolio rendering all still work against the unchanged APIs.

- [ ] **Step 6: Commit**

  ```bash
  git add viewer/daily-brief-viewer.html
  git commit -m "feat(viewer): migrate Environments into the shell"
  ```

---

### Task 6: Migrate Account Health into the shell (+ relocate Customers roster)

**Files:**
- Modify: `viewer/daily-brief-viewer.html`
- Delete: `viewer/webapp/templates/account_health.html`

**Interfaces:**
- Consumes: `AREAS['account-health']` stub; existing `/api/account-health/<date>`, `/api/customers/config`, `/api/key-contacts` (unchanged); Settings' existing Customers JS (`load`/`render`/`editRow`/.../`saveKeyContacts`, lines 1854-2200 per Research notes) and markup (`#tab-customers` panel, lines ~404-479).
- Produces: `loadAccountHealth()` (renamed from `account_health.html`'s `load()`); `loadCustomersConfig()` (renamed from the shell's own pre-existing Customers-tab `load()` at line 1854 — this is the fourth and last `load()` collision named in Review Focus, resolved here since this is where that code ends up living).
- Produces: the shell now reads an `area=account-health` query param (from Task 2's retargeted `/customers` redirect) to... **no special handling needed**: since Customers config is now just always part of the Account Health page (not something a query param needs to "open"), `navigateTo('account-health')` already shows it. Confirm the `area=` query param on `/account-health?area=account-health` is simply ignored (harmless) rather than wired up to anything — close the "loose end" Task 2 flagged by explicitly deciding this, not by writing new param-handling code.

- [ ] **Step 1: Copy `account_health.html`'s body scaffold into `<template id="tpl-account-health">`**, same `user_email` handling as prior tasks.

- [ ] **Step 2: Move the Customers roster + Key Contacts panels**

  Cut the `#tab-customers` `<div class="tab-panel">` markup (Settings modal, ~lines 404-479 — both the "Account List" table and the "Key Contacts" table) and append into `<template id="tpl-account-health">`, above or below the health cards (builder's call on ordering — the roster is configuration, the health cards are the page's main content, so put the roster panel in a collapsed/secondary position, e.g. below the stat tiles and health cards, not above them).

- [ ] **Step 3: Move the Customers JS into the shell's `<script>`, renaming the shell's own `load()` → `loadCustomersConfig()`**

  Update every internal call site that referenced the old bare `load()` for this feature (`switchSettingsTab`'s `tab === 'customers'` branch, before it's deleted in Task 7) to call `loadCustomersConfig()` instead, until Task 7 removes that branch entirely. Also move `account_health.html`'s own `load()` → `loadAccountHealth()`, and all its `render*` helpers (`renderCard`, `renderGroups`, `renderStatTiles`, `renderCallout`) — these don't collide with anything, no rename needed. Set `AREAS['account-health'].mount(signal) { loadAccountHealth(signal); loadCustomersConfig(); loadKeyContacts(); }`.

- [ ] **Step 4: Move `account_health.html`'s page-specific CSS into the shell's `<style>`**, scoped under `#area-content`, same collision check as prior tasks.

- [ ] **Step 5: Delete the old template**

  ```bash
  git rm viewer/webapp/templates/account_health.html
  ```

- [ ] **Step 6: Manual verification**

  Dev server; click Account Health — stat tiles, callout, and account cards render from the unchanged API; the Customers roster table and Key Contacts table are now visible directly on the page, and add/edit/remove/scan-for-accounts/save-to-Drive still round-trip correctly. Visit `/customers` directly and confirm it redirects to `/account-health` and the roster is right there, no modal involved.

- [ ] **Step 7: Commit**

  ```bash
  git add viewer/daily-brief-viewer.html
  git commit -m "feat(viewer): migrate Account Health into the shell, move customers roster onto the page"
  ```

---

### Task 7: Trim Settings to Setup / Account / Admin

**Files:**
- Modify: `viewer/daily-brief-viewer.html`

**Interfaces:**
- Consumes: nothing new.
- Produces: `switchSettingsTab(tab)` now only handles `'setup' | 'account' | 'admin'`; `openSettingsFromQuery()` no longer recognizes `openSettings=customers` or `=day-planning` (both features have their own pages now, not a settings tab to deep-link into).

- [ ] **Step 1: Remove the Customers and Day Planning tab buttons and panels**

  Delete the `<button class="settings-tab" data-tab="customers">` and `data-tab="day-planning"` buttons, and the (now-empty, their content moved in Tasks 4 & 6) `#tab-customers` / `#tab-day-planning` `<div class="tab-panel">` wrapper elements themselves if anything still references them.

- [ ] **Step 2: Clean up `switchSettingsTab` and the loaded-guards**

  Remove the `tab === 'customers'` and `tab === 'day-planning'` branches (and their `custLoaded`/`dayPlanningLoaded` guard variables, now unused) from `switchSettingsTab`.

- [ ] **Step 3: Update `openSettingsFromQuery()`**

  Remove its handling of `openSettings=customers`/`=day-planning` values (if it special-cased them) since the gear panel no longer has those tabs to open into.

- [ ] **Step 4: Manual verification**

  Dev server; open Settings via the sidebar gear — only Setup, Account, Admin tabs are present; no console errors from removed function calls.

- [ ] **Step 5: Commit**

  ```bash
  git add viewer/daily-brief-viewer.html
  git commit -m "feat(viewer): trim Settings down to Setup/Account/Admin"
  ```

---

### Task 8: Sidebar responsive collapse below 640px

**Files:**
- Modify: `viewer/daily-brief-viewer.html`

**Interfaces:**
- Consumes: the existing `@media(max-width:640px)` breakpoint already used for the old topbar reflow (spec Constraints — "carry forward for the sidebar's mobile behavior").

- [ ] **Step 1: Add a collapse rule at the existing breakpoint**

  Under `@media(max-width:640px)`, collapse `#sidebar` to an icon-only rail (hide the text label in each `.sidebar-item`, keep a glyph/first-letter, shrink width to ~48px) rather than a full off-canvas drawer — simplest change consistent with "no behavior that only makes sense if you know the old layout" (an always-visible icon rail stays discoverable; a hidden hamburger menu does not).

- [ ] **Step 2: Manual verification**

  Resize the browser (or devtools device toolbar) below 640px; confirm all five areas plus Settings remain clickable as icons, and above 640px the full labeled sidebar returns.

- [ ] **Step 3: Commit**

  ```bash
  git add viewer/daily-brief-viewer.html
  git commit -m "feat(viewer): collapse sidebar to an icon rail below 640px"
  ```

---

### Task 9: Final regression pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend test suite**

  Run: `pytest viewer/webapp/tests -v`
  Expected: only the 3 pre-existing, unrelated failures noted in Research notes (`test_toolbar_has_account_health_link`, `test_toolbar_has_day_plan_link`, `test_day_plan_link_threads_the_viewed_date`); nothing else newly failing.

- [ ] **Step 2: Grep for leftover collisions**

  Run: `grep -n "function load(" viewer/daily-brief-viewer.html`
  Expected: zero matches (all four `load()` definitions were renamed in Tasks 3, 5, 6; confirms Review Focus's collision risk was fully closed).

- [ ] **Step 3: Full manual walkthrough**

  Dev server; from a cold load of `/`: confirm it's Brief. Click through all five sidebar areas and Settings in sequence, then use browser back/forward to retrace the same path, confirming each stop shows the right area with no full-page reload (watch the browser's network tab for document requests — there should be exactly one, the initial load). Reload the browser while on `/account-health` and confirm it still lands there, not Brief.

- [ ] **Step 4: Commit** (only if Steps 1-3 required fixes; otherwise this task produces no diff)

  ```bash
  git add -A
  git commit -m "fix(viewer): regression fixes from navigation shell final pass"
  ```
