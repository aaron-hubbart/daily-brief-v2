# Account Health Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new "Account Health" page that shows every account in Aaron's
book, grouped by health, sourced from each account's Context Doc on Drive,
with a synthesized "This week" callout and a daily triage panel.

**Architecture:** All parsing/classification/grouping logic lives in a new
pure module (`viewer/webapp/account_health.py`, no Flask/Drive imports),
following the existing split this codebase already uses for `es_health.py`
(pure logic, dependency-injected Drive reads) — this keeps every rule from
the spec unit-testable without mocking Google Drive. `gdrive_briefs.py`
gains the Drive-specific plumbing (resolving a Context Doc, exporting its
text, registering the `portfolio-summary` brief section), reusing its
existing `_find_account_folder`/`_normalize_account_name` helpers rather
than duplicating account-name matching. `app.py` gains two thin routes that
wire config + Drive reads into `account_health.build_page_model`, mirroring
how `day_plan_page`/`api_day_plan_morning` stay thin around
`_day_plan_payload`. The page itself (`account_health.html`) is fully
client-rendered from one JSON payload — like `environments.html`, not like
`day_plan.html`'s server-rendered-fragment pattern — because the triage
panel's open/jump/highlight interactions need JS state regardless, and
keeping 100% of the parsing in Python keeps it testable in this test suite
(this repo's JS has no test runner).

This plan's tasks are all source-level and test-covered via pytest. Running
the page in a real browser (`run` skill or manual dev-server check) against
at least one real account is a final manual step after all tasks are
green — this plan's tests use synthetic fixture text (see Task 1), not real
customer Context Doc content, so they cannot by themselves confirm the
regexes work against Aaron's actual Docs.

**Tech Stack:** Flask, Jinja2, vanilla JS (no build step — matches every
other page in `viewer/webapp/templates/`), `pytest`.

**Spec:** [docs/superpowers/specs/2026-11-06-portfolio-design.md](../specs/2026-11-06-portfolio-design.md)

## Global Constraints

- Page name is **Account Health** (renamed from "Portfolio" during design
  to avoid colliding with the Environments tab's own internal "Portfolio"
  view) — every user-facing string, route name, and template/test filename
  uses "Account Health"/`account_health`/`account-health`, never
  "portfolio", **except** the already-shipped Drive JSON contract
  (`portfolio-summary.json`, `section: portfolio-summary`,
  `item_key: portfolio-summary-callout`), which stays unchanged — see spec.
- Account list is `/config/account-config.json`'s `accounts` array, every
  entry regardless of `tier` (`primary` and `secondary` both show) — no
  filtering by tier for this page.
- An account's identifying name is `acct.get('account_name') or
  acct.get('name')` — this repo's config has used both keys historically
  (see `gdrive_briefs.get_account_projects`); match that same fallback here
  rather than assuming one key.
- Every Drive call that touches the Consulting > Customers Shared Drive
  must pass `supportsAllDrives=True, includeItemsFromAllDrives=True` (every
  existing call in `gdrive_briefs.py` does this — Shared Drive content is
  silently invisible without it).
- A single `drive` service object is **not thread-safe** (see
  `_read_subfolder_files`'s docstring) — reads across accounts must be
  sequential within one request, not parallelized with a shared `drive`
  object.
- Every account in `account-config.json` renders a card, even with every
  field reading a placeholder — never silently dropped (anti-goal in spec).
- Never commit real customer Context Doc content (ARR, risk, renewal data)
  into this repo's test fixtures — Task 1/2's tests use synthetic text that
  exercises the same structural patterns described in the spec (inline
  labels vs. CSV-style table rows, multi-score health, disputed-ARR
  language), not Aaron's real accounts' data.

## Review Focus

- An account whose Context Doc has no health color anywhere must land in
  **No Health Data**, not crash or silently default to another group —
  covered in Task 1's classification tests.
- A doc citing two different health scores (e.g. "C8: Green, Overall:
  Yellow") must group by the **worse** of the two and show both scores with
  a disagreement note — covered in Task 1.
- An account in `account-config.json` whose Context Doc genuinely cannot be
  found on Drive (not "found but unparseable") must still render a full
  card in **No Health Data** with every field as "No research yet" and a
  working Refresh-research link — never omitted from the page — covered in
  Task 2.
- `portfolio-summary.json` missing for today vs. present-but-empty
  `findings` must both hide the callout with no error and no empty box —
  the spec explicitly says treat these the same — covered in Task 3.
- A parsed CSM/AE/TAM name matching the signed-in user (case-insensitively,
  allowing for a full-name vs. first-name mismatch) must render as "You" —
  covered in Task 1.

---

### Task 1: Field parsers and health classification

**Files:**
- Create: `viewer/webapp/account_health.py`
- Test: `viewer/webapp/tests/test_account_health_parsing.py`

**Interfaces:**
- Produces (used by Task 2): `HEALTH_GROUPS = ('needs_attention', 'watch', 'healthy', 'no_health_data')` (in display order), `HEALTH_GROUP_LABELS = {...}` (display names: "Needs Attention", "Watch", "Healthy", "No Health Data"); `classify_health(text: str) -> Tuple[str, List[str]]` (group key, raw signal words found, worst-of-two already applied); `parse_arr(text: str) -> Dict` with keys `raw: Optional[str]`, `value: Optional[float]`, `disputed: bool`, `note: Optional[str]`; `parse_renewal(text: str) -> Optional[str]`; `parse_owners(text: str, current_user_name: Optional[str]) -> Dict[str, Optional[str]]` with keys `csm`, `ae`, `tam` (each a name string or `None`, substituted to `"You"` when it matches `current_user_name` case-insensitively); `parse_commercial_tier(text: str) -> Optional[str]`.

- [ ] **Step 1: Write failing tests for `classify_health`**

```python
def test_classify_health_red_is_needs_attention():
    assert classify_health("Health: Red") == ('needs_attention', ['Red'])

def test_classify_health_amber_is_watch():
    assert classify_health("Gainsight health score: Amber") == ('watch', ['Amber'])

def test_classify_health_green_is_healthy():
    assert classify_health("Overall health: Lime Green") == ('healthy', ['Lime Green'])

def test_classify_health_no_signal_is_no_health_data():
    assert classify_health("No health mentions in this document at all.") == ('no_health_data', [])

def test_classify_health_worse_of_two_scores():
    # Two scores disagree -> group by the worse (Yellow beats Green), both signals kept
    group, signals = classify_health("C8: Green, Overall health: Yellow")
    assert group == 'watch'
    assert set(signals) == {'Green', 'Yellow'}
```

- [ ] **Step 2: Run tests, verify they fail** (`classify_health` not defined)

Run: `pytest viewer/webapp/tests/test_account_health_parsing.py -v -k classify_health`
Expected: FAIL — `ImportError`/`NameError: classify_health`

- [ ] **Step 3: Implement `classify_health(text: str) -> Tuple[str, List[str]]`**

Match case-insensitively on color words appearing near "health" or
"Gainsight" (within the same sentence/line is sufficient — don't match a
color word that appears far away in an unrelated sentence). Map found
colors to a group rank (Red=3, Amber/Orange/Yellow=2, Green/"Lime
Green"=1); when more than one color is found, the group is the worst
(highest rank); no color found anywhere → `'no_health_data'`, `[]`.

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest viewer/webapp/tests/test_account_health_parsing.py -v -k classify_health`
Expected: PASS (5/5)

- [ ] **Step 5: Write failing tests for `parse_arr`**

```python
def test_parse_arr_plain_figure():
    r = parse_arr("Current ARR: $256,000.")
    assert r == {'raw': '$256,000', 'value': 256000.0, 'disputed': False, 'note': None}

def test_parse_arr_disputed_figure_flagged():
    r = parse_arr("ARR: $1.2M per Salesforce, $980K per Gainsight — figures conflict and do not reconcile.")
    assert r['disputed'] is True
    assert r['note'] and 'conflict' in r['note'].lower()

def test_parse_arr_not_found():
    assert parse_arr("No commercial figures in this section.") == {'raw': None, 'value': None, 'disputed': False, 'note': None}
```

- [ ] **Step 6: Run tests, verify they fail**

Run: `pytest viewer/webapp/tests/test_account_health_parsing.py -v -k parse_arr`
Expected: FAIL — `NameError: parse_arr`

- [ ] **Step 7: Implement `parse_arr(text: str) -> Dict`**

Find a dollar figure (`$` + digits, optionally with `,`/`.`/`K`/`M` suffix)
near "ARR"/"commercial"/"annual recurring". Parse `value` as a float in raw
dollars (`$1.2M` → `1200000.0`, `$980K` → `980000.0`). Flag `disputed=True`
and capture the sentence as `note` when any of `conflict`, `disagree`,
`unreconciled`, `disputed`, `does not reconcile` appears near the figure.
When disputed with multiple figures, `raw`/`value` hold the first figure
found (display and subtotal math both use "a" figure, not every figure —
the disputed flag and note are what signal the uncertainty).

- [ ] **Step 8: Run tests, verify they pass**

Run: `pytest viewer/webapp/tests/test_account_health_parsing.py -v -k parse_arr`
Expected: PASS (3/3)

- [ ] **Step 9: Write failing tests for `parse_renewal`**

```python
def test_parse_renewal_found():
    assert parse_renewal("Renewal date: 2027-03-15") == '2027-03-15'

def test_parse_renewal_not_found():
    assert parse_renewal("No renewal info here.") is None
```

- [ ] **Step 10: Run tests, verify they fail**

Run: `pytest viewer/webapp/tests/test_account_health_parsing.py -v -k parse_renewal`
Expected: FAIL

- [ ] **Step 11: Implement `parse_renewal(text: str) -> Optional[str]`**

Match a `YYYY-MM-DD` (or common `Month D, YYYY`) date near "renewal";
normalize to `YYYY-MM-DD` either way. Return `None` if nothing matches.

- [ ] **Step 12: Run tests, verify they pass**

Run: `pytest viewer/webapp/tests/test_account_health_parsing.py -v -k parse_renewal`
Expected: PASS (2/2)

- [ ] **Step 13: Write failing tests for `parse_owners`**

```python
def test_parse_owners_inline_labels():
    text = "CSM: Jane Doe\nAE: John Smith\nTAM: Aaron Hubbart"
    assert parse_owners(text, current_user_name='Aaron Hubbart') == {'csm': 'Jane Doe', 'ae': 'John Smith', 'tam': 'You'}

def test_parse_owners_table_rows():
    text = "Field, Detail\nCSM, Jane Doe\nAE, John Smith\nTAM, Aaron Hubbart"
    assert parse_owners(text, current_user_name='Aaron Hubbart') == {'csm': 'Jane Doe', 'ae': 'John Smith', 'tam': 'You'}

def test_parse_owners_missing_role_is_none():
    assert parse_owners("CSM: Jane Doe", current_user_name=None) == {'csm': 'Jane Doe', 'ae': None, 'tam': None}

def test_parse_owners_you_match_is_case_insensitive():
    assert parse_owners("TAM: aaron hubbart", current_user_name='Aaron Hubbart')['tam'] == 'You'
```

- [ ] **Step 14: Run tests, verify they fail**

Run: `pytest viewer/webapp/tests/test_account_health_parsing.py -v -k parse_owners`
Expected: FAIL

- [ ] **Step 15: Implement `parse_owners(text: str, current_user_name: Optional[str]) -> Dict[str, Optional[str]]`**

Match both an inline `"CSM: Name"`-style label line and a two-column
`Field, Detail` table row whose first column is `CSM`/`AE`/`TAM`
(case-insensitive). For each of the three roles, substitute `"You"` when
the parsed name equals `current_user_name` case-insensitively (exact match
on the full name is enough — no fuzzy/partial-name matching required).

- [ ] **Step 16: Run tests, verify they pass**

Run: `pytest viewer/webapp/tests/test_account_health_parsing.py -v -k parse_owners`
Expected: PASS (4/4)

- [ ] **Step 17: Write failing tests for `parse_commercial_tier`**

```python
def test_parse_commercial_tier_found():
    assert parse_commercial_tier("Edition: Enterprise") == 'Enterprise'

def test_parse_commercial_tier_not_found():
    assert parse_commercial_tier("No edition mentioned.") is None
```

- [ ] **Step 18: Run tests, verify they fail**

Run: `pytest viewer/webapp/tests/test_account_health_parsing.py -v -k parse_commercial_tier`
Expected: FAIL

- [ ] **Step 19: Implement `parse_commercial_tier(text: str) -> Optional[str]`**

Match a short label (e.g. "Enterprise", "Self-Managed") near
"Edition"/"Tier"/"Plan" wording. Return `None` if nothing matches — this
is informational-pill-only per the spec, so a miss is not an error.

- [ ] **Step 20: Run tests, verify they pass**

Run: `pytest viewer/webapp/tests/test_account_health_parsing.py -v -k parse_commercial_tier`
Expected: PASS (2/2)

- [ ] **Step 21: Commit**

```bash
git add viewer/webapp/account_health.py viewer/webapp/tests/test_account_health_parsing.py
git commit -m "feat: add Account Health field parsers and health classification"
```

---

### Task 2: Risks/next-step/staleness parsing, card assembly, and page model

**Files:**
- Modify: `viewer/webapp/account_health.py`
- Test: `viewer/webapp/tests/test_account_health_parsing.py` (continue), new `viewer/webapp/tests/test_account_health_page_model.py`

**Interfaces:**
- Consumes: everything Task 1 produces.
- Produces (used by Task 4 — the Flask route): `parse_risks(text: str) -> List[Dict]` (each `{'text': str, 'source_tag': Optional[str]}`); `parse_next_step(text: str) -> str` (never empty — falls back to a generic line); `compute_swept_days_ago(text: str, modified_time: Optional[str]) -> Optional[int]`; `format_days_ago(days: Optional[int]) -> str` (`"swept 3d ago"` / `"swept today"` / `"swept date unknown"`); `format_arr_abbreviated(value: Optional[float]) -> str` (`"$256K"`, `"$3.47M"`, `"—"` for `None`); `build_account_entry(account_name: str, tier: str, doc_result: Union[Dict, str, None], current_user_name: Optional[str], today: date) -> Dict` (the full uniform card dict — see below); `build_page_model(accounts_config: List[Dict], doc_fetcher: Callable[[str], Union[Dict, str, None]], current_user_name: Optional[str], today: date) -> Dict` with keys `groups` (ordered `List[Dict]`, each `{'key', 'label', 'count', 'arr_subtotal_raw', 'accounts': [...]}`) and `stat_tiles` (`{'accounts_count', 'combined_arr_raw', 'combined_arr_disputed_count', 'needs_attention_count', 'stale_count'}`).

`doc_result` (what Task 3's `gdrive_briefs.read_account_context_doc`
returns, consumed here) is one of: a dict `{'text': str, 'doc_url': str,
'modified_time': str}` on success; the string `'not_found'` when no
Context Doc exists for this account; `None` only on an actual Drive/auth
failure (treated the same as `'not_found'` here — Task 4's route is where
a real Drive outage gets surfaced differently, this function just needs
every account to render *something*).

`build_account_entry`'s returned dict always has these keys, regardless of
whether a doc was found: `account_name`, `tier`, `health_group`,
`health_signals` (`List[str]`), `commercial_tier` (`Optional[str]`),
`swept_label` (`str`, from `format_days_ago`), `arr` (`parse_arr`'s dict, or
all-`None`/`False` defaults), `renewal` (`Optional[str]`), `csm`/`ae`/`tam`
(`Optional[str]`), `risks` (`List[Dict]`, possibly empty), `next_step`
(`str`), `doc_url` (`Optional[str]`), `refresh_query` (`str`, the plain-text
`"refresh the context for {account_name}"` the route URL-encodes), `no_doc`
(`bool` — true only in the genuinely-not-found case, drives the "No
research yet" placeholder text per-field).

- [ ] **Step 1: Write failing tests for `parse_risks`**

```python
def test_parse_risks_bullet_list_with_source_tag():
    text = "Top open risks:\n- Renewal timeline slipping [Gainsight via Glean, 2026-10-01]\n- No exec sponsor identified"
    risks = parse_risks(text)
    assert risks[0] == {'text': 'Renewal timeline slipping', 'source_tag': 'Gainsight via Glean, 2026-10-01'}
    assert risks[1] == {'text': 'No exec sponsor identified', 'source_tag': None}

def test_parse_risks_alternate_heading():
    text = "Open Risks & Issues:\n- Budget frozen until Q2"
    assert parse_risks(text) == [{'text': 'Budget frozen until Q2', 'source_tag': None}]

def test_parse_risks_no_section_is_empty_list():
    assert parse_risks("Nothing relevant here.") == []
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest viewer/webapp/tests/test_account_health_parsing.py -v -k parse_risks`
Expected: FAIL

- [ ] **Step 3: Implement `parse_risks(text: str) -> List[Dict]`**

Find a heading matching "Top open risks", "Open Risks & Issues", or a
"Blockers/Risks"-style heading (case-insensitive); read the bullet list
(`-`/`*` prefixed lines) immediately under it until a blank line or the
next heading. Strip a trailing `[...]` tag off each bullet into
`source_tag`; `None` when no bracketed tag is present.

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest viewer/webapp/tests/test_account_health_parsing.py -v -k parse_risks`
Expected: PASS (3/3)

- [ ] **Step 5: Write failing tests for `parse_next_step`**

```python
def test_parse_next_step_found():
    text = "Recommendation: Schedule an exec QBR before renewal."
    assert parse_next_step(text) == 'Schedule an exec QBR before renewal.'

def test_parse_next_step_fallback():
    assert parse_next_step("No recommendation language in this doc.") == "Review this account's Context Doc for next steps"
```

- [ ] **Step 6: Run tests, verify they fail**

Run: `pytest viewer/webapp/tests/test_account_health_parsing.py -v -k parse_next_step`
Expected: FAIL

- [ ] **Step 7: Implement `parse_next_step(text: str) -> str`**

Find the first sentence following "recommendation"/"next step"/"decide"
wording; return it trimmed. No match → the fixed fallback string from the
spec, verbatim.

- [ ] **Step 8: Run tests, verify they pass**

Run: `pytest viewer/webapp/tests/test_account_health_parsing.py -v -k parse_next_step`
Expected: PASS (2/2)

- [ ] **Step 9: Write failing tests for staleness and formatting helpers**

```python
def test_compute_swept_days_ago_from_doc_line():
    assert compute_swept_days_ago("Last swept: 2026-11-01", modified_time=None) == 8  # relative to a fixed `today` passed by the caller in build_account_entry; this helper takes `today` too

def test_compute_swept_days_ago_falls_back_to_modified_time():
    assert compute_swept_days_ago("No sweep line here.", modified_time="2026-11-05T00:00:00.000Z") == 4

def test_compute_swept_days_ago_unknown():
    assert compute_swept_days_ago("Nothing here.", modified_time=None) is None

def test_format_days_ago_variants():
    assert format_days_ago(0) == 'swept today'
    assert format_days_ago(3) == 'swept 3d ago'
    assert format_days_ago(None) == 'swept date unknown'

def test_format_arr_abbreviated_variants():
    assert format_arr_abbreviated(256000.0) == '$256K'
    assert format_arr_abbreviated(3470000.0) == '$3.47M'
    assert format_arr_abbreviated(None) == '—'
```

(`compute_swept_days_ago` takes an explicit `today: date` parameter so
these tests don't depend on wall-clock time — adjust the two numeric
examples above to whatever `today` the test fixture fixes; the exact
numbers aren't the point, the relative-to-`today` behavior is.)

- [ ] **Step 10: Run tests, verify they fail**

Run: `pytest viewer/webapp/tests/test_account_health_parsing.py -v -k "swept or format_days_ago or format_arr"`
Expected: FAIL

- [ ] **Step 11: Implement `compute_swept_days_ago`, `format_days_ago`, `format_arr_abbreviated`**

`compute_swept_days_ago(text, modified_time, today)`: look for `"Last
swept: YYYY-MM-DD"` in the text first; if absent, parse `modified_time`
(an RFC3339 string, as Drive's API returns it) as a fallback date; if
neither is available, return `None`. `format_arr_abbreviated`: `>= 1_000_000` → `$X.XXM` (2 decimal places); `>= 1_000` → `$XK` (no decimals); otherwise
the plain dollar amount; `None` → `'—'`.

- [ ] **Step 12: Run tests, verify they pass**

Run: `pytest viewer/webapp/tests/test_account_health_parsing.py -v -k "swept or format_days_ago or format_arr"`
Expected: PASS (5/5)

- [ ] **Step 13: Commit**

```bash
git add viewer/webapp/account_health.py viewer/webapp/tests/test_account_health_parsing.py
git commit -m "feat: add Account Health risk/next-step/staleness parsers"
```

- [ ] **Step 14: Write failing tests for `build_account_entry`'s no-doc-found case**

```python
def test_build_account_entry_no_doc_found():
    entry = build_account_entry('Acme Corp', 'primary', 'not_found', current_user_name=None, today=date(2026, 11, 9))
    assert entry['no_doc'] is True
    assert entry['health_group'] == 'no_health_data'
    assert entry['arr']['raw'] is None
    assert entry['renewal'] is None
    assert entry['csm'] is None and entry['ae'] is None and entry['tam'] is None
    assert entry['risks'] == []
    assert entry['next_step'] == "Review this account's Context Doc for next steps"
    assert entry['doc_url'] is None
    assert entry['refresh_query'] == 'refresh the context for Acme Corp'

def test_build_account_entry_none_doc_result_treated_same_as_not_found():
    entry = build_account_entry('Acme Corp', 'primary', None, current_user_name=None, today=date(2026, 11, 9))
    assert entry['no_doc'] is True
```

- [ ] **Step 15: Run tests, verify they fail**

Run: `pytest viewer/webapp/tests/test_account_health_page_model.py -v -k no_doc`
Expected: FAIL — `build_account_entry` not defined (create the new test file now)

- [ ] **Step 16: Write failing test for `build_account_entry`'s found-doc case**

```python
SAMPLE_DOC = """
Edition: Enterprise
Last swept: 2026-11-01
Overall health: Yellow
Current ARR: $256,000.
Renewal date: 2027-03-15
CSM: Jane Doe
AE: John Smith
TAM: Aaron Hubbart

Top open risks:
- Renewal timeline slipping [Gainsight via Glean, 2026-10-01]

Recommendation: Schedule an exec QBR before renewal.
"""

def test_build_account_entry_found_doc():
    doc_result = {'text': SAMPLE_DOC, 'doc_url': 'https://docs.google.com/x', 'modified_time': '2026-11-01T00:00:00.000Z'}
    entry = build_account_entry('Acme Corp', 'primary', doc_result, current_user_name='Aaron Hubbart', today=date(2026, 11, 9))
    assert entry['no_doc'] is False
    assert entry['health_group'] == 'watch'
    assert entry['arr']['value'] == 256000.0
    assert entry['renewal'] == '2027-03-15'
    assert entry['tam'] == 'You'
    assert entry['doc_url'] == 'https://docs.google.com/x'
    assert entry['swept_label'] == 'swept 8d ago'
```

- [ ] **Step 17: Run tests, verify they fail**

Run: `pytest viewer/webapp/tests/test_account_health_page_model.py -v -k found_doc`
Expected: FAIL

- [ ] **Step 18: Implement `build_account_entry`**

Branch on `doc_result`: a dict → run every Task 1/Task 2 parser against
`doc_result['text']`, pass `doc_result['modified_time']` to
`compute_swept_days_ago`, set `doc_url` and `no_doc=False`. The string
`'not_found'` or `None` → every field takes its placeholder default
(`no_doc=True`, `health_group='no_health_data'`, `arr={'raw': None, 'value':
None, 'disputed': False, 'note': None}`, everything else `None`/`[]`/the
`next_step` fallback string), `doc_url=None`. `refresh_query` is always
`f"refresh the context for {account_name}"` regardless of branch — the
spec requires Refresh to be available even when a doc already exists.

- [ ] **Step 19: Run tests, verify they pass**

Run: `pytest viewer/webapp/tests/test_account_health_page_model.py -v -k "no_doc or found_doc"`
Expected: PASS (3/3)

- [ ] **Step 20: Write failing tests for `build_page_model`**

```python
def _fetcher(docs):
    return lambda name: docs.get(name, 'not_found')

def test_build_page_model_groups_in_fixed_order_with_subtotals():
    accounts_config = [
        {'account_name': 'Red Co', 'tier': 'primary'},
        {'account_name': 'Green Co', 'tier': 'primary'},
        {'account_name': 'Unknown Co', 'tier': 'secondary'},
    ]
    docs = {
        'Red Co': {'text': 'Health: Red\nCurrent ARR: $100,000.', 'doc_url': 'u1', 'modified_time': None},
        'Green Co': {'text': 'Health: Green\nCurrent ARR: $200,000.', 'doc_url': 'u2', 'modified_time': None},
    }
    model = build_page_model(accounts_config, _fetcher(docs), current_user_name=None, today=date(2026, 11, 9))
    keys = [g['key'] for g in model['groups']]
    assert keys == ['needs_attention', 'watch', 'healthy', 'no_health_data']
    needs_attention = next(g for g in model['groups'] if g['key'] == 'needs_attention')
    assert needs_attention['count'] == 1
    assert needs_attention['arr_subtotal_raw'] == '$100K'
    no_health = next(g for g in model['groups'] if g['key'] == 'no_health_data')
    assert no_health['count'] == 1
    assert no_health['accounts'][0]['account_name'] == 'Unknown Co'

def test_build_page_model_stat_tiles():
    accounts_config = [{'account_name': 'A'}, {'account_name': 'B'}]
    docs = {
        'A': {'text': 'Health: Red\nARR: $1.2M vs $900K, figures conflict.', 'doc_url': 'u', 'modified_time': None},
        'B': {'text': 'Health: Green\nCurrent ARR: $500,000.', 'doc_url': 'u', 'modified_time': None},
    }
    model = build_page_model(accounts_config, _fetcher(docs), current_user_name=None, today=date(2026, 11, 9))
    tiles = model['stat_tiles']
    assert tiles['accounts_count'] == 2
    assert tiles['needs_attention_count'] == 1
    assert tiles['combined_arr_disputed_count'] == 1

def test_build_page_model_stale_count_ignores_unknown_staleness():
    accounts_config = [{'account_name': 'Old'}, {'account_name': 'Fresh'}, {'account_name': 'Unknown'}]
    docs = {
        # 45 days before the fixed `today` below -> stale
        'Old': {'text': 'Health: Green\nLast swept: 2026-09-25', 'doc_url': 'u', 'modified_time': None},
        # 2 days before -> not stale
        'Fresh': {'text': 'Health: Green\nLast swept: 2026-11-07', 'doc_url': 'u', 'modified_time': None},
        # no sweep line, no modified_time -> staleness unknown, must NOT count as stale
        'Unknown': {'text': 'Health: Green', 'doc_url': 'u', 'modified_time': None},
    }
    model = build_page_model(accounts_config, _fetcher(docs), current_user_name=None, today=date(2026, 11, 9))
    assert model['stat_tiles']['stale_count'] == 1

def test_build_page_model_missing_account_name_key_does_not_crash():
    # account-config.json entries have used both 'account_name' and 'name' historically
    accounts_config = [{'name': 'Legacy Co', 'tier': 'primary'}]
    model = build_page_model(accounts_config, _fetcher({}), current_user_name=None, today=date(2026, 11, 9))
    assert model['groups'][-1]['accounts'][0]['account_name'] == 'Legacy Co'
```

- [ ] **Step 21: Run tests, verify they fail**

Run: `pytest viewer/webapp/tests/test_account_health_page_model.py -v -k build_page_model`
Expected: FAIL — `build_page_model` not defined (4 new tests, all erroring)

- [ ] **Step 22: Implement `build_page_model`**

For each config entry, resolve the name via `acct.get('account_name') or
acct.get('name')`, call `doc_fetcher(name)`, build its entry via
`build_account_entry`. Bucket entries into the four groups in the fixed
spec order (`needs_attention`, `watch`, `healthy`, `no_health_data`); each
group's `arr_subtotal_raw` sums its entries' `arr['value']` (skipping
`None`) through `format_arr_abbreviated`. `stat_tiles`: `accounts_count` =
total entries; `combined_arr_raw` = `format_arr_abbreviated` of the sum
across *all* groups; `combined_arr_disputed_count` = count of entries with
`arr['disputed']` True; `needs_attention_count` = that group's count;
`stale_count` = count of entries whose swept-days value (recompute or
thread through from `build_account_entry`) is `> 30` — treat `None`
(unknown) as not stale, since "unknown" and "known old" are different
claims the spec's anti-goals say not to blur.

- [ ] **Step 23: Run tests, verify they pass**

Run: `pytest viewer/webapp/tests/test_account_health_page_model.py -v`
Expected: PASS (all 7: 2 no-doc/found-doc + 5 build_page_model)

- [ ] **Step 24: Commit**

```bash
git add viewer/webapp/account_health.py viewer/webapp/tests/test_account_health_page_model.py
git commit -m "feat: add Account Health card assembly and page model"
```

---

### Task 3: Drive integration — resolve and read Context Docs

**Files:**
- Modify: `viewer/webapp/gdrive_briefs.py`

**Interfaces:**
- Consumes: `_find_account_folder(drive, account_name)`, `_normalize_account_name(name)`, `_list_all_files_in_shared_drive(drive, query, fields)`, `_get_drive_service(refresh_token)` — all existing, lines ~684-816.
- Produces (used by Task 4): `find_account_context_doc(drive, account_name: str) -> Optional[Dict]` (`{'doc_id', 'doc_url', 'modified_time'}` or `None`); `read_doc_text(drive, doc_id: str) -> str`; `read_account_context_doc(refresh_token: str, account_name: str) -> Union[Dict, str, None]` — `{'text', 'doc_url', 'modified_time'}` on success, the string `'not_found'` when the account folder or the Doc inside it can't be resolved, `None` only on an actual Drive/auth failure (same three-outcome convention as `read_account_environments`).

No unit tests for this task — like every other `_find_account_folder`
caller in this file, it isn't independently tested without a real/mocked
Drive service, and this codebase's existing convention doesn't mock Drive
for this layer (`read_account_environments`/`write_account_environments`
have no direct tests either; `account_health.py`'s own tests inject a fake
`doc_fetcher` instead, which is the layer this task's three-outcome
contract is designed to satisfy).

- [ ] **Step 1: Implement `find_account_context_doc(drive, account_name: str) -> Optional[Dict]`**

```python
def find_account_context_doc(drive, account_name: str) -> Optional[Dict]:
    match = _find_account_folder(drive, account_name)
    if not match:
        return None
    account_folder_id, matched_name = match

    query = (
        f"parents='{account_folder_id}' and trashed=false "
        f"and mimeType='application/vnd.google-apps.document'"
    )
    candidates = _list_all_files_in_shared_drive(
        drive, query, fields='files(id,name,modifiedTime,webViewLink)')

    expected = f'{matched_name} Context'
    doc = next((f for f in candidates if f['name'].strip() == expected), None)
    if not doc:
        lowered = expected.lower()
        doc = next((f for f in candidates if f['name'].strip().lower() == lowered), None)
    if not doc:
        # last resort: any Doc in the folder whose normalized name contains
        # both the normalized account name and "context"
        norm_account = _normalize_account_name(account_name)
        doc = next((f for f in candidates
                    if norm_account in _normalize_account_name(f['name'])
                    and 'context' in f['name'].lower()), None)
    if not doc:
        return None

    return {'doc_id': doc['id'], 'doc_url': doc.get('webViewLink'), 'modified_time': doc.get('modifiedTime')}
```

- [ ] **Step 2: Implement `read_doc_text(drive, doc_id: str) -> str`**

```python
def read_doc_text(drive, doc_id: str) -> str:
    content = drive.files().export(fileId=doc_id, mimeType='text/plain').execute()
    return content.decode('utf-8') if isinstance(content, bytes) else content
```

- [ ] **Step 3: Implement `read_account_context_doc(refresh_token, account_name) -> Union[Dict, str, None]`**

```python
def read_account_context_doc(refresh_token: str, account_name: str) -> Union[Dict, str, None]:
    if not refresh_token:
        return None
    try:
        drive = _get_drive_service(refresh_token)
        if not drive:
            return None
        found = find_account_context_doc(drive, account_name)
        if not found:
            return 'not_found'
        text = read_doc_text(drive, found['doc_id'])
        return {'text': text, 'doc_url': found['doc_url'], 'modified_time': found['modified_time']}
    except Exception as e:
        logger.error('read_account_context_doc: %s: %s', account_name, e, exc_info=True)
        return None
```

- [ ] **Step 4: Add the `portfolio-summary` brief-section mapping**

In `_FILE_TO_SECTION` (line ~58), add the entry
`'portfolio-summary.json': 'portfolio-summary'`. This alone makes
`read_section(brief_date, 'portfolio-summary', ...)` work — no other
change needed, per `read_section`'s existing generic file-to-section
lookup (confirmed by reading `read_section`'s implementation — it has no
special-casing per section, it's table-driven off this dict).

- [ ] **Step 5: Run the full existing Drive test suite to confirm no regression**

Run: `pytest viewer/webapp/tests/ -v`
Expected: PASS — every pre-existing test still passes (this task adds no
new test files, so this is purely a regression check on the dict edit and
new functions not breaking any existing import).

- [ ] **Step 6: Commit**

```bash
git add viewer/webapp/gdrive_briefs.py
git commit -m "feat: resolve and read account Context Docs from Drive"
```

---

### Task 4: Flask routes

**Files:**
- Modify: `viewer/webapp/app.py`

**Interfaces:**
- Consumes: `gdrive_briefs.read_account_config`, `gdrive_briefs.read_section`, `gdrive_briefs.read_account_context_doc` (Task 3); `account_health.build_page_model` (Task 2); existing `db.get_google_refresh_token`, `db.get_google_drive_folder_id`, `login_required`, `DATE_RE`.
- Produces (used by Task 5's template): `GET /account-health` → renders `account_health.html`; `GET /api/account-health/<date_str>` → JSON `{'accounts_connected': bool, 'groups': [...], 'stat_tiles': {...}, 'callout': {'findings': [...]} | None}`.

No new test file for this task — matches this codebase's existing
convention of leaving thin Flask routes themselves untested while their
delegate functions (here, all of Task 1/2/3) are fully covered; Task 5's
manual browser check is what exercises this route end-to-end.

- [ ] **Step 1: Add `account_health_page` route**

```python
@app.route('/account-health')
@login_required
def account_health_page():
    return render_template('account_health.html', user_email=request.brief_user['email'])
```

- [ ] **Step 2: Add `api_account_health` route**

```python
@app.route('/api/account-health/<date_str>')
@login_required
def api_account_health(date_str):
    if not DATE_RE.match(date_str):
        abort(400)
    google_token = db.get_google_refresh_token(request.brief_user['id'])
    folder_id = db.get_google_drive_folder_id(request.brief_user['id'])
    if not google_token:
        return jsonify({'error': 'Google Drive not connected'}), 400

    config = gdrive_briefs.read_account_config(google_token, folder_id)
    if config is None:
        return jsonify({'error': 'Could not read account-config.json'}), 500

    def doc_fetcher(name):
        return gdrive_briefs.read_account_context_doc(google_token, name)

    model = account_health.build_page_model(
        config.get('accounts', []), doc_fetcher,
        current_user_name=request.brief_user.get('name'),
        today=date.today(),
    )

    callout_items = gdrive_briefs.read_section(date_str, 'portfolio-summary', google_token, folder_id)
    findings = None
    if callout_items and isinstance(callout_items[0], dict):
        candidate = callout_items[0].get('content', {}).get('findings')
        if candidate:
            findings = candidate

    return jsonify({
        'groups': model['groups'],
        'stat_tiles': model['stat_tiles'],
        'callout': {'findings': findings} if findings else None,
    })
```

- [ ] **Step 3: Add the module import**

At the top of `app.py` next to `import gdrive_briefs` (line ~57), add
`import account_health`.

- [ ] **Step 4: Run the full test suite**

Run: `pytest viewer/webapp/tests/ -v`
Expected: PASS — confirms the new import and routes don't break app.py's
existing module-level behavior (no new tests of their own; see note above).

- [ ] **Step 5: Commit**

```bash
git add viewer/webapp/app.py
git commit -m "feat: add Account Health Flask routes"
```

---

### Task 5: Template, toolbar link, and manual verification

**Files:**
- Create: `viewer/webapp/templates/account_health.html`
- Modify: `viewer/webapp/templates/brief_fragment.html`
- Test: `viewer/webapp/tests/test_toolbar_account_health_link.py`

**Interfaces:**
- Consumes: `GET /api/account-health/<date_str>` (Task 4)'s JSON shape, exactly as `build_page_model` + the route assemble it.

- [ ] **Step 1: Write the failing toolbar test**

```python
from template_test_utils import make_env


def render_brief_fragment():
    env = make_env()
    env.globals['url_for'] = lambda endpoint, **kwargs: (
        '/' + endpoint + ('?' + '&'.join(f'{k}={v}' for k, v in kwargs.items()) if kwargs else '')
    )
    template = env.get_template('brief_fragment.html')
    return template.render(
        brief_date='2026-09-15', brief_date_label='Tuesday, September 15',
        brief_type='morning', checkable_count=0, sections=[], items_by_section={},
        action_subsections=[], asana_pat_configured=False, today_iso='2026-09-15',
        progressive=False,
    )


def test_toolbar_has_account_health_link():
    html = render_brief_fragment()
    assert 'Account Health' in html
    assert 'href="/account_health_page"' in html
```

- [ ] **Step 2: Run the test, verify it fails**

Run: `pytest viewer/webapp/tests/test_toolbar_account_health_link.py -v`
Expected: FAIL — link not present yet

- [ ] **Step 3: Add the toolbar link**

In `brief_fragment.html`, next to the existing Day Plan link (line ~129):

```html
<a class="toolbtn" href="{{ url_for('account_health_page') }}">Account Health</a>
```

- [ ] **Step 4: Run the test, verify it passes**

Run: `pytest viewer/webapp/tests/test_toolbar_account_health_link.py -v`
Expected: PASS

- [ ] **Step 5: Build `account_health.html`**

A self-contained page (own `<style>` block, no shared stylesheet — matches
every other top-level page in this app) using the same CSS custom
properties as `day_plan.html` (`--bg`, `--surface`, `--surface2`,
`--border`, `--t1`/`--t2`/`--t3`, `--accent`/`--accent-bg`/`--accent-t`,
`--good-bg`/`--good-t`, `--bad-bg`/`--bad-t`, `--r`, both light and
`prefers-color-scheme: dark` variants). Structure per the spec's "The
design, as decided" section:
- Header: "Account Health" title, subtitle with `user_email` and account
  count (filled in by JS after the fetch), back link to `{{ url_for('index') }}`.
- Four stat tiles (Accounts / Combined ARR / Needs Attention / Stale Data
  (>30d)), each a clickable element that opens the triage panel filtered
  per the spec's per-tile rule.
- "This week" callout: a numbered list from `callout.findings`, the whole
  block hidden (not an empty box) when `callout` is `null`.
- Account cards grouped under header rows in the server's `groups` order
  (already fixed by `build_page_model`), each header showing `count` and
  `arr_subtotal_raw`.
- Each card renders every field from the spec's "Account card" section in
  the fixed order, using the API payload's per-account dict as-is (no
  client-side parsing — all parsing already happened server-side in
  Task 1/2). A field that's `None`/empty renders "Not captured this
  sweep" (or "No research yet" when `no_doc` is true) inline in the JS
  render function, never omitted.
- Footer links: `doc_url` (or hidden if `null` — "No research yet" already
  covers that case visibly elsewhere on the card) and the always-present
  Refresh link built as `` `claude://claude.ai/new?q=${encodeURIComponent(account.refresh_query)}` ``.
- Triage panel: a modal (`<dialog>` or a plain fixed-position div — match
  whichever pattern reads simplest against this app's existing modals, if
  any) listing the matching accounts' `next_step` lines; clicking a row
  closes the panel and scrolls to/briefly highlights that card (`scrollIntoView`
  + a temporary CSS class); Escape/backdrop-click closes it.
- Fetch `/api/account-health/${todayLocalIso()}` on load (reuse the
  `todayLocalIso()` pattern from `day_plan.html`, no date-switcher needed
  since this page doesn't have a morning/evening toggle).

- [ ] **Step 6: Manual verification (not pytest — UI/interaction only)**

Start the dev server (`run` skill or the project's existing dev-server
script) signed in as Aaron, open `/account-health`, and confirm against a
few of his real accounts (Goldman Sachs, Blink Health, ICON Clinical
Research, Optum, Bristol Myers Squibb — the ones the design doc was
calibrated against):
- Every account in `account-config.json` appears as a card — none missing.
- At least one account with a genuinely-missing Context Doc shows "No
  research yet" placeholders, not a blank/missing card.
- An account with a known multi-score health disagreement groups by the
  worse score and shows the disagreement note.
- Stat tiles open the triage panel pre-filtered correctly; clicking a row
  scrolls to and highlights the right card.
- Both footer links work: "Open Context doc" opens the real Doc; "Refresh
  research" opens the correct `claude://` deep link.
- If any real-doc pattern doesn't match what Task 1/2's synthetic fixtures
  assumed, fix the parser (adding a regression test with a new *synthetic*
  fixture modeled on the real pattern, never the real doc text itself —
  see Global Constraints) rather than special-casing the one account.

- [ ] **Step 7: Commit**

```bash
git add viewer/webapp/templates/account_health.html viewer/webapp/templates/brief_fragment.html viewer/webapp/tests/test_toolbar_account_health_link.py
git commit -m "feat: add Account Health page template and toolbar entry point"
```
