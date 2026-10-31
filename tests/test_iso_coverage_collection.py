import copy
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('coverage_collection', ROOT / 'scripts/collect-iso-coverage.py')
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)
NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
SHA = 'a' * 40
CELLS = [{'id': f'base:{d}:linux/amd64', 'variant': 'base', 'flavor': d,
          'platform': 'linux/amd64', 'install_admitted': True} for d in ('a', 'b', 'c')]


class API:
    def main_sha(self): return SHA
    def resolve_workflow_id(self): return 7


def receipt(cell=CELLS[0]['id'], status='pass', source=SHA):
    return {'schema_version': 1, 'cell_id': cell, 'stage': 'legacy-luks', 'mode': 'luks',
            'status': status, 'finished_at': '2026-10-22T12:00:00Z', 'source_sha': source,
            'workflow_sha': source, 'source_digest': 'sha256:' + 'b' * 64,
            'media_digest': 'sha256:' + 'c' * 64, 'installer_digest': 'sha256:' + 'd' * 64,
            'repository': 'tuna-os/tunaOS', 'run_id': 1, 'run_attempt': 1, 'artifact_id': 2,
            'artifact_digest': 'sha256:' + 'e' * 64, 'evidence_available': True,
            'evidence_expires_at': '2027-01-01T00:00:00Z',
            'checks': {key: status == 'pass' for key in ('backend_install', 'installed_boot', 'passphrase_unlock')}}


def collect(monkeypatch, receipts=(), complete=True):
    monkeypatch.setattr(collector, 'discover_import', lambda *a, **k: {
        'receipts': list(receipts), 'complete_history': complete, 'rejected': []})
    return collector.reconstruct(API(), CELLS, SHA, NOW)


def test_bootstrap_measures_inputs_without_claiming_fresh(monkeypatch):
    report = collect(monkeypatch)
    assert len(report['selected']) == 2
    assert all(row['status'] == 'unresolved-inputs' for row in report['freshness']['cells'])
    assert report['execution_ready']


def test_current_trusted_measurement_fresh_but_never_strict_gui(monkeypatch):
    report = collect(monkeypatch, [receipt()])
    assert report['freshness']['cells'][0]['status'] == 'fresh'
    assert CELLS[0] not in report['selected']
    assert report['strict_gui_status'].startswith('unqualified')


def test_new_revision_does_not_reuse_green_or_reset_fairness(monkeypatch):
    report = collect(monkeypatch, [receipt(source='f' * 40)])
    assert report['freshness']['cells'][0]['status'] == 'unresolved-inputs'
    assert [c['flavor'] for c in report['selected']] == ['b', 'c']


def test_failure_before_media_capture_advances_queue_without_invented_inputs(monkeypatch):
    failed = receipt(status='infra')
    for key in ('source_digest', 'media_digest', 'installer_digest'):
        failed[key] = None
    report = collect(monkeypatch, [failed])
    assert report['freshness']['cells'][0]['status'] != 'fresh'
    assert [c['flavor'] for c in report['selected']] == ['b', 'c']


def test_partial_discovery_blocks_execution(monkeypatch):
    report = collect(monkeypatch, [receipt()], complete=False)
    assert not report['execution_ready'] and report['selected'] == []


def test_stale_or_draft_checkout_cannot_execute():
    with pytest.raises(ValueError, match='current main'):
        collector.reconstruct(API(), CELLS, 'b' * 40, NOW)


def test_repeated_same_day_dispatch_cannot_spend_daily_budget_twice(monkeypatch):
    attempts = [receipt(cell=c['id'], status='infra') for c in CELLS[:2]]
    for index, item in enumerate(attempts):
        item['finished_at'] = '2026-10-23T10:00:00Z'
        item['run_id'] = index + 10
    report = collect(monkeypatch, attempts)
    assert report['remaining_daily_cells'] == 0
    assert report['selected'] == []


def test_authenticated_historical_attempts_preserve_budget_not_freshness(monkeypatch):
    prior = [receipt(cell=c['id']) for c in CELLS[:2]]
    for item in prior:
        item['finished_at'] = '2026-10-23T10:00:00Z'
    monkeypatch.setattr(collector, 'discover_import', lambda *a, **k: {
        'receipts': [], 'historical_attempts': prior, 'complete_history': True, 'rejected': []})
    report = collector.reconstruct(API(), CELLS, SHA, NOW)
    assert report['selected'] == [] and report['remaining_daily_cells'] == 0
    assert all(row['status'] == 'unresolved-inputs' for row in report['freshness']['cells'])
