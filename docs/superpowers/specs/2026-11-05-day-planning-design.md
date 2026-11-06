# Day Planning — Design

## Goal

A new **Day Planning** view, inspired by three mockup screenshots Aaron
shared ("Your Day at a Glance" / "Day Wrap-Up" / a portfolio-risk dashboard
used only for density/style inspiration, not part of this feature). It
pairs a morning view (what to focus on today) with an evening view (what
moved today, what carried over), alongside the existing seven brief
sections — not folded into their accordion, but a dedicated page of its
own, reachable from a new toolbar button.

Today, the skill (`customer-success-toolkit:daily-brief-generation`, in
the `actora` repo) already writes per-date section JSON to Drive for seven
sections (yesterday-meetings, account-recap, today, action-items, fyi,
customer-updates, manager-update), and this webapp renders what it's
handed — it does no synthesis of its own. Day Planning follows that same
split: the skill does all the reasoning (what to recommend, which items
are on the critical path, how to score the day), and this webapp adds two
new JSON files per date to read, plus the page and settings UI to render
and configure it. Concretely this design covers two repos:

- **This repo (daily-brief-v2)** — the page, its route/API, the toolbar
  entry point, and a new Settings tab for managing quick-action
  categories. This is the part ready to build from this document.
- **actora (`customer-success-toolkit:daily-brief-generation` skill)** —
  generating the two new JSON files each run, including the recommendation
  engine, critical-path carryover logic, category classification, and the
  day-score calculation. §8 below is the handoff spec for that work; it
  isn't implemented in this repo.

### Non-goals / anti-goals

- Not a replacement for any of the existing seven sections — those are
  unchanged.
- Not the "My Customers" portfolio overview Aaron also wants (a separate,
  later brainstorm — different data, different page).
- Not a historical Day Score trend/chart — just today's/yesterday's
  number, same as the mockup.
- The exact numbers in the mockups (7+ hrs, 5 open priorities, 8/10, etc.)
  are illustrative, not contractual — what matters is the structure below,
  not reproducing those exact figures.
- The meeting-prep auto-trigger (auto-running meeting-manager's prep agent
  before a configurable local time) is separate, already-decided scope
  that lives entirely in actora's `config.json` + skill behavior — not
  part of this document, beyond the schedule item shape in §8.3 expecting
  a prep link once that ships.

## 1. Shared concepts

Three things that look like separate UI elements on the two mockups are
actually the same underlying concept, viewed at two different moments in
the day. Documenting them here once, since both §2 (data layer) and §8
(skill handoff) depend on this framing:

- **One recommendation engine.** The morning's "Recommendations" callout
  and the evening's "Tomorrow's Focus" callout are the same kind of
  output — a short, time-blocked list of suggestions synthesized from
  everything else available that day (schedule, quick actions, critical
  path). The only difference is lookahead window: "today" in the morning,
  "tomorrow" in the evening.
- **One critical-path list.** Renewal/support-decision items with urgency
  attached. The morning view shows it as open items ("Critical Path
  (Renewals)"); the evening view splits the same list into what resolved
  during the day (feeding **Key Wins**) and what didn't (**Still
  Blocking**).
- **Quick-action categories.** A small, fixed, user-managed set (capped at
  3, sized to fit the layout) that Aaron defines and describes himself.
  Each quick-action item gets classified into one of these categories by
  the skill, matched against the category's description — not a
  daily-regenerated grouping, and not tied to customer accounts (unlike
  every other grouping in the existing brief).

Day Score (evening-only) is a single number, weighted mostly toward
completion rate (today's planned work done vs. carried over) with a
secondary factor for whether protected focus-time blocks actually held up
against meeting interruptions. The precise weighting formula is left to
the skill's implementation (§8.4) — this document only fixes what it must
be *about*.

## 2. Data layer — two new Drive files per date

Mirrors the existing per-date file convention described in
`gdrive_briefs.py`'s module docstring (`today.json`, `meetings.json`,
etc.). Two new files, written by the skill into the same per-date Drive
folder:

- `morning-plan.json`
- `evening-wrapup.json`

Add both to the existing filename↔slug maps in `gdrive_briefs.py`:

```python
_FILE_TO_SECTION = {
    ...,
    'morning-plan.json': 'morning-plan',
    'evening-wrapup.json': 'evening-wrapup',
}
```

(`_SLUG_TO_FILE` is derived from this, per the existing code — no separate
edit needed there.) This makes `read_section(brief_date, 'morning-plan',
...)` and `read_section(brief_date, 'evening-wrapup', ...)` work for free,
same as every other section.

Unlike the seven existing slugs, these two are **not** added to `app.py`'s
`SECTIONS` constant — that list drives the home page's accordion, and Day
Planning is a separate page (§4), not an accordion row. `available_sections`
(from `manifest.json`) will include these slugs once the skill writes them,
but the home page's accordion logic doesn't consult that list for
anything beyond matching against `SECTIONS`, so no accordion changes are
needed.

Each file is a single JSON object (not an `{"items": [...]}` wrapper,
following the `manager-update.json` precedent for single-object sections).
See §8 for the full schema of each.

## 3. Category settings — `config.json`

The quick-action categories are a skill-behavior setting (the skill reads
them to classify items), so they live in `config.json` on Drive — same
home as `missing_transcript_asana_task_enabled` and the other skill
toggles — not Postgres, and not `account-config.json` (which is
account/project data, not day-planning config).

New key: `day_planning_categories`, a list of 1–3 objects:

```json
{
  "day_planning_categories": [
    {"name": "ESUP Follow-Ups", "description": "Tasks related to the ESUP account renewal and proposal work."},
    {"name": "Alan + Alana", "description": "Anything involving Alan or Alana directly."},
    {"name": "Strategic", "description": "Big Rocks planning, skip-levels, anything not tied to a specific account."}
  ]
}
```

New routes in `app.py`, following the
`api_missing_transcript_asana_task_status`/`_update` pattern exactly
(read/write via `gdrive_briefs.read_config`/`write_config`, 400 when
Drive isn't connected):

- **`GET /api/settings/day-planning-categories`** — returns
  `{"day_planning_categories": [...]}`, defaulting to `[]` when unset.
- **`PUT /api/settings/day-planning-categories`** — body
  `{"day_planning_categories": [...]}`. Validates server-side: 1–3
  entries, each with non-empty `name` and `description` (both trimmed);
  rejects with 400 and a specific message otherwise, rather than silently
  truncating or saving an incomplete category — matches the existing
  `max-briefs-to-load` route's "reject, don't clamp" precedent. Also
  rejects duplicate names (case-insensitive compare) with 400 — §8.1 keys
  `quick_actions` by category name, so two identically-named categories
  would silently collapse into one key and drop a category's items with
  no error anywhere.

## 4. Routes

- **`GET /day-plan`** — renders `templates/day_plan.html` (page shell),
  same `@login_required` guard as `/tasks` and `/environments`.
- **`GET /api/day-plan/<date_str>/morning`** — reads `morning-plan.json`
  via `gdrive_briefs.read_section(date_str, 'morning-plan', ...)` for the
  signed-in user's Drive. Missing file (not generated yet for that date)
  returns `200` with a `{"available": false}` shape the page can render as
  an empty/"not generated yet" state, not an error — the skill may not
  have run for that date yet, same as any other section. No Google token
  at all returns `400 {"error": "Google Drive not connected"}`, matching
  the Settings-route precedent (`api_missing_transcript_asana_task_status`)
  rather than `serve_brief`'s `403` — this is a JSON endpoint the page
  renders a "connect Google Drive" prompt from, not a full-page route.
- **`GET /api/day-plan/<date_str>/evening`** — same, for
  `evening-wrapup.json`.
- Date defaults to today's local date; the page can accept a `?date=`
  query param the same way the main brief page does, for viewing a past
  day's plan/wrap-up.

## 5. Page — `templates/day_plan.html`

Modeled on `tasks.html`'s page-shell pattern (same nav shell, fetch into a
container). Within the page:

- **Default view by time of day**: only applies when viewing **today**.
  Before noon (viewer's local time) shows the morning plan; noon or later
  shows the evening wrap-up. A toggle (two buttons/tabs, e.g. "Morning" /
  "Evening") lets Aaron flip to the other view regardless of the default.
  Viewing a **past** date via `?date=` always defaults to the evening
  wrap-up — a 3-day-old date defaulting to "morning" because it happens to
  be 9am right now would be visibly wrong, and a past day is presumably
  over.
- **Morning layout** (structurally, not numerically, per the mockup):
  stats row → Recommendations callout → Your Schedule list → Quick
  Actions (one column per configured category, §3) → Critical Path row.
- **Evening layout**: stats row → What Got Done Today (checked items) →
  Carried Over to Tomorrow (unchecked items) → Key Wins / Still Blocking
  side-by-side → Tomorrow's Focus callout.
- **Your Schedule** rows: once the meeting-prep auto-trigger ships
  (actora-side, out of scope here per the Non-goals section), each
  schedule item may carry a prep link field — render it as an "Open prep"
  link when present, same visual treatment as Today's existing
  join/prep links, and simply omit it when absent so this page doesn't
  block on that work landing first.
- **Refresh**: each view gets its own `sec-refresh`-style link, matching
  the existing section-refresh pattern:
  `claude://claude.ai/new?q={{ ('/daily-brief Refresh section:morning-plan date:' + brief_date)|urlencode }}`
  (and `evening-wrapup` for the other view) — independently refreshable,
  per the two-separate-files decision in §2.
- **Empty state**: when `/api/day-plan/<date>/<view>` returns
  `{"available": false}`, show a brief "not generated yet" message with
  the Refresh link, rather than a blank page.
- **Rendering `quick_actions`**: render whatever keys are present in the
  fetched `morning-plan.json` for that date, using each key as its column
  header — don't filter or relabel against the *current*
  `day_planning_categories` config. Every other section's JSON is an
  immutable historical snapshot rendered as-is (today.json for a past date
  isn't re-filtered against anything live either); a renamed or deleted
  category shouldn't make an old day's plan look broken.

## 6. Settings UI — new "Day Planning" tab

Add a fifth tab to the existing Settings modal in `daily-brief-viewer.html`
(`Setup | Account | Customers | Day Planning | Admin`), following the
`tab-customers` panel's structure:

- Lists the current categories (name + description), each editable
  in-place.
- An "Add category" control, disabled/hidden once 3 exist (matching the
  layout cap from §1 and the server-side validation from §3).
- Delete per category.
- Save calls `PUT /api/settings/day-planning-categories` with the full
  list (same whole-document-replace pattern `api_customers_config_update`
  uses for `account-config.json`); surfaces the 400 validation message
  inline if the server rejects it (e.g. empty description) rather than a
  generic error toast.

## 7. Toolbar button

Add a link next to "Weekly Time Tracking" in `brief_fragment.html`'s
`.toolbar` (§ around line 125), same `toolbtn` styling, but a plain page
link rather than a `claude://` trigger (this page shows stored/rendered
data, unlike Weekly Time Tracking which only produces a downloadable
deliverable via the skill):

```html
<a class="toolbtn" href="{{ url_for('day_plan_page', date=brief_date) }}">Day Plan</a>
```

Threads the currently-viewed `brief_date` through, consistent with every
other date-aware element already in this fragment (e.g. the section
`Refresh` links) — clicking it while viewing a past day's brief opens that
day's plan/wrap-up, not always today's.

## 8. Skill-side handoff (actora repo — not built here)

This section is the contract the `daily-brief-generation` skill needs to
fulfill; it's documentation for that work, not something this repo
implements.

### 8.1 `morning-plan.json`

A single JSON object, written alongside the other per-date section files:

```json
{
  "generated_at": "2026-11-05T07:03:00-05:00",
  "stats": {
    "free_focus_hours": 7.5,
    "open_priorities": 5,
    "critical_path_count": 4
  },
  "recommendations": [
    {"time_range": "8:00 AM–10:00 AM", "text": "Block this for ESUP proposal finalization before your Micah 1:1."}
  ],
  "schedule": [
    {"time": "10:00 AM", "title": "Micah 1:1", "meeting_prep_link": null}
  ],
  "quick_actions": {
    "ESUP Follow-Ups": [{"text": "Finalize pricing model with Alana"}],
    "Alan + Alana": [{"text": "Alan follow-up and thank you"}],
    "Strategic": [{"text": "Define Big Rocks for H2/H1"}]
  },
  "critical_path": [
    {"title": "Extended 8.7 Support Decision", "detail": "...", "amount": "$2.28M", "due": null}
  ]
}
```

`quick_actions` keys must match the category **names** currently
configured in `config.json`'s `day_planning_categories` (§3) at
generation time — the skill reads that config each run rather than
hardcoding category names, so renaming a category in Settings takes
effect on the next refresh without a skill code change. An item that
doesn't clearly match any configured category's description is dropped
rather than forced into the nearest bucket, since a wrong classification
would be more misleading than a shorter list.

### 8.2 `evening-wrapup.json`

```json
{
  "generated_at": "2026-11-05T18:00:00-05:00",
  "stats": {
    "meetings": 6,
    "completed": 3,
    "carried_over": 2,
    "day_score": 8
  },
  "completed": [
    {"title": "Finalized ESUP proposal with Alana", "detail": "Blocked path cleared; ready for Kurt/Daniel meeting"}
  ],
  "carried_over": [
    {"title": "What are my Big Rocks?", "detail": "Scheduled for tomorrow morning before Micah 1:1"}
  ],
  "key_wins": ["ESUP blocking path cleared", "Wells Fargo renewal unstuck"],
  "still_blocking": [
    {"title": "Extended 8.7 support decision", "detail": "$2.28M"}
  ],
  "tomorrows_focus": [
    {"time_range": "8–10 AM", "text": "Define Big Rocks before Micah 1:1"}
  ]
}
```

### 8.3 Critical path continuity

`still_blocking` in a given evening's `evening-wrapup.json` should be the
subset of that same morning's `morning-plan.json` → `critical_path` that
didn't get resolved; resolved ones surface via `key_wins` instead (per
§1). This is a same-day pairing — the skill doesn't need cross-day
critical-path state beyond what it already re-derives each morning from
account recap / renewal data.

### 8.4 Day Score

Primarily a completion-rate calculation (`completed` vs. `completed +
carried_over`, or similar), with a secondary deduction/factor when
protected focus-time blocks (from that morning's `recommendations`) were
displaced by unplanned meetings. Exact weighting is left to the skill
implementer to tune — this document fixes the two inputs that must feed
it (completion, focus-time protection), not the formula. Scale is a fixed
integer **0–10** (matching the mockup's "8/10"), so the page can render it
as a simple meter rather than a bare, unbounded number.

## 9. Out of scope / later

- The "My Customers" portfolio overview (separate feature, separate
  brainstorm, per Aaron — do that one after this).
- Any settings UI for the meeting-prep auto-trigger threshold (actora
  config, unrelated to this feature beyond the schedule item shape in
  §8.1).
- Historical trends for Day Score, or any charting.

## 10. Testing

Following the existing per-feature test file pattern
(`tests/test_tasks_tab.py`-style):

- `GET /day-plan` redirects to `/login` when signed out; 200 when signed
  in.
- `GET /api/day-plan/<date>/morning` and `/evening` return
  `{"available": false}` when the file doesn't exist on Drive, without
  raising.
- `GET /api/settings/day-planning-categories` defaults to `[]` when unset.
- `PUT /api/settings/day-planning-categories` rejects >3 categories, and
  rejects a category missing `name` or `description`, each with a 400 and
  a specific message (not a silent truncation).
- Toolbar: `brief_fragment.html` renders a "Day Plan" link (mirrors
  `test_toolbar_time_tracking_link.py`'s pattern, asserting the link text
  and href rather than the `claude://` scheme since this one is a plain
  page link).
