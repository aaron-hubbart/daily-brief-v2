# HTML Output Reference

Read this file when you reach HTML generation in a brief run. It is used on every run (the HTML file is always generated), but lives here rather than in `SKILL.md` so the core skill file stays short for the trigger/timing/data-pull decisions that happen before HTML generation starts.

Every brief run produces a standalone interactive HTML file in addition to the in-chat response. The file is self-contained (no external dependencies), works offline, and persists checkbox state in `localStorage` so it can be referenced throughout the day.

### When to generate

Generate the HTML file on every brief run. Name the file: `Daily Brief_YYYY-MM-DD_hh-mm.html` using the local date and 24-hour local time (zero-padded, hyphen-separated) at the moment the file is generated — e.g. `Daily Brief_2026-07-14_08-42.html`.

### HTML structure

The file has eight sections, in order. This list is the canonical, version-controlled definition of the HTML file — if the in-chat Output Format section (`SKILL.md` Section 1/2) and this list ever seem to imply different HTML content, this list wins for what actually gets generated in the file.

1. **Header** — date, brief type (Morning / Midday / Evening), timezone label, progress counter ("N of N done"), progress bar
2. **Yesterday's Meetings** — one checkable item per meeting from the last business day (Section 1, Part A). Each item shows title, time, attendees, a recording/transcript link if `get_meeting_assets` found one, and an Asana action-item status line (logged / not found, per the run-log-then-Asana-search check). If no recording/transcript was found, the item's subtitle asks directly for a link or transcript, and the item stays unchecked until that's resolved — this is a real to-do, not just informational, so it belongs here checkable rather than in FYI. Use `data-id="ym-N"` (1-indexed).
3. **Account / Initiative Recap** (Section 1, Part B) — this is its own HTML section, distinct from Yesterday's Meetings above, and must appear in every generated file; it is not optional narrative that only shows up in the chat response. One checkable item per account or internal initiative, ordered per the priority rule in Part B (active-signal accounts first, then internal initiatives, then the mandatory "General / Admin" catch-all). Item title is the account/initiative name; item subtitle is the synthesized narrative paragraph for that account (calendar + email + Slack + Zoom, consolidated — never a source-by-source list). Include a link button only when a specific source link is directly relevant to the recap (e.g. an email thread referenced in the narrative); most recap items have no badges and no links, since this section is about narrative content, not processing status or action tracking. Use `data-id="recap-N"` (1-indexed).
4. **Today** (renamed from "Schedule" — every meeting for the full current day, past or future, per the calendar-pull rule above) — checkable item per meeting with time, title, attendees, a Join link if a Zoom/Webex/Teams URL is present, and a meeting-prep output link. Append " (occurred)" to the item title for any meeting whose end time has already passed at the moment the brief runs, so a same-day full-calendar list makes clear at a glance which entries are past vs. upcoming. A meeting qualifies for a prep link if it has attendees beyond the user (personal reminders and solo admin blocks don't). For an upcoming qualifying meeting: check whether meeting-prep already exists (via the meeting-manager skill's routing table / per-account Drive folder); if it does, link to it; if not, run the meeting-manager skill's pre-meeting flow for that meeting as part of this brief, then link to the newly generated doc. For a qualifying meeting that has already occurred today by the time the brief runs, don't run pre-meeting prep after the fact — treat it like a Part A entry instead (recording/transcript + Asana status), since "prep" for a meeting that's already over doesn't make sense. Use `data-id="today-N"` (1-indexed).
5. **Action Items** — every task that needs action today: overdue Asana tasks, email threads needing a reply, Slack items flagged for response, meeting manager runs needed. Each item is checkable and has a one-line subtitle. **Include a link button whenever a real URL exists for that item** — the Asana task permalink (`https://app.asana.com/0/0/{gid}/f`), the Slack message permalink (construct as `https://{workspace}.slack.com/archives/{channel_id}/p{ts_without_dot}` if not returned directly by the search/read call), the Zoom meeting summary doc URL, or a mailto/webLink for an email thread. This is not optional decoration — it's the difference between a checklist and something the user can actually act on with one click. Only omit the link button when no real URL exists for that item (never use a placeholder `#`). Use `data-id="action-N"` (0-indexed, matching the existing example).

**Every action item must resolve to a real Asana task, created automatically if one doesn't already exist.** Before generating this section, collect the full list of action items needing a new task, then create them in a single `Asana:create_tasks` call (it accepts 1-50 tasks per call) rather than one call per item. For each item: search Asana first for an existing matching task (by text, scoped to the relevant account project if known); only include items with no existing match in the batch create call. Use `assignee: "me"`, `due_on` today, `project_id` set to the account's Asana Project GID from `Meeting Manager Config.xlsx` when known, and notes summarizing the context and any source link. If the account has no configured project GID (blank in the config sheet), omit `project_id` and let it land in My Tasks rather than blocking — don't treat a missing project mapping as a reason to skip creating the task. Always link the Asana permalink returned by the creation/search call — never a placeholder. This means there is no client-side "add to Asana" button anywhere in this skill; the task is guaranteed to exist by the time the person sees the brief.

**For action items where meeting-manager applies** (post-meeting processing needed, most commonly triggered by a missing recording/transcript from Section 1 Part A), add a second link button using the same `claude://` deep-link pattern the viewer already uses for Today items: `href="claude://claude.ai/new?q=" + encodeURIComponent('/meeting-manager Run post-meeting notes for: ' + meetingTitle + ' (' + dateOrTime + ')')`. This opens Claude Desktop with the prompt pre-filled so the person can paste a recording link or transcript directly into that conversation. Only add this button when meeting-manager genuinely applies — most action items (a Slack thread to review, a ticket to check) don't map to any specific skill, and a button with nowhere useful to go is worse than no button. Note in the brief output that this button requires Claude Desktop registered as the `claude://` protocol handler; it won't do anything in a browser-only viewing context.
5. **FYI** — non-actionable signals worth knowing: post-meeting summaries generated, recurring tasks spawned, informational Slack threads, status summary highlights. **Include a link button whenever a real URL exists**, same standard as Action Items — the Zoom meeting summary doc or recording URL, the Slack thread/message permalink (construct as `https://{workspace}.slack.com/archives/{channel_id}/p{ts_without_dot}` if not returned directly), a calendar event's `webLink`, or an Asana task permalink for a spawned recurring task. Nothing actionable is expected here, but "worth knowing" should still be one click from "worth reading in full" — don't make the user go dig for the source. Only omit the link when no real URL exists for that item. Use `data-id="fyi-N"` (1-indexed).
6. **Customer Updates** — collapsed by default, one outer `<details>` labeled "Expand — N assigned accounts", containing one nested `<details class="acct-card">` per assigned account (Section 3). Each card's summary line shows the account name and a badge with the last-known-update timestamp (or "no previous update found"). Each card body has an editable textarea pre-populated with the generated update, a read-only channel field, and a "Post to Slack" button. These are `<details>` elements, not `.item` blocks — they have no checkbox and do not count toward `TOTAL`. **The content of these cards is subject to the caching rule in `references/status-updates.md` — see that file before regenerating this section's content.**
7. **Manager / Leadership Update** — collapsed by default, single outer `<details>` (summary: "Expand — " plus the last-known-update badge) containing one editable textarea (Section 4), a "Post to Manager" button. Also a `<details>` element, not a `.item` block — no checkbox, not counted in `TOTAL`. **Same caching rule as Customer Updates — see `references/status-updates.md`.**

### CSS design system

Use exactly the CSS from the existing example (reproduced below). Do not deviate from the design tokens, class names, or layout. The only dynamic changes are content and the `data-id` / `TOTAL` values in the script.

```css
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg:#f5f4f1; --surface:#fff; --border:#e2e0d8; --border-strong:#c8c6bc;
  --t1:#1a1916; --t2:#5a5850; --t3:#9a9890;
  --accent:#1a5ca0; --accent-bg:#eef3fb; --accent-t:#1a5ca0;
  --warn-bg:#fdf5e6; --warn-t:#7a5000;
  --bad-bg:#fef1f0; --bad-t:#b02520;
  --done:.35; --font:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
  --mono:ui-monospace,"SF Mono","Cascadia Code",monospace; --r:5px;
}
@media(prefers-color-scheme:dark){:root{
  --bg:#18181b; --surface:#1e1e22; --border:#2c2c32; --border-strong:#3c3c44;
  --t1:#e6e4de; --t2:#9a9890; --t3:#5a5850;
  --accent:#5a9de0; --accent-bg:#0f2140; --accent-t:#6aade8;
  --warn-bg:#28200a; --warn-t:#e8a020; --bad-bg:#280e0e; --bad-t:#e06868;
}}
body { font-family: var(--font); background: var(--bg); color: var(--t1); padding: 24px 16px 60px; max-width: 1400px; margin: 0 auto; }
```

This `body` rule (font, background, color, padding, max-width, centering) sets `max-width: 1400px` explicitly so every run is consistent. Treat `example/Daily Brief_EXAMPLE.html` in the repo as the living reference implementation of this CSS and the overall markup shape; if the two ever disagree, update both in the same PR rather than letting them drift.

### Badge types

| Class | Use |
|-------|-----|
| `bwarn` | Tentative, needs confirmation, time-sensitive |
| `bbad` | Overdue, blocking, critical |
| Custom inline style using `--accent-bg`/`--accent-t` | Informational label (e.g., "hiring", "prep run") |

### Link buttons

Use `class="lbtn primary"` for the primary CTA (Join Zoom, Open doc). Use `class="lbtn"` for secondary links (Asana task, Slack thread, email). All `href` values must be real URLs from the data — never placeholder `#` values in actual output. The example file uses `#` only because it is a sanitized demo.

### localStorage key

Use `brief:YYYY-MM-DD` as the key — the calendar date only, not the filename. Multiple runs in the same day now produce distinct timestamped files (see filename convention above), but they should still share checkbox progress, so the storage key intentionally does not include the time component. The `TOTAL` constant in the script must equal the actual number of checkable items (`.item[data-id]` elements) in that specific brief.

### Sensitive data rules

The HTML file produced during a live brief run will contain real names, meeting titles, and links. That is correct for personal use. However:

- **Never commit a real brief to the GitHub repo.** The `example/` folder in the repo is for sanitized demo files only.
- The example file must use fictional names, companies, and placeholder `#` links.
- No real email addresses, Slack user IDs, Asana GIDs, Zoom meeting IDs, or calendar event IDs may appear in any committed file.
- Customer names in examples must be fictional (e.g., "Acme Financial", "Pinnacle Health", "Meridian Bank") — never real account names.

### Delivering the file

Write the HTML to a local file first (needed anyway to present it as a downloadable artifact in chat), then upload that same content to Google Drive folder `BRIEF_OUTPUT_FOLDER_ID` (value configured in the local copy's Admin Config block, not committed here) using `Google Drive: create_file` with `contentMimeType: text/html` and `disableConversionToGoogleType: true`.

Use the `textContent` parameter, not `base64Content`. This file is plain text — base64-encoding it first only inflates the payload by roughly a third and adds an unnecessary encode/read-back pass before the upload call, which measurably slows the run for no benefit. Pass the HTML directly as `textContent`.

Name the file `Daily Brief_YYYY-MM-DD_hh-mm.html`. Because the filename includes the run time, multiple runs on the same day naturally coexist as separate files — there is no overwrite step, and no need for one.

Also present the file as a downloadable artifact in chat so it is immediately accessible without opening Drive.
