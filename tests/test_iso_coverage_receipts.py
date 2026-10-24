"""Receipt identity and freshness cannot be fabricated by a planned matrix."""
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from lib.iso_coverage_receipts import (required_checks, assess_coverage, merge_receipts,
                                     select_catchup, validate_receipt, read_ledger, update_ledger)

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
IDENTITY = {'source_sha': 'a' * 40, 'workflow_sha': 'b' * 40,
            'installer_digest': 'sha256:' + 'f' * 64, 'source_digest': 'sha256:' + 'c' * 64, 'media_digest': 'sha256:' + 'd' * 64}
CELLS = [{'id': f'base:{name}:linux/amd64', 'install_admitted': True} for name in ('a', 'b', 'c')]
EXPECTED = {c['id']: copy.deepcopy(IDENTITY) for c in CELLS}


def iso(value):
    return value.isoformat().replace('+00:00', 'Z')


def receipt(cell=CELLS[0]['id'], age=1, status='pass', run=10, stage='strict-gui', mode='luks'):
    return {'schema_version': 1, 'cell_id': cell, 'stage': stage, 'mode': mode,
            'status': status, 'finished_at': iso(NOW - timedelta(days=age)),
            **IDENTITY, 'repository': 'tuna-os/tunaOS', 'run_id': run, 'run_attempt': 1,
            'artifact_id': run, 'artifact_digest': 'sha256:' + 'e' * 64,
            'checks': {name: status == 'pass' for name in required_checks(stage, mode)},
            'evidence_available': True, 'evidence_expires_at': iso(NOW + timedelta(days=60))}


def report(receipts=(), cells=CELLS, expected=EXPECTED, now=NOW, **kwargs):
    return assess_coverage(cells, receipts, expected, now, 'strict-gui', 'luks', **kwargs)


def test_missing_then_fresh_then_stale_and_latest_failure():
    assert report()['cells'][0]['status'] == 'missing'
    assert report([receipt()])['cells'][0]['status'] == 'fresh'
    assert report([receipt(age=28)])['cells'][0]['status'] == 'stale'
    result = report([receipt(age=2), receipt(age=1, status='fail', run=11)])['cells'][0]
    assert result['status'] == 'failed'
    assert result['last_success_at'] is None


@pytest.mark.parametrize('field,value', [
    ('source_sha', 'f' * 40), ('workflow_sha', 'f' * 40),
    ('installer_digest', 'sha256:' + '9' * 64), ('source_digest', 'sha256:' + 'f' * 64), ('media_digest', 'sha256:' + 'f' * 64),
])
def test_wrong_input_never_counts_but_actual_attempt_preserves_fairness(field, value):
    wrong = receipt()
    wrong[field] = value
    result = report([wrong])['cells'][0]
    assert result['status'] == 'input-mismatch'
    assert result['last_current_attempt_at'] is None
    assert result['last_attempt_at'] == wrong['finished_at']
    assert select_catchup(report([wrong]), 1)['selected'][0]['cell_id'] == CELLS[1]['id']


def test_different_stage_and_mode_do_not_cover_requested_stage():
    for record in [receipt(stage='legacy-luks'), receipt(mode='plain')]:
        assert report([record])['cells'][0]['status'] == 'missing'


@pytest.mark.parametrize('field,value', [
    ('evidence_available', False), ('evidence_expires_at', iso(NOW)),
])
def test_unavailable_or_expired_artifact_does_not_count(field, value):
    record = receipt()
    record[field] = value
    result = report([record])
    assert result['cells'][0]['status'] == 'missing-evidence'
    assert result['cells'][0]['last_success_at'] is None
    assert len(select_catchup(result)['selected']) == 2


def test_unknown_receipts_cannot_expand_inventory():
    result = report([receipt(cell='invented:kde:linux/amd64')])
    assert len(result['cells']) == len(CELLS)
    assert result['rejected_receipts']
    assert all(c['status'] == 'missing' for c in result['cells'])
    with pytest.raises(ValueError, match='unknown cells'):
        report(expected={**EXPECTED, 'invented': IDENTITY})


def test_conflicting_attempt_invalidates_both_not_latest_wins():
    first, other = receipt(), receipt(status='fail')
    result = report([first, other])
    assert result['cells'][0]['status'] == 'conflicting-evidence'
    assert result['rejected_receipts']
    with pytest.raises(ValueError, match='conflicting'):
        merge_receipts([first], [other], EXPECTED, NOW)


def test_append_dedup_reorder_and_config_growth():
    one, two = receipt(), receipt(cell=CELLS[1]['id'])
    ledger = merge_receipts([one], [two, one], EXPECTED, NOW)
    assert len(ledger) == 2
    assert report(ledger) == report(list(reversed(ledger)), cells=list(reversed(CELLS)))
    cells = CELLS + [{'id': 'new:de:linux/amd64', 'install_admitted': True}]
    result = report(ledger, cells, {**EXPECTED, cells[-1]['id']: IDENTITY})
    assert next(c for c in result['cells'] if c['cell_id'] == cells[-1]['id'])['status'] == 'missing'


def test_missing_inputs_and_unadmitted_cells_are_blocked():
    cells = [*CELLS, {'id': 'base:tuna:linux/amd64', 'install_admitted': False}]
    result = report(cells=cells, expected={CELLS[0]['id']: IDENTITY})
    queue = select_catchup(result)
    assert len(queue['selected']) == 1
    assert {r['status'] for r in queue['blocked']} == {'unsupported', 'unresolved-inputs'}


def test_fair_queue_failure_does_not_starve_other_cells_or_reset_on_missed_days():
    ledger = []
    selected = []
    for offset in (0, 1, 7):
        now = NOW + timedelta(days=offset)
        queue = select_catchup(report(ledger, now=now), capacity=1)
        cell = queue['selected'][0]['cell_id']
        selected.append(cell)
        failed = receipt(cell=cell, status='fail', run=10 + offset)
        failed['finished_at'] = iso(now)
        ledger = merge_receipts(ledger, [failed], EXPECTED, now)
    assert selected == [c['id'] for c in CELLS]
    next_pick = select_catchup(report(ledger, now=NOW + timedelta(days=8)), 1)
    assert next_pick['selected'][0]['cell_id'] == CELLS[0]['id']


@pytest.mark.parametrize('mutation', [
    {'cell_id': []}, {'run_id': True}, {'run_attempt': 0}, {'artifact_id': -1},
    {'repository': 'attacker/repo'}, {'source_sha': 'main'},
    {'finished_at': iso(NOW + timedelta(seconds=1))},
    {'finished_at': '2026-10-22T00:00:00'}, {'extra': 'untrusted'},
    {'checks': {}}, {'evidence_available': 'yes'}, {'schema_version': True},
])
def test_malformed_receipt_rejected(mutation):
    record = receipt()
    record.update(mutation)
    with pytest.raises(ValueError):
        validate_receipt(record, EXPECTED, NOW)
    assert report([record])['rejected_receipts']


def test_pass_requires_every_stage_check_and_queue_budget_is_strict():
    record = receipt()
    record['checks']['cold_boot'] = False
    with pytest.raises(ValueError, match='every required check'):
        validate_receipt(record, EXPECTED, NOW)
    queue = select_catchup(report(), 2)
    assert len(queue['selected']) == 2
    assert len(queue['deferred']) == 1
    with pytest.raises(ValueError):
        select_catchup(report(), 0)


def test_durable_ledger_atomic_validated_append_and_read(tmp_path):
    path = tmp_path / 'coverage.json'
    assert read_ledger(path) == []
    original = receipt()
    assert update_ledger(path, [original], EXPECTED, NOW) == [original]
    assert read_ledger(path) == [original]
    before = path.read_bytes()
    with pytest.raises(ValueError):
        update_ledger(path, [receipt(cell='unknown:cell:linux/amd64')], EXPECTED, NOW)
    assert path.read_bytes() == before
    update_ledger(path, [original], EXPECTED, NOW)
    assert path.read_bytes() == before


def test_interrupted_replace_preserves_old_ledger(tmp_path, monkeypatch):
    from lib import iso_coverage_receipts as module
    path = tmp_path / 'coverage.json'
    update_ledger(path, [receipt()], EXPECTED, NOW)
    before = path.read_bytes()
    def interrupted(*args):
        raise OSError('simulated interruption')
    monkeypatch.setattr(module.os, 'replace', interrupted)
    with pytest.raises(OSError, match='interruption'):
        update_ledger(path, [receipt(cell=CELLS[1]['id'])], EXPECTED, NOW)
    assert path.read_bytes() == before
    assert not list(tmp_path.glob('*.tmp'))


def test_removed_cells_archived_without_reintroducing_them(tmp_path):
    path = tmp_path / 'coverage.json'
    old = receipt()
    update_ledger(path, [old], EXPECTED, NOW)
    remaining = CELLS[1:]
    remaining_inputs = {c['id']: IDENTITY for c in remaining}
    update_ledger(path, [receipt(cell=CELLS[1]['id'])], remaining_inputs, NOW)
    assert len(read_ledger(path)) == 2
    result = report(read_ledger(path), remaining, remaining_inputs)
    assert len(result['cells']) == 2
    assert result['rejected_receipts']
    with pytest.raises(ValueError):
        update_ledger(path, [receipt(run=20)], remaining_inputs, NOW)


@pytest.mark.parametrize('content', ['[]', '{}', '{"schema_version":true,"receipts":[]}', 'partial-json'])
def test_corrupt_durable_ledger_never_resets_to_empty(tmp_path, content):
    path = tmp_path / 'coverage.json'
    path.write_text(content)
    with pytest.raises(ValueError):
        read_ledger(path)
    with pytest.raises(ValueError):
        update_ledger(path, [receipt()], EXPECTED, NOW)
    assert path.read_text() == content


def test_newer_conflicting_attempt_cannot_fall_back_to_older_green():
    older = receipt(age=3, run=9)
    newer_pass, newer_fail = receipt(age=1, run=10), receipt(age=1, run=10, status='fail')
    result = report([older, newer_pass, newer_fail])
    assert result['cells'][0]['status'] == 'conflicting-evidence'
    assert result['cells'][0]['last_success_at'] is None
    assert result['cells'][0]['receipt'] is None
    assert CELLS[0]['id'] in [c['cell_id'] for c in select_catchup(result, 3)['selected']]


@pytest.mark.parametrize('mode,missing', [('plain', 'plain_layout'), ('luks', 'encrypted_layout'), ('luks', 'passphrase_unlock')])
def test_strict_mode_requires_measured_layout_and_unlock(mode, missing):
    record = receipt(mode=mode)
    record['checks'].pop(missing)
    with pytest.raises(ValueError, match='stage contract'):
        validate_receipt(record, EXPECTED, NOW)


def test_newer_invalid_authenticated_receipt_cannot_revive_older_green():
    older = receipt(age=3, run=9)
    newer = receipt(age=1, run=10, status='fail')
    newer.pop('checks')
    result = report([older, newer])
    assert result['cells'][0]['status'] == 'invalid-evidence'
    assert result['cells'][0]['last_success_at'] is None
    assert result['cells'][0]['receipt'] is None
    assert CELLS[0]['id'] in [c['cell_id'] for c in select_catchup(result, 3)['selected']]
    assert result['cells'][1]['status'] == 'missing'


def test_invalid_foreign_cell_cannot_quarantine_known_cell():
    invalid = receipt(cell='foreign:gnome:linux/amd64')
    invalid.pop('checks')
    assert report([receipt(), invalid])['cells'][0]['status'] == 'fresh'


def test_daily_desired_revision_changes_cannot_starve_tail_cells():
    ledger = []
    seen = set()
    for day in range(3):
        now = NOW + timedelta(days=day)
        identity = dict(IDENTITY, source_sha=str(day) * 40)
        expected = {cell['id']: identity for cell in CELLS}
        queue = select_catchup(report(ledger, expected=expected, now=now), 2)
        assert len(queue['selected']) <= 2
        for selected in queue['selected']:
            seen.add(selected['cell_id'])
            record = receipt(cell=selected['cell_id'], run=100 + day)
            record.update(identity, finished_at=iso(now))
            ledger = merge_receipts(ledger, [record], EXPECTED, now)
    assert seen == {c['id'] for c in CELLS}


@pytest.mark.parametrize('status', ['fail', 'infra'])
def test_early_failed_attempt_with_unmeasured_digests_advances_fairness(status):
    record = receipt(status=status)
    for key in ('source_digest', 'media_digest', 'installer_digest'):
        record[key] = None
    assert validate_receipt(record, EXPECTED, NOW) == record
    result = report([record])
    lane = result['cells'][0]
    assert lane['status'] == ('failed' if status == 'fail' else 'infra')
    assert lane['last_attempt_at'] == record['finished_at']
    assert lane['last_current_attempt_at'] is None
    assert lane['last_success_at'] is None
    assert select_catchup(result, 1)['selected'][0]['cell_id'] == CELLS[1]['id']


@pytest.mark.parametrize('status', ['pass', 'unsupported'])
@pytest.mark.parametrize('key', ['source_digest', 'media_digest', 'installer_digest'])
def test_null_identity_cannot_qualify_or_become_expected_input(status, key):
    record = receipt(status=status)
    record[key] = None
    with pytest.raises(ValueError, match='invalid'):
        validate_receipt(record, EXPECTED, NOW)
    bad_expected = copy.deepcopy(EXPECTED)
    bad_expected[CELLS[0]['id']][key] = None
    with pytest.raises(ValueError, match='invalid'):
        report(expected=bad_expected)


@pytest.mark.parametrize('key', ['source_sha', 'workflow_sha'])
def test_early_failure_cannot_omit_api_bound_commit_identity(key):
    record = receipt(status='infra')
    record[key] = None
    with pytest.raises(ValueError, match='invalid'):
        validate_receipt(record, EXPECTED, NOW)
