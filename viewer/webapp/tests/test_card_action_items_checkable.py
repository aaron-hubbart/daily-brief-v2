"""Tests for account-recap cards' Action Items list rendering as
individually-checkable checkboxes (Task 4 of the "Brief Content: Tabbed
Sections & Universal Checkability" plan). Reuses the exact `.subcheck`
markup pattern Task 3 established for Account Update bucket bullets --
see test_account_updates_checkable_buckets.py."""
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


def test_account_recap_card_action_items_are_checkable():
    html = render_section_fragment(
        section_slug='account-recap',
        section_items=[{'item_key': 'recap-acme', 'item_type': 'card', 'title': 'Acme',
                         'content': {'action_items': ['Schedule QBR', 'Send renewal doc']}}],
        checked_subitems={'recap-acme': {'action_items:1': True}},
    )
    assert 'data-subitem-key="action_items:0"' in html
    assert 'data-subitem-key="action_items:1"' in html


def test_account_recap_action_item_checked_state_reflected_in_done_class():
    html = render_section_fragment(
        section_slug='account-recap',
        section_items=[{'item_key': 'recap-acme', 'item_type': 'card', 'title': 'Acme',
                         'content': {'action_items': ['Schedule QBR', 'Send renewal doc']}}],
        checked_subitems={'recap-acme': {'action_items:1': True}},
    )
    # action_items:1 is checked -- scoped to that label's own opening tag.
    label_start = html.index('data-subitem-key="action_items:1"')
    label_tag_end = html.index('>', label_start)
    label_tag = html[max(0, label_start - 80):label_tag_end]
    assert 'class="subcheck done"' in label_tag
    checkbox_start = label_tag_end
    checkbox_end = html.index('>', checkbox_start + 1)
    assert 'checked' in html[checkbox_start:checkbox_end]

    # action_items:0 is NOT checked.
    label0_start = html.index('data-subitem-key="action_items:0"')
    label0_tag_end = html.index('>', label0_start)
    label0_tag = html[max(0, label0_start - 80):label0_tag_end]
    assert 'class="subcheck"' in label0_tag
    assert ' done' not in label0_tag
    checkbox0_start = label0_tag_end
    checkbox0_end = html.index('>', checkbox0_start + 1)
    assert 'checked' not in html[checkbox0_start:checkbox0_end]


def test_account_recap_action_item_unchecked_by_default():
    html = render_section_fragment(
        section_slug='account-recap',
        section_items=[{'item_key': 'recap-acme', 'item_type': 'card', 'title': 'Acme',
                         'content': {'action_items': ['Schedule QBR']}}],
        checked_subitems={},
    )
    label_start = html.index('data-subitem-key="action_items:0"')
    label_tag_end = html.index('>', label_start)
    label_tag = html[max(0, label_start - 80):label_tag_end]
    assert 'class="subcheck"' in label_tag
    assert ' done' not in label_tag


def test_account_recap_action_item_subcheck_carries_section_and_item_key():
    """wireSubchecks (client JS) reads section/item_key/subitem_key straight
    off the .subcheck label itself, exactly like Task 3's bucket bullets."""
    html = render_section_fragment(
        section_slug='account-recap',
        section_items=[{'item_key': 'recap-acme', 'item_type': 'card', 'title': 'Acme',
                         'content': {'action_items': ['Schedule QBR']}}],
    )
    label_start = html.index('class="subcheck')
    label_tag_end = html.index('>', label_start)
    label_tag = html[max(0, label_start - 10):label_tag_end]
    assert 'data-item-key="recap-acme"' in label_tag
    assert 'data-section="account-recap"' in label_tag


def test_account_recap_card_without_action_items_renders_no_subchecks():
    html = render_section_fragment(
        section_slug='account-recap',
        section_items=[{'item_key': 'recap-acme', 'item_type': 'card', 'title': 'Acme',
                         'content': {'html_content': 'Some recap text.'}}],
    )
    assert 'subcheck' not in html
    assert 'Some recap text.' in html
