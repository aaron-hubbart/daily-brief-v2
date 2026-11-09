"""
Pure parsing/classification/assembly logic for the Account Health page.

No Flask or Google Drive imports here on purpose — this module takes
already-downloaded Context Doc text (or a dependency-injected fetcher
callable) and turns it into the page's data model, so every rule from
the design doc is unit-testable without mocking Drive. See
docs/superpowers/specs/2026-11-06-portfolio-design.md.
"""
import re
from datetime import date, datetime
from typing import Callable, Dict, List, Optional, Tuple, Union

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

NEXT_STEP_FALLBACK = "Review this account's Context Doc for next steps"

_RISK_HEADING_RE = re.compile(
    r'(?:Top open risks|Open Risks\s*&\s*Issues|Blockers\s*/\s*Risks|Risks\s*/\s*Blockers)\s*:?\s*\n'
    r'((?:[ \t]*[-*].*(?:\n|$))+)',
    re.IGNORECASE,
)
_RISK_SOURCE_TAG_RE = re.compile(r'\s*\[([^\]]+)\]\s*$')

_NEXT_STEP_RE = re.compile(
    r'(?:recommendation|next step|decide)\w*\s*:\s*(.+?)(?:\n|$)',
    re.IGNORECASE,
)

_SWEPT_RE = re.compile(r'Last swept\s*:\s*(\d{4}-\d{2}-\d{2})', re.IGNORECASE)


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
    """Find a date on the same line as "renewal" wording; normalize to
    YYYY-MM-DD. Searching per-line (not the whole doc) keeps this from
    picking up an unrelated date elsewhere in the doc (e.g. "Last swept")
    once "renewal" appears anywhere at all."""
    for line in text.splitlines():
        if not _RENEWAL_CONTEXT_RE.search(line):
            continue

        iso_match = _ISO_DATE_RE.search(line)
        if iso_match:
            return iso_match.group(1)

        month_match = _MONTH_DATE_RE.search(line)
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


def parse_risks(text: str) -> List[Dict]:
    """Read the bullet list under a risks/issues heading; strip a trailing
    [...] tag off each bullet into source_tag."""
    match = _RISK_HEADING_RE.search(text)
    if not match:
        return []

    risks = []
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line:
            continue
        bullet = re.sub(r'^[-*]\s*', '', line)
        tag_match = _RISK_SOURCE_TAG_RE.search(bullet)
        if tag_match:
            source_tag = tag_match.group(1)
            bullet = bullet[:tag_match.start()].strip()
        else:
            source_tag = None
        risks.append({'text': bullet, 'source_tag': source_tag})
    return risks


def parse_next_step(text: str) -> str:
    """First sentence following recommendation/next-step/decide wording;
    the fixed fallback string if nothing matches."""
    match = _NEXT_STEP_RE.search(text)
    if not match:
        return NEXT_STEP_FALLBACK
    return match.group(1).strip()


def compute_swept_days_ago(text: str, modified_time: Optional[str], today: date) -> Optional[int]:
    """Days between `today` and the doc's own "Last swept: YYYY-MM-DD"
    line, falling back to the Drive file's modified_time (RFC3339) when
    that line isn't present. None if neither is available."""
    match = _SWEPT_RE.search(text)
    if match:
        swept_date = datetime.strptime(match.group(1), '%Y-%m-%d').date()
        return (today - swept_date).days

    if modified_time:
        swept_date = datetime.strptime(modified_time[:10], '%Y-%m-%d').date()
        return (today - swept_date).days

    return None


def format_days_ago(days: Optional[int]) -> str:
    if days is None:
        return 'swept date unknown'
    if days == 0:
        return 'swept today'
    return f'swept {days}d ago'


def format_arr_abbreviated(value: Optional[float]) -> str:
    if value is None:
        return '—'
    if value >= 1_000_000:
        return f'${value / 1_000_000:.2f}M'
    if value >= 1_000:
        return f'${int(round(value / 1_000))}K'
    return f'${value:.0f}'


STALE_THRESHOLD_DAYS = 30

_EMPTY_ARR = {'raw': None, 'value': None, 'disputed': False, 'note': None}


def build_account_entry(
    account_name: str,
    tier: str,
    doc_result: Union[Dict, str, None],
    current_user_name: Optional[str],
    today: date,
) -> Dict:
    """Assemble one account's uniform card dict. doc_result is a dict on
    success, 'not_found' or None (treated identically) otherwise -- every
    account renders a full card either way, per the spec's anti-goal
    against silently dropping accounts."""
    refresh_query = f'refresh the context for {account_name}'

    if not isinstance(doc_result, dict):
        return {
            'account_name': account_name,
            'tier': tier,
            'health_group': 'no_health_data',
            'health_signals': [],
            'commercial_tier': None,
            'swept_label': format_days_ago(None),
            'swept_days': None,
            'arr': dict(_EMPTY_ARR),
            'renewal': None,
            'csm': None,
            'ae': None,
            'tam': None,
            'risks': [],
            'next_step': NEXT_STEP_FALLBACK,
            'doc_url': None,
            'refresh_query': refresh_query,
            'no_doc': True,
        }

    text = doc_result['text']
    health_group, health_signals = classify_health(text)
    owners = parse_owners(text, current_user_name)
    swept_days = compute_swept_days_ago(text, doc_result.get('modified_time'), today)

    return {
        'account_name': account_name,
        'tier': tier,
        'health_group': health_group,
        'health_signals': health_signals,
        'commercial_tier': parse_commercial_tier(text),
        'swept_label': format_days_ago(swept_days),
        'swept_days': swept_days,
        'arr': parse_arr(text),
        'renewal': parse_renewal(text),
        'csm': owners['csm'],
        'ae': owners['ae'],
        'tam': owners['tam'],
        'risks': parse_risks(text),
        'next_step': parse_next_step(text),
        'doc_url': doc_result.get('doc_url'),
        'refresh_query': refresh_query,
        'no_doc': False,
    }


def build_page_model(
    accounts_config: List[Dict],
    doc_fetcher: Callable[[str], Union[Dict, str, None]],
    current_user_name: Optional[str],
    today: date,
) -> Dict:
    """Resolve every account-config entry into a card, bucket into the
    fixed-order health groups with ARR subtotals, and compute the stat
    tiles. Every entry renders somewhere -- never silently dropped."""
    entries = []
    for acct in accounts_config:
        name = acct.get('account_name') or acct.get('name') or 'Unknown'
        tier = acct.get('tier', 'primary')
        doc_result = doc_fetcher(name)
        entries.append(build_account_entry(name, tier, doc_result, current_user_name, today))

    groups = []
    for key in HEALTH_GROUPS:
        group_entries = [e for e in entries if e['health_group'] == key]
        subtotal = sum(e['arr']['value'] for e in group_entries if e['arr']['value'] is not None)
        groups.append({
            'key': key,
            'label': HEALTH_GROUP_LABELS[key],
            'count': len(group_entries),
            'arr_subtotal_raw': format_arr_abbreviated(subtotal) if group_entries else format_arr_abbreviated(None),
            'accounts': group_entries,
        })

    combined_arr = sum(e['arr']['value'] for e in entries if e['arr']['value'] is not None)
    stat_tiles = {
        'accounts_count': len(entries),
        'combined_arr_raw': format_arr_abbreviated(combined_arr if entries else None),
        'combined_arr_disputed_count': sum(1 for e in entries if e['arr']['disputed']),
        'needs_attention_count': sum(1 for e in entries if e['health_group'] == 'needs_attention'),
        'stale_count': sum(1 for e in entries if e['swept_days'] is not None and e['swept_days'] > STALE_THRESHOLD_DAYS),
    }

    return {'groups': groups, 'stat_tiles': stat_tiles}
