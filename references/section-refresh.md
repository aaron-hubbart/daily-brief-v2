# Section Refresh Runs

Not part of the normal brief trigger. Read this file when a Customer Update or Manager Update card's Refresh button is clicked (arrives as a new chat message via the `claude://` deep link — see `references/html-output.md`, items 6/7) or when the user directly types an equivalent request: "refresh the AcmeFin update," "regenerate manager update," "the Zebra Financial card is stale, redo it." This patches one card into the latest existing brief file. It does not run a full brief and does not touch any other card, section, or item.

## Trigger phrases

`/daily-brief Refresh customer update for {Account Name}` and `/daily-brief Refresh manager update` are the exact strings the Refresh buttons send. Recognize close variations typed directly by the user the same way — match on account name (or "manager") plus a refresh/regenerate/redo verb.

## Steps

1. **Identify the target.** One customer account by name, or the manager update. If the account name doesn't match anything in `Meeting Manager Config.xlsx` closely enough to be confident, ask which account rather than guessing.
2. **Locate the source file.** List files in `BRIEF_OUTPUT_FOLDER_ID` matching `Daily Brief_<today's date>_*.html` and take the one with the latest `hh-mm` in the filename — same rule as `references/post-meeting-patch.md`, since this is the same "find today's most recent file" problem.
3. **Download and parse.** Pull the file content. Find `<details data-section="customer-updates">` and within it the `<details data-id="cust-update-{slug}">` node for the target account (or `<details data-section="manager-update" data-id="mgr-update">` directly for the manager target — that node carries both attributes). Compute `{slug}` from the account name using the same lowercase-hyphenate rule as generation. If the node isn't found, stop and tell the user the card wasn't in the latest file rather than fabricating one.
4. **Regenerate just that entry.** Run the Section 3 (or Section 4) generation process from `references/status-updates.md` for this one account/manager only — full Slack search and synthesis for that entry, nothing else. This is the only step in this flow that costs a real data-source call; every other account's Slack search is skipped entirely.
5. **Update the cache.** Write the new `content` and `generated_at` (now) into that one entry in `STATUS_UPDATE_CACHE_FILE_ID`. Leave every other entry — every other account, and the manager entry if this was a customer refresh — byte-for-byte untouched.
6. **Splice into the file.** Replace the target `<details>` node's `outerHTML` with the newly generated card markup (same shape as a freshly generated card: badge, textarea, channel field, buttons — see `references/html-output.md` items 6/7). Leave every other section, every other card, the header, `TOTAL`, and all other `data-id` values exactly as they were in the source file. This is a full-document string operation (parse, replace one node, reserialize), not a re-render of the whole file from scratch — the risk of a re-render is subtly drifting other sections' content even when that isn't intended.
7. **Save as a new timestamped file, not an overwrite:** `Daily Brief_YYYY-MM-DD_hh-mm.html` using the current time, same folder — no Drive update-by-fileId capability exists, and none is needed, per the same reasoning as `references/post-meeting-patch.md`.
8. **Respond briefly.** One line confirming which card refreshed, plus the Drive link. Don't reproduce the new card's content in chat — the person can read it in the file, same rule as a normal brief run.

If the Refresh click arrives when today's most recent file is quite old (earlier in the day, well before the current moment) that's expected and fine — this flow only ever touches the one card, so staleness elsewhere in that file is not this flow's concern.
