# Environments Tab — Design (Phase 1: data model & manual entry)

## Goal & phasing

A new **Environments** tab tracking, per in-scope customer, one or more
Camunda deployment environments (e.g. Production, Staging) — deployment
basics, version/component info, links, notes, and a dated history of
diagnostic report and Helm `values.yaml` links.

This is Phase 1 of three, scoped deliberately narrow — a data model plus a
manual entry/edit UI:

- **Phase 1 (this spec)**: data model + manual CRUD UI. A TAM fills this in
  by hand.
- **Phase 2** (separate spec, later): a skill that takes an uploaded Camunda
  Support diagnostic bundle and auto-populates an environment record from
  it, recording the bundle's own link/date/ticket in the process.
- **Phase 3** (separate spec, later): a broader Claude-driven discovery pass
  that fills in whatever it can find across other already-connected sources
  (Drive, Slack, Asana) for a given customer.

Phases 2 and 3 both only ever *write into* this phase's data model — they
don't change it — so building this first is a hard prerequisite either way.

## Data model

New `environments-config.json`, stored in the same Drive `/config` folder as
the existing `account-config.json`, read/written with the exact same
pattern already in `gdrive_briefs.py` (`_download_json` /
`MediaIoBaseUpload`, 5-minute cache, create-on-first-write). No new
database — this is organizational reference data with the same low write
frequency and single-digit-user scale as `account-config.json`, so the same
"one JSON file in Drive" approach applies without modification.

```json
{
  "Acme, Inc.": {
    "teams": [
      {"id": "team-platform", "name": "Platform Team", "notes": ""},
      {"id": "team-claims-app", "name": "Claims App Team", "notes": ""}
    ],
    "environments": [
      {
        "id": "prod",
        "label": "Production",
        "team_ids": ["team-platform", "team-claims-app"],
        "deployment": {
          "model": "SaaS",
          "install_method": "",
          "region": "",
          "multi_tenancy": "",
          "sizing": ""
        },
        "versions": {
          "camunda_version": "",
          "components": ["Zeebe", "Operate", "Tasklist", "Optimize", "Connectors"]
        },
        "links": {
          "console_url": "",
          "cluster_urls": [],
          "support_plan": "",
          "runbook_links": []
        },
        "notes": "",
        "diagnostic_reports": [
          {"link": "", "generated_date": "YYYY-MM-DD", "ticket": ""}
        ],
        "helm_values": [
          {"link": "", "date": "YYYY-MM-DD"}
        ]
      }
    ]
  }
}
```

Keyed by the same account name `account-config.json` already uses, so an
environment list hangs off the same customer identity the Customers and
Tasks tabs use — no second customer list to keep in sync by hand.
`diagnostic_reports` and `helm_values` are both append-mostly dated lists
per environment (a customer's Production environment accumulates a history
of reports and Helm values snapshots over time, rather than only ever
holding the latest one).

**Teams**: each customer has its own small list of named teams (e.g. "Platform
Team", "Claims App Team") — scoped to that customer, not shared globally.
The relationship to environments is many-to-many, represented as
`team_ids` on each environment: a team can appear on more than one
environment (e.g. Platform Team owns both Staging and Production), and an
environment can list more than one team (e.g. Production is jointly owned
by Platform and an app team). No separate join structure is needed since
both sides live under the same customer key — deleting a team just means
removing its id from any environment's `team_ids` and from the `teams`
list.

**On scope**: the fields above are deliberately minimal for a first cut.
The real expectation is that this schema grows substantially as it gets
used against real customer environments — more deployment detail, more
link types, whatever Phase 2's diagnostic-bundle parsing turns out to
surface. Adding fields later is just adding optional keys to this JSON
shape (no migration), so this spec intentionally doesn't try to
anticipate that detail now — extend it iteratively as concrete needs
show up rather than speculatively now.

## Customer list scope

**Superseded from an earlier draft of this spec**, which proposed a
Salesforce `Success Tier` lookup. That required a new service credential
and an unconfirmed custom-field name, and has been replaced with a much
simpler mechanism using data already flowing through this app:

Shows only customers with a project in a specific **Asana portfolio**
(`https://app.asana.com/0/portfolio/1209916881329688/1209923685916686` —
`1209916881329688` is the portfolio GID; the second ID is the portfolio
view, not needed for the API call). One project per customer in that
portfolio, per your description — a customer is in scope if their
`account-config.json` account name matches the name of a project currently
in the portfolio.

- **No new integration**: this app already talks to Asana (per-user stored
  PAT, same one Tasks/Customers already use). Uses Asana's
  `GET /portfolios/{portfolio_gid}/items` endpoint (returns the portfolio's
  member projects) via the existing `_asana_api_get` helper — same call
  shape `asana_discovery.py` already uses for a different Asana lookup.
- **No active/pending distinction** carried over from the earlier
  Salesforce draft — portfolio membership doesn't have a "stage" concept
  the way a Salesforce Opportunity does, so a customer is simply in scope
  or not. Revisit if you want finer-grained status later.
- **The portfolio is authoritative** — every project name it returns is a
  customer, full stop. No cross-check against `account-config.json`'s
  `account_name` values. (An earlier draft of this section described an
  intersection with `account-config.json`; the implemented and reviewed
  behavior is portfolio-only, and this is that call made explicit rather
  than a stray non-customer project silently requiring a second config
  file to stay in sync.) Environment records are still keyed by this same
  project-name string, matching how `account-config.json`'s `account_name`
  is used elsewhere in this app — so renaming the Asana project orphans
  its saved environments, a known limitation for this first cut.
- **No caching**: every other Asana call in this app (`_fetch_live_action_items`,
  `asana_discovery.find_new_projects`, PAT validation) is called fresh on
  each request rather than cached — only Drive *folder-GID* lookups are
  cached in this codebase, not Asana API results. This lookup follows that
  same precedent rather than introducing a new caching layer.
- The portfolio GID above should be double-checked against a real
  `GET /portfolios/{gid}/items` call before relying on it — Asana portfolio
  URLs aren't fully standardized across UI versions, so confirm it returns
  projects (not an error) before treating it as final; it's a one-line
  config value to correct if wrong.

## UI

New "Environments" nav entry alongside Brief / Tasks / Customers / Admin.
Lists in-scope customers (from the Asana-portfolio-backed lookup above), each
expandable to show a small **Teams** management list (add/rename/remove)
and their environment(s) as cards below it; each environment's edit form
includes a multi-select of that customer's teams for `team_ids`. Modeled
on `customers.html`'s edit-in-place table pattern for consistency with the
rest of the viewer.

## Testing

- The portfolio-membership lookup takes an injectable `fetch_fn` (same
  signature `asana_discovery.find_new_projects` already uses:
  `fetch_fn(pat, path, params) -> dict`), so it's unit-tested with a
  hand-rolled fake — no network, no mocking library — exactly like
  `test_asana_discovery.py` already does for that sibling function.
- **No automated test for the new `read_environments_config`/
  `write_environments_config` functions or the new Flask routes.**
  `read_account_config`/`write_account_config`/`read_config`/`write_config`
  — the three existing sibling "config JSON in Drive" pairs this new one
  matches exactly — have no tests today either (there's no stubbed-Drive-
  client pattern anywhere in this codebase to extend), and no route in
  this app has an automated test (same reason as the Tasks tab: `app.py`
  needs live env vars and Postgres to import). This isn't a new gap this
  feature introduces — it's the existing, consistent level of coverage for
  this whole category of code. Verified manually instead, same as every
  sibling function and every route.
`tests/test_environments_view.py`:
- Route auth-gating (same pattern as every other authenticated route).
- `environments-config.json` read/write round-trips correctly against a
  stubbed Drive client (mirrors how `account-config.json`'s round-trip
  would be tested).
- The Salesforce Success-Tier query function is isolated behind a small
  wrapper so it can be unit-tested against a stubbed SOQL response rather
  than a live Salesforce call.
