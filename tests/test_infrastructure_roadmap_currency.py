"""Currency boundaries, pagination and API failures for #3230."""
import datetime as dt
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    'currency', Path(__file__).parents[1] / 'scripts/infrastructure-roadmap-currency.py')
currency = importlib.util.module_from_spec(spec)
spec.loader.exec_module(currency)


def test_report_paginates_and_uses_default_branch(monkeypatch):
    monkeypatch.setattr(currency, 'PROJECTS', ('example',))
    seen = []

    def api(path):
        seen.append(path)
        if path == 'repos/tuna-os/example':
            return {'default_branch': 'dev'}
        if '/commits?' in path:
            return [{'commit': {'committer': {'date': '2026-09-30T00:00:00Z'}},
                     'html_url': 'https://example.com/commit'}]
        if '&page=1' in path:
            return [{'labels': [], 'created_at': '2026-10-01T00:00:00Z'}] * 100
        return [{'labels': [{'name': 'p0'}], 'created_at': '2026-10-17T00:00:00Z',
                 'number': 1, 'html_url': 'https://example.com/issue'}]

    monkeypatch.setattr(currency, 'api', api)
    result = currency.report(dt.date(2026, 10, 24))
    assert 'review due' in result
    assert 'open 7 days' in result
    assert any('sha=dev' in path for path in seen)
    assert any('page=2' in path for path in seen)


def test_api_failure_is_not_healthy_report(monkeypatch):
    def fail(path):
        raise RuntimeError('unavailable')
    monkeypatch.setattr(currency, 'api', fail)
    with pytest.raises(RuntimeError, match='unavailable'):
        currency.report(dt.date(2026, 10, 24))


def test_age_boundary():
    assert currency.age_days('2026-10-18T23:59:59Z', dt.date(2026, 10, 24)) == 6
