# Post-Meeting Patch Runs

This is not part of the normal daily-brief trigger path. Read this file only when `meeting-manager`'s post-meeting agent finishes processing a meeting that appears in **today's most recent brief** as a Yesterday's Meetings item carrying the "not found — needs input" badge (recording/transcript/summary was missing at brief-generation time). It should patch that item instead of waiting for the next scheduled brief run.

This is a single-item patch to `meetings.json`, not a fresh brief run — there is nothing to locate, download, or parse beyond the read-merge-rewrite in Step 4 below.

1. **Determine `brief_date`.** Use today's local date per the Timezone Resolution logic in `SKILL.md` — Yesterday's Meetings items live under the brief_date for the day the brief itself ran (today), not the day the meeting occurred.
2. **Recompute `item_key`.** `ym-{HHmm}-{slug(title)}`, using the same meeting title and time that produced this item's key when the brief originally generated it (see `references/item-sync.md`). This is deterministic — no need to look anything up first.
3. **Build the updated item body:**
   - Drop `badge` (the "not found — needs input" badge no longer applies).
   - `subtitle`: a one-line outcome describing what was processed (e.g. "Meeting processed — 3 action items logged to Asana").
   - `links`: drop the `claude://` "Post-meeting in Claude" deep link (no longer relevant), keep or update the Asana link to point at the real follow-up task(s), and add any other real link that now exists (Drive doc, Slack recap permalink). Never leave a placeholder.
   - `checked: false` — unchanged from generation; checkbox state is client-side in the viewer, not something this flow manages.
   - Everything else about the item (`section: yesterday-meetings`, `item_type: checkable`, `title`) stays as it was.
4. **Read, merge, rewrite `meetings.json`.** Read the current `/briefs/{brief_date}/meetings.json` (the newest version, per references/item-sync.md — if this skill's memory of that day's brief run already has it in context from generating the brief, use that rather than re-reading). Find the entry whose `item_key` matches the one recomputed in Step 2, replace it with the updated item body from Step 3, and write the complete array (every other item unchanged, byte-for-byte) back to `/briefs/{brief_date}/meetings.json` via `Google Drive: create_file`. This creates a new version of the whole file — the webapp always reads the newest-by-creation-time version, so this supersedes the version written at brief-generation time. No other section file is touched.
5. **If the recomputed `item_key` doesn't correspond to anything meaningful** (e.g. the brief already regenerated with different meetings, or this meeting was never flagged) — there's no matching entry to replace in `meetings.json`'s array — don't append a new, unrelated entry to the array in that case (unlike an upsert, a straight append here would be a real, visible extra item, not a harmless no-op row). If there's a clear signal beforehand that the brief already moved on (a new calendar day, or a re-check of the current `meetings.json` shows no `item_key` match), stop and note it once in the post-meeting completion summary instead of writing anything.
6. **Don't reproduce brief content in chat.** The post-meeting completion summary gets one line noting the patch happened; note that the patch is reflected in the hosted viewer on next page load, without needing to construct or share a direct link — same rule as a normal brief run.

This lets a person who just ran post-meeting processing see the update by reloading the hosted viewer, without waiting for the next full brief.
