# Section Refresh Runs

Not part of the normal brief trigger. Read this file when a Customer Update or Manager Update card's Refresh button is clicked (arrives as a new chat message via the `claude://` deep link — see `references/item-sync.md`, Customer Updates / Manager Update) or when the user directly types an equivalent request: "refresh the AcmeFin update," "regenerate manager update," "the Zebra Financial card is stale, redo it." This patches one card via a single-item upsert. It does not run a full brief and does not touch any other card, section, or item.

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
