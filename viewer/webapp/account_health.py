"""
Pure parsing/classification/assembly logic for the Account Health page.

No Flask or Google Drive imports here on purpose — this module takes
already-downloaded Context Doc text (or a dependency-injected fetcher
callable) and turns it into the page's data model, so every rule from
the design doc is unit-testable without mocking Drive. See
docs/superpowers/specs/2026-11-06-portfolio-design.md.
"""
import re
from typing import Dict, List, Optional, Tuple

HEALTH_GROUPS = ('needs_attention', 'watch', 'healthy', 'no_health_data')
HEALTH_GROUP_LABELS = {
    'needs_attention': 'Needs Attention',
    'watch': 'Watch',
    'healthy': 'Healthy',
    'no_health_data': 'No Health Data',
}

# Color word -> (group, rank). Higher rank wins when a doc cites more than
# one score (see classify_health).
_COLOR_GROUP_RANK = {
    'red': ('needs_attention', 3),
    'yellow': ('watch', 2),
    'amber': ('watch', 2),
    'orange': ('watch', 2),
    'green': ('healthy', 1),
    'lime green': ('healthy', 1),
}
# Longest names first so "Lime Green" matches before bare "Green".
_COLOR_RE = re.compile(
    r'\b(' + '|'.join(sorted(_COLOR_GROUP_RANK, key=len, reverse=True)) + r')\b',
    re.IGNORECASE,
)
_HEALTH_CONTEXT_RE = re.compile(r'health|gainsight', re.IGNORECASE)

_ARR_DISPUTE_WORDS = ('conflict', 'disagree', 'unreconciled', 'disputed', 'does not reconcile')
_ARR_CONTEXT_RE = re.compile(r'\b(ARR|commercial|annual recurring)\b', re.IGNORECASE)
_DOLLAR_RE = re.compile(r'\$\s?([\d,]+(?:\.\d+)?)\s?([KM])?', re.IGNORECASE)

_RENEWAL_CONTEXT_RE = re.compile(r'renewal', re.IGNORECASE)
_ISO_DATE_RE = re.compile(r'\b(\d{4}-\d{2}-\d{2})\b')
_MONTH_DATE_RE = re.compile(
    r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})\b',
    re.IGNORECASE,
)
_MONTH_NUM = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
    'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
}

_OWNER_ROLES = ('csm', 'ae', 'tam')
_OWNER_INLINE_RE = {
    role: re.compile(rf'^\s*{role}\s*:\s*(.+?)\s*$', re.IGNORECASE | re.MULTILINE)
    for role in _OWNER_ROLES
}
_OWNER_TABLE_ROW_RE = {
    role: re.compile(rf'^\s*{role}\s*,\s*(.+?)\s*$', re.IGNORECASE | re.MULTILINE)
    for role in _OWNER_ROLES
}

_TIER_CONTEXT_RE = re.compile(r'(?:Edition|Tier|Plan)\s*:\s*(.+)', re.IGNORECASE)


def classify_health(text: str) -> Tuple[str, List[str]]:
    """Find color words near "health"/"Gainsight" and map to one of the
    four groups, using the worst (highest-rank) color when more than one
    is found. No match anywhere -> ('no_health_data', [])."""
    signals: List[str] = []
    best_rank = -1
    best_group = 'no_health_data'
    for line in text.splitlines():
        if not _HEALTH_CONTEXT_RE.search(line):
            continue
        for match in _COLOR_RE.finditer(line):
            word = match.group(1)
            group, rank = _COLOR_GROUP_RANK[word.lower()]
            # Preserve the doc's own casing/spelling (e.g. "Lime Green").
            canonical = word if word[0].isupper() else word.title()
            signals.append(canonical)
            if rank > best_rank:
                best_rank = rank
                best_group = group
    return best_group, signals


def _parse_dollar_value(raw_digits: str, suffix: Optional[str]) -> float:
    value = float(raw_digits.replace(',', ''))
    if suffix:
        if suffix.upper() == 'K':
            value *= 1_000
        elif suffix.upper() == 'M':
            value *= 1_000_000
    return value


def parse_arr(text: str) -> Dict:
    """Find a dollar figure near ARR/commercial wording; flag disputed when
    conflict language appears anywhere in the surrounding text."""
    if not _ARR_CONTEXT_RE.search(text):
        return {'raw': None, 'value': None, 'disputed': False, 'note': None}

    match = _DOLLAR_RE.search(text)
    if not match:
        return {'raw': None, 'value': None, 'disputed': False, 'note': None}

    digits, suffix = match.group(1), match.group(2)
    raw = f"${digits}{suffix.upper() if suffix else ''}"
    value = _parse_dollar_value(digits, suffix)

    disputed = False
    note = None
    lowered = text.lower()
    for word in _ARR_DISPUTE_WORDS:
        if word in lowered:
            disputed = True
            # Surface the sentence containing the dispute language as the note.
            for sentence in re.split(r'(?<=[.!?])\s+', text.strip()):
                if word in sentence.lower():
                    note = sentence.strip()
                    break
            break

    return {'raw': raw, 'value': value, 'disputed': disputed, 'note': note}


def parse_renewal(text: str) -> Optional[str]:
    """Find a date near "renewal" wording; normalize to YYYY-MM-DD."""
    if not _RENEWAL_CONTEXT_RE.search(text):
        return None

    iso_match = _ISO_DATE_RE.search(text)
    if iso_match:
        return iso_match.group(1)

    month_match = _MONTH_DATE_RE.search(text)
    if month_match:
        month_name, day, year = month_match.groups()
        month_num = _MONTH_NUM[month_name.lower()]
        return f'{int(year):04d}-{month_num:02d}-{int(day):02d}'

    return None


def parse_owners(text: str, current_user_name: Optional[str]) -> Dict[str, Optional[str]]:
    """Match an inline "Role: Name" label or a "Role, Name" table row for
    each of CSM/AE/TAM; substitute "You" for a case-insensitive match
    against current_user_name."""
    result: Dict[str, Optional[str]] = {}
    for role in _OWNER_ROLES:
        name = None
        inline_match = _OWNER_INLINE_RE[role].search(text)
        if inline_match:
            name = inline_match.group(1).strip()
        else:
            table_match = _OWNER_TABLE_ROW_RE[role].search(text)
            if table_match:
                name = table_match.group(1).strip()

        if name and current_user_name and name.lower() == current_user_name.lower():
            name = 'You'
        result[role] = name
    return result


def parse_commercial_tier(text: str) -> Optional[str]:
    """Find a short label near Edition/Tier/Plan wording. Informational
    only per the spec -- a miss is not an error."""
    match = _TIER_CONTEXT_RE.search(text)
    if not match:
        return None
    return match.group(1).strip().rstrip('.')
