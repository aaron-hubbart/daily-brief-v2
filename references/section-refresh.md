# Section Refresh Runs

Not part of the normal brief trigger. Read this file whenever any viewer Refresh button is clicked (arrives as a new chat message via the `claude://` deep link) or the user directly types an equivalent request. Two flavors, covered in order below: a single Customer Update / Manager Update card (`/daily-brief Refresh customer update for {Account Name}` / `/daily-brief Refresh manager update`), or a whole section's Refresh button (`/daily-brief Refresh {Section Label}`, covered further down). Neither flavor runs a full brief or touches anything outside its own target.

## Trigger phrases

`/daily-brief Refresh customer update for {Account Name}` and `/daily-brief Refresh manager update` are the exact strings the Refresh buttons send. Recognize close variations typed directly by the user the same way — match on account name (or "manager") plus a refresh/regenerate/redo verb.

## Steps

1. **Identify the target.** One customer account by name, or the manager update. If the account name doesn't match anything in `Meeting Manager Config.xlsx` closely enough to be confident, ask which account rather than guessing.
2. **Determine `brief_date`.** Use today's local date per the Timezone Resolution logic in `SKILL.md` — Customer Update and Manager Update items live under today's brief_day row regardless of when they were last generated or refreshed.
3. **Regenerate just that entry.** Run the Section 3 (or Section 4) generation process from `references/status-updates.md` for this one account/manager only — full Slack search and synthesis for that entry, nothing else. This is the only step in this flow that costs a real data-source call; every other account's Slack search is skipped entirely.
4. **Update the cache.** Write the new `content` and `generated_at` (now) into that one entry in `STATUS_UPDATE_CACHE_FILE_ID`. Leave every other entry — every other account, and the manager entry if this was a customer refresh — byte-for-byte untouched.
5. **Upsert the item.** `POST $DAILY_BRIEF_API_BASE_URL/api/items/upsert` (per `references/item-sync.md`) with:
   - Customer account: `section: customer-updates`, `item_key: cust-update-{slug}`, `item_type: card`, `content: {"textarea": "<new update>", "channel_id": "<from config>", "last_posted_at": "<now>"}`.
   - Manager update: `section: manager-update`, `item_key: mgr-update`, `item_type: text-block`, `content: {"textarea": "<new update>"}`.
   This updates the one existing row in place — every other item, card, and section is untouched by definition, since each is its own row.
6. **Respond briefly.** One line confirming which card refreshed, plus a link to `$DAILY_BRIEF_API_BASE_URL/brief/{brief_date}`. Don't reproduce the new card's content in chat — the person can read it in the viewer, same rule as a normal brief run.

If the Refresh click arrives well after the day's brief was first generated, that's expected and fine — this flow only ever touches the one card, so staleness elsewhere is not this flow's concern.

## Section-level refresh (the other five sections)

The viewer's other five sections (Yesterday's Meetings, Account / Initiative Recap, Today, Action Items, FYI) each have their own section-header Refresh button. Read this part when one of those arrives as `/daily-brief Refresh {Section Label}` via the `claude://` deep link, or an equivalent typed request: "refresh today," "redo action items," "the yesterday's meetings section is stale, rerun it."

This is a whole-section regeneration, not a single-item patch — there's no per-account cache involved here (that's specific to Customer Updates/Manager Update), so it always does a fresh pull.

### Trigger phrases

`/daily-brief Refresh {label}` where `{label}` is one of: `Yesterday's Meetings`, `Account / Initiative Recap`, `Today`, `Action Items`, `FYI` — the exact labels the buttons send. Match close variations the same way as above.

### Steps

1. **Identify the target section** from the five slugs above.
2. **Determine `brief_date`** the same way as a normal run (today's local date per Timezone Resolution in `SKILL.md`).
3. **Re-run that section's normal data pull and generation logic only** — the same source calls and item shape described in `references/item-sync.md`'s per-section notes for that slug (e.g. Outlook + Zoom + Asana for Yesterday's Meetings, Asana search/create for Action Items). Skip every other section's data sources entirely; this is the whole point of a section-level refresh over a full brief run.
4. **Batch-upsert only this section's items.** `POST $DAILY_BRIEF_API_BASE_URL/api/items/batch-upsert` with `brief_date` and an `items` array containing only entries for the refreshed section, using the same `item_key` conventions from `references/item-sync.md` so existing rows are updated in place rather than duplicated. Items in every other section are untouched by definition, since each row is addressed by its own `(section, item_key)`.
5. **Respond briefly.** One line confirming which section refreshed, plus a link to `$DAILY_BRIEF_API_BASE_URL/brief/{brief_date}`. Same no-reproduction rule as a normal brief run and the card-level refresh above.

A caveat worth naming for **Action Items** specifically: re-running its Asana search/create step could pick up genuinely new action items that weren't part of the original run (e.g. from a meeting that just ended) — that's expected and desirable, not a bug. It does not touch or duplicate any task already represented by an existing `action-{asana_gid}` item.
