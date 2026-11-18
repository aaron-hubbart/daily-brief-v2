"""Tests for Account Update cards' FYI/Pending Action Items/Blockers-Risks
bucket bullets rendering as individually-checkable checkboxes (Task 3 of the
"Brief Content: Tabbed Sections & Universal Checkability" plan).

The PATCH /api/items/<section>/<item_key>/subitems/<subitem_key>/checked
route itself (app.py) isn't covered here -- there's no Flask test-client
fixture in this suite yet (see template_test_utils.py's docstring: importing
app.py needs Azure/Flask env vars and a live-ish db module), and this plan
doesn't add one just for this one route. It was instead verified manually
(see task-3-report.md for the request/response transcript)."""
from template_test_utils import make_env


def render_section_fragment(section_slug, section_items, checked_subitems=None):
    env = make_env()
    template = env.get_template('section_fragment.html')
    return template.render(
        section_slug=section_slug,
        section_items=section_items,
        action_subsections=[],
        asana_pat_configured=False,
        brief_date='2026-11-18',
        today_iso='2026-11-18',
        checked_subitems=checked_subitems or {},
    )


BUCKET_TEXTAREA = (
    'Updates/FYI\n'
    '- Renewal signed\n'
    '- Expansion conversation started\n'
    'Pending Action Items\n'
    '- Send updated SOW\n'
    'Blockers/Risks\n'
    '- None'
)


def test_customer_update_bucket_bullets_are_checkable():
    html = render_section_fragment(
        section_slug='customer-updates',
        section_items=[{'item_key': 'cust-update-acme', 'title': 'Acme Corp',
                         'content': {'textarea': BUCKET_TEXTAREA}}],
        checked_subitems={'cust-update-acme': {'sb-fyi:0': True}},
    )
    assert 'data-subitem-key="sb-fyi:0"' in html
    # Scoped to the sb-fyi:0 label specifically, not just "checked" appearing
    # anywhere in the document.
    label_start = html.index('data-subitem-key="sb-fyi:0"')
    label_tag_end = html.index('>', label_start)
    label_tag = html[max(0, label_start - 80):label_tag_end]
    assert 'class="subcheck done"' in label_tag
    checkbox_start = label_tag_end
    checkbox_end = html.index('>', checkbox_start + 1)
    assert 'checked' in html[checkbox_start:checkbox_end]


def test_customer_update_bucket_bullet_unchecked_by_default():
    html = render_section_fragment(
        section_slug='customer-updates',
        section_items=[{'item_key': 'cust-update-acme', 'title': 'Acme Corp',
                         'content': {'textarea': BUCKET_TEXTAREA}}],
        checked_subitems={},
    )
    label_start = html.index('data-subitem-key="sb-fyi:0"')
    label_tag_end = html.index('>', label_start)
    label_tag = html[max(0, label_start - 80):label_tag_end]
    assert 'class="subcheck"' in label_tag
    assert ' done' not in label_tag
    checkbox_start = label_tag_end
    checkbox_end = html.index('>', checkbox_start + 1)
    assert 'checked' not in html[checkbox_start:checkbox_end]


def test_customer_update_bucket_bullets_have_distinct_subitem_keys_per_bucket():
    html = render_section_fragment(
        section_slug='customer-updates',
        section_items=[{'item_key': 'cust-update-acme', 'title': 'Acme Corp',
                         'content': {'textarea': BUCKET_TEXTAREA}}],
    )
    assert 'data-subitem-key="sb-fyi:0"' in html
    assert 'data-subitem-key="sb-fyi:1"' in html
    assert 'data-subitem-key="sb-action:0"' in html
    # Blockers/Risks collapses to a plain "None" div (no bullet, no checkbox)
    # for a single "None" bullet -- same as the existing format_status_buckets
    # behavior this mirrors.
    assert 'data-subitem-key="sb-risk:0"' not in html
    assert '<div class="status-bucket-none">None</div>' in html


def test_customer_update_subcheck_carries_section_and_item_key():
    """wireSubchecks (client JS) reads section/item_key/subitem_key straight
    off the .subcheck label itself -- scoped to that label's own opening
    tag, not just anywhere in the document (the .update-row div a few lines
    down already has its own data-item-key/data-section, unrelated to this)."""
    html = render_section_fragment(
        section_slug='customer-updates',
        section_items=[{'item_key': 'cust-update-acme', 'title': 'Acme Corp',
                         'content': {'textarea': BUCKET_TEXTAREA}}],
    )
    label_start = html.index('class="subcheck')
    label_tag_end = html.index('>', label_start)
    label_tag = html[max(0, label_start - 10):label_tag_end]
    assert 'data-item-key="cust-update-acme"' in label_tag
    assert 'data-section="customer-updates"' in label_tag


def test_customer_update_without_bucket_headers_falls_back_unchanged():
    html = render_section_fragment(
        section_slug='customer-updates',
        section_items=[{'item_key': 'cust-update-legacy', 'title': 'Legacy Account',
                         'content': {'textarea': 'A single flowing paragraph, no bucket headers.'}}],
    )
    assert 'subcheck' not in html
    assert 'A single flowing paragraph, no bucket headers.' in html


def test_customer_update_textarea_stays_raw_and_untouched_by_checkboxes():
    html = render_section_fragment(
        section_slug='customer-updates',
        section_items=[{'item_key': 'cust-update-acme', 'title': 'Acme Corp',
                         'content': {'textarea': BUCKET_TEXTAREA}}],
        checked_subitems={'cust-update-acme': {'sb-fyi:0': True}},
    )
    assert '<textarea class="update-textarea">' in html
    textarea_start = html.index('<textarea class="update-textarea">')
    textarea_end = html.index('</textarea>', textarea_start)
    textarea_html = html[textarea_start:textarea_end]
    assert 'subcheck' not in textarea_html
    assert 'checkbox' not in textarea_html
    assert BUCKET_TEXTAREA in textarea_html
