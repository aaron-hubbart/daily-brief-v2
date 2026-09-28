# Environments Tab: Use Cases Section + Account-Environments-Discovery Skill

## Goal

Two coupled pieces of work against the Environments tab (`viewer/webapp/templates/environments.html`, `viewer/webapp/app.py`, `viewer/webapp/gdrive_briefs.py`):

1. A new **Use Cases** section on the Environments page — manual CRUD, same pattern as the existing Teams and Environments panels.
2. A new skill, **`account-environments-discovery`**, that researches a customer across every connected source and proposes (never silently writes) Teams / Environments / Use Case data to fill in — invoked from a button on the Environments page or directly from claude.ai.

This is the "Phase 3" discovery pass the original [2026-09-23 Environments Tab design spec](2026-09-23-environments-tab-design.md) called out as future work ("a broader Claude-driven discovery pass that fills in whatever it can find across other already-connected sources"), plus a genuinely new Use Case data section that wasn't part of that original three-phase plan.

## 1. Use Case data model & UI

### Data model

Add a `use_cases` array to the existing per-account `<Account Name>-environments.json` file, as a sibling to `teams` and `environments`:

```json
{
  "teams": [ ... ],
  "environments": [ ... ],
  "use_cases": [
    {
      "id": "usecase-<timestamp>",
      "name": "",
      "description": "",
      "status": "",
      "go_live_date": "",
      "environment_id": "",
      "team_id": ""
    }
  ]
}
```

- `status` is one of `"Discovery"`, `"In Progress"`, `"Live"`, `"On Hold"`, `"Retired"`, or `""` if unset.
- `go_live_date` is an ISO `YYYY-MM-DD` string, or `""`.
- `environment_id` references an entry in that same account's `environments[].id`, or `""` if not linked to a specific environment.
- `team_id` references an entry in that same account's `teams[].id`, or `""` if not linked to a specific team.
- Both reference fields are single values (not arrays) — a use case maps to at most one environment and one team, unlike the many-to-many `team_ids` relationship between environments and teams.

No migration needed: `read_account_environments`'s empty-defaults path and any file predating this field simply gain `use_cases: []`.

### UI

A third panel on `environments.html`, below the existing Environments panel, following the same visual language already established by the Teams/Environments panels: `.panel` / `.panel-head` with an "Add use case" button on the right, one card per use case rendered with the existing `.env-card` styling and the existing caret-based collapse/expand behavior (`caretHtml` / `toggleExpanded` / `isExpanded`), consistent with how Teams and Environments cards already collapse.

Each use case card:

| Field | Control |
|---|---|
| Use Case Name | text input in the card header (like the environment label input) |
| Use Case Description | textarea |
| Status | `<select>` with the 5 fixed options above, plus a blank `""` option |
| Go-Live Date | `<input type="date">` |
| Related Environment | `<select>` populated from `c.environments` (value = `env.id`, display = `env.label`), plus a blank "—" option |
| Related Team | `<select>` populated from `c.teams` (value = `team.id`, display = `team.name`), plus a blank "—" option |

A `normalizeUseCase(uc)` function mirrors `normalizeTeam`/`normalizeEnvironment`, filling in `id`, and defaulting every field above to `""`. `ensureCustomer()` calls `c.use_cases = (c.use_cases || []).map(normalizeUseCase)` alongside its existing team/environment normalization.

Add/edit/remove reuse the exact same `markDirty()` → (user clicks "Save to Drive") → `saveAll()` flow already in place for Teams and Environments — no new save mechanism. `saveAll()`'s PUT body gains `use_cases: c.use_cases` alongside the existing `teams`/`environments` keys.

If a related environment or team is deleted, its id is simply left dangling in any use case's `environment_id`/`team_id` (rendered as the blank "—" option, since the dropdown only offers ids that currently exist) — same "just drops out of the list" behavior the existing `team_ids`-on-environment relationship already has when a team is removed (see `removeTeam`).

### Backend changes

- **`gdrive_briefs.py`**: `_EMPTY_ACCOUNT_ENVIRONMENTS` gains `"use_cases": []`.
- **`app.py` `api_environments_account_update`**: accepts an optional `use_cases` list in the PUT payload (validated as a list if present, defaulted to `[]` if absent for backward compatibility), passed through to `write_account_environments` alongside `teams` and `environments`.

## 2. Skill: `account-environments-discovery`

New skill folder in this repo, sibling to the root `daily-brief-v2` skill: `account-environments-discovery/SKILL.md`.

### Trigger

- "discover environments for `<account>`"
- "populate environments tab for `<account>`" / "populate environments for `<account>`"
- Explicit slash command: `/account-environments-discovery <account>`

### Invocation from the viewer

A "Discover via Claude" button in `environments.html`'s toolbar, next to the customer selector. Unlike every existing `claude://` deep link in this codebase (all server-side Jinja-templated `<a>` tags in Flask-rendered fragments), the Environments page is a client-side SPA where the selected customer only exists as the JS variable `CURRENT`. So this is a plain `<button>` whose `onclick` builds the URL at click time:

```js
function openDiscoverySkill() {
  const url = 'claude://claude.ai/new?q=' +
    encodeURIComponent('/account-environments-discovery ' + CURRENT);
  window.open(url, '_blank');
}
```

matching the `window.open(this.href, '_blank')` pattern `brief_fragment.html`'s Refresh link already uses to fire a `claude://` link via script rather than a plain anchor navigation.

### Flow

1. **Resolve the account.** Fetch the Asana Environments portfolio (`ENVIRONMENTS_PORTFOLIO_GID`, same one the viewer's `/api/environments/config` uses) and match the typed name against its project list — exact match first, fuzzy fallback (same spirit as the viewer's `isMyCustomer`/`bigramSimilarity`) — so "acme" or "Acme Corp." resolves to the portfolio's actual project name. If no match is found, say so and stop rather than guessing.
2. **Read existing data.** Locate `<Consulting > Customers>/<Letter>/<Account Name>/<Account Name>-environments.json` via Google Drive, per the path convention in the [2026-09-23 design spec](2026-09-23-environments-tab-design.md#data-model), and read the current `teams`, `environments`, and `use_cases`. Treat a missing file as the empty-defaults baseline (`{teams: [], environments: [], use_cases: []}`) — everything found in that case becomes a "new record," not an "update." This baseline is authoritative: nothing gets overwritten, only filled in or added to.
3. **Research broadly**, using whatever connectors are available in the running session:
   - **Google Drive** — the account's own folder (context doc, sizing decks, meeting notes, handover sheets, prior diagnostic bundles).
   - **Slack** — the account's channels and the tiger team channel.
   - **Asana** — the customer's own project (task descriptions, custom fields, notes).
   - **Glean** (or equivalent enterprise search) — Salesforce account/opportunity data, Confluence, email — whatever is indexed for that account name.
   Look for: team members and roles (→ Teams), environment names and deployment details — SaaS vs. Self-Managed, Camunda version, components, cluster/broker info, links (→ Environments), and candidate use cases with a name, description, lifecycle status, and go-live date (→ Use Cases).
4. **Draft a proposal — do not write yet.** Present findings in chat as two clearly separated groups:
   - **New records** — teams, environments, or use cases that don't exist in the file at all yet, shown as full new entries.
   - **Updates to existing records** — blank fields being filled on a team/environment/use case that's already there, shown per-record as `Field: (empty) → proposed value` so it's unambiguous which existing entry each update lands on.
   Every item in both groups carries a short source note (e.g. "from #acme-tiger-team, 2026-09-10") so the user can judge provenance before approving either group. Conflicting signals from different sources (e.g. one says SaaS, another says Self-Managed) are surfaced as a flagged conflict rather than silently resolved. Low-confidence inferences (implied, not stated outright) are still proposed, but flagged as low-confidence in the source note.
5. **On confirmation, write.** Merge only into currently-blank fields and append new records — never overwrite a populated field — then write back using the same title-based lookup + create-new/trash-old Drive pattern `write_account_environments` uses (find the existing file by name in the account folder, create a new version with the same name, trash the old one).

### Explicitly out of scope

- No automatic overwrite of any already-populated field, ever — this skill only fills blanks and adds new records.
- No fabricated data — if nothing is found for a field, it stays blank; the skill does not invent plausible-sounding values (version numbers, dates, etc.).
- No write happens without an explicit user confirmation of the proposal.

## 3. Error handling & edge cases

- **Account not found** in the Environments portfolio or as a Drive folder → report clearly and stop.
- **No existing file for this account** → empty baseline; everything found is a "new record."
- **Nothing found anywhere** → say so plainly.
- **Conflicting signals** across sources → surfaced in the proposal, not silently resolved.
- **Low-confidence guesses** → proposed but flagged, so the user can choose to exclude them at approval time.
- **User declines the proposal** → nothing is written.
- **Concurrent edit risk**: the skill reads-then-writes the same file the viewer reads-then-writes on Save; if a TAM is mid-edit in the browser while the skill writes, last write wins. This is the same risk that already exists between two people editing the same account in the viewer — not a new failure mode introduced by this design.

## 4. Testing plan

- **Viewer (Use Case UI + backend)**: manual smoke test — add/edit/remove a use case; verify the Related Environment/Related Team dropdowns populate from that customer's current teams/environments and persist the chosen `id`; verify `use_cases` round-trips through `PUT /api/environments/config/<account>`; verify an account with a pre-existing file that predates this field (no `use_cases` key) loads cleanly with an empty Use Cases panel.
- **Skill**: no automated tests — it's a prose skill, not code, matching every other skill in this repo. Validated by running it against a real account with intentionally mixed existing/missing data and confirming the new-vs-updated split, source notes, and conflict flagging all render correctly, and that a declined proposal writes nothing to Drive.
