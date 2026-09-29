---
name: account-environments-discovery
description: >
  Researches a Camunda customer account across every connected source (Google Drive, Slack, Asana, and enterprise search such as Glean/Salesforce/Confluence) and proposes Teams, Environments, and Use Case data to fill into that account's Environments tab record — never writing anything until the user reviews and approves the proposal.

  Trigger on "discover environments for [account]", "populate environments tab for [account]", "populate environments for [account]", or the explicit "/account-environments-discovery [account]".

  Invoked either directly in claude.ai/Claude Desktop, or via the "Discover via Claude" button on the hosted daily-brief viewer's Environments page (viewer/webapp/templates/environments.html), which opens a claude:// deep link with the currently-selected account name already filled in.
---

# Account Environments Discovery

Fills in gaps in a customer's Environments tab record — Teams, Environments, and Use Cases — by researching across connected sources, then proposing what it found for the user to approve before anything is written. This is the discovery pass described as future work ("Phase 3") in `docs/superpowers/specs/2026-09-23-environments-tab-design.md`, plus discovery of the newer Use Cases section from `docs/superpowers/specs/2026-09-28-environments-use-cases-and-discovery-skill-design.md` — read both if you need the full data-model and storage-path rationale; this file has everything needed to run the skill.

**Golden rule: propose, don't write.** This skill never overwrites a field that already has a value, never invents plausible-sounding data, and never writes to Drive without an explicit "yes, save this" from the user in the same conversation.

## Step 1 — Resolve the account

The account name comes from the trigger (e.g. `/account-environments-discovery Acme Corp`). Canonicalize it against the Asana **Environments** portfolio — the same one the viewer's `/api/environments/config` endpoint uses (`ENVIRONMENTS_PORTFOLIO_GID`, default `1209916881329688`, one project per in-scope customer):

1. Call `GET /portfolios/{portfolio_gid}/items` via the Asana MCP connector to list in-scope customer project names.
2. Match the typed name against that list — exact (case-insensitive) match first; if none, fuzzy-match (ignore case/punctuation/legal suffixes like Inc./LLC/Corp) and confirm the best candidate with the user if it's not an obvious single match.
3. If nothing matches at all, tell the user plainly and stop — do not guess a name or invent a folder.

The portfolio's exact project name (once matched) is the canonical account name for every step below.

## Step 2 — Read the existing record

The account's data lives at:

```
<Consulting > Customers Shared Drive>/<Letter>/<Account Name>/<Account Name>-environments.json
```

where `<Letter>` is the account name's first character, uppercased (`A`-`Z`, or `1-9` for a name starting with a digit).

Via the Google Drive connector: find the account's folder under the Customers Shared Drive (match by folder name — exact first, case-insensitive fallback), then find `<Account Name>-environments.json` inside it (matching the Drive folder's own spelling, which may differ slightly in case from the Asana project name). Read its contents.

- **If the file exists**: this is your baseline — `{teams: [...], environments: [...], use_cases: [...]}`. Every field that's already populated is off-limits for overwriting.
- **If the file doesn't exist yet** (or the account folder has no such file): treat the baseline as empty — `{teams: [], environments: [], use_cases: []}`. Everything you find becomes a "new record" (see Step 4), not an "update."
- **If the account folder itself can't be found**: tell the user and stop.

Keep the exact shape of `teams[]`, `environments[]`, and `use_cases[]` entries in mind for Step 4 — see the schema in `docs/superpowers/specs/2026-09-28-environments-use-cases-and-discovery-skill-design.md` (Use Cases) and `2026-09-23-environments-tab-design.md` (Teams/Environments) if you need a refresher on field names.

## Step 3 — Research broadly

Search whatever connectors are available in this session for the canonical account name (and obvious variants/abbreviations):

- **Google Drive** — the account's own Customers-Drive folder: sizing decks, meeting notes, handover sheets, any `<Account Name>-context.md`, prior diagnostic bundles or Helm `values.yaml` exports.
- **Slack** — the account's dedicated channel(s) and the tiger team channel, for architecture discussion, go-live announcements, team introductions, and infrastructure details.
- **Asana** — the customer's own project (not just the portfolio-membership check from Step 1): task descriptions, custom fields, and project notes.
- **Enterprise search (Glean or equivalent)** — whatever's indexed for that account name: Salesforce account/opportunity data, Confluence pages, email threads.

Look specifically for:

| Target | What to look for |
|---|---|
| **Teams** | Named teams/squads on the customer side, their members (name, title, email), notes about ownership |
| **Environments** | Environment names (Production, Staging, ...), SaaS vs. Self-Managed, install method, sizing, Camunda version, components (Zeebe/Operate/Tasklist/Optimize/Connectors), OS, hosting platform, cluster/broker/partition/replication counts, multi-region, observability setup, multi-tenancy, links (cluster URL, support plan, runbooks) |
| **Use Cases** | Named business processes or automation initiatives running on Camunda — a name, a short description, lifecycle status, target/actual go-live date, and which environment/team it's tied to if that's evident |

Don't fabricate anything. If a field can't be found anywhere, leave it out of the proposal entirely rather than guessing.

## Step 4 — Draft the proposal (do not write yet)

Present findings in chat as two clearly separated groups, so the user can tell at a glance what's brand-new versus what's touching something that already exists:

### New records
Full new entries — a team, environment, or use case that isn't in the baseline at all. Show the whole proposed entry plus a short source note, e.g.:

> **New environment: "Staging"** — SaaS, Camunda 8.6, cluster URL `https://...`
> *(source: #acme-tiger-team, 2026-09-10)*

### Updates to existing records
Only for currently-blank fields on a record that already exists. Show each field change scoped to its record so it's unambiguous which existing team/environment/use case it applies to, e.g.:

> **Production environment** — Camunda version: *(empty)* → `8.5.3`
> *(source: Acme sizing deck, Consulting > Customers > A > Acme Corp)*

Flag anything worth extra scrutiny inline, right next to the item:
- **Conflicting signals** — e.g. one source says SaaS, another says Self-Managed for the same environment. Show both sources and ask the user to pick, rather than resolving it yourself.
- **Low-confidence inferences** — something implied but not stated outright (e.g. a use case only mentioned in passing in a Slack thread). Mark it clearly as low-confidence so the user can exclude it easily.

End with a plain question: which of these should be saved?

## Step 5 — Write only what's approved

Once the user confirms (they may approve everything, a subset, or ask for edits first):

1. Take the current baseline read in Step 2 (re-read it if meaningful time has passed, in case someone edited it in the viewer meanwhile) and merge in only the approved items: append approved new records to their respective arrays, and set only the specific approved blank fields on existing records.
2. Write the merged `{teams, environments, use_cases}` object back to `<Account Name>-environments.json` using the same Drive write pattern the viewer's backend uses: find the existing file by name in the account folder, create a new file with the same name and same parent folder containing the merged content, then trash the old file (Drive's `update` only changes metadata, not content — this is a create-new/trash-old replace, not an in-place patch).
3. Confirm back to the user what was written, and where (link to the file/folder if easily available).

If the user declines the whole proposal, don't write anything — just end the conversation there.

## Edge cases

- **Nothing found anywhere** for this account: say so plainly instead of presenting an empty or padded-out proposal.
- **Account has no folder in Consulting > Customers**: stop and tell the user — don't create one.
- **User is mid-edit in the viewer**: this skill and the viewer both do read-then-write against the same file; if both happen at once, last write wins. Not this skill's problem to solve — same risk already exists between two people editing the same account in the viewer.
