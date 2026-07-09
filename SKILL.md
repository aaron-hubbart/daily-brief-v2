---
name: daily-brief
version: 2.0.0
description: >
  Generates a personalized daily briefing for Aaron Hubbart, Senior TAM at Camunda.
  Pulls from all available data sources: Outlook calendar, Outlook email, Slack (DMs,
  account channels, tiger team channels, direct mentions), Zoom meeting summaries,
  and Asana tasks. Produces a standalone interactive HTML file saved to Google Drive
  under the configured folder, and presents a Drive link in chat.

  Trigger on any of these phrases or clear variations: "daily brief", "morning brief",
  "evening brief", "brief me", "what's my day look like", "catch me up", "day ahead",
  "what happened today", "end of day summary", "start of day", "eod brief", "sod brief",
  "what do I have today", "what's on my plate", "run my brief", "give me my brief".
  Also trigger when the user says something like "brief" with no other context, or
  asks to be caught up on the day, communications, or schedule.

  Do NOT require the user to specify morning vs. evening — infer from context or current
  time. Always run the brief without asking for confirmation first.
---

# Daily Brief Skill

---

## Configuration

```
gdrive_folder_id:  1h6AGEIHGLTAFM_6OB17_K4zl3HoLJ1uT
gdrive_folder_path: Claude Outputs/Daily Briefs
```

To change the output folder, tell Claude: "Update my daily brief folder to [new name or Drive URL]."
Claude will find or create the folder, update this config block, and confirm.

The folder ID above was created on 2026-07-09 and points to:
https://drive.google.com/drive/folders/1h6AGEIHGLTAFM_6OB17_K4zl3HoLJ1uT

---

## Purpose

Produce a standalone interactive HTML brief that:
- Covers a recap of the previous/current day and a forward look at the day ahead
- Is named `Daily Brief_YYYY-MM-DD.html` matching the brief date
- Is uploaded to Google Drive in the configured folder
- Works as a self-contained file (no external dependencies, no server required)
- Supports persistent checkboxes via localStorage, dark mode, and clickable links throughout

The brief is always split into two sections: **Yesterday / Today So Far** and **Today / Tomorrow**.

---

## Timing Logic

Infer the user's intent from the current time and any contextual cues:

- Before noon: assume **morning brief** — recap yesterday, plan today
- After noon but before 5pm: assume **midday check-in** — recap today so far, plan remainder + tomorrow
- After 5pm: assume **evening brief** — recap today, plan tomorrow
- If the user specifies morning/evening explicitly, honor that regardless of time

State the timing assumption once in chat before starting (e.g., "Morning brief for Thursday, July 9") then proceed without further commentary.

---

## Data Sources and What to Pull

Run all data pulls in parallel where possible. Use the time windows below.

### Outlook Calendar (Microsoft 365: outlook_calendar_search)
- Recap window: yesterday (or today so far if midday/evening)
- Ahead window: today (morning) or tomorrow (evening)
- Pull all events in the window: title, time, attendees, location/link
- Extract Zoom join URLs from event body/location for direct linking in the brief
- Convert all times from UTC to CDT (UTC-5 in summer, UTC-6 in winter)
- Flag tentative events, Webex meetings (no transcript available), and back-to-back blocks

### Outlook Email (Microsoft 365: outlook_email_search)
- Recap window: emails received since EOD yesterday (or past 24 hours)
- Focus on: unread, flagged, or emails from key contacts
- Key contacts: Rodrigo Scaldaferri, Micah De Boer, David Paroulek, Colin Teubner, and any contact at AcmeFin, Zebra Financial, Umbrella Financial, Initech Financial, Acme Health, Zebra Health
- Summarize threads, not individual messages — group by sender/topic
- Surface anything needing a response as an action item

### Slack (Slack: slack_search_public_and_private)
Run multiple targeted searches:
1. Direct mentions: `<@U0A0ZRB4JM8>`
2. DMs: channel_types=im, recent messages
3. Account channels: AcmeFin, Zebra Financial, Umbrella Financial, Initech Financial, Acme Health, Zebra Health
4. Tiger team / AI-First CS: `in:#prj-cs-ai-first`
5. Time-scope all searches to the recap window

Consolidate into the relevant brief sections. Surface only items that need attention or are informational — skip noise, bot messages, and automated notifications. Promote Slack items requiring action into the Action Items section of the HTML.

### Zoom (Zoom for Claude: search_meetings + get_meeting_assets)
- Search for meetings completed in the recap window
- Pull AI summary and next steps for each completed meeting
- If no summary is available, note the meeting occurred
- Only surface meetings that produced meaningful content (skip standups with no summary)

### Asana (Asana: get_status_overview with account keywords + search_tasks_preview)
- Pull incomplete tasks assigned to me, due today or overdue
- Group by: overdue, due today, due tomorrow (for evening brief)
- Include tasks with no due date only if they appear high priority from the name
- Use account keywords: "Acme Financial, Zebra Financial, Umbrella Financial, Initech Financial, Acme Health, Zebra Health, Umbrella Clinical Research, TAM" for get_status_overview

---

## Account and People Context

Aaron's primary accounts: Acme Financial, Zebra Financial, Umbrella Financial, Initech Financial, Acme Health, Zebra Health, Umbrella Clinical Research.
Key Camunda colleagues: Rodrigo Scaldaferri (AE), Micah De Boer (CS leadership), David Paroulek (Senior SA), John Kelleher (Senior Manager CS), Colin Teubner.
Tiger team: Liz Stevens, Daan, Alana Whipp (AI-First CS Tiger Team / #prj-cs-ai-first).

Use this context to prioritize: a Slack DM from Rodrigo about AcmeFin matters more than a general #announcements post. Customer-facing items surface above internal ones.

---

## Process

1. Read the configuration block above to get `gdrive_folder_id`.
2. Determine today's date and brief type (morning/midday/evening).
3. Pull all data sources in parallel (calendar, email, Slack, Zoom, Asana).
4. Organize data into three categories: **Schedule**, **Action Items**, and **FYI**.
5. Generate the complete HTML brief from the template below, substituting all placeholders with real data.
6. Write the file locally as `Daily Brief_YYYY-MM-DD.html` (date = the brief date, not necessarily today if running an evening brief for tomorrow).
7. Upload to Google Drive using `Google Drive:create_file`:
   - `title`: `Daily Brief_YYYY-MM-DD`
   - `parentId`: value of `gdrive_folder_id` from config
   - `contentMimeType`: `text/html`
   - `disableConversionToGoogleType`: `true`
   - `textContent`: the full HTML string
8. Return the Drive `viewUrl` in chat with one line of context (e.g., "Morning brief saved. 6 meetings, 4 action items.").

Do not reproduce the full brief content in chat. The file is the output. A single summary line + Drive link is sufficient.

---

## Error Handling

If a data source is unavailable, note it in the FYI section of the HTML brief and proceed with available data. Do not fail the whole brief because one source errored.

If Google Drive upload fails, fall back to presenting the HTML file as a downloadable artifact in chat and note the upload failure.

---

## HTML Template

Generate the brief using the structure below. All placeholders in `{{DOUBLE_BRACES}}` must be replaced with real data. Do not output literal placeholder text in the final file.

```
TEMPLATE VARIABLES:
  {{DATE_DISPLAY}}     — "Thursday, July 9, 2026"
  {{DATE_ISO}}         — "2026-07-09"
  {{BRIEF_TYPE}}       — "Morning brief" | "Midday check-in" | "Evening brief"
  {{TOTAL_ITEMS}}      — integer count of all checkable items (schedule + action)
  {{STORAGE_KEY}}      — "brief:{{DATE_ISO}}"
  {{SCHEDULE_ROWS}}    — HTML for schedule item rows (see Row Templates below)
  {{ACTION_ROWS}}      — HTML for action item rows
  {{FYI_ROWS}}         — HTML for FYI rows (no checkboxes)
```

### Full HTML Structure

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Brief · {{DATE_DISPLAY_SHORT}}</title>
<meta name="theme-color" content="#f7f6f3" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#17171a" media="(prefers-color-scheme: dark)">
<style>
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
html{font-size:14px;}
body{font-family:var(--font);background:var(--bg);color:var(--t1);line-height:1.5;-webkit-font-smoothing:antialiased;}
.wrap{max-width:520px;margin:0 auto;padding:1.5rem 1.25rem 3rem;}
.head{display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:1.5rem;padding-bottom:1rem;border-bottom:1.5px solid var(--border-strong);}
.head h1{font-size:19px;font-weight:600;letter-spacing:-.025em;}
.head .sub{font-size:12px;color:var(--t3);margin-top:1px;}
.prog-label{font-size:11px;font-weight:500;color:var(--t3);margin-bottom:5px;text-align:right;}
.prog-track{width:110px;height:3px;background:var(--border);border-radius:99px;overflow:hidden;margin-left:auto;}
.prog-fill{height:100%;background:var(--accent);border-radius:99px;transition:width .2s;width:0%;}
.section{margin-bottom:1.75rem;}
.sec-label{font-size:10px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--t3);margin-bottom:.5rem;}
.item{display:flex;align-items:flex-start;gap:8px;padding:9px 0;border-bottom:.5px solid var(--border);cursor:pointer;transition:opacity .15s;-webkit-user-select:none;user-select:none;}
.item:last-child{border-bottom:none;}
.item.done{opacity:var(--done);}
.item.done .ititle{text-decoration:line-through;}
.icb{padding-top:1px;flex-shrink:0;}
.icb input[type=checkbox]{width:15px;height:15px;cursor:pointer;accent-color:var(--accent);}
.itime{font-size:11px;color:var(--t3);font-family:var(--mono);width:60px;flex-shrink:0;padding-top:2px;}
.ibody{flex:1;min-width:0;}
.ititle{font-size:13px;font-weight:500;color:var(--t1);line-height:1.35;display:flex;flex-wrap:wrap;align-items:center;gap:4px;}
.isub{font-size:11.5px;color:var(--t2);margin-top:3px;line-height:1.45;}
.ilinks{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px;}
.badge{font-size:9.5px;font-weight:700;letter-spacing:.03em;padding:1px 5px;border-radius:3px;line-height:1.6;flex-shrink:0;}
.bwarn{background:var(--warn-bg);color:var(--warn-t);}
.bbad{background:var(--bad-bg);color:var(--bad-t);}
.lbtn{display:inline-flex;align-items:center;gap:3px;font-size:11px;font-weight:500;padding:3px 8px;border-radius:var(--r);text-decoration:none;border:.5px solid var(--border-strong);color:var(--t2);background:var(--surface);cursor:pointer;white-space:nowrap;transition:filter .1s;}
.lbtn:hover{filter:brightness(.95);}
.lbtn.primary{background:var(--accent-bg);border-color:var(--accent);color:var(--accent-t);}
.fyi-item{display:flex;gap:10px;padding:8px 0;border-bottom:.5px solid var(--border);}
.fyi-item:last-child{border-bottom:none;}
.fyi-dot{width:4px;height:4px;border-radius:50%;background:var(--t3);flex-shrink:0;margin-top:7px;}
.fyi-lbl{font-size:11px;font-weight:600;color:var(--t2);margin-bottom:2px;}
.fyi-txt{font-size:12px;color:var(--t2);line-height:1.45;}
.footer{margin-top:1.5rem;padding-top:1rem;border-top:.5px solid var(--border);display:flex;justify-content:space-between;align-items:center;}
.foot-note{font-size:11px;color:var(--t3);}
.reset-btn{font-size:11px;color:var(--t3);background:none;border:none;cursor:pointer;text-decoration:underline;text-underline-offset:2px;text-decoration-color:var(--border-strong);padding:0;}
.reset-btn:hover{color:var(--t2);}
</style>
</head>
<body>
<div class="wrap">
  <div class="head">
    <div>
      <h1>{{DATE_DISPLAY}}</h1>
      <div class="sub">{{BRIEF_TYPE}} &middot; Central time</div>
    </div>
    <div>
      <div class="prog-label" id="prog-label">0 of {{TOTAL_ITEMS}} done</div>
      <div class="prog-track"><div class="prog-fill" id="prog-fill"></div></div>
    </div>
  </div>

  <div class="section">
    <div class="sec-label">Schedule</div>
    {{SCHEDULE_ROWS}}
  </div>

  <div class="section">
    <div class="sec-label">Action items</div>
    {{ACTION_ROWS}}
  </div>

  <div class="section">
    <div class="sec-label">FYI</div>
    {{FYI_ROWS}}
  </div>

  <div class="footer">
    <span class="foot-note" id="saved-note"></span>
    <button class="reset-btn" onclick="resetAll()">Reset all</button>
  </div>
</div>
<script>
const KEY='{{STORAGE_KEY}}';const TOTAL={{TOTAL_ITEMS}};let state={};
function load(){try{const s=localStorage.getItem(KEY);if(s)state=JSON.parse(s);}catch(e){}apply();}
function save(){try{localStorage.setItem(KEY,JSON.stringify(state));const n=document.getElementById('saved-note');if(n){n.textContent='Saved';setTimeout(()=>{n.textContent='';},1500);}}catch(e){}}
function toggle(id){state[id]=!state[id];save();apply();}
function apply(){document.querySelectorAll('.item[data-id]').forEach(el=>{const id=el.dataset.id;const cb=el.querySelector('input[type=checkbox]');const on=!!state[id];el.classList.toggle('done',on);if(cb)cb.checked=on;});const done=Object.values(state).filter(Boolean).length;const pct=Math.round(done/TOTAL*100);const lbl=document.getElementById('prog-label');const fill=document.getElementById('prog-fill');if(lbl)lbl.textContent=done+' of '+TOTAL+' done';if(fill)fill.style.width=pct+'%';}
function resetAll(){if(!confirm('Reset all checkboxes?'))return;state={};save();apply();}
document.querySelectorAll('.item[data-id]').forEach(el=>{const id=el.dataset.id;el.addEventListener('click',e=>{if(e.target.closest('a'))return;toggle(id);});const cb=el.querySelector('input[type=checkbox]');if(cb)cb.addEventListener('change',e=>{e.stopPropagation();toggle(id);});});
load();
</script>
</body>
</html>
```

---

### Row Templates

Use these snippets to build `{{SCHEDULE_ROWS}}`, `{{ACTION_ROWS}}`, and `{{FYI_ROWS}}`.

**Schedule item with Zoom link (item IDs: s1, s2, s3, ...):**
```html
<div class="item" data-id="s1">
  <div class="icb"><input type="checkbox"></div>
  <div class="itime">10:30a</div>
  <div class="ibody">
    <div class="ititle">Meeting Title <span class="badge bwarn">tentative</span></div>
    <div class="isub">25 min &middot; Attendees &middot; Any context note</div>
    <div class="ilinks">
      <a class="lbtn primary" href="ZOOM_URL" target="_blank">Join Zoom &nearr;</a>
      <a class="lbtn" href="ASANA_OR_OTHER_URL" target="_blank">Open in Asana &nearr;</a>
    </div>
  </div>
</div>
```

Available badge classes: `bwarn` (tentative/warning), `bbad` (overdue/urgent).
Use `.lbtn.primary` for the primary action link (Zoom join), `.lbtn` for secondary links.
Omit `<div class="ilinks">` entirely if there are no links.
Omit `<div class="itime">` for action items (they have no time).

**FYI item (no checkbox, IDs not needed):**
```html
<div class="fyi-item">
  <div class="fyi-dot"></div>
  <div>
    <div class="fyi-lbl">Source or topic &middot; brief descriptor</div>
    <div class="fyi-txt">One to two sentences of context. No action required.</div>
  </div>
</div>
```

---

## Output in Chat

After uploading, respond in chat with exactly this pattern:

```
{{BRIEF_TYPE}} saved — {{DATE_DISPLAY}}.
[N meetings · N action items]
[Drive link]
```

Example:
```
Morning brief saved — Thursday, July 9.
6 meetings · 6 action items
https://drive.google.com/file/d/FILE_ID/view
```

No other prose. The file is the brief.

---

## Tone

Content inside the brief: peer-level, direct, no filler. The `isub` text under each item should read like a prepared colleague wrote it, not a dashboard widget. Attendee lists are comma-separated first names where unambiguous, full names otherwise.
