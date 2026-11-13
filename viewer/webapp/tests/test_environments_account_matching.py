"""Tests for gdrive_briefs's pure account-name-matching and brief-count
helpers — no real Drive calls. See docs/superpowers/specs/
2026-09-23-environments-tab-design.md's "known limitation" note about
Asana project names drifting from their Drive folder's actual name."""
from gdrive_briefs import _normalize_account_name, _bigram_similarity, clamp_max_briefs_to_load


def test_normalize_strips_legal_suffix_and_period():
    assert _normalize_account_name('Acme Corp.') == 'acme'
    assert _normalize_account_name('Acme Corp') == 'acme'


def test_normalize_is_case_and_whitespace_insensitive():
    assert _normalize_account_name('  ACME   Industries  ') == 'acme industries'
    assert _normalize_account_name('Acme Industries') == 'acme industries'


def test_normalize_strips_commas():
    assert _normalize_account_name('Acme, Inc.') == 'acme'


def test_bigram_similarity_identical_strings_is_one():
    assert _bigram_similarity('acme industries', 'acme industries') == 1.0


def test_bigram_similarity_unrelated_strings_is_low():
    assert _bigram_similarity('acme industries', 'zzz corp') < 0.2


def test_bigram_similarity_empty_string_is_zero():
    assert _bigram_similarity('', 'acme') == 0.0
    assert _bigram_similarity('acme', '') == 0.0


def test_bigram_similarity_clears_fuzzy_threshold_for_drifted_legal_name():
    # The real-world case this tier exists for: account-config.json's name
    # and a Drive folder's actual name differ by more than just
    # punctuation/a legal suffix normalization strips outright (here, a
    # missing space -- "J.P. Morgan..." normalizes to "jp morgan...", the
    # Drive folder's "JPMorgan..." to "jpmorgan...") -- exact-after-
    # normalization still misses it, but the strings are clearly the same
    # account.
    score = _bigram_similarity(
        _normalize_account_name('J.P. Morgan Chase & Co.'),
        _normalize_account_name('JPMorgan Chase & Co'),
    )
    assert score >= 0.72


def test_clamp_defaults_for_missing_or_invalid_values():
    assert clamp_max_briefs_to_load(None) == 10
    assert clamp_max_briefs_to_load('not-a-number') == 10


def test_clamp_enforces_range():
    assert clamp_max_briefs_to_load(0) == 1
    assert clamp_max_briefs_to_load(1) == 1
    assert clamp_max_briefs_to_load(20) == 20
    assert clamp_max_briefs_to_load(21) == 20
    assert clamp_max_briefs_to_load(5) == 5
