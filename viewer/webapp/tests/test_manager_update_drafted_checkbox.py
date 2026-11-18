"""Tests for the Manager Update section's single "drafted" checkbox (Task 4
of the "Brief Content: Tabbed Sections & Universal Checkability" plan).
Reuses the exact `.subcheck` markup pattern Task 3 established for Account
Update bucket bullets -- see test_account_updates_checkable_buckets.py."""
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


def test_manager_update_has_single_drafted_checkbox():
    html = render_section_fragment(
        section_slug='manager-update',
        section_items=[{'item_key': 'mgr-update', 'content': {'textarea': 'Draft text...'}}],
        checked_subitems={'mgr-update': {'drafted': False}},
    )
    assert 'data-subitem-key="drafted"' in html
    assert html.count('data-subitem-key="drafted"') == 1


def test_manager_update_drafted_checkbox_reflects_checked_state():
    html = render_section_fragment(
        section_slug='manager-update',
        section_items=[{'item_key': 'mgr-update', 'content': {'textarea': 'Draft text...'}}],
        checked_subitems={'mgr-update': {'drafted': True}},
    )
    label_start = html.index('data-subitem-key="drafted"')
    label_tag_end = html.index('>', label_start)
    label_tag = html[max(0, label_start - 80):label_tag_end]
    assert 'class="subcheck done"' in label_tag
    checkbox_start = label_tag_end
    checkbox_end = html.index('>', checkbox_start + 1)
    assert 'checked' in html[checkbox_start:checkbox_end]


def test_manager_update_drafted_checkbox_unchecked_by_default():
    html = render_section_fragment(
        section_slug='manager-update',
        section_items=[{'item_key': 'mgr-update', 'content': {'textarea': 'Draft text...'}}],
        checked_subitems={},
    )
    label_start = html.index('data-subitem-key="drafted"')
    label_tag_end = html.index('>', label_start)
    label_tag = html[max(0, label_start - 80):label_tag_end]
    assert 'class="subcheck"' in label_tag
    assert ' done' not in label_tag
    checkbox_start = label_tag_end
    checkbox_end = html.index('>', checkbox_start + 1)
    assert 'checked' not in html[checkbox_start:checkbox_end]


def test_manager_update_drafted_checkbox_carries_section_and_item_key():
    html = render_section_fragment(
        section_slug='manager-update',
        section_items=[{'item_key': 'mgr-update', 'content': {'textarea': 'Draft text...'}}],
    )
    label_start = html.index('class="subcheck')
    label_tag_end = html.index('>', label_start)
    label_tag = html[max(0, label_start - 10):label_tag_end]
    assert 'data-item-key="mgr-update"' in label_tag
    assert 'data-section="manager-update"' in label_tag
