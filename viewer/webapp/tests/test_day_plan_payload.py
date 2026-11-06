import ast
from pathlib import Path


def _load_day_plan_payload():
    src = (Path(__file__).resolve().parent.parent / 'app.py').read_text(encoding='utf-8')
    node = next(n for n in ast.parse(src).body
                if isinstance(n, ast.FunctionDef) and n.name == '_day_plan_payload')
    ns = {}
    exec(compile(ast.Module([node], []), 'app.py', 'exec'), ns)
    return ns['_day_plan_payload']


_day_plan_payload = _load_day_plan_payload()


def test_no_sections_means_not_available():
    assert _day_plan_payload([]) == (False, None)


def test_drive_error_means_not_available():
    assert _day_plan_payload(None) == (False, None)


def test_populated_sections_returns_the_single_dict():
    data = {'stats': {}, 'recommendations': []}
    assert _day_plan_payload([data]) == (True, data)


def test_non_dict_single_item_is_not_available():
    # A malformed Drive file (e.g. the skill wrote a bare string or a
    # {"items": [...]} list that _extract_items unwrapped to its first
    # non-dict element) must not be treated as a valid day-plan payload.
    assert _day_plan_payload(['just a string']) == (False, None)
    assert _day_plan_payload([42]) == (False, None)
