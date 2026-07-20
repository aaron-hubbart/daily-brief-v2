# Post-Meeting Patch Runs

This is not part of the normal daily-brief trigger path. Read this file only when `meeting-manager`'s post-meeting agent finishes processing a meeting that appears in **today's most recent brief** as a Yesterday's Meetings item carrying the "not found — needs input" badge (recording/transcript/summary was missing at brief-generation time). It should patch that item instead of waiting for the next scheduled brief run.

This is a single-item upsert, not a fresh brief and not a file operation — there is nothing to locate, download, or parse.

1. **Determine `brief_date`.** Use today's local date per the Timezone Resolution logic in `SKILL.md` — Yesterday's Meetings items live under the brief_day row for the day the brief itself ran (today), not the day the meeting occurred.
2. **Recompute `item_key`.** `ym-{HHmm}-{slug(title)}`, using the same meeting title and time that produced this item's key when the brief originally generated it (see `references/item-sync.md`). This is deterministic — no need to look anything up first.
3. **Build the updated item body:**
   - Drop `badge` (the "not found — needs input" badge no longer applies).
   - `subtitle`: a one-line outcome describing what was processed (e.g. "Meeting processed — 3 action items logged to Asana").
   - `links`: drop the `claude://` "Post-meeting in Claude" deep link (no longer relevant), keep or update the Asana link to point at the real follow-up task(s), and add any other real link that now exists (Drive doc, Slack recap permalink). Never leave a placeholder.
   - `checked: false` — unchanged from generation; checkbox state is client-side in the viewer, not something this flow manages.
   - Everything else about the item (`section: yesterday-meetings`, `item_type: checkable`, `title`) stays as it was.
4. **Upsert.** `POST $DAILY_BRIEF_API_BASE_URL/api/items/upsert` with the body above, per `references/item-sync.md`. This updates the existing row in place — no other item, section, or brief_day is touched.
5. **If the recomputed `item_key` doesn't correspond to anything meaningful** (e.g. the brief already regenerated with different meetings, or this meeting was never flagged) — the upsert will simply create a new row rather than update one. That's harmless but not useful; if there's a clear signal beforehand that the brief already moved on (e.g. it's a new calendar day), stop and note it once in the post-meeting completion summary instead of upserting.
6. **Don't reproduce brief content in chat.** The post-meeting completion summary gets one line noting the patch happened, plus a link to `$DAILY_BRIEF_API_BASE_URL/brief/{brief_date}` — same rule as a normal brief run.

This lets a person who just ran post-meeting processing see the update by reloading the hosted viewer, without waiting for the next full brief.
