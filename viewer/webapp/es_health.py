"""ES (Enterprise Success) meeting catalog and health-scoring logic for the
Environments tab. Pure functions, no Flask/Drive dependency, so the scoring
rules are unit-testable directly — see
docs/superpowers/specs/2026-11-05-environments-key-meetings-and-es-health-design.md
for the rules this module implements."""
from datetime import date, timedelta
from typing import Callable, Dict, List, Optional, Tuple, Union

MEETING_CATALOG: List[Dict] = [
    {'id': 'es101-01-handover', 'name': 'Internal Handover (AE→CS)', 'category': 'one_time', 'default_cadence': None, 'default_requirement': 'required'},
    {'id': 'es101-02-cs-intro', 'name': 'CS Introduction', 'category': 'one_time', 'default_cadence': None, 'default_requirement': 'required'},
    {'id': 'es101-03-joint-adoption-planning', 'name': 'Joint Adoption Planning', 'category': 'one_time', 'default_cadence': None, 'default_requirement': 'required'},
    {'id': 'es101-04-technical-kickoff', 'name': 'Technical Kickoff / Environment Overview', 'category': 'one_time', 'default_cadence': None, 'default_requirement': 'required'},
    {'id': 'es101-05-onboarding-completion', 'name': 'Onboarding Completion Review', 'category': 'one_time', 'default_cadence': None, 'default_requirement': 'required'},
    {'id': 'es104-03-program-team-cadence', 'name': 'Program Team Cadence', 'category': 'recurring', 'default_cadence': 'monthly', 'default_requirement': 'required'},
    {'id': 'es103-cvr', 'name': 'Customer Value Review (CVR / QBR)', 'category': 'recurring', 'default_cadence': 'quarterly', 'default_requirement': 'required'},
    {'id': 'es104-02-exec-meeting', 'name': 'Executive Meeting', 'category': 'recurring', 'default_cadence': 'yearly', 'default_requirement': 'optional'},
    {'id': 'es301-platform-best-practices', 'name': 'Platform Best Practices', 'category': 'recurring', 'default_cadence': 'ongoing', 'default_requirement': 'conditional'},
    {'id': 'es105-03-technical-roadmap-review', 'name': 'Technical Roadmap Review', 'category': 'recurring', 'default_cadence': 'periodic', 'default_requirement': 'required'},
]

RECURRING_CADENCE_DAYS = {
    'monthly': 30, 'quarterly': 91, 'yearly': 365,
    'periodic': 91,   # ES105.03 Technical Roadmap Review — spec treats "periodic" as quarterly by default
    'ongoing': None,  # ES301 — never overdue; it's also never `required`, so this never matters for scoring
}
ES_ACTIVITY_STALE_GRACE_DAYS = 14   # guess — not_done activity must be at least this old to count as stale
OPEN_ISSUES_YELLOW_THRESHOLD = 10   # guess — placeholder per spec, trivially tunable later

_LEVEL_RANK = {'Green': 0, 'Yellow': 1, 'Red': 2}


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    return date.fromisoformat(value)


def _is_applicable(entry: Dict, team: Dict) -> bool:
    if entry['default_requirement'] not in ('optional', 'conditional'):
        return True
    return entry['id'] not in team.get('inapplicable_meeting_types', [])


def _one_time_overdue(entry: Dict, row: Optional[Dict], today: date) -> bool:
    if not row or row.get('status') != 'occurred':
        if row and row.get('status') == 'scheduled':
            scheduled = _parse_date(row.get('scheduled_date'))
            return scheduled is not None and scheduled < today
        return True
    return False


def _recurring_overdue(entry: Dict, row: Optional[Dict], today: date) -> bool:
    cadence_days = RECURRING_CADENCE_DAYS[entry['default_cadence']]
    if cadence_days is None:
        return False
    last_held = _parse_date(row.get('last_held_date')) if row else None
    if last_held is None:
        return True
    return today > last_held + timedelta(days=cadence_days)


def compute_team_health(team: Dict, meetings: List[Dict], es_activities: List[Dict], today: Optional[date] = None) -> Dict:
    if team.get('exempt'):
        return {'level': 'Exempt', 'reasons': [], 'overdue_count': 0, 'stale_count': 0}

    today = today or date.today()
    meetings_by_type = {m['meeting_type_id']: m for m in meetings}
    reasons: List[str] = []
    overdue_count = 0

    one_time_entries = [e for e in MEETING_CATALOG if e['category'] == 'one_time']
    for entry in one_time_entries:
        if entry['default_requirement'] != 'required' or not _is_applicable(entry, team):
            continue
        row = meetings_by_type.get(entry['id'])
        if _one_time_overdue(entry, row, today):
            overdue_count += 1
            if row and row.get('status') == 'scheduled':
                reasons.append(f"{entry['name']} is overdue")
            else:
                reasons.append(f"{entry['name']} has not been scheduled")
            break  # only the earliest incomplete one-time step counts

    recurring_entries = [e for e in MEETING_CATALOG if e['category'] == 'recurring']
    for entry in recurring_entries:
        if entry['default_requirement'] != 'required' or not _is_applicable(entry, team):
            continue
        row = meetings_by_type.get(entry['id'])
        if _recurring_overdue(entry, row, today):
            overdue_count += 1
            reasons.append(f"{entry['name']} is overdue")

    stale_count = 0
    for activity in es_activities:
        if activity.get('status') != 'not_done':
            continue
        last_updated = _parse_date(activity.get('last_updated'))
        if last_updated is None or today - last_updated > timedelta(days=ES_ACTIVITY_STALE_GRACE_DAYS):
            stale_count += 1
            reasons.append(f"{activity.get('label', 'An ES activity')} hasn't been updated recently")

    sentiment = team.get('sentiment') or ''
    open_issues = team.get('open_issues')
    if sentiment:
        reasons.append(f"Sentiment: {sentiment}")
    if open_issues is not None and open_issues > OPEN_ISSUES_YELLOW_THRESHOLD:
        reasons.append(f"Open issues: {open_issues} (over threshold {OPEN_ISSUES_YELLOW_THRESHOLD})")

    total_issues = overdue_count + stale_count
    if sentiment == 'Red' or total_issues >= 2:
        level = 'Red'
    elif sentiment == 'Yellow' or total_issues == 1 or (open_issues is not None and open_issues > OPEN_ISSUES_YELLOW_THRESHOLD):
        level = 'Yellow'
    else:
        level = 'Green'

    return {'level': level, 'reasons': reasons, 'overdue_count': overdue_count, 'stale_count': stale_count}


def compute_customer_rollup(team_healths: List[Tuple[Dict, Dict]]) -> Dict:
    if not team_healths:
        return {'level': 'Green', 'team_count': 0, 'overdue_count': 0, 'sentiment_level': '', 'open_issues_total': 0}

    level = 'Green'
    overdue_count = 0
    sentiment_level = ''
    open_issues_total = 0
    for team, health in team_healths:
        if _LEVEL_RANK[health['level']] > _LEVEL_RANK[level]:
            level = health['level']
        overdue_count += health['overdue_count'] + health['stale_count']
        sentiment = team.get('sentiment') or ''
        if sentiment and (not sentiment_level or _LEVEL_RANK[sentiment] > _LEVEL_RANK[sentiment_level]):
            sentiment_level = sentiment
        open_issues_total += team.get('open_issues') or 0

    return {
        'level': level, 'team_count': len(team_healths), 'overdue_count': overdue_count,
        'sentiment_level': sentiment_level, 'open_issues_total': open_issues_total,
    }


def compute_account_health(data: Dict, today: Optional[date] = None) -> Dict:
    meetings = data.get('meetings', [])
    es_activities = data.get('es_activities', [])
    non_exempt_results = []

    for team in data.get('teams', []):
        team_meetings = [m for m in meetings if m.get('team_id') == team['id']]
        team_activities = [a for a in es_activities if a.get('team_id') == team['id']]
        health = compute_team_health(team, team_meetings, team_activities, today)
        team['health'] = health
        if not team.get('exempt'):
            non_exempt_results.append((team, health))

    data['rollup'] = compute_customer_rollup(non_exempt_results)
    return data


def build_portfolio_rollup(customers: List[Dict], read_fn: Callable[[str], Union[Dict, str, None]], today: Optional[date] = None) -> List[Dict]:
    results = []
    for customer in customers:
        name, theater = customer['name'], customer.get('theater')
        data = read_fn(name)
        if isinstance(data, dict):
            rollup = compute_account_health(data, today)['rollup']
            results.append({'name': name, 'theater': theater, 'error': None, **rollup})
        else:
            error = data if isinstance(data, str) else 'Could not read environments data'
            results.append({
                'name': name, 'theater': theater, 'error': error,
                'level': 'Green', 'team_count': 0, 'overdue_count': 0,
                'sentiment_level': '', 'open_issues_total': 0,
            })

    results.sort(key=lambda c: c['name'].lower())
    return results
