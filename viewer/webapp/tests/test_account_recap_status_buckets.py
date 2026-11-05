from template_test_utils import make_env


def render_account_recap(items):
    env = make_env()
    template = env.get_template('section_fragment.html')
    return template.render(
        section_slug='account-recap',
        section_items=items,
        action_subsections=[],
        asana_pat_configured=False,
        brief_date='2026-11-04',
        today_iso='2026-11-04',
    )


BUCKETED_SUBTITLE = (
    "Updates/FYI\n"
    "- Global ES Org Meeting (11/4): Gainsight value touchpoints must be tracked now.\n"
    "- Hiring: two TAM LATAM interviews today.\n"
    "Pending Action Items\n"
    "- Update 1:1 Asana (9:00 AM block today)\n"
    "- Reply to Pavel on TAM coverage for 11/9 to 11/13\n"
    "Blockers/Risks\n"
    "- About 55 overdue items on the GTD and onboarding boards"
)


def test_account_recap_subtitle_renders_three_labeled_buckets():
    items = [{
        'item_key': 'acct-recap-general-admin',
        'item_type': 'checkable',
        'title': 'General / Admin',
        'subtitle': BUCKETED_SUBTITLE,
        'checked': False,
        'content': {},
    }]

    html = render_account_recap(items)

    assert html.count('status-bucket-label') == 3
    assert '<div class="status-bucket-label">Updates/FYI</div>' in html
    assert '<div class="status-bucket-label">Pending Action Items</div>' in html
    assert '<div class="status-bucket-label">Blockers/Risks</div>' in html
    # Bullets become real list items, not a flattened paragraph.
    assert '<li>Global ES Org Meeting (11/4): Gainsight value touchpoints must be tracked now.</li>' in html
    assert '<li>Update 1:1 Asana (9:00 AM block today)</li>' in html
    assert '<li>About 55 overdue items on the GTD and onboarding boards</li>' in html
    # Raw text shouldn't leak through unparsed.
    assert 'Updates/FYI - Global ES Org Meeting' not in html


def test_account_recap_bucket_with_only_none_renders_plain_text_not_bullet():
    items = [{
        'item_key': 'acct-recap-quiet-account',
        'item_type': 'checkable',
        'title': 'Quiet Account',
        'subtitle': (
            "Updates/FYI\n"
            "- Bi-Weekly Sync occurred, no summary available\n"
            "Pending Action Items\n"
            "- None\n"
            "Blockers/Risks\n"
            "- None"
        ),
        'checked': False,
        'content': {},
    }]

    html = render_account_recap(items)

    assert html.count('status-bucket-none') == 2
    assert '<div class="status-bucket-none">None</div>' in html
    assert '<li>None</li>' not in html


def test_account_recap_subtitle_without_bucket_headers_falls_back_unchanged():
    items = [{
        'item_key': 'acct-recap-legacy',
        'item_type': 'checkable',
        'title': 'Legacy Narrative Account',
        'subtitle': 'A single flowing paragraph from before the bucket format shipped.',
        'checked': False,
        'content': {},
    }]

    html = render_account_recap(items)

    assert 'status-bucket' not in html
    assert 'A single flowing paragraph from before the bucket format shipped.' in html
