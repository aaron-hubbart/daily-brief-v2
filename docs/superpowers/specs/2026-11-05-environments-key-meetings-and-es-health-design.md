# Environments Tab — Key Meetings & ES Health (Design)

## Intent & why

Aaron manages too many accounts to track by memory which required ES
(Enterprise Success) meetings have happened, which are overdue, and how
healthy each engagement is. Today there's no record of this anywhere in
the app — a TAM would have to check calendars/Gainsight/memory per
account. This adds:

1. **Key Meetings** — per-team tracking of the standard ES playbook
   meeting cadence (one-time onboarding sequence + recurring reviews),
   so "has this happened / is it overdue" is answered by looking, not
   remembering.
2. **ES Health** — a per-team health signal (Green/Yellow/Red) derived
   from meeting compliance, a lightweight non-meeting ES-activities
   checklist, manually-set sentiment, and open-issue count — with the
   *contributing factors always visible*, so a TAM can see exactly what
   to fix to improve the score, not just a opaque number.
3. **Three dashboard levels** — portfolio (all customers), customer
   (all teams at one customer), team (one team's full detail) — so the
   same health/meeting data supports "who across my whole book needs
   attention" down to "what exactly does this team need."

Explicit instruction from Aaron: ship a usable v1 and iterate on design
and scoring based on real usage, rather than over-specifying up front.
This doc is deliberately a thin v1 — see Non-goals.

## Current state (grounding)

The Environments tab (`viewer/webapp/templates/environments.html`,
`app.py`, `gdrive_briefs.py`) already exists:

- One JSON file per in-scope customer in Google Drive
  (`Consulting > Customers/<Letter>/<Account>/<Account>-environments.json`),
  containing sibling arrays `teams`, `environments`, `use_cases`. No
  database table is involved anywhere in this feature.
- `teams` is a simple list of `{id, name, notes}`, scoped to that
  customer. A team is otherwise just a label referenced by
  `environments[].team_ids`.
- The page is a client-rendered single-page app: a customer dropdown
  drives a `CURRENT` JS variable; `GET/PUT /api/environments/config/<account>`
  round-trips that one customer's whole `{teams, environments, use_cases}`
  object. Each section (Teams, Environments, Use Cases) is its own
  collapsible `.panel`, edited in place, saved together via one
  "Save to Drive" button and `markDirty()`/`saveAll()`.
- In-scope customers come from an Asana portfolio lookup
  (`/api/environments/config`), independent of per-account data.
- Precedent for Claude-driven enrichment already exists:
  `account-environments-discovery` is a skill, triggered by a
  `claude://` deep link button on this same page, that researches a
  customer across connected sources and proposes (never silently
  writes) new/updated Teams/Environments/Use Case data for the TAM to
  approve.

This feature extends that same file shape and UI pattern rather than
introducing a new storage mechanism or app.

## Goals

- Track the standard ES playbook meeting cadence per team: the one-time
  onboarding sequence (ES101) and the recurring reviews (ES103/104/105
  family), with enough structure to tell "done / scheduled / overdue."
- Let a team be marked fully exempt (membership-only team, not an
  active engagement) and, independently, let specific optional/
  conditional meeting types be marked not-applicable for a specific
  active team (e.g. no Executive Meeting for a team with no exec
  sponsor engaged).
- Track a small set of non-meeting required ES activities per team
  (free-text checklist, not a synced catalog) — anything from the
  broader ES playbook (Lamppost) that matters enough to track but isn't
  itself a meeting.
- Compute a per-team Green/Yellow/Red health signal from: meeting
  compliance, ES-activity staleness, manually-set sentiment, and open
  issue count — and always show *why* (the specific overdue meetings /
  stale activities / sentiment / issue count behind the color), so the
  user can act on it.
- Three views: Portfolio (every in-scope customer, rolled up),
  Customer (one customer, every team), Team (one team, full detail) —
  each a drill-down from the one above it.

## Non-goals (v1)

- **No live Jira/Salesforce/Gainsight integration.** Sentiment and
  issue counts are populated by a human or by a Claude-driven refresh
  (see below) — not a live API call from the Flask backend on every
  page load.
- **No ingestion of the full Lamppost ES playbook catalog.** That's
  dozens of modules across ES101–ES401+, most of which are either
  already a meeting (covered by Key Meetings) or a Drive-hosted
  document, not app-owned data. ES Activities is a free-text checklist,
  not a synced structured catalog.
- **No enforced data-entry ordering** for the one-time onboarding
  sequence — a TAM can mark any step occurred/scheduled regardless of
  earlier steps' state. (Scoring *does* use catalog order to decide
  which single step counts against health — see Health computation —
  but nothing blocks data entry out of order.)
- **No calendar integration.** "Standing day/time" for a recurring
  meeting is a descriptive field a TAM fills in, not a real calendar
  event; "last held" is self-reported by the TAM, not detected
  automatically.
- **No tuned scoring model.** The Green/Yellow/Red rule below is a
  first cut, explicitly expected to be adjusted once there's real data
  to look at — don't over-invest in making it clever now.

## Anti-goals

- Don't let this become a second source of truth that drifts from
  Gainsight once that sync exists — field names and shapes here should
  be chosen so a future Gainsight sync can map onto them without a
  redesign (e.g. `sentiment` as a plain enum, not something
  app-specific).
- Don't block the whole Save flow on Glean/health computation — saving
  meeting/activity edits must stay instant and offline-safe, same as
  today's Teams/Environments/Use Cases save.
- Don't silently overwrite a TAM's manual sentiment/issue-count entry
  with a stale or failed Glean lookup — same "never overwrite a
  populated field, only fill blanks" discipline the discovery skill
  already follows.

## Data model

Two new sibling arrays in the same per-account
`<Account Name>-environments.json`, alongside the existing `teams`,
`environments`, `use_cases` — plus a few new fields directly on each
`teams[]` entry:

```json
{
  "teams": [
    {
      "id": "team-platform",
      "name": "Platform Team",
      "notes": "",
      "exempt": false,
      "sentiment": "",
      "sentiment_updated": "",
      "open_issues": null,
      "open_issues_updated": "",
      "inapplicable_meeting_types": ["es104-02-exec-meeting"],
      "onboarding_date": "",
      "renewal_date": ""
    }
  ],
  "environments": [ ... ],
  "use_cases": [ ... ],
  "meetings": [
    {
      "id": "mtg-<timestamp>",
      "team_id": "team-platform",
      "meeting_type_id": "es101-02-cs-intro",
      "status": "occurred",
      "scheduled_date": "",
      "occurred_date": "2026-03-10",
      "last_held_date": "",
      "standing_schedule": "",
      "notes": ""
    }
  ],
  "es_activities": [
    {
      "id": "act-<timestamp>",
      "team_id": "team-platform",
      "label": "Technical Workstream Overview kept current",
      "status": "done",
      "last_updated": "2026-10-01",
      "notes": ""
    }
  ]
}
```

Field notes:

- `teams[].exempt`: fully opts the team out of meetings, ES activities,
  and health — the team still exists (for membership/notes) but
  contributes nothing to any rollup and renders greyed out, same as
  the mockup.
- `teams[].sentiment`: one of `"Green"`, `"Yellow"`, `"Red"`, or `""`
  if unset. Plain enum (see Anti-goals) so it maps cleanly to a future
  Gainsight value.
- `teams[].open_issues`: integer or `null` if never populated.
- `teams[].onboarding_date` / `teams[].renewal_date`: ISO `YYYY-MM-DD`
  strings, or `""` if unset. Kept at the **team** level, not customer —
  most accounts aren't on an ELA (one company-wide contract), so
  different teams/projects at the same customer can have different
  onboarding and renewal timing. Revisit if that stops being true for
  enough accounts. Informational for v1 (shown on the team view) —
  not yet wired into the health/overdue computation; a natural future
  use is flagging renewal risk or anchoring the onboarding sequence's
  grace period to `onboarding_date` instead of an arbitrary one, once
  there's usage data to justify it.
- `teams[].inapplicable_meeting_types`: list of `meeting_type_id`
  values from the catalog (below) that a TAM has marked "doesn't apply
  to this team" — only meaningful for catalog entries whose
  `default_requirement` is `"optional"` or `"conditional"`; a
  `"required"` entry can't be marked inapplicable except via full team
  `exempt`.
- `meetings[]`: one row per *meeting-type-per-team* that has any state
  worth recording (not pre-created for every catalog entry — a team's
  meeting list is the catalog filtered by applicability, left-joined
  against whatever rows exist here). `status` is `"not_scheduled"`,
  `"scheduled"`, or `"occurred"` for one-time types; for recurring
  types, `standing_schedule` (free text, e.g. "Monthly, 1st Tue 10am")
  and `last_held_date` drive the on-track/overdue computation, and
  `status` is unused for those.
- `es_activities[]`: free-form per team, no catalog — `status` is
  `"done"` or `"not_done"`.

### Meeting catalog (new, global — not per-account)

A fixed-for-now, easy-to-edit list of meeting types, seeded from the
exact playbook Aaron provided, stored as a Python constant in `app.py`
(same pattern as `STATUS_BUCKET_HEADERS`) — **not** Drive-stored, since
every customer shares the same catalog:

| id | name | category | default cadence | default_requirement |
|---|---|---|---|---|
| `es101-01-handover` | Internal Handover (AE→CS) | one_time | — | required |
| `es101-02-cs-intro` | CS Introduction | one_time | — | required |
| `es101-03-joint-adoption-planning` | Joint Adoption Planning | one_time | — | required |
| `es101-04-technical-kickoff` | Technical Kickoff / Environment Overview | one_time | — | required |
| `es101-05-onboarding-completion` | Onboarding Completion Review | one_time | — | required |
| `es104-03-program-team-cadence` | Program Team Cadence | recurring | monthly | required |
| `es103-cvr` | Customer Value Review (CVR / QBR) | recurring | quarterly | required |
| `es104-02-exec-meeting` | Executive Meeting | recurring | yearly | optional |
| `es301-platform-best-practices` | Platform Best Practices | recurring | ongoing | conditional |
| `es105-03-technical-roadmap-review` | Technical Roadmap Review | recurring | periodic | required |

This table is the builder's seed data, not fixed forever — adding a
row later (e.g. ES302 Platform Health Check) is just adding a constant,
no migration, matching the "add fields later" philosophy the original
Environments spec already established for its own schema.

`ongoing` (ES301, not required either way) and `periodic` (Technical
Roadmap Review, required) aren't real durations. For overdue math,
treat `periodic` as quarterly by default — an explicit guess, called
out in code as such, same as the grace periods below — and `ongoing` as
never-overdue (it's conditional/optional, so it never drives the score
regardless).

### Health computation (v1 — explicitly tunable)

Per non-exempt team, in order (first match wins):

- **Red** if `sentiment == "Red"`, or 2+ `required` items are
  overdue/stale, counted as one combined pool across meetings and ES
  activities together (e.g. one overdue meeting plus one stale activity
  is enough to trip Red, not two of the same kind).
- **Yellow** if `sentiment == "Yellow"`, or exactly 1 `required`
  meeting/activity is overdue/stale, or `open_issues` exceeds a
  hardcoded placeholder threshold (e.g. 10 — call this out as a guess
  in code so it's trivially findable to tune).
- **Green** otherwise (including when sentiment/issues are unset —
  unknown isn't treated as bad).

"Overdue": a one-time meeting with no `occurred_date` past some grace
period, or a recurring meeting whose `last_held_date` + catalog cadence
has passed. "Stale": an ES activity marked `not_done` with
`last_updated` older than some grace period. Exact grace-period lengths
are a builder call (e.g. 2 weeks for one-time, cadence-dependent for
recurring) — not worth bikeshedding before real usage data exists.

**No data at all counts as overdue/stale**, not unknown — confirmed by
Aaron. A required catalog entry with no `meetings[]`/`es_activities[]`
row yet is treated exactly like a missed one for scoring purposes. This
is a deliberate, known tradeoff: since this rolls out onto Aaron's
whole existing book at once, nearly every pre-existing team will show
Red/Yellow on day one until its data is backfilled — that's expected,
not a bug to design around.

**One-time sequence scoring uses catalog order as an implied
dependency**: of the 5 one-time catalog entries, only the *earliest*
one (by catalog table order) that isn't `occurred` counts toward the
overdue tally for a team — later steps in the sequence are not
separately counted as additional overdue items even if they're also
not `occurred`, since they can't realistically happen before the
earlier ones do. (Nothing stops a TAM from recording them out of order
per the Non-goals note above — this rule only affects which single item
the score "blames.") Once the earliest incomplete step is marked
`occurred`, the next one in order becomes the one that counts.

The **breakdown is always computed and returned alongside the color**
(a list of human-readable reason strings, as in the mockup's "Why
Yellow" box) — the color is a derived display convenience, the
breakdown is the actual product.

### Issue counts via Glean — mechanism

The Flask backend has no access to Glean/company-search — that's a
Claude-session capability, not an API this Python app can call
directly. So `open_issues` is populated the same way
`account-environments-discovery` already populates other fields: a
`claude://` deep-link button (e.g. "Refresh issue count via Claude") on
the team's detail view that invokes a small skill, which searches Glean
for that customer/team's open issues and writes `open_issues` +
`open_issues_updated` back via the existing write API — on-demand, not
live-polling. This is a natural, small follow-up skill once the UI
exists; this doc doesn't design that skill in detail.

## UI

Reuses the existing Environments page/SPA rather than adding new
routes, consistent with how Teams/Environments/Use Cases already work:

- **Portfolio** becomes the Environments tab's landing view (replacing
  "pick a customer from a dropdown" as the first thing you see): a
  sortable table of every in-scope customer with health badge, overdue
  meeting count, sentiment, open issues. Requires a new endpoint that
  reads every in-scope customer's file server-side and rolls it up
  (worst-case team health per customer) — this fans out to N Drive
  reads per request where every other endpoint here does 1, so it gets
  a short in-memory TTL cache (a few minutes) rather than following the
  "no caching" precedent the rest of this module uses for single-file
  reads. Clicking a row drills into that customer (today's existing
  per-customer view).
- **Customer**: existing per-customer view gains a health/sentiment/
  issues strip at the top (rolled up across that customer's non-exempt
  teams) and a new "Teams" overview — a card per team (including
  exempt ones, greyed out) showing that team's health badge and a
  one-line meeting-status summary. Clicking a team card drills into
  that team.
- **Team**: a new in-page view (client-side state switch, not a new
  Flask route — same SPA pattern as everything else here) showing the
  team header (name, onboarding date, renewal date — plain editable
  date fields alongside the existing name/notes inputs), then the
  health breakdown box, then Key Meetings (One-time / Recurring,
  following the mockup's layout), then ES Activities, each its own
  `.panel` following the existing Teams/Environments/Use Cases visual
  language (collapsible cards, inline edit, `markDirty()`/`saveAll()`).

## What's left to the builder

- Exact grace-period lengths for "overdue"/"stale" and the open-issues
  Yellow threshold — pick reasonable placeholder defaults, comment them
  clearly as first-cut guesses (matching this repo's existing
  "no voodoo constants" norm of justifying config values in comments).
- Exact route/endpoint shapes for the new portfolio-rollup endpoint and
  for reading/writing `meetings`/`es_activities` (likely folded into
  the existing `GET/PUT /api/environments/config/<account>` payload,
  same as `use_cases` was added, rather than new endpoints — builder's
  call based on what's cleanest against the current `app.py`).
- Visual details beyond the wireframe (exact badge styling, table vs.
  card layout specifics) — follow `environments.html`'s existing CSS
  rather than introducing a new visual language.
- The Glean-refresh skill itself (trigger phrasing, exact Glean query
  shape) is explicitly out of scope for this doc — build the UI and
  data model first with a manual `open_issues` entry field, add the
  skill as a fast follow-up.
- Whether the portfolio rollup's TTL cache needs manual invalidation
  (e.g. on save) or a short TTL is good enough — short TTL is the
  simpler default, revisit if it proves confusing in practice.

## Testing

Follows this codebase's existing precedent for this whole feature
area: no automated test exists for any Environments route or Drive
read/write today (documented, accepted gap — same reasoning as
`use_cases`), so this is verified manually: add/edit/remove meetings
and activities for a team, toggle exempt and inapplicable-meeting-type
flags, confirm health badge and breakdown update accordingly, confirm
round-trip through Save-to-Drive, confirm the three views drill down
correctly end to end.
