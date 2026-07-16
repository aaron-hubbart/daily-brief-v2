# Post-Meeting Patch Runs

This is not part of the normal daily-brief trigger path. Read this file only when `meeting-manager`'s post-meeting agent finishes processing a meeting that appears in **today's most recent brief** as a Section 1 Part A item carrying the "not found — needs input" badge (recording/transcript/summary was missing at brief-generation time). It should patch that item instead of waiting for the next scheduled brief run.

This is a lightweight update to the existing file, not a fresh brief:

1. **Locate the source file.** List files in `BRIEF_OUTPUT_FOLDER_ID` matching `Daily Brief_<today's date>_*.html` and take the one with the latest `hh-mm` in the filename — the filename's own timestamp is the reliable ordering signal, not Drive's modified-time metadata.
2. **Download and parse.** Pull the file content and find the `.item[data-id]` block whose title text matches the meeting (account/topic + time). Match on visible title text, not `data-id` — `data-id` values are only unique within a single file, not stable across regenerations or patch runs.
3. **Patch that block only:**
   - Remove the `bbad` "not found — needs input" badge.
   - Replace the subtitle line with a one-line outcome describing what was processed (e.g. "Meeting processed — 3 action items logged to Asana").
   - Swap the button row: drop the `claude://` "Post-meeting in Claude" deep link (no longer relevant), keep or update the Asana link to point at the real follow-up task(s), and add any other real link that now exists (Drive doc, Slack recap permalink). Never leave a placeholder `#`.
   - Leave everything else untouched: other items, `data-id` values, the `TOTAL` count, the header, and all unrelated sections.
4. **If no matching item is found** — brief already regenerated, meeting wasn't flagged, etc. — stop silently. Do not fabricate an item and do not error loudly; just note it once in the post-meeting completion summary.
5. **Save as a new timestamped file, not an overwrite:** `Daily Brief_YYYY-MM-DD_hh-mm.html` using the current time, same folder. This follows the multi-run convention above rather than working around it — there is no Drive delete/update tool available for this to use, and none is needed, since the viewer already lets a person pick between same-day runs and checkbox state is keyed by date only (see the localStorage key note in `references/html-output.md`), so nothing is lost by producing a new file instead of replacing the old one.
6. **Don't reproduce brief content in chat.** The post-meeting completion summary gets one line noting the patch happened, plus the Drive link — same rule as a normal brief run.

This lets a person who just ran post-meeting processing see the update by refreshing the local viewer and selecting the newest timestamp for today, without waiting for the next full brief.
