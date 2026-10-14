"""Groups the Action Items list (brief-file items + live Asana pulls) into
the fixed due-date-based subsections used by the brief's Action Items
section and the standalone Tasks page. Pure logic — no Flask, no DB, no
network — so it's importable in tests without app.py's env-var
requirements (FLASK_SECRET_KEY, AZURE_TENANT_ID, etc.) or a live Postgres
connection. Moved out of app.py verbatim; see app.py's git history before
this change for the original inline version."""
from datetime import date, timedelta
from urllib.parse import quote

# Fixed order and labels for the Action Items subsections. "New Items"
# always renders first regardless of due date so a freshly created task
# doesn't get buried under overdue items from prior days.
ACTION_SUBSECTIONS = [
    {'slug': 'new', 'label': 'New Items'},
    {'slug': 'overdue', 'label': 'Overdue'},
    {'slug': 'due-today', 'label': 'Due Today'},
    {'slug': 'due-soon', 'label': 'Due Next 7 Days'},
    {'slug': 'no-due-date', 'label': 'No Due Date'},
]


# Matches app.py's own ASANA_ACTION_ITEM_PREFIX constant of the same name —
# duplicated rather than imported to keep this module Flask/env-free (see
# module docstring). Both must stay 'action-' per the item_key convention
# in references/item-sync.md.
ASANA_ACTION_ITEM_PREFIX = 'action-'


def task_intelligence_deep_links(task_title: str, task_gid: str):
    """Two claude:// deep-links attached to every Asana task item, same
    pattern as the meeting-manager links in references/item-sync.md: Method A
    (signal sync — look for updates) and Method B (per-task research) from
    the task-intelligence-sync skill, scoped to this one task by GID so it
    doesn't sweep the person's whole task list."""
    ref = f'{task_title} (GID: {task_gid})'
    prompts = [
        ('Check for updates', f'/task-intelligence-sync Run Method A (signal sync) for just this task — {ref}. Do not pull my full task list.'),
        ('Research', f'/task-intelligence-sync Run Method B (task triage/research) for: {ref}'),
    ]
    return [
        {
            'label': label,
            'url': 'claude://claude.ai/new?q=' + quote(prompt, safe=''),
            'class': 'lbtn',
        }
        for label, prompt in prompts
    ]


def _ensure_task_intelligence_links(item):
    """Backfills the two task_intelligence_deep_links onto an Action Item
    if they're not already there. Live-pulled items already have them (see
    app.py's _fetch_live_action_items), but brief-written "New Items" get
    their links from the daily-brief-generation skill's own output at
    content-generation time (references/item-sync.md) — this re-asserts
    them at render time instead, so a New Item made by an older skill
    version (or a run that just missed the instruction) still gets the
    buttons rather than silently lacking them until the brief regenerates.
    No-ops if both links are already present; mutates and returns item."""
    item_key = item.get('item_key', '')
    if not item_key.startswith(ASANA_ACTION_ITEM_PREFIX):
        return item
    existing_labels = {l.get('label') for l in (item.get('links') or [])}
    task_gid = item_key[len(ASANA_ACTION_ITEM_PREFIX):]
    missing = [
        link for link in task_intelligence_deep_links(item.get('title') or '', task_gid)
        if link['label'] not in existing_labels
    ]
    if missing:
        item['links'] = [*(item.get('links') or []), *missing]
    return item


def group_action_items(items, today_iso: str):
    """
    Splits the flat Action Items list into the fixed subsections the
    template renders. Membership is exclusive — an item lands in exactly
    one group, checked in this priority order:

      1. is_new  — content.is_new is true (this brief run created the
         Asana task itself; see references/item-sync.md). Takes priority
         over the date-based groups below so a brand-new overdue-looking
         task still shows up under "New Items", not "Overdue".
      2. overdue — content.due_on is set and before today.
      3. due-today — content.due_on is set and equal to today.
      4. due-soon — content.due_on is set and within the next 7 days
         (after today, up to and including 7 days out).
      5. no-due-date — everything else: no due_on at all, or a non-Asana
         action item with no natural date.

    Items are sorted by due_on ascending within groups 2-4; group 5
    keeps upstream display_order (already priority-ordered by the skill)
    since there's no date to sort on, and group 1 does the same.
    Returns a list of {slug, label, items} dicts, omitting empty groups —
    the template skips rendering a subsection header with nothing under it.
    """
    today = date.fromisoformat(today_iso)
    week_out = today + timedelta(days=7)
    buckets = {s['slug']: [] for s in ACTION_SUBSECTIONS}

    for item in items:
        _ensure_task_intelligence_links(item)
        content = item.get('content') or {}
        due_on = content.get('due_on')
        if content.get('is_new'):
            buckets['new'].append(item)
            continue
        if due_on:
            try:
                due_date = date.fromisoformat(due_on)
            except ValueError:
                due_date = None
        else:
            due_date = None
        if due_date is not None and due_date < today:
            buckets['overdue'].append(item)
        elif due_date is not None and due_date == today:
            buckets['due-today'].append(item)
        elif due_date is not None and due_date <= week_out:
            buckets['due-soon'].append(item)
        else:
            buckets['no-due-date'].append(item)

    for slug in ('overdue', 'due-today', 'due-soon'):
        buckets[slug].sort(key=lambda it: (it.get('content') or {}).get('due_on') or '')

    groups = [
        {**s, 'items': buckets[s['slug']]}
        for s in ACTION_SUBSECTIONS
        if buckets[s['slug']]
    ]

    # Every subsection is further split by board (Asana project name) so
    # items are visually grouped by account rather than rendering as one
    # undifferentiated list. "My Tasks" (content.project_name is null,
    # meaning no configured project GID for that account, or a non-Asana
    # action item) sorts last since it's the catch-all. Item order within
    # each board is preserved from the incoming list (display_order for
    # New-Item-shaped rows, due_on sort for date-bucketed rows, upstream
    # ordering for live-pulled ones).
    for group in groups:
        boards = {}
        for item in group['items']:
            board_name = (item.get('content') or {}).get('project_name') or 'My Tasks'
            boards.setdefault(board_name, []).append(item)
        group['boards'] = [
            {'name': name, 'items': boards[name]}
            for name in sorted(boards, key=lambda n: (n == 'My Tasks', n))
        ]

    return groups
