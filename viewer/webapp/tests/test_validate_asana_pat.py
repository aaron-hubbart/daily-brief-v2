import ast
import io
import logging
import socket
import urllib.error
from unittest import mock

import pytest

from pathlib import Path
from types import SimpleNamespace


def _load_validator():
    """app.py connects to Postgres at import time, so pull the function out
    of its source instead of importing the module."""
    src = (Path(__file__).resolve().parent.parent / 'app.py').read_text(encoding='utf-8')
    node = next(n for n in ast.parse(src).body
                if isinstance(n, ast.FunctionDef) and n.name == '_validate_asana_pat')
    ns = {'urllib': urllib, 'logger': logging.getLogger('test'), '_asana_api_get': None}
    exec(compile(ast.Module([node], []), 'app.py', 'exec'), ns)
    return ns


viewer_app = SimpleNamespace()
_ns = _load_validator()
viewer_app._validate_asana_pat = _ns['_validate_asana_pat']


def _http_error(code):
    return urllib.error.HTTPError('u', code, 'x', {}, io.BytesIO(b'{}'))


def test_valid_token_returns_user():
    with mock.patch.dict(_ns, {'_asana_api_get': mock.Mock(return_value={'data': {'name': 'A'}})}):
        assert viewer_app._validate_asana_pat('t') == ({'name': 'A'}, None)


@pytest.mark.parametrize('code', [401, 403])
def test_rejected_token_is_invalid(code):
    with mock.patch.dict(_ns, {'_asana_api_get': mock.Mock(side_effect=_http_error(code))}):
        assert viewer_app._validate_asana_pat('t') == (None, 'invalid')


@pytest.mark.parametrize('exc', [
    _http_error(500), urllib.error.URLError('dns'), socket.timeout(), ValueError('bad json'),
])
def test_transport_failures_are_unreachable(exc):
    with mock.patch.dict(_ns, {'_asana_api_get': mock.Mock(side_effect=exc)}):
        assert viewer_app._validate_asana_pat('t') == (None, 'unreachable')


def test_empty_data_is_unreachable():
    with mock.patch.dict(_ns, {'_asana_api_get': mock.Mock(return_value={})}):
        assert viewer_app._validate_asana_pat('t') == (None, 'unreachable')
