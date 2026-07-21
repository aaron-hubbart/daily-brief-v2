# Section Refresh Runs

Not part of the normal brief trigger. Read this file whenever any viewer Refresh button is clicked (arrives as a new chat message via the `claude://` deep link) or the user directly types an equivalent request. Two flavors, covered in order below: a single Customer Update / Manager Update card, or a whole section's Refresh button (covered further down). Neither flavor runs a full brief or touches anything outside its own target.

## Trigger phrases and prompt format

The buttons send a structured command, not a bare label:

- Card-level: `/daily-brief Refresh customer update for {Account Name} date:{brief_date}` or `/daily-brief Refresh manager update date:{brief_date}`.
- Section-level: `/daily-brief Refresh section:{slug} date:{brief_date}`, where `{slug}` is one of `yesterday-meetings`, `account-recap`, `today`, `action-items`, `fyi` (matching the canonical slugs in `references/item-sync.md`).
- Single-item section refresh: `/daily-brief Refresh section:{slug} date:{brief_date} item:{item_key}` — narrower than a full section refresh, regenerates and upserts only that one row. Not yet sent by any viewer button, but recognize it when typed or sent by a future per-item control.

`date:{brief_date}` is the date shown on the page the button was clicked from — always trust it over "today." This matters most when someone refreshes a section on an archived (non-today) brief; without the explicit date the skill would regenerate today's row instead of the one on screen.

**Legacy fallback:** older cached HTML may still send the bare pre-upgrade form (`/daily-brief Refresh {Section Label}` with a human label, no `date:`). If no `date:` is present, fall back to resolving today's local date via the Timezone Resolution logic in `SKILL.md`, and match `{Section Label}` against the five section labels case-insensitively. Treat this path as deprecated — it only exists for links rendered before this update went out.

Recognize close variations typed directly by the user the same way — match on account name (or "manager") plus a refresh/regenerate/redo verb, or on a section slug/label plus the same.

## Card-level steps (Customer Update / Manager Update)

1. **Identify the target.** One customer account by name, or the manager update. If the account name doesn't match anything in `Meeting Manager Config.xlsx` closely enough to be confident, ask which account rather than guessing.
2. **Use `brief_date` from the command** (or the Timezone Resolution fallback above if absent). Customer Update and Manager Update items live under that date's row regardless of when they were last generated or refreshed.
3. **Regenerate just that entry.** Run the Section 3 (or Section 4) generation process from `references/status-updates.md` for this one account/manager only — full Slack search and synthesis for that entry, nothing else. This is the only step in this flow that costs a real data-source call; every other account's Slack search is skipped entirely.
4. **Update the cache.** Write the new `content` and `generated_at` (now) into that one entry in `STATUS_UPDATE_CACHE_FILE_ID`. Leave every other entry — every other account, and the manager entry if this was a customer refresh — byte-for-byte untouched.
5. **Upsert the item.** `POST $DAILY_BRIEF_API_BASE_URL/api/items/upsert` (per `references/item-sync.md`) with:
   - Customer account: `section: customer-updates`, `item_key: cust-update-{slug}`, `item_type: card`, `content: {"textarea": "<new update>", "channel_id": "<from config>", "last_posted_at": "<now>"}`.
   - Manager update: `section: manager-update`, `item_key: mgr-update`, `item_type: text-block`, `content: {"textarea": "<new update>"}`.
   This updates the one existing row in place — every other item, card, and section is untouched by definition, since each is its own row.
6. **Respond briefly.** One line confirming which card refreshed, plus a link to `$DAILY_BRIEF_API_BASE_URL/brief/{brief_date}`. Don't reproduce the new card's content in chat — the person can read it in the viewer, same rule as a normal brief run.

If the Refresh click arrives well after the day's brief was first generated, that's expected and fine — this flow only ever touches the one card, so staleness elsewhere is not this flow's concern.

## Section-level refresh (the other five sections)

The viewer's other five sections (Yesterday's Meetings, Account / Initiative Recap, Today, Action Items, FYI) each have their own section-header Refresh button. This is a whole-section regeneration, not a single-item patch — there's no per-account cache involved here (that's specific to Customer Updates/Manager Update), so it always does a fresh pull.

### Steps

1. **Identify the target section** from `section:{slug}` (or the legacy label, per the fallback above).
2. **Use `brief_date`** from the command (or the Timezone Resolution fallback if absent).
3. **Re-run that section's normal data pull and generation logic only** — the same source calls and item shape described in `references/item-sync.md`'s per-section notes for that slug (e.g. Outlook + Zoom + Asana for Yesterday's Meetings, Asana search/create for Action Items — see the Action Items exception below). Skip every other section's data sources entirely; this is the whole point of a section-level refresh over a full brief run.
4. **Batch-upsert only this section's items.** `POST $DAILY_BRIEF_API_BASE_URL/api/items/batch-upsert` with `brief_date` and an `items` array containing only entries for the refreshed section, using the same `item_key` conventions from `references/item-sync.md` so existing rows are updated in place rather than duplicated. Items in every other section are untouched by definition, since each row is addressed by its own `(section, item_key)`.
5. **Respond briefly.** One line confirming which section refreshed, plus a link to `$DAILY_BRIEF_API_BASE_URL/brief/{brief_date}`. Same no-reproduction rule as a normal brief run and the card-level refresh above. If step 3 hit partial failures, name them here (see below) rather than only reporting success.

### Partial run handling

A section-level refresh doesn't get to assume every item will regenerate cleanly. Handle these cases explicitly:

- **Partial data-source failure.** If some items in the section regenerate successfully and others error (an API timeout on one meeting's Zoom assets, one Asana search failing), upsert the items that succeeded and report the specific failures by name in the chat response. Don't abort the whole refresh because one item in a multi-item section failed, and don't silently drop the failure from the response either.
- **Item count drift.** If the fresh pull returns fewer items than currently exist in Postgres for that `(section, brief_date)` (a meeting got cancelled, a task got completed elsewhere), there's no delete endpoint to remove the orphaned row. Instead, upsert that row with `stale: true` added to its `content` so the viewer can gray it out rather than show it as current. Never leave a stale item indistinguishable from a fresh one, and never fabricate a reason it disappeared.
- **Single-item refresh.** When the command includes `item:{item_key}`, only regenerate and upsert that one row via `api/items/upsert` (not `batch-upsert`) — same partial-failure and drift handling as above, scoped to the one item.

### Action Items exception

As of the PR #57–#59 architecture, only the **New** subsection is Postgres-backed (`is_new: true` items). Overdue, Due Next 7 Days, and No Due Date are always pulled live from Asana at render time and are never stored. A section-level refresh of Action Items therefore only has real work to do on the New subsection: re-run the Asana search/create step described in `references/item-sync.md` for that subsection only, and batch-upsert just those rows. Re-running it can pick up genuinely new action items that weren't part of the original run (e.g. from a meeting that just ended) — that's expected and desirable, not a bug, and does not touch or duplicate any task already represented by an existing `action-{asana_gid}` item. Do not attempt to batch-upsert Overdue/Due/No Due Date rows on a refresh — there is nothing to write for them; the viewer already re-queries Asana live on every page load.
