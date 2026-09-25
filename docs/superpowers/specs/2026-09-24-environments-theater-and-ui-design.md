# Environments Tab — Theater-Based Regions, Robust Customer Matching & Collapsible UI

Builds on `2026-09-23-environments-tab-design.md`. Two independent problems
on the same page, shipped together:

1. The Region filter is driven by a manually-typed per-environment
   `deployment.region` field that's almost never filled in, so it only ever
   shows "All regions".
2. The in-scope customer list is matched against Asana purely by exact
   project-name string equality, which silently drops any customer whose
   Asana project name doesn't match `account_name` verbatim.
3. (UI) Teams and environments render as long flat lists with no way to
   collapse them, and the save-status text lives in a bare div at the
   bottom of the page, disconnected from the Save button.

## 1. Theater-based regions & customer matching

### Current state

`asana_discovery.get_portfolio_project_names()` calls
`/portfolios/{gid}/items` with `opt_fields=name` and returns a sorted list
of plain name strings. `app.py`'s `/api/environments/config` treats any
`account-config.json` customer whose `account_name` exactly equals one of
those strings as "in scope." The Region toolbar filter (`environments.html`)
separately scans every in-scope customer's environments for a non-empty
`deployment.region` and offers those as filter options.

Meanwhile `account-config.json` already stores an exact Asana mapping per
customer — `project_gid` — used elsewhere (action-item fetching, the "new
projects" discovery scan) to identify a customer's Asana project. The
Environments in-scope check just wasn't using it.

### Change

**`asana_discovery.get_portfolio_project_names(fetch_fn, pat, portfolio_gid)`**
— now requests `opt_fields=name,custom_fields.name,custom_fields.display_value`
and returns `List[{"gid": str, "name": str, "theater": Optional[str]}]`,
sorted by name (case-insensitive). `theater` is the `display_value` of
whichever custom field's `name` matches `"theater"` case-insensitively, or
`None` if the item has no such field. (Breaking return-shape change from
`List[str]` — no other caller exists besides `app.py` and its own tests.)

**`app.py`'s `/api/environments/config`** now also loads
`account-config.json` via the already-existing `gdrive_briefs.read_account_config()`,
and does matching server-side in a new pure helper
(`asana_discovery.match_accounts_to_theaters` or similar, unit-testable the
same way as the rest of the module):

1. Build a `{gid: item}` map from the portfolio items.
2. For each account: if `account["project_gid"]` is set and present in that
   map, it's matched — take that item's `theater`.
3. Otherwise, fuzzy-match `account_name` against the names of portfolio
   items not already claimed by another account's exact match, using
   `difflib.SequenceMatcher.ratio()` on lowercased/whitespace-normalized
   strings. Best match above a `0.72` threshold wins; below it, the account
   is left out of scope (today's behavior, just with better recall than
   pure equality).
4. Returns `[{"name": account_name, "theater": theater_or_none}, ...]`
   sorted by name — this is the new `in_scope_customers` field, replacing
   `in_scope_names` in the JSON response. (`needs_pat` / Asana-error
   branches keep returning `None` for it, same as today.)

No new Drive-stored schema and no new manual-mapping UI: `project_gid`
already *is* the manual override, just newly wired up to this feature.

### Frontend (`environments.html`)

- `STATE.in_scope_names: string[]` → `STATE.in_scope_customers: {name, theater}[]`.
  Every read site updates: the customer `<select>` options, the "My
  Customers" toggle filter, the `needs_pat`/error/empty branches.
- `allRegions()` / `customerHasRegion()` are removed. The Region dropdown's
  options become the sorted distinct set of non-null `theater` values across
  `in_scope_customers`; the filter checks a customer's own `theater`
  directly. The toolbar keeps the "Region" label — least disruptive, and
  the concept it now filters on (Asana Theater, e.g. AMER/EMEA/APAC) is
  still "region" in the everyday sense TAMs use it.
- The per-environment `deployment.region` field (free-text infra region,
  e.g. `us-east-1`) is untouched — unrelated concept, stays manual.
- A customer with `theater: null` just never matches a specific region
  filter value, but still shows under "All regions."

### Testing

- `test_asana_discovery.py`: update the three existing
  `get_portfolio_project_names` tests for the new return shape; add cases
  for theater extraction (present, absent, custom field present but not
  named "Theater") and for the new matching helper (gid match wins over a
  worse name match; fuzzy match above/below threshold; two accounts
  competing for one name only one gets it).

## 2. Collapsible teams & environments, grouped by team

### Collapse mechanism

Not native `<details>/<summary>` — team and environment headers already
contain an editable name `<input>` and a Remove button, which would fight
with `<summary>`'s click-to-toggle. Instead, each collapsible header gets a
caret button (▸/▾) that toggles a `collapsed` class on its body, via
existing `data-*`-attribute delegation (same pattern already used for
team-checkbox wiring).

### Persistence

One localStorage key per customer, e.g. `env-tab:expanded:<customer name>`,
holding a JSON array of ids that are **expanded**. Nothing recorded for an
id means collapsed — matching the chosen default (everything starts
collapsed on first view). Toggling a header adds/removes its id from this
set and re-saves it immediately (no dependency on the unrelated
Save-to-Drive flow, since collapse state is a local UI preference, not
persisted config data).

Ids in this set, by kind: team ids (`team.id`), environment ids (`env.id`,
independent per rendered copy — see below), and one group id per team plus
a literal `"__unassigned__"` for the trailing group.

### Environments grouped by team

The Environments panel changes from a flat `c.environments.map(...)` list
to one collapsible group per team (in `c.teams` order), plus a trailing
"Unassigned" group for environments with an empty `team_ids`. An
environment linked to multiple teams renders — independently collapsible
— under every one of its teams' groups; all copies reference the same
`c.environments[idx]`, so editing any field in either copy edits the same
underlying object (looked up by the environment's real index in
`c.environments`, not a per-group position).

Each individual environment card remains its own collapsible unit nested
inside its group(s), on top of the group-level collapse.

### Save confirmation placement

The bottom-of-page `<div class="msg" id="msg">` is removed. A small inline
status `<span>` next to the Save button shows "Unsaved changes" while dirty
and "Saving…" mid-request, clearing once the request resolves. The final
outcome — "Saved to Drive" / "Save failed: …" — keeps using the existing
top-center toast popup (`showToast`, already implemented and already
matches the "popup" style referenced), so there's exactly one confirmation
mechanism instead of two.

### Testing

Manual verification in-browser (this module has no existing JS test
harness): collapse/expand persists across reload; an environment linked to
two teams shows in both groups and edits propagate; unassigned environments
land in the trailing group; Save button's inline status and the toast both
behave correctly on success and failure.
