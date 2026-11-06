from datetime import date

from es_health import build_portfolio_rollup, compute_account_health, compute_customer_rollup, compute_team_health, MEETING_CATALOG

TODAY = date(2026, 11, 5)


def test_exempt_team_returns_exempt_level_ignoring_bad_data():
    team = {"id": "t1", "exempt": True, "sentiment": "Red", "open_issues": 999}
    stale_activity = [{"team_id": "t1", "status": "not_done", "last_updated": "2020-01-01"}]
    result = compute_team_health(team, meetings=[], es_activities=stale_activity, today=TODAY)
    assert result == {"level": "Exempt", "reasons": [], "overdue_count": 0, "stale_count": 0}


def test_no_data_at_all_is_overdue_not_unknown():
    team = {"id": "t1"}
    result = compute_team_health(team, meetings=[], es_activities=[], today=TODAY)
    assert result["level"] in ("Yellow", "Red")
    assert result["overdue_count"] >= 1


def test_one_time_sequence_only_cites_earliest_incomplete_step():
    first_id = MEETING_CATALOG[0]["id"]      # es101-01-handover
    second_name = MEETING_CATALOG[1]["name"]  # "CS Introduction"
    team = {"id": "t1"}
    # Required recurring entries are given a fresh last_held_date so they
    # don't also count as overdue ("no data = overdue" applies to them too) —
    # this test isolates the one-time sequence's "earliest incomplete step
    # only" rule, not the independent recurring-overdue rule.
    recurring_ids = [m["id"] for m in MEETING_CATALOG if m["category"] == "recurring" and m["default_requirement"] == "required"]
    meetings = [{"team_id": "t1", "meeting_type_id": first_id, "status": "occurred", "occurred_date": "2026-01-01"}]
    meetings += [{"team_id": "t1", "meeting_type_id": mid, "last_held_date": "2026-11-01"} for mid in recurring_ids]
    result = compute_team_health(team, meetings, es_activities=[], today=TODAY)
    # first step is done, so only the second step counts — not both, not neither
    assert result["overdue_count"] == 1
    assert any(second_name in r for r in result["reasons"])


def test_one_time_sequence_future_scheduled_step_is_not_blamed_and_doesnt_advance():
    first_id = MEETING_CATALOG[0]["id"]  # es101-01-handover
    recurring_ids = [m["id"] for m in MEETING_CATALOG if m["category"] == "recurring" and m["default_requirement"] == "required"]
    team = {"id": "t1"}
    # First one-time step is scheduled for a date after `today` -- it's
    # incomplete (not occurred) but not yet overdue, so it should be the
    # one the sequence is "waiting on", and nothing should be blamed.
    meetings = [{"team_id": "t1", "meeting_type_id": first_id, "status": "scheduled", "scheduled_date": "2026-11-20"}]
    meetings += [{"team_id": "t1", "meeting_type_id": mid, "last_held_date": "2026-11-01"} for mid in recurring_ids]
    result = compute_team_health(team, meetings, es_activities=[], today=TODAY)
    assert result["overdue_count"] == 0, result
    assert result["level"] == "Green", result
    assert not any("CS Introduction" in r for r in result["reasons"]), result


def test_optional_meeting_never_counts_even_when_overdue_and_applicable():
    exec_id = next(m["id"] for m in MEETING_CATALOG if m["default_requirement"] == "optional")
    team = {"id": "t1"}
    # no row for the exec meeting at all (maximally "overdue"), but it's optional
    result = compute_team_health(team, meetings=[], es_activities=[], today=TODAY)
    # confirm by checking that marking it inapplicable changes nothing about overdue_count
    result_marked = compute_team_health({"id": "t1", "inapplicable_meeting_types": [exec_id]}, meetings=[], es_activities=[], today=TODAY)
    assert result["overdue_count"] == result_marked["overdue_count"]


def test_sentiment_red_forces_red_even_with_no_other_issues():
    recurring_ids = [m["id"] for m in MEETING_CATALOG if m["category"] == "recurring" and m["default_requirement"] == "required"]
    one_time_ids = [m["id"] for m in MEETING_CATALOG if m["category"] == "one_time"]
    meetings = [{"team_id": "t1", "meeting_type_id": mid, "status": "occurred", "occurred_date": "2026-01-01"} for mid in one_time_ids]
    meetings += [{"team_id": "t1", "meeting_type_id": mid, "last_held_date": "2026-11-01"} for mid in recurring_ids]
    team = {"id": "t1", "sentiment": "Red"}
    result = compute_team_health(team, meetings, es_activities=[], today=TODAY)
    assert result["level"] == "Red"


def test_rollup_of_no_teams_is_green_and_empty():
    assert compute_customer_rollup([]) == {
        "level": "Green", "team_count": 0, "overdue_count": 0,
        "sentiment_level": "", "open_issues_total": 0,
    }


def test_rollup_takes_worst_level_and_sums_issues():
    teams = [
        ({"id": "a", "sentiment": "Yellow"}, {"level": "Yellow", "reasons": [], "overdue_count": 1, "stale_count": 0}),
        ({"id": "b", "sentiment": "Red", "open_issues": 5}, {"level": "Red", "reasons": [], "overdue_count": 2, "stale_count": 0}),
    ]
    result = compute_customer_rollup(teams)
    assert result["level"] == "Red"
    assert result["team_count"] == 2
    assert result["overdue_count"] == 3
    assert result["sentiment_level"] == "Red"
    assert result["open_issues_total"] == 5


def test_compute_account_health_annotates_teams_and_excludes_exempt_from_rollup():
    data = {
        "teams": [
            {"id": "a", "exempt": True, "sentiment": "Red"},
            {"id": "b"},
        ],
        "meetings": [], "es_activities": [], "environments": [], "use_cases": [],
    }
    result = compute_account_health(data, today=TODAY)
    assert result["teams"][0]["health"]["level"] == "Exempt"
    assert "health" in result["teams"][1]
    assert result["rollup"]["team_count"] == 1  # exempt team excluded


def test_build_portfolio_rollup_isolates_one_customers_read_failure():
    customers = [{"name": "Acme", "theater": "AMER"}, {"name": "Globex", "theater": "EMEA"}]

    def fake_read(name):
        if name == "Acme":
            return {"teams": [{"id": "a"}], "meetings": [], "es_activities": [], "environments": [], "use_cases": []}
        return "No Drive folder found for 'Globex'"  # simulates the 404 string case

    result = build_portfolio_rollup(customers, fake_read, today=TODAY)

    assert len(result) == 2
    acme = next(c for c in result if c["name"] == "Acme")
    globex = next(c for c in result if c["name"] == "Globex")
    assert acme["error"] is None
    assert acme["team_count"] == 1
    assert globex["error"] == "No Drive folder found for 'Globex'"
    assert globex["team_count"] == 0
    assert globex["level"] == "Green"  # placeholder, not a crash


def test_malformed_last_held_date_does_not_crash_and_is_treated_as_overdue():
    team = {"id": "t1"}
    meetings = [{"team_id": "t1", "meeting_type_id": "es104-03-program-team-cadence", "last_held_date": "11/01/2026"}]
    result = compute_team_health(team, meetings, es_activities=[], today=TODAY)
    assert result["overdue_count"] >= 1  # unparseable date treated like no data, not a crash


def test_malformed_open_issues_does_not_crash():
    team = {"id": "t1", "open_issues": "12"}  # a hand-edited Drive file could have a stringified number
    result = compute_team_health(team, meetings=[], es_activities=[], today=TODAY)
    assert result["level"] in ("Green", "Yellow", "Red")  # doesn't raise


def test_build_portfolio_rollup_isolates_an_exception_not_just_a_bad_return_value():
    customers = [{"name": "Acme", "theater": "AMER"}, {"name": "Broken", "theater": "EMEA"}]

    def fake_read(name):
        if name == "Acme":
            return {"teams": [{"id": "a"}], "meetings": [], "es_activities": [], "environments": [], "use_cases": []}
        # "teams": None (a corrupted or hand-edited file) raises a plain
        # TypeError inside compute_account_health well past the specific
        # date/int coercions -- this is the general safety net, not a
        # specific-field guard.
        return {"teams": None, "meetings": [], "es_activities": [], "environments": [], "use_cases": []}

    result = build_portfolio_rollup(customers, fake_read, today=TODAY)

    assert len(result) == 2
    acme = next(c for c in result if c["name"] == "Acme")
    broken = next(c for c in result if c["name"] == "Broken")
    assert acme["error"] is None
    assert broken["error"] is not None
    assert broken["level"] == "Green"
