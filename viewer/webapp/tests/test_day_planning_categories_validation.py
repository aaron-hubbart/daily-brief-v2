from gdrive_briefs import validate_day_planning_categories, MAX_DAY_PLANNING_CATEGORIES


def test_accepts_one_to_three_valid_categories():
    cats = [{'name': 'Strategic', 'description': 'Big Rocks planning'}]
    cleaned, error = validate_day_planning_categories(cats)
    assert error is None
    assert cleaned == [{'name': 'Strategic', 'description': 'Big Rocks planning'}]


def test_trims_whitespace_in_name_and_description():
    cats = [{'name': '  Strategic  ', 'description': '  Big Rocks  '}]
    cleaned, error = validate_day_planning_categories(cats)
    assert error is None
    assert cleaned == [{'name': 'Strategic', 'description': 'Big Rocks'}]


def test_rejects_empty_list():
    cleaned, error = validate_day_planning_categories([])
    assert cleaned is None
    assert error is not None


def test_rejects_non_list_input():
    assert validate_day_planning_categories(None)[0] is None
    assert validate_day_planning_categories('not a list')[0] is None


def test_rejects_non_dict_entries():
    cleaned, error = validate_day_planning_categories(['just a string'])
    assert cleaned is None
    assert error is not None


def test_rejects_more_than_max_categories():
    assert MAX_DAY_PLANNING_CATEGORIES == 3
    cats = [{'name': f'Cat{i}', 'description': 'desc'} for i in range(4)]
    cleaned, error = validate_day_planning_categories(cats)
    assert cleaned is None
    assert error is not None


def test_rejects_missing_or_blank_name_or_description():
    assert validate_day_planning_categories([{'name': '', 'description': 'x'}])[0] is None
    assert validate_day_planning_categories([{'name': 'x', 'description': '   '}])[0] is None
    assert validate_day_planning_categories([{'description': 'x'}])[0] is None


def test_rejects_case_and_whitespace_insensitive_duplicate_names():
    cats = [
        {'name': 'Strategic', 'description': 'a'},
        {'name': ' strategic ', 'description': 'b'},
    ]
    cleaned, error = validate_day_planning_categories(cats)
    assert cleaned is None
    assert error is not None
