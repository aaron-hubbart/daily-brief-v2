from template_test_utils import make_env


def render_customer_updates(items):
    env = make_env()
    template = env.get_template('section_fragment.html')
    return template.render(
        section_slug='customer-updates',
        section_items=items,
        action_subsections=[],
        asana_pat_configured=False,
        brief_date='2026-11-11',
        today_iso='2026-11-11',
    )


SLACK_FORMATTED_TEXTAREA = (
    "[TAM-UPDATE] #claude-brief-skill\n\n"
    "*Acme Financial — TAM Update*\n"
    "Nov 4 – Nov 11, 2026\n\n"
    "*Updates/FYI*\n"
    "• QBR held 11/6, Gainsight health score reviewed and agreed at 82.\n"
    "• Migration kickoff call scheduled for next week.\n\n"
    "*Pending Action Items*\n"
    "• Send updated SOW — due 11/13\n"
    "• None\n\n"
    "*Blockers/Risks*\n"
    "• Renewal at risk: budget freeze flagged by economic buyer."
)


def test_customer_update_preview_renders_three_labeled_buckets():
    items = [{
        'item_key': 'cust-update-acme',
        'item_type': 'card',
        'title': 'Acme Financial',
        'content': {
            'textarea': SLACK_FORMATTED_TEXTAREA,
            'channel_id': 'C0TESTACME',
            'last_posted_label': 'Last posted 11/4',
        },
    }]

    html = render_customer_updates(items)

    assert html.count('status-bucket-label') == 3
    assert '<div class="status-bucket-label">Updates/FYI</div>' in html
    assert '<div class="status-bucket-label">Pending Action Items</div>' in html
    assert '<div class="status-bucket-label">Blockers/Risks</div>' in html
    assert '<li>QBR held 11/6, Gainsight health score reviewed and agreed at 82.</li>' in html
    assert '<li>Send updated SOW — due 11/13</li>' in html
    assert '<li>Renewal at risk: budget freeze flagged by economic buyer.</li>' in html


def test_customer_update_preview_keeps_tam_update_wrapper_as_raw_preamble():
    items = [{
        'item_key': 'cust-update-acme',
        'item_type': 'card',
        'title': 'Acme Financial',
        'content': {'textarea': SLACK_FORMATTED_TEXTAREA, 'channel_id': 'C0TESTACME'},
    }]

    html = render_customer_updates(items)

    assert '<div class="status-bucket-preamble">' in html
    assert '[TAM-UPDATE] #claude-brief-skill' in html
    assert '*Acme Financial — TAM Update*' in html
    assert 'Nov 4 – Nov 11, 2026' in html


def test_customer_update_preview_none_bucket_renders_plain_not_bullet():
    items = [{
        'item_key': 'cust-update-quiet',
        'item_type': 'card',
        'title': 'Quiet Account',
        'content': {
            'textarea': (
                "[TAM-UPDATE] #claude-brief-skill\n\n"
                "*Quiet Account — TAM Update*\n"
                "Nov 4 – Nov 11, 2026\n\n"
                "*Updates/FYI*\n"
                "• None\n\n"
                "*Pending Action Items*\n"
                "• None\n\n"
                "*Blockers/Risks*\n"
                "• None"
            ),
            'channel_id': 'C0TESTQUIET',
        },
    }]

    html = render_customer_updates(items)

    assert html.count('status-bucket-none') == 3
    assert '<li>None</li>' not in html


def test_customer_update_textarea_stays_raw_and_editable():
    items = [{
        'item_key': 'cust-update-acme',
        'item_type': 'card',
        'title': 'Acme Financial',
        'content': {'textarea': SLACK_FORMATTED_TEXTAREA, 'channel_id': 'C0TESTACME'},
    }]

    html = render_customer_updates(items)

    assert '<textarea class="update-textarea">' in html
    textarea_start = html.index('<textarea class="update-textarea">')
    textarea_end = html.index('</textarea>', textarea_start)
    textarea_html = html[textarea_start:textarea_end]
    # The editable textarea keeps the exact Slack mrkdwn source (asterisks,
    # bullets, brackets) unprocessed -- no status-bucket markup inside it.
    assert 'status-bucket' not in textarea_html
    assert '*Updates/FYI*' in textarea_html
    assert '• QBR held 11/6' in textarea_html


def test_customer_update_without_bucket_headers_falls_back_unchanged():
    items = [{
        'item_key': 'cust-update-legacy',
        'item_type': 'card',
        'title': 'Legacy Narrative Account',
        'content': {
            'textarea': 'A single flowing paragraph from before the bucket format shipped.',
            'channel_id': 'C0TESTLEGACY',
        },
    }]

    html = render_customer_updates(items)

    assert 'status-bucket' not in html
    assert 'A single flowing paragraph from before the bucket format shipped.' in html
