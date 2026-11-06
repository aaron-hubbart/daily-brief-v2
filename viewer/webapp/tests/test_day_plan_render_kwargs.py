import ast
from pathlib import Path


def _load_day_plan_render_kwargs():
    src = (Path(__file__).resolve().parent.parent / 'app.py').read_text(encoding='utf-8')
    node = next(n for n in ast.parse(src).body
                if isinstance(n, ast.FunctionDef) and n.name == '_day_plan_render_kwargs')
    ns = {}
    exec(compile(ast.Module([node], []), 'app.py', 'exec'), ns)
    return ns['_day_plan_render_kwargs']


_day_plan_render_kwargs = _load_day_plan_render_kwargs()


def test_fills_missing_fields_with_empty_defaults():
    kwargs = _day_plan_render_kwargs({}, dict_fields=('stats',), list_fields=('recommendations',))
    assert kwargs == {'stats': {}, 'recommendations': []}


def test_treats_null_value_as_missing():
    kwargs = _day_plan_render_kwargs(
        {'stats': None, 'recommendations': None}, dict_fields=('stats',), list_fields=('recommendations',),
    )
    assert kwargs == {'stats': {}, 'recommendations': []}


def test_passes_through_present_values_unchanged():
    data = {'stats': {'day_score': 8}, 'recommendations': [{'text': 'x'}]}
    kwargs = _day_plan_render_kwargs(data, dict_fields=('stats',), list_fields=('recommendations',))
    assert kwargs == {'stats': {'day_score': 8}, 'recommendations': [{'text': 'x'}]}


def test_ignores_fields_not_asked_for():
    kwargs = _day_plan_render_kwargs({'extra': 'ignored'}, dict_fields=(), list_fields=())
    assert kwargs == {}
