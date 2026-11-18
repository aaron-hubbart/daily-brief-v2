# Brief Content: Tabbed Sections & Universal Checkability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the brief's stacked, scrolling section accordions into tabs with a color-coded "x of y" progress indicator per tab, and make every section checkable — including the FYI/Action/Risk buckets inside each Account Update card (independently, per bullet) and a single "drafted" checkbox for the Manager Update.

**Architecture:** All sections already fetch their content in parallel today (the existing `progressive` loading already calls `/api/brief/<date>/section/<slug>` for every section up front, regardless of which accordion is open) — tabs only change *visibility*, not fetch timing: each section's `<details class="sec">` becomes a `<div class="sec-panel" data-section="...">` that's always in the DOM, with CSS showing exactly one at a time, switched by a new tab bar. The one new piece of backend work is a lightweight table for checked state on things that have never been checkable before (a bucket bullet, an action-items list entry, the Manager Update draft) — kept deliberately decoupled from the existing `items`/`checked` machinery (see Research notes: that machinery's row-creation path is dead code today, so the new table does not depend on it).

**Tech Stack:** Flask + Jinja (`viewer/webapp/app.py`, `viewer/webapp/templates/`), Postgres (`viewer/webapp/db.py`, `viewer/webapp/db/migrations/`), vanilla JS + `fetch`, pytest + `template_test_utils.py`'s `make_env()` harness.

**Spec:** `docs/superpowers/specs/2026-11-13-navigation-redesign-design.md`

## Global Constraints

- No visual redesign beyond what tabs/checkability need (spec Non-goals).
- No change to the brief-generation skill or to `gdrive_briefs.py`'s Drive-reading logic (spec Non-goals) — all new state lives in a new Postgres table, not in the generated brief content.
- Progress is shown as `x of y`, never a percentage (spec Decision 5, as amended).
- Color-coded red → amber → green per tab (spec Decision 5).
- Manager Update is a single binary checkbox (`0 of 1` / `1 of 1`), not forced through FYI/Action/Risk buckets (spec Decision 6).
- "Expand all / Collapse all" scopes to the active tab only (spec Decision 7).

## Review Focus

- **A section with zero items still needs a tab.** `fyi`/`action-items`/etc. can legitimately be empty some days — the tab must still render (`0 of 0`, not a crash from dividing by zero), just with nothing to expand. Covered in Task 5's progress-computation step.
- **Bucket-shaped text that isn't actually three buckets.** `_format_status_buckets`' existing header-detection returns the raw text unchanged (falls back to `autolink_jira`) when the three headers aren't all present — the new structured parser (Task 2) must have the identical fallback, or an account update that's just a few lines of free text (not yet drafted in the FYI/Action/Risk shape) would crash the new checkbox renderer instead of rendering as plain text. Covered in Task 2's Step 2 test.
- **Checking a bucket bullet must not touch the draft textarea.** The textarea underneath (the actual Slack-post draft) is a separate, freely-editable field — a checkbox PATCH must never rewrite `items.content.textarea` or any Drive-backed content. Covered in Task 3's API contract (the new endpoint only ever touches the new table).
- **Two tabs' worth of checkable bullets must not collide on key.** `sb-fyi:0` in one account card and `sb-fyi:0` in a different account card are different checkable things — the uniqueness must be scoped by `(brief_day_id, section, item_key, subitem_key)`, not just `subitem_key` alone. Covered in Task 1's schema (composite unique constraint) and Task 2's test.
- **Rapid tab-switching while a toggle PATCH is in flight.** Switching away from a tab mid-toggle must not lose the optimistic UI update when the user switches back — since all sections stay in the DOM (just hidden), this is naturally fine as long as Task 4 doesn't tear down/rebuild panel contents on tab switch, only toggles `display`. Called out explicitly in Task 4 so the builder doesn't "simplify" by re-fetching on every tab click.

---

## Research notes (ground truth, so no task has to re-derive this)

- **The `items` table's row-creation path is dead code.** `db.upsert_item()` (`db.py:419`) is never called anywhere in the repository — grepped and confirmed zero call sites. `serve_brief()` (`app.py:1672`) only calls `db.upsert_brief_day()` (records the day, not items); `api_section()` (`app.py:1869`) renders items straight from `gdrive_briefs.read_section()` (a pure Google-Drive read) with no Postgres merge at all. Practical effect: `db.set_item_checked()`'s `UPDATE ... WHERE brief_day_id=... AND section=... AND item_key=...` almost never matches a row, so today's existing checkbox persistence (`checkable_item`/`action_item` macros + `/api/items/<section>/<item_key>/checked`) is **effectively localStorage-only** for everything except Asana-linked Action Items (which separately sync via Asana's own `completed` field). **This is a pre-existing bug, unrelated to this plan — flagged for the user's awareness, not fixed here.** It's the reason this plan's new checked-state table (Task 1) is deliberately self-contained (keyed by `brief_day_id`/`section`/`item_key`/`subitem_key` values, upserting its own rows on first toggle) rather than foreign-keying into `items.id` the way a "do it the way the old code almost does" instinct would suggest — an FK into a table nothing populates would make the new feature just as silently broken as the old one.
- **Two parallel "Customer Updates"/"Manager Update" implementations exist; only one is live.** `daily-brief-viewer.html`'s `injectUpdateSections()` (line 1289) and its helpers (`makeAccountCard`, `generateAccountUpdate`, `generateManagerUpdate`, `callClaudeForUpdate`, `makeCollapsible`, `_renderUpdateSections`, `loadUpdateState`/`saveUpdateState`) are **dead code** — the call site is commented out (line 894) with an explicit note: "Those two sections are now generated statically by the daily-brief skill and shipped inside the brief HTML itself." The live path is `section_fragment.html`'s `customer-updates`/`manager-update` branches, fetched via `/api/brief/<date>/section/<slug>`. This plan only touches the live path. Do not confuding the dead `injectUpdateSections` block for something this plan needs to update.
- **`_format_status_buckets`** (`app.py`'s real filter, mirrored by hand in `viewer/webapp/tests/template_test_utils.py`'s `_format_status_buckets`) is used by **two different callers**: `customer-updates`' account-card preview (`section_fragment.html:61`) and the generic `checkable_item` macro's subtitle (`section_fragment.html:36`, used by `fyi`/`account-recap`/`today`/etc. whenever an item's subtitle happens to contain bucket-shaped text). This plan's new checkbox behavior is scoped **only** to the `customer-updates` account-card preview — it must not change what the shared `format_status_buckets` filter does anywhere else, or every other section's subtitle rendering changes as a side effect. That's why Task 2 adds a **new**, separate filter rather than modifying `_format_status_buckets` in place.
- Bucket headers/CSS classes (exact strings, from `template_test_utils.py:19-24`): `STATUS_BUCKET_HEADERS = ('Updates/FYI', 'Pending Action Items', 'Blockers/Risks')`, CSS classes `sb-fyi` / `sb-action` / `sb-risk` respectively. This plan's new subitem keys reuse these class names as the bucket identifier (`sb-fyi:0`, `sb-action:1`, `sb-risk:0`, ...).
- `account-recap`/`today` "card"-type items' Action Items list (`section_fragment.html:123-131`) is a plain Python list at `item.content.action_items`, rendered as bare `<li>` — unrelated code path to the bucket parser, simpler to make checkable (flat list, one bucket).
- Manager Update's existing item (`section_fragment.html:72-80`) has exactly one item per brief day, `item_key` conventionally `'mgr-update'` (per `db/schema.sql`'s own comment). Its single checkbox uses `subitem_key='drafted'` in the new table — same mechanism as bucket bullets, just one row.
- The brief's toolbar (`#expand-all-btn`/`#collapse-all-btn`, `section_fragment.html` lines 128-129, wired in `brief_fragment.html`'s own `<script>` at lines 202-208) calls `setAllDetails(open)`, which today does `document.querySelectorAll('details').forEach(d => d.open = open)` — global, not section-scoped. After tabbing, this must scope to `document.querySelector('.sec-panel.active')` so inactive tabs' nested `<details>` (account-cards, Action-Items board-groups) aren't touched.
- Section list source of truth: `SECTIONS` in `app.py:77-85` (7 fixed slugs: `yesterday-meetings`, `account-recap`, `today`, `action-items`, `fyi`, `customer-updates`, `manager-update`) — `serve_brief()` filters this down to whichever are `available` for a given brief day (`app.py:1702-1705`), so the tab bar must be built from that same filtered, per-brief-day list, not the full static `SECTIONS` constant.
- `initBriefState()` (`daily-brief-viewer.html:771`) today computes **one combined** progress bar (`#prog-label`/`#prog-fill` in `brief_fragment.html`'s `.head`) by counting every `.item[data-id]` on the page regardless of section. This plan retires that combined bar (redundant once every tab shows its own count) and adds **per-section** counting instead.
- Existing DB migration convention: numbered `NNN_description.sql` in `viewer/webapp/db/migrations/`, each with a `-- Up` section, an `INSERT INTO schema_migrations (version) VALUES (...)  ON CONFLICT (version) DO NOTHING;`, and a commented-out `-- Down (rollback)`. Latest is `012_add_max_briefs_to_load.sql`; this plan adds `013_add_item_subchecks.sql`.

---

### Task 1: `item_subchecks` table + db.py helpers

**Files:**
- Create: `viewer/webapp/db/migrations/013_add_item_subchecks.sql`
- Modify: `viewer/webapp/db.py`
- Test: `viewer/webapp/tests/test_item_subchecks_db.py` (new)

**Interfaces:**
- Produces: `db.set_subitem_checked(brief_day_id: int, section: str, item_key: str, subitem_key: str, checked: bool) -> None` (always succeeds — upsert, no "not found" case, unlike `set_item_checked`).
- Produces: `db.get_subitem_checks(brief_day_id: int, section: str) -> dict[str, dict[str, bool]]` — `{item_key: {subitem_key: checked}}` for every row in that section of that brief day.

- [ ] **Step 1: Write the migration**

  ```sql
  -- Migration 013: Add item_subchecks for checkable bucket bullets / sub-items
  -- Up
  CREATE TABLE IF NOT EXISTS item_subchecks (
      id            SERIAL PRIMARY KEY,
      brief_day_id  INTEGER NOT NULL REFERENCES brief_days(id) ON DELETE CASCADE,
      section       TEXT NOT NULL,
      item_key      TEXT NOT NULL,
      subitem_key   TEXT NOT NULL,
      checked       BOOLEAN NOT NULL DEFAULT false,
      updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE (brief_day_id, section, item_key, subitem_key)
  );
  CREATE INDEX IF NOT EXISTS idx_item_subchecks_lookup ON item_subchecks (brief_day_id, section, item_key);

  INSERT INTO schema_migrations (version) VALUES ('013_add_item_subchecks.sql')
  ON CONFLICT (version) DO NOTHING;
  -- Down (rollback)
  -- DROP TABLE item_subchecks;
  ```

- [ ] **Step 2: Write the failing tests**

  (Use whatever lightweight Postgres test fixture the rest of `db.py` already relies on for its own tests — check for an existing `test_db.py` or similar pattern before assuming one needs to be invented; if `db.py` has no existing unit tests at all, these two become integration-style tests gated the same way the rest of the module's untested-but-reviewed functions are, and this step becomes a code-review note instead of a runnable test — confirm which is true before writing.)

  ```python
  def test_set_subitem_checked_then_get_round_trips():
      db.set_subitem_checked(brief_day_id, 'customer-updates', 'cust-update-acme', 'sb-fyi:0', True)
      result = db.get_subitem_checks(brief_day_id, 'customer-updates')
      assert result['cust-update-acme']['sb-fyi:0'] is True

  def test_set_subitem_checked_is_idempotent_upsert():
      db.set_subitem_checked(brief_day_id, 'manager-update', 'mgr-update', 'drafted', True)
      db.set_subitem_checked(brief_day_id, 'manager-update', 'mgr-update', 'drafted', False)
      result = db.get_subitem_checks(brief_day_id, 'manager-update')
      assert result['mgr-update']['drafted'] is False
  ```

- [ ] **Step 3: Implement `set_subitem_checked` and `get_subitem_checks` in `db.py`**

  `set_subitem_checked`: single `INSERT ... ON CONFLICT (brief_day_id, section, item_key, subitem_key) DO UPDATE SET checked = EXCLUDED.checked, updated_at = now()`, same `cursor(commit=True)` pattern as `set_item_checked`. `get_subitem_checks`: `SELECT item_key, subitem_key, checked FROM item_subchecks WHERE brief_day_id = %s AND section = %s`, folded into the `{item_key: {subitem_key: checked}}` shape in Python.

- [ ] **Step 4: Run the migration locally and run the tests**

  Apply `013_add_item_subchecks.sql` against the dev database per this project's existing migration-running convention (check `db/README.md`); run the tests from Step 2.
  Expected: PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add viewer/webapp/db/migrations/013_add_item_subchecks.sql viewer/webapp/db.py viewer/webapp/tests/test_item_subchecks_db.py
  git commit -m "feat(db): add item_subchecks table for bucket/sub-item checked state"
  ```

---

### Task 2: Structured bucket parser (new filter, existing one untouched)

**Files:**
- Modify: `viewer/webapp/app.py` (new `@app.template_filter`)
- Modify: `viewer/webapp/tests/template_test_utils.py` (mirror, per its existing "kept in sync by hand" convention)
- Test: `viewer/webapp/tests/test_parse_status_buckets.py` (new)

**Interfaces:**
- Produces: `parse_status_buckets(text: str) -> list[dict] | None` — returns `None` when the three headers (`STATUS_BUCKET_HEADERS`) aren't all present in order (mirrors `_format_status_buckets`'s existing fallback condition exactly), otherwise a list of `{'key': 'sb-fyi'|'sb-action'|'sb-risk', 'label': str, 'bullets': list[str]}` in header order. Registered as the Jinja filter `parse_status_buckets`.

- [ ] **Step 1: Write the failing tests**

  ```python
  def test_parse_status_buckets_returns_none_for_plain_text():
      assert parse_status_buckets("Just a few notes, nothing structured.") is None

  def test_parse_status_buckets_splits_three_buckets():
      text = "Updates/FYI\n- Renewal signed\nPending Action Items\n- Schedule QBR\nBlockers/Risks\n- Champion unresponsive"
      result = parse_status_buckets(text)
      assert [b['key'] for b in result] == ['sb-fyi', 'sb-action', 'sb-risk']
      assert result[0]['bullets'] == ['Renewal signed']
      assert result[1]['bullets'] == ['Schedule QBR']
      assert result[2]['bullets'] == ['Champion unresponsive']

  def test_parse_status_buckets_none_bucket_yields_empty_bullets():
      text = "Updates/FYI\n- None\nPending Action Items\n- None\nBlockers/Risks\n- None"
      result = parse_status_buckets(text)
      assert all(b['bullets'] == [] for b in result)
  ```

- [ ] **Step 2: Run the tests to verify they fail**

  Run: `pytest viewer/webapp/tests/test_parse_status_buckets.py -v`
  Expected: FAIL (`parse_status_buckets` not defined).

- [ ] **Step 3: Implement `parse_status_buckets` in `app.py`, mirrored in `template_test_utils.py`**

  Reuse `_format_status_buckets`'s existing header-detection logic (same `header_positions`/`STATUS_BUCKET_BULLET_RE` approach) but build and return the structured list instead of an HTML string; when the "None" sentinel bullet is the only one in a bucket (same check `_format_status_buckets` already does), return `bullets: []` for that bucket rather than a literal "None" string, so the checkbox renderer (Task 3) doesn't render a checkable "None". Register via `@app.template_filter('parse_status_buckets')` in `app.py`, and add the identical function plus `env.filters['parse_status_buckets'] = parse_status_buckets` in `template_test_utils.py`'s `make_env()`.

- [ ] **Step 4: Run the tests to verify they pass**

  Run: `pytest viewer/webapp/tests/test_parse_status_buckets.py -v`
  Expected: PASS.

- [ ] **Step 5: Confirm the existing `format_status_buckets` filter and its tests are untouched**

  Run: `pytest viewer/webapp/tests/test_customer_update_status_buckets.py viewer/webapp/tests/test_account_recap_status_buckets.py viewer/webapp/tests/test_fyi_section_checkable.py -v`
  Expected: PASS, unchanged (confirms the new filter is additive, per Review Focus).

- [ ] **Step 6: Commit**

  ```bash
  git add viewer/webapp/app.py viewer/webapp/tests/template_test_utils.py viewer/webapp/tests/test_parse_status_buckets.py
  git commit -m "feat(brief): add parse_status_buckets filter returning structured bucket data"
  ```

---

### Task 3: Checkbox endpoint + Account Updates bucket rendering

**Files:**
- Modify: `viewer/webapp/app.py` (new route; `api_section()` gains the subitem-checks fetch for `customer-updates`)
- Modify: `viewer/webapp/templates/section_fragment.html` (`customer-updates` branch)
- Test: `viewer/webapp/tests/test_account_updates_checkable_buckets.py` (new)

**Interfaces:**
- Consumes: `db.set_subitem_checked`, `db.get_subitem_checks` (Task 1); `parse_status_buckets` filter (Task 2).
- Produces: `PATCH /api/items/<section>/<item_key>/subitems/<subitem_key>/checked` — same `date` query param + `{"checked": bool}` JSON body contract as the existing `/checked` route (`app.py:1929`), calling `db.set_subitem_checked`. Always `200 {"status": "ok"}` on a valid date/body (no 404 branch — this table always upserts).

- [ ] **Step 1: Write the failing endpoint test**

  ```python
  def test_patch_subitem_checked_round_trips(client, seeded_brief_day):
      resp = client.patch(
          f'/api/items/customer-updates/cust-update-acme/subitems/sb-fyi:0/checked?date={seeded_brief_day.date}',
          json={'checked': True},
      )
      assert resp.status_code == 200
  ```
  (If no Flask test client fixture exists yet in this suite — confirmed none does per Plan 1's Research notes — this is a manual/curl verification step instead; don't invent a new app-importing test harness just for this one route. Replace with: `curl -X PATCH "http://localhost:<port>/api/items/customer-updates/cust-update-acme/subitems/sb-fyi:0/checked?date=<today>" -H "Content-Type: application/json" -d '{"checked": true}'` against the running dev server, confirm `{"status": "ok"}`.)

- [ ] **Step 2: Implement the route**

  Mirror `set_item_checked`'s (`app.py:1929`) shape: validate `date` via `DATE_RE`, require `checked` in the JSON body, resolve `brief_day_id` via `db.get_brief_day(request.brief_user['id'], date_str)` (404 if the day itself doesn't exist), call `db.set_subitem_checked(brief_day['id'], section, item_key, subitem_key, checked)`, return `{"status": "ok"}`.

- [ ] **Step 3: Write the failing template test for bucket checkboxes**

  ```python
  def test_customer_update_bucket_bullets_are_checkable():
      html = render_section_fragment(
          section_slug='customer-updates',
          section_items=[{'item_key': 'cust-update-acme', 'title': 'Acme Corp',
                           'content': {'textarea': 'Updates/FYI\n- Renewal signed\nPending Action Items\n- None\nBlockers/Risks\n- None'}}],
          checked_subitems={'cust-update-acme': {'sb-fyi:0': True}},
      )
      assert 'data-subitem-key="sb-fyi:0"' in html
      assert 'checked' in html  # the sb-fyi:0 checkbox specifically — assert via a scoped substring, not just presence anywhere
  ```

- [ ] **Step 4: Run it to verify it fails**

  Run: `pytest viewer/webapp/tests/test_account_updates_checkable_buckets.py -v`
  Expected: FAIL (`section_fragment.html` doesn't accept/use `checked_subitems` yet).

- [ ] **Step 5: Implement the bucket checkbox rendering in `section_fragment.html`'s `customer-updates` branch**

  Replace the `update-preview` div's `{{ ... |format_status_buckets }}` with a loop over `item.get('content', {}).get('textarea', '')|parse_status_buckets`: when it returns `None`, fall back to the current plain-text rendering (via the *existing*, untouched `format_status_buckets` filter — same as today for anything not yet in the three-bucket shape); when it returns bucket data, render each bucket's label + a `<label class="subcheck">` per bullet with `data-subitem-key="{{ bucket.key }}:{{ loop.index0 }}"` and a checkbox pre-checked from `checked_subitems.get(item.item_key, {}).get(bucket.key ~ ':' ~ loop.index0, false)`, using the same strike-through visual language as `.item.done` (reuse that CSS class on the `<label>`, don't invent a new one). The raw `<textarea>` draft below is untouched.

- [ ] **Step 6: Thread `checked_subitems` through `api_section()`**

  In `app.py`'s `api_section()`, when `slug == 'customer-updates'`, call `db.get_subitem_checks(brief_day['id'], 'customer-updates')` (resolve `brief_day` via `db.get_brief_day` the same way `set_item_checked` does) and pass it to `render_template(..., checked_subitems=...)`; default to `{}` for every other slug.

- [ ] **Step 7: Run the tests to verify they pass**

  Run: `pytest viewer/webapp/tests/test_account_updates_checkable_buckets.py -v`
  Expected: PASS.

- [ ] **Step 8: Wire the client-side toggle**

  In `daily-brief-viewer.html`'s brief-rendering wiring (near `initBriefState`/`wireDueBox`), add a `wireSubchecks(container, filename)` that finds every `.subcheck input[type=checkbox]` and, on `change`, PATCHes `api/items/<section>/<item_key>/subitems/<subitem_key>/checked?date=<filename>` (reading `section`/`item_key`/`subitem_key` off `data-*` attributes on the ancestor `.subcheck`/`[data-section]`/`[data-id]` elements, same lookup pattern `wireDueBox` uses) and toggles a `.done`-equivalent class on the `<label>` optimistically — no localStorage mirroring needed here (see Research notes: the new table's writes are reliable upserts, unlike the legacy localStorage-first pattern).

- [ ] **Step 9: Manual verification**

  Dev server; open an account card with FYI/Action/Risk content, check a bullet, reload the brief, confirm it's still checked; confirm editing the draft textarea below is unaffected by checking/unchecking bullets.

- [ ] **Step 10: Commit**

  ```bash
  git add viewer/webapp/app.py viewer/webapp/templates/section_fragment.html viewer/daily-brief-viewer.html viewer/webapp/tests/test_account_updates_checkable_buckets.py
  git commit -m "feat(brief): make Account Updates' FYI/Action/Risk bullets independently checkable"
  ```

---

### Task 4: Account-recap/today Action Items list + Manager Update checkbox

**Files:**
- Modify: `viewer/webapp/app.py` (`api_section()` fetches subitem checks for `account-recap`, `today`, `manager-update` too)
- Modify: `viewer/webapp/templates/section_fragment.html` (`account-recap`/`today` card branches; `manager-update` branch)
- Test: `viewer/webapp/tests/test_card_action_items_checkable.py`, `viewer/webapp/tests/test_manager_update_drafted_checkbox.py` (new)

**Interfaces:**
- Consumes: Task 1's `db.set_subitem_checked`/`get_subitem_checks`; Task 3's `PATCH .../subitems/<key>/checked` route (same route, different `section`/`item_key`/`subitem_key` values — no new route needed).

- [ ] **Step 1: Write the failing template tests**

  ```python
  def test_account_recap_card_action_items_are_checkable():
      html = render_section_fragment(
          section_slug='account-recap',
          section_items=[{'item_key': 'recap-acme', 'item_type': 'card', 'title': 'Acme',
                           'content': {'action_items': ['Schedule QBR', 'Send renewal doc']}}],
          checked_subitems={'recap-acme': {'action_items:1': True}},
      )
      assert 'data-subitem-key="action_items:0"' in html
      assert 'data-subitem-key="action_items:1"' in html

  def test_manager_update_has_single_drafted_checkbox():
      html = render_section_fragment(
          section_slug='manager-update',
          section_items=[{'item_key': 'mgr-update', 'content': {'textarea': 'Draft text...'}}],
          checked_subitems={'mgr-update': {'drafted': False}},
      )
      assert 'data-subitem-key="drafted"' in html
  ```

- [ ] **Step 2: Run them to verify they fail**

  Run: `pytest viewer/webapp/tests/test_card_action_items_checkable.py viewer/webapp/tests/test_manager_update_drafted_checkbox.py -v`
  Expected: FAIL.

- [ ] **Step 3: Implement the Action Items list checkboxes**

  In `section_fragment.html`'s `account-recap`/`today` `item_type == 'card'` branches, replace `{% for action in item.get('content', {}).get('action_items', []) %}<li>{{ action }}</li>{% endfor %}` with a loop emitting `<label class="subcheck">` + checkbox per action, `data-subitem-key="action_items:{{ loop.index0 }}"`, pre-checked from `checked_subitems.get(item.item_key, {}).get('action_items:' ~ loop.index0, false)` — same markup pattern Task 3 established for bucket bullets (reuse, don't reinvent).

- [ ] **Step 4: Implement the Manager Update checkbox**

  In `section_fragment.html`'s `manager-update` branch, add one `<label class="subcheck">` above the textarea, `data-subitem-key="drafted"`, pre-checked from `checked_subitems.get(item.item_key, {}).get('drafted', false)`.

- [ ] **Step 5: Thread `checked_subitems` through for these three slugs**

  Extend `api_section()`'s Task 3 Step 6 change to also call `db.get_subitem_checks(..., slug)` when `slug in ('account-recap', 'today', 'manager-update')`.

- [ ] **Step 6: Run the tests to verify they pass**

  Run: `pytest viewer/webapp/tests/test_card_action_items_checkable.py viewer/webapp/tests/test_manager_update_drafted_checkbox.py -v`
  Expected: PASS.

- [ ] **Step 7: Confirm `wireSubchecks` (Task 3 Step 8) needs no changes**

  It's generic over `data-subitem-key`/`data-section`/`data-id`, so these new checkboxes wire up for free — manually verify in the browser: check an Action Items bullet on an account-recap card, check the Manager Update "drafted" box, reload, confirm both persisted.

- [ ] **Step 8: Commit**

  ```bash
  git add viewer/webapp/app.py viewer/webapp/templates/section_fragment.html viewer/webapp/tests/test_card_action_items_checkable.py viewer/webapp/tests/test_manager_update_drafted_checkbox.py
  git commit -m "feat(brief): make account-recap/today action items and Manager Update checkable"
  ```

---

### Task 5: Sections become tabs, with per-tab color-coded "x of y" progress

**Files:**
- Modify: `viewer/webapp/templates/brief_fragment.html`
- Modify: `viewer/daily-brief-viewer.html` (`initBriefState`'s progress computation)

**Interfaces:**
- Produces: a `.sec-tabs` bar (one `<button class="sec-tab" data-section="{{ section.slug }}">` per section in `sections`) replacing the per-`<details>` summary headers; a `.sec-panel[data-section]` per section (same content as today's `<details>` body, just not inside a `<details>`), exactly one holding `.active` at a time.
- Produces: `updateTabProgress()` (new, in `daily-brief-viewer.html`) — for each `.sec-panel`, counts checkable elements within it (`.item[data-id]` plus the new `.subcheck input[type=checkbox]` from Tasks 3-4) to get `done`/`total`, writes `done + ' of ' + total` and a red/amber/green class onto that section's `.sec-tab`. Called from `applyState()` (replacing its old single combined-bar computation) and from `wireSubchecks`' change handler (Task 3 Step 8) so toggling a bucket bullet updates its tab live.

- [ ] **Step 1: Replace the accordion markup with tabs**

  In `brief_fragment.html`: remove the `{% for section in sections %}<details class="sec" ...><summary class="sec-summary">...</summary><div class="sec-body">` wrapper (keep everything *inside* `sec-body` as-is) and instead emit a `.sec-tabs` bar before the loop (one button per `section`, label from `section.label`, a `<span class="tab-progress" data-section="{{ section.slug }}"></span>` placeholder filled in by JS) and wrap each section's unchanged inner content in `<div class="sec-panel" data-section="{{ section.slug }}"{% if loop.first %} class="sec-panel active"{% endif %}>`. Remove the `.head`'s `#prog-label`/`#prog-fill` combined progress markup (superseded by per-tab progress).

- [ ] **Step 2: Add tab-switching CSS and JS**

  CSS: `.sec-panel { display: none; } .sec-panel.active { display: block; }`. JS (in `brief_fragment.html`'s own `<script>`, alongside `setAllDetails`): clicking a `.sec-tab` removes `.active` from all `.sec-tab`/`.sec-panel`, adds it to the clicked tab and its matching panel (match by `data-section`). Overflow (more tabs than fit the width): `.sec-tabs { display: flex; overflow-x: auto; }` — horizontal scroll, matching the sidebar's own `overflow-x`-free but similarly simple approach from the Navigation & Shell plan (no dropdown/collapse menu; this is the simplest option and the spec left the exact choice to the builder).

- [ ] **Step 3: Scope "Expand all / Collapse all" to the active panel**

  Change `setAllDetails(open)` from `document.querySelectorAll('details')` to `document.querySelector('.sec-panel.active').querySelectorAll('details')` (per Review Focus — the fix is exactly this one scoping change).

- [ ] **Step 4: Implement `updateTabProgress()` and the color thresholds**

  In `daily-brief-viewer.html`: for each `.sec-panel`, `total = panel.querySelectorAll('.item[data-id], .subcheck').length`, `done = panel.querySelectorAll('.item.done[data-id], .subcheck.done').length` (the new checkbox markup from Tasks 3-4 should toggle the same `.done` class `wireSubchecks` applies, so this one selector covers both the legacy `.item` checkboxes and the new `.subcheck` ones). Write `done + ' of ' + total` into that section's `.tab-progress` span; pick a CSS class — `tab-progress-empty` (total === 0, no bar at all, just the label), `tab-progress-low`/`-mid`/`-done` by `done/total` ratio (e.g. `<40%` red, `<100%` amber, `100%` green — exact cutoffs are this task's call, not pinned by the spec) — and set it as the span's class so CSS (not JS) owns the actual colors, matching the mockup's visual language from the design doc.

- [ ] **Step 5: Call `updateTabProgress()` from the right places**

  Call it once after `initBriefState()` finishes its initial wiring, and again inside `wireSubchecks`' (Task 3 Step 8) checkbox change handler and inside `initBriefState`'s own `toggle()` function (both places a `.done` class changes).

- [ ] **Step 6: Run the existing template tests to confirm the non-progressive fallback branch (if any still render via `brief_fragment.html` directly) isn't broken**

  Run: `pytest viewer/webapp/tests -k brief_fragment -v`
  Expected: PASS (adjust any test that asserted on now-removed `<details class="sec">`/`#prog-label` markup — check `tests/test_toolbar_time_tracking_link.py` and any other `render_brief_fragment()`-based test for such an assertion before concluding none needs updating).

- [ ] **Step 7: Manual verification**

  Dev server; load a brief with several sections. Confirm: tabs show instead of a stacked scroll; each tab's progress reflects only that section's items; checking a bucket bullet or a Manager Update box updates that tab's progress live without needing a reload; Expand all/Collapse all only affects the active tab's nested `<details>` (account-cards, Action-Items board-groups), leaving other tabs' (hidden) `<details>` state untouched; a section with zero items shows `0 of 0` without error.

- [ ] **Step 8: Commit**

  ```bash
  git add viewer/webapp/templates/brief_fragment.html viewer/daily-brief-viewer.html
  git commit -m "feat(brief): replace section accordions with tabs and per-tab x-of-y progress"
  ```

---

### Task 6: Final regression pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend test suite**

  Run: `pytest viewer/webapp/tests -v`
  Expected: only the 3 pre-existing, unrelated toolbar-link failures noted in the Navigation & Shell plan's Research notes; nothing else newly failing.

- [ ] **Step 2: Full manual walkthrough**

  Dev server; open a brief with at least one Account Update card containing FYI/Action/Risk content, an account-recap card with action items, and a Manager Update. Click through every tab, toggle a mix of top-level items, bucket bullets, action-items-list entries, and the Manager Update box; reload the page; confirm every one of the new checkboxes (bucket bullets, action-items-list, Manager Update) survived the reload (they're backed by the new, working table) and note for the user that pre-existing top-level checkboxes (FYI items etc.) may *not* survive reload — that's the pre-existing bug from Research notes, not a regression from this plan.

- [ ] **Step 3: Commit** (only if Steps 1-2 required fixes; otherwise this task produces no diff)

  ```bash
  git add -A
  git commit -m "fix(brief): regression fixes from tabs and checkability final pass"
  ```
