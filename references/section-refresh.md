# Section Refresh Runs

Not part of the normal brief trigger. Read this file whenever any viewer Refresh button is clicked (arrives as a new chat message via the `claude://` deep link) or the user directly types an equivalent request. Two flavors, covered in order below: a single Customer Update / Manager Update card, or a whole section's Refresh button (covered further down). Neither flavor runs a full brief or touches anything outside its own target.

## Trigger phrases and prompt format

The buttons send a structured command, not a bare label:

- Card-level: `/daily-brief Refresh customer update for {Account Name} date:{brief_date}` or `/daily-brief Refresh manager update date:{brief_date}`.
- Section-level: `/daily-brief Refresh section:{slug} date:{brief_date}`, where `{slug}` is one of `yesterday-meetings`, `account-recap`, `today`, `action-items`, `fyi` (matching the canonical slugs in `references/item-sync.md`).
- Single-item section refresh: `/daily-brief Refresh section:{slug} date:{brief_date} item:{item_key}` — narrower than a full section refresh, regenerates only that one item's entry. Not yet sent by any viewer button, but recognize it when typed or sent by a future per-item control.

`date:{brief_date}` is the date shown on the page the button was clicked from — always trust it over "today." This matters most when someone refreshes a section on an archived (non-today) brief; without the explicit date the skill would regenerate today's entry instead of the one on screen.

**Legacy fallback:** older cached HTML may still send the bare pre-upgrade form (`/daily-brief Refresh {Section Label}` with a human label, no `date:`). If no `date:` is present, fall back to resolving today's local date via the Timezone Resolution logic in `SKILL.md`, and match `{Section Label}` against the five section labels case-insensitively. Treat this path as deprecated — it only exists for links rendered before this update went out.

Recognize close variations typed directly by the user the same way — match on account name (or "manager") plus a refresh/regenerate/redo verb, or on a section slug/label plus the same.

## Card-level steps (Customer Update / Manager Update)

1. **Identify the target.** One customer account by name, or the manager update. If the account name doesn't match anything in `Meeting Manager Config.xlsx` closely enough to be confident, ask which account rather than guessing.
2. **Use `brief_date` from the command** (or the Timezone Resolution fallback above if absent). Customer Update and Manager Update items live under that date's files regardless of when they were last generated or refreshed.
3. **Regenerate just that entry.** Run the Section 3 (or Section 4) generation process from `references/status-updates.md` for this one account/manager only — full Slack search and synthesis for that entry, nothing else. This is the only step in this flow that costs a real data-source call; every other account's Slack search is skipped entirely.
4. **Update the cache.** Write the new `content` and `generated_at` (now) into that one entry in `STATUS_UPDATE_CACHE_FILE_ID`. Leave every other entry — every other account, and the manager entry if this was a customer refresh — byte-for-byte untouched.
5. **Write the card's file.** Customer account: write `/briefs/{brief_date}/updates/{slug}.json` (per `references/item-sync.md`) with `{"item_key": "cust-update-{slug}", "item_type": "card", "content": {"textarea": "<new update>", "channel_id": "<from account-config.json>", "last_posted_at": "<now>"}, ...}` via `Google Drive: create_file`. Manager update: write `/briefs/{brief_date}/manager-update.json` the same way, `{"item_key": "mgr-update", "item_type": "text-block", "content": {"textarea": "<new update>"}, ...}`. Both of these are one-file-per-item sections (per `references/item-sync.md`), so this write is a complete, self-contained replacement — no read-merge step needed, and every other item, card, and section is untouched by definition, since each lives in its own file.
6. **Respond briefly.** One line confirming which card refreshed; note that the refresh is reflected in the hosted viewer on next page load, without needing to construct or share a direct link. Don't reproduce the new card's content in chat — the person can read it in the viewer, same rule as a normal brief run.

If the Refresh click arrives well after the day's brief was first generated, that's expected and fine — this flow only ever touches the one card, so staleness elsewhere is not this flow's concern.

## Section-level refresh (the other five sections)

The viewer's other five sections (Yesterday's Meetings, Account / Initiative Recap, Today, Action Items, FYI) each have their own section-header Refresh button. This is a whole-section regeneration, not a single-item patch — there's no per-account cache involved here (that's specific to Customer Updates/Manager Update), so it always does a fresh pull.

### Steps

1. **Identify the target section** from `section:{slug}` (or the legacy label, per the fallback above).
2. **Use `brief_date`** from the command (or the Timezone Resolution fallback if absent).
3. **Re-run that section's normal data pull and generation logic only** — the same source calls and item shape described in `references/item-sync.md`'s per-section notes for that slug (e.g. Outlook + Zoom + Asana for Yesterday's Meetings, Asana search/create for Action Items — see the Action Items exception below). Skip every other section's data sources entirely; this is the whole point of a section-level refresh over a full brief run.
4. **Write the section's file.** For an array-shaped section (`meetings.json`, `today.json`, `action-items.json`, `fyi.json` — per `references/item-sync.md`), this is a full-section refresh, so write the complete regenerated array for that one file via `Google Drive: create_file` — unlike the single-item merge in `references/post-meeting-patch.md`, there's nothing to read-and-merge first, since every item in the section is being regenerated. For the one-file-per-account sections (`accounts/{slug}.json`), refreshing "a section" doesn't really apply the same way — Account/Initiative Recap is a whole-section refresh across every account/initiative subsection at once, so write each account's file that changed. Files for every other section (or, for `accounts/`, every other account) are untouched by definition, since each lives in its own path.
5. **Respond briefly.** One line confirming which section refreshed; note that the refresh is reflected in the hosted viewer on next page load, without needing to construct or share a direct link. Same no-reproduction rule as a normal brief run and the card-level refresh above. If step 3 hit partial failures, name them here (see below) rather than only reporting success.

### Partial run handling

A section-level refresh doesn't get to assume every item will regenerate cleanly. Handle these cases explicitly:

- **Partial data-source failure.** If some items in the section regenerate successfully and others error (an API timeout on one meeting's Zoom assets, one Asana search failing), read the section's current file first if one exists for that date (same conditional-read note as `references/item-sync.md` — skip the read if this is the first write of the day), replace only the items that regenerated successfully by matching `item_key` per the mechanic in `references/post-meeting-patch.md`, keep the prior version of any item that failed to regenerate rather than dropping it from the array, and write the complete array back via `Google Drive: create_file`. Report the specific failures by name in the chat response. Don't abort the whole refresh because one item in a multi-item section failed, and don't silently drop the failure from the response either.
- **Item count drift.** If the fresh pull returns fewer items than the section's current file has (a meeting got cancelled, a task got completed elsewhere), there's no way to delete just one entry from a file that's about to be fully rewritten anyway — but there's also no reason to invent one: since a full-section refresh writes the complete regenerated array, an item that no longer exists in the fresh pull simply isn't in the array you write, and it disappears from the section on next page load. This is different from `references/post-meeting-patch.md`'s single-item patch, which must explicitly preserve every item it isn't updating — a whole-section refresh doesn't have that constraint, since the whole array is authoritative. Never fabricate a reason an item disappeared; if it's worth calling out, note it once in the chat response.
- **Single-item refresh.** When the command includes `item:{item_key}`, only that one entry needs regenerating — apply the same read-current-array/replace-matching-item_key/write-complete-array mechanic `references/post-meeting-patch.md` describes, scoped to this section's file instead of `meetings.json`. Same partial-failure and drift handling as above.

### Action Items exception

As of the PR #57–#59 architecture, only the **New** subsection is written to `action-items.json` (`is_new: true` items) — see `references/item-sync.md`'s live-pull architecture note. Overdue, Due Next 7 Days, and No Due Date are always pulled live from Asana at render time and are never stored in a file. A section-level refresh of Action Items therefore only has real work to do on the New subsection: re-run the Asana search/create step described in `references/item-sync.md` for that subsection only, and write the regenerated New Items array to `/briefs/{brief_date}/action-items.json`. Re-running it can pick up genuinely new action items that weren't part of the original run (e.g. from a meeting that just ended) — that's expected and desirable, not a bug, and does not touch or duplicate any task already represented by an existing `action-{asana_gid}` item. Do not attempt to write Overdue/Due/No Due Date entries to `action-items.json` on a refresh — there is nothing to write for them; the viewer already re-queries Asana live on every page load.
