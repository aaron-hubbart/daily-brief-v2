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

Shows only customers judged in-scope by **Salesforce `Success Tier`**:

- Research into "Enterprise Success" turned up no queryable field or
  status by that name — it exists only as free-text Opportunity naming
  (e.g. "... - Enterprise Success Plan"). `Success Tier` (values seen:
  Deal-Level / Enterprise / Essential) is a related-but-distinct existing
  field on Opportunity records, and is what this filter uses instead, per
  your call.
- Proposed mapping, carrying over the active/pending distinction from the
  original ask: a customer is **in scope** if they have any Opportunity with
  `Success Tier = Enterprise`; **active** if that Opportunity is Closed Won,
  **pending** if it's open (any non-closed-lost stage). Flag if this isn't
  the right read of "active/pending" once you see it in practice — easy to
  adjust, since it's one query.
- **New integration**: nothing in this app talks to Salesforce today. Adds
  a shared, app-level service credential (same pattern as the existing
  `SLACK_BOT_TOKEN` — one org-wide secret, not per-user OAuth), via
  `simple-salesforce` (already vendored locally for reference, and on
  PyPI). The exact custom-field API name for `Success Tier` (e.g. something
  like `Success_Tier__c`) needs confirming against the real schema — Support
  or RevOps can confirm it — before this part is implemented; the query
  itself is written as configurable (an env var), not hardcoded, so
  correcting it later is a one-line change.
- Results cached the same 5 minutes as the Drive config lookups, to avoid
  hitting Salesforce on every page load.

## UI

New "Environments" nav entry alongside Brief / Tasks / Customers / Admin.
Lists in-scope customers (from the Salesforce-backed lookup above), each
expandable to show a small **Teams** management list (add/rename/remove)
and their environment(s) as cards below it; each environment's edit form
includes a multi-select of that customer's teams for `team_ids`. Modeled
on `customers.html`'s edit-in-place table pattern for consistency with the
rest of the viewer.

## Testing

`tests/test_environments_view.py`:
- Route auth-gating (same pattern as every other authenticated route).
- `environments-config.json` read/write round-trips correctly against a
  stubbed Drive client (mirrors how `account-config.json`'s round-trip
  would be tested).
- The Salesforce Success-Tier query function is isolated behind a small
  wrapper so it can be unit-tested against a stubbed SOQL response rather
  than a live Salesforce call.
