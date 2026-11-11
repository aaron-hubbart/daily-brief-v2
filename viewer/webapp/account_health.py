"""
Pure parsing/classification/assembly logic for the Account Health page.

No Flask or Google Drive imports here on purpose — this module takes
already-downloaded Context Doc text (or a dependency-injected fetcher
callable) and turns it into the page's data model, so every rule from
the design doc is unit-testable without mocking Drive. See
docs/superpowers/specs/2026-11-06-portfolio-design.md.
"""
import logging
import re
from datetime import date, datetime
from typing import Callable, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

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
_COLOR_WORDS = sorted(_COLOR_GROUP_RANK, key=len, reverse=True)
# A health-score label ("Health:", "Gainsight health score:", bare
# "Overall:", or a short score code like "C8:") immediately followed by a
# color. Requiring the colon right after the label is what keeps this from
# false-positiving on prose like "Platform health check on Red Hat" (no
# colon right after "health") while still matching the spec's own
# multi-score example "C8: Green, Overall: Yellow" (neither "C8:" nor
# "Overall:" contains the word "health" at all).
_HEALTH_SIGNAL_RE = re.compile(
    r'\b(?:(?:overall\s+)?(?:gainsight\s+)?health(?:\s+score)?|overall|C\d+)\s*:\s*'
    r'(' + '|'.join(_COLOR_WORDS) + r')\b',
    re.IGNORECASE,
)

_ARR_DISPUTE_WORDS = ('conflict', 'disagree', 'unreconciled', 'disputed', 'does not reconcile')
_ARR_CONTEXT_RE = re.compile(r'\b(ARR|commercial|annual recurring)\b', re.IGNORECASE)
# \b after the optional K/M suffix keeps "$1,200 monthly" from reading the
# leading "m" of "monthly" as an M-for-million suffix (which would inflate
# $1,200 into $1.2B) -- "m" immediately followed by "onthly" has no word
# boundary, so the suffix group fails to match there and backtracks to None.
_DOLLAR_RE = re.compile(r'\$\s?([\d,]+(?:\.\d+)?)\s?([KM])?\b', re.IGNORECASE)

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
    """Find a health-score label ("Health:", "Gainsight health score:",
    "Overall:", "C8:") immediately followed by a color, and map to one of
    the four groups, using the worst (highest-rank) color when more than
    one is found. Distinct signals only (a doc repeating the same color
    twice isn't a second signal). No match anywhere -> ('no_health_data', [])."""
    signals: List[str] = []
    best_rank = -1
    best_group = 'no_health_data'
    for line in text.splitlines():
        for match in _HEALTH_SIGNAL_RE.finditer(line):
            word = match.group(1)
            group, rank = _COLOR_GROUP_RANK[word.lower()]
            # Preserve the doc's own casing/spelling (e.g. "Lime Green").
            canonical = word if word[0].isupper() else word.title()
            if canonical not in signals:
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
    """Find a dollar figure on a line that also mentions ARR/commercial
    wording; flag disputed when conflict language appears on that same
    line. Scoping both the figure and the dispute check to the ARR line
    (not the whole doc) keeps an unrelated $ figure elsewhere, or
    unrelated conflict language elsewhere, from being misattributed to
    ARR."""
    for line in text.splitlines():
        if not _ARR_CONTEXT_RE.search(line):
            continue

        match = _DOLLAR_RE.search(line)
        if not match:
            continue

        digits, suffix = match.group(1), match.group(2)
        raw = f"${digits}{suffix.upper() if suffix else ''}"
        value = _parse_dollar_value(digits, suffix)

        disputed = False
        note = None
        lowered = line.lower()
        for word in _ARR_DISPUTE_WORDS:
            if word in lowered:
                disputed = True
                note = line.strip()
                break

        return {'raw': raw, 'value': value, 'disputed': disputed, 'note': note}

    return {'raw': None, 'value': None, 'disputed': False, 'note': None}


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


_TRAILING_PAREN_RE = re.compile(r'\s*\([^)]*\)\s*$')


def _is_current_user(name: str, current_user_name: Optional[str]) -> bool:
    """A case-insensitive full-name match, or a match against just the
    user's first name (docs sometimes name a TAM by first name only),
    ignoring a trailing parenthetical like "(Camunda)"."""
    if not name or not current_user_name:
        return False
    cleaned = _TRAILING_PAREN_RE.sub('', name).strip().lower()
    user_lower = current_user_name.strip().lower()
    if cleaned == user_lower:
        return True
    user_first_name = user_lower.split()[0] if user_lower.split() else user_lower
    return cleaned == user_first_name


def parse_owners(text: str, current_user_name: Optional[str]) -> Dict[str, Optional[str]]:
    """Match an inline "Role: Name" label or a "Role, Name" table row for
    each of CSM/AE/TAM; substitute "You" for a match against
    current_user_name (full name or first name only)."""
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

        if _is_current_user(name, current_user_name):
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
    that line isn't present or isn't a real date. None if neither is
    available/parseable -- a malformed date (human typo, e.g. "2026-02-30")
    must degrade to "unknown", never raise and take down the whole page."""
    match = _SWEPT_RE.search(text)
    if match:
        try:
            swept_date = datetime.strptime(match.group(1), '%Y-%m-%d').date()
            return (today - swept_date).days
        except ValueError:
            logger.warning('compute_swept_days_ago: malformed "Last swept" date %r', match.group(1))

    if modified_time:
        try:
            swept_date = datetime.strptime(modified_time[:10], '%Y-%m-%d').date()
            return (today - swept_date).days
        except ValueError:
            logger.warning('compute_swept_days_ago: malformed modified_time %r', modified_time)

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
            'health_disagree': False,
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
        'health_disagree': len(health_signals) > 1,
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


def extract_callout_findings(callout_items: Optional[List]) -> Optional[List[str]]:
    """Defensively pull the findings list out of what
    gdrive_briefs.read_section('portfolio-summary', ...) returns. A
    malformed or half-written portfolio-summary.json (wrong type for
    content, a non-list findings, missing section entirely) must degrade
    to "no callout today", never raise -- one bad file in another repo's
    pipeline must not blank the whole Account Health page."""
    if not callout_items:
        return None
    first = callout_items[0]
    if not isinstance(first, dict):
        return None
    content = first.get('content')
    if not isinstance(content, dict):
        return None
    findings = content.get('findings')
    if not isinstance(findings, list) or not findings:
        return None
    return findings


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
        try:
            entry = build_account_entry(name, tier, doc_result, current_user_name, today)
        except Exception:
            # A parsing bug on one account's doc must never take the whole
            # page down -- fall back to the same placeholder card a
            # genuinely-missing doc gets, per the spec's anti-goal against
            # silently dropping an account.
            logger.warning('build_page_model: build_account_entry raised for %r -- falling back to placeholder', name, exc_info=True)
            entry = build_account_entry(name, tier, 'not_found', current_user_name, today)
        entries.append(entry)

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
