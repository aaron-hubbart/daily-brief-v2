from template_test_utils import parse_status_buckets


def test_parse_status_buckets_returns_none_for_plain_text():
    assert parse_status_buckets("Just a few notes, nothing structured.") is None


def test_parse_status_buckets_splits_three_buckets():
    text = "Updates/FYI\n- Renewal signed\nPending Action Items\n- Schedule QBR\nBlockers/Risks\n- Champion unresponsive"
    result = parse_status_buckets(text)
    assert [b['key'] for b in result] == ['sb-fyi', 'sb-action', 'sb-risk']
    assert result[0]['bullets'] == ['Renewal signed']
    assert result[1]['bullets'] == ['Schedule QBR']
    assert result[2]['bullets'] == ['Champion unresponsive']


def test_parse_status_buckets_none_bucket_yields_empty_bullets():
    text = "Updates/FYI\n- None\nPending Action Items\n- None\nBlockers/Risks\n- None"
    result = parse_status_buckets(text)
    assert all(b['bullets'] == [] for b in result)


def test_parse_status_buckets_drops_none_bullet_alongside_real_bullets():
    """A "None" bullet can appear alongside real bullets in the same bucket
    (not just as the bucket's sole line) -- it must still be dropped, not
    rendered as a checkable row or counted toward the bucket's total."""
    text = (
        "Updates/FYI\n- Real thing\n- None\n- Another real thing\n"
        "Pending Action Items\n- None\n"
        "Blockers/Risks\n- None"
    )
    result = parse_status_buckets(text)
    assert result[0]['bullets'] == ['Real thing', 'Another real thing']
