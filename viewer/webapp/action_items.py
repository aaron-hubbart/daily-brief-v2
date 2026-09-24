"""Groups the Action Items list (brief-file items + live Asana pulls) into
the fixed due-date-based subsections used by the brief's Action Items
section and the standalone Tasks page. Pure logic — no Flask, no DB, no
network — so it's importable in tests without app.py's env-var
requirements (FLASK_SECRET_KEY, AZURE_TENANT_ID, etc.) or a live Postgres
connection. Moved out of app.py verbatim; see app.py's git history before
this change for the original inline version."""
from datetime import date, timedelta

# Fixed order and labels for the Action Items subsections. "New Items"
# always renders first regardless of due date so a freshly created task
# doesn't get buried under overdue items from prior days.
ACTION_SUBSECTIONS = [
    {'slug': 'new', 'label': 'New Items'},
    {'slug': 'overdue', 'label': 'Overdue'},
    {'slug': 'due-soon', 'label': 'Due Next 7 Days'},
    {'slug': 'no-due-date', 'label': 'No Due Date'},
]


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
      3. due-soon — content.due_on is set and within the next 7 days
         (inclusive of today).
      4. no-due-date — everything else: no due_on at all, or a non-Asana
         action item with no natural date.

    Items are sorted by due_on ascending within groups 2 and 3; group 4
    keeps upstream display_order (already priority-ordered by the skill)
    since there's no date to sort on, and group 1 does the same.
    Returns a list of {slug, label, items} dicts, omitting empty groups —
    the template skips rendering a subsection header with nothing under it.
    """
    today = date.fromisoformat(today_iso)
    week_out = today + timedelta(days=7)
    buckets = {s['slug']: [] for s in ACTION_SUBSECTIONS}

    for item in items:
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
        elif due_date is not None and due_date <= week_out:
            buckets['due-soon'].append(item)
        else:
            buckets['no-due-date'].append(item)

    for slug in ('overdue', 'due-soon'):
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
