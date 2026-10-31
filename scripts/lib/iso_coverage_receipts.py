"""Fail-closed coverage receipts and fair bounded catch-up planning.

JSON validity is not producer authentication. The caller must authenticate workflow
run/artifact provenance before importing receipts, and resolve expected immutable
inputs independently. Receipt data NEVER supplies new matrix cells or expectations.
Persist merged receipts atomically in an authenticated, durable store; a plan is
not an attempt, and failed attempts must also be retained to ensure fair retries.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import copy
import json
import os
from pathlib import Path
import re
import tempfile

UTC = timezone.utc
SHA = re.compile(r'[0-9a-f]{40}\Z')
DIGEST = re.compile(r'sha256:[0-9a-f]{64}\Z')
IDENTITY_FIELDS = ('source_sha', 'source_digest', 'media_digest', 'installer_digest', 'workflow_sha')
RECEIPT_FIELDS = {
    'schema_version', 'cell_id', 'stage', 'mode', 'status', 'finished_at',
    'source_sha', 'source_digest', 'media_digest', 'installer_digest', 'workflow_sha',
    'repository', 'run_id', 'run_attempt', 'artifact_id', 'artifact_digest',
    'checks', 'evidence_available', 'evidence_expires_at',
}
STAGE_CHECKS = {
    'legacy-luks': {'backend_install', 'installed_boot', 'passphrase_unlock'},
    'strict-gui': {'offline', 'gui_install', 'iso_detached', 'cold_boot', 'warm_boot', 'identity'},
}
STATUSES = {'pass', 'fail', 'infra', 'unsupported'}


def required_checks(stage, mode):
    checks = set(STAGE_CHECKS[stage])
    if stage == 'strict-gui':
        checks |= {'plain_layout'} if mode == 'plain' else {'encrypted_layout', 'passphrase_unlock'}
    return checks


def timestamp(value):
    """Require explicit UTC ISO timestamps; reject naive/local wall time."""
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z', value):
        raise ValueError('timestamp must use UTC Z')
    try:
        parsed = datetime.fromisoformat(value[:-1] + '+00:00')
    except ValueError as error:
        raise ValueError('invalid timestamp') from error
    return parsed


def utc_now(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError('now must be an aware UTC datetime')
    return value


def validate_identity(value):
    if not isinstance(value, dict) or set(value) != set(IDENTITY_FIELDS):
        raise ValueError('expected inputs must contain exactly the immutable identity fields')
    for field in IDENTITY_FIELDS:
        pattern = SHA if field.endswith('_sha') else DIGEST
        if not isinstance(value[field], str) or not pattern.fullmatch(value[field]):
            raise ValueError(f'invalid {field}')


def validate_receipt(receipt, known_cell_ids, now, repository='tuna-os/tunaOS'):
    """Return a copy or raise; an admissible receipt still needs origin verification."""
    now = utc_now(now)
    if not isinstance(receipt, dict) or set(receipt) != RECEIPT_FIELDS:
        raise ValueError('receipt fields do not match schema')
    if type(receipt['schema_version']) is not int or receipt['schema_version'] != 1:
        raise ValueError('unsupported receipt schema')
    if not isinstance(receipt['cell_id'], str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]*:[a-z0-9][a-z0-9-]*:linux/(?:amd64(?:/v[23])?|arm64)', receipt['cell_id']):
        raise ValueError('invalid cell identifier')
    if receipt['cell_id'] not in known_cell_ids:
        raise ValueError('receipt cell is not in authoritative inventory')
    stage, mode = receipt['stage'], receipt['mode']
    if not isinstance(stage, str) or not isinstance(mode, str) or stage not in STAGE_CHECKS or mode not in {'plain', 'luks'} or (stage == 'legacy-luks' and mode != 'luks'):
        raise ValueError('unsupported stage/mode')
    if not isinstance(receipt['status'], str) or receipt['status'] not in STATUSES:
        raise ValueError('invalid receipt status')
    if receipt['repository'] != repository:
        raise ValueError('wrong repository')
    # A failed build can finish before ISO/source/installer digests exist. Keep
    # that authenticated attempt for scheduling fairness without inventing bytes.
    # Only these explicitly nonqualifying statuses may omit measured digests.
    for field in IDENTITY_FIELDS:
        value = receipt[field]
        if value is None and field.endswith('_digest') and receipt['status'] in {'fail', 'infra'}:
            continue
        pattern = SHA if field.endswith('_sha') else DIGEST
        if not isinstance(value, str) or not pattern.fullmatch(value):
            raise ValueError(f'invalid {field}')
    if not isinstance(receipt['artifact_digest'], str) or not DIGEST.fullmatch(receipt['artifact_digest']):
        raise ValueError('invalid artifact digest')
    for key in ('run_id', 'run_attempt', 'artifact_id'):
        if type(receipt[key]) is not int or receipt[key] < 1:
            raise ValueError(f'{key} must be a positive integer')
    if timestamp(receipt['finished_at']) > now:
        raise ValueError('receipt finishes in the future')
    if type(receipt['evidence_available']) is not bool:
        raise ValueError('evidence_available must be boolean')
    if timestamp(receipt['evidence_expires_at']) <= timestamp(receipt['finished_at']):
        raise ValueError('evidence expiry must follow receipt completion')
    checks = receipt['checks']
    if not isinstance(checks, dict) or set(checks) != required_checks(stage, mode) or any(type(v) is not bool for v in checks.values()):
        raise ValueError('checks do not match stage contract')
    if receipt['status'] == 'pass' and not all(checks.values()):
        raise ValueError('pass receipt does not establish every required check')
    return copy.deepcopy(receipt)


def receipt_key(receipt):
    return (receipt['cell_id'], receipt['stage'], receipt['mode'], receipt['run_id'], receipt['run_attempt'])


def merge_receipts(existing, incoming, known_cell_ids, now):
    """Preserve removed historical cells; reject unknown incoming cells and conflicts."""
    merged = {}
    for historical, receipt in [(True, r) for r in existing] + [(False, r) for r in incoming]:
        # Removed cells remain archived but can never re-enter current inventory.
        # Only previously admitted ledger history gets this structural-only check.
        ids = {receipt.get('cell_id')} if historical and isinstance(receipt, dict) and isinstance(receipt.get('cell_id'), str) else known_cell_ids
        record = validate_receipt(receipt, ids, now)
        key = receipt_key(record)
        if key in merged and merged[key] != record:
            raise ValueError('conflicting receipts for the same cell/run/attempt')
        merged[key] = record
    return sorted(merged.values(), key=lambda r: (timestamp(r['finished_at']), receipt_key(r)))


def assess_coverage(inventory, receipts, expected_inputs, now, stage, mode, freshness_days=28):
    """Report latest matching-stage attempts against independently resolved identities.

    A newer failure supersedes an older pass. Changed source/media/workflow identity
    invalidates old passes. An unsupported/missing expectation is not inferred from
    a receipt. Invalid receipts are visible diagnostics, never accepted as coverage.
    """
    now = utc_now(now)
    if not isinstance(stage, str) or not isinstance(mode, str) or stage not in STAGE_CHECKS or mode not in {'plain', 'luks'} or (stage == 'legacy-luks' and mode != 'luks'):
        raise ValueError('unsupported stage/mode')
    if type(freshness_days) is not int or freshness_days < 1:
        raise ValueError('freshness_days must be a positive integer')
    cells = {cell['id']: cell for cell in inventory}
    if len(cells) != len(inventory):
        raise ValueError('duplicate inventory cells')
    if not set(expected_inputs).issubset(cells):
        raise ValueError('expected inputs contain unknown cells')
    for identity in expected_inputs.values():
        validate_identity(identity)
    valid, rejected, unique, invalid = [], [], {}, []
    for index, receipt in enumerate(receipts):
        try:
            record = validate_receipt(receipt, cells, now)
            key = receipt_key(record)
            if key in unique and unique[key] != record:
                raise ValueError('conflicting receipts for the same cell/run/attempt')
            unique[key] = record
        except (ValueError, TypeError) as error:
            rejected.append({'index': index, 'reason': str(error)})
            if not str(error).startswith('conflicting receipts'):
                invalid.append(receipt)
    # A contradictory attempt cannot be trusted even if one copy said pass.
    conflicted = set()
    for receipt in receipts:
        if isinstance(receipt, dict):
            try:
                key = receipt_key(receipt)
                if key in unique and unique[key] != receipt:
                    conflicted.add(key)
            except (KeyError, TypeError):
                pass
    valid = [r for key, r in unique.items() if key not in conflicted]
    results = []
    for cell_id, cell in sorted(cells.items()):
        relevant = [r for r in valid if r['cell_id'] == cell_id and r['stage'] == stage and r['mode'] == mode]
        latest = max(relevant, key=lambda r: (timestamp(r['finished_at']), r['run_id'], r['run_attempt']), default=None)
        result = {'cell_id': cell_id, 'stage': stage, 'mode': mode, 'status': 'missing',
                  'last_attempt_at': latest['finished_at'] if latest else None,
                  'last_success_at': None, 'last_current_attempt_at': None, 'receipt': latest}
        if cell_id in expected_inputs:
            matching = [r for r in relevant if all(r[k] == expected_inputs[cell_id][k] for k in IDENTITY_FIELDS)]
            if matching:
                result['last_current_attempt_at'] = max(matching, key=lambda r: timestamp(r['finished_at']))['finished_at']
        if not cell.get('install_admitted'):
            result['status'] = 'unsupported'
        elif cell_id not in expected_inputs:
            result['status'] = 'unresolved-inputs'
        elif latest:
            identity = expected_inputs[cell_id]
            if latest['status'] in {'fail', 'infra'} and any(latest[k] is None for k in IDENTITY_FIELDS):
                result['status'] = 'failed' if latest['status'] == 'fail' else 'infra'
            elif any(latest[key] != identity[key] for key in IDENTITY_FIELDS):
                result['status'] = 'input-mismatch'
            elif latest['status'] != 'pass':
                result['status'] = {'fail': 'failed', 'infra': 'infra', 'unsupported': 'unsupported'}[latest['status']]
            elif not latest['evidence_available'] or timestamp(latest['evidence_expires_at']) <= now:
                result['status'] = 'missing-evidence'
            else:
                result['last_success_at'] = latest['finished_at']
                result['status'] = 'fresh' if now - timestamp(latest['finished_at']) < timedelta(days=freshness_days) else 'stale'
        conflicting = [r for key, r in unique.items() if key in conflicted and r['cell_id'] == cell_id and r['stage'] == stage and r['mode'] == mode]
        newest_conflict = max(conflicting, key=lambda r: timestamp(r['finished_at']), default=None)
        if (newest_conflict is not None and cell.get('install_admitted')
                and (latest is None or timestamp(newest_conflict['finished_at']) >= timestamp(latest['finished_at']))):
            result['status'] = 'conflicting-evidence'
            result['last_success_at'] = None
            result['receipt'] = None
        for invalid_record in invalid:
            if (isinstance(invalid_record, dict) and invalid_record.get('cell_id') == cell_id
                    and invalid_record.get('stage') == stage and invalid_record.get('mode') == mode):
                try:
                    invalid_time = timestamp(invalid_record.get('finished_at'))
                except ValueError:
                    invalid_time = None
                if latest is None or invalid_time is None or invalid_time >= timestamp(latest['finished_at']):
                    result['status'] = 'invalid-evidence'
                    result['last_success_at'] = None
                    result['receipt'] = None
        results.append(result)
    return {'schema_version': 1, 'stage': stage, 'mode': mode,
            'as_of': now.isoformat().replace('+00:00', 'Z'),
            'freshness_days': freshness_days, 'cells': results, 'rejected_receipts': rejected}


def select_catchup(report, capacity=2):
    """Least-recently attempted first, bounded; every failure consumes a turn.

    Never-attempted cells sort first, then stale/failed/mismatched cells by last
    authenticated attempt regardless of source revision. Freshness still requires
    current inputs; daily desired revisions must not reset scheduling age.
    This avoids a permanently failing first cell monopolizing retries. Progress
    requires durable attempt receipts; scheduled-but-never-run is not an attempt.
    Unsupported and unresolved-input cells are returned as blocked, not executed.
    """
    if type(capacity) is not int or capacity < 1:
        raise ValueError('capacity must be a positive integer')
    eligible = [r for r in report['cells'] if r['status'] in {'missing', 'stale', 'failed', 'infra', 'input-mismatch', 'missing-evidence', 'conflicting-evidence', 'invalid-evidence'}]
    ordered = sorted(eligible, key=lambda r: (timestamp(r['last_attempt_at']) if r['last_attempt_at'] else datetime.min.replace(tzinfo=UTC), r['cell_id']))
    return {'selected': ordered[:capacity], 'deferred': ordered[capacity:],
            'blocked': [r for r in report['cells'] if r['status'] in {'unsupported', 'unresolved-inputs'}],
            'capacity': capacity}


def read_ledger(path):
    """Read the canonical durable wrapper; missing file means no evidence, not pass."""
    path = Path(path)
    if not path.exists():
        return []
    try:
        document = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise ValueError(f'unreadable coverage ledger: {path}') from error
    if (not isinstance(document, dict) or set(document) != {'schema_version', 'receipts'}
            or type(document['schema_version']) is not int or document['schema_version'] != 1
            or not isinstance(document['receipts'], list)):
        raise ValueError('coverage ledger schema mismatch')
    return document['receipts']


def update_ledger(path, incoming, known_cell_ids, now):
    """Validate then atomically append receipts, with an exclusive writer lock.

    The caller authenticates both the retained ledger and incoming artifacts.
    Same-directory temporary write + file fsync + replace + directory fsync avoids
    partial JSON on interruption. Invalid updates never replace existing bytes.
    POSIX flock serializes readers of old state inside concurrent updates.
    """
    import fcntl

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + '.lock')
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        merged = merge_receipts(read_ledger(path), incoming, known_cell_ids, now)
        document = {'schema_version': 1, 'receipts': merged}
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                             prefix=path.name + '.', suffix='.tmp', delete=False) as stream:
                temporary = stream.name
                json.dump(document, stream, sort_keys=True, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            temporary = None
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if temporary is not None:
                os.unlink(temporary)
        return merged
