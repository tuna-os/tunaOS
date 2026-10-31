"""Bounded GitHub Actions receipt import through an injected authenticated API.

The API adapter, not receipt JSON, establishes repository/run/workflow identity.
No network access occurs in this module; the caller supplies authenticated GitHub
API methods. Only configured producer workflows on main may supply candidates.
A successful workflow is never itself a qualification receipt.
"""
from __future__ import annotations

from datetime import timedelta
import hashlib
import io
import json
import re
import zipfile

from lib.iso_coverage_receipts import (
    RECEIPT_FIELDS, timestamp, utc_now, validate_receipt, required_checks,
)

REPOSITORY = 'tuna-os/tunaOS'
TRANSPORT_FIELDS = {'artifact_id', 'artifact_digest', 'evidence_available', 'evidence_expires_at'}
PRODUCER_FIELDS = RECEIPT_FIELDS - TRANSPORT_FIELDS
MAX_ARCHIVE_BYTES = 1024 * 1024
MAX_RECEIPT_BYTES = 1024 * 1024


def _bound_payload(run, artifact, archive, now, member_name, name_pattern):
    """Verify transport identity before interpreting either plan or receipt data."""
    if not isinstance(archive, bytes) or len(archive) > MAX_ARCHIVE_BYTES:
        raise ValueError('artifact exceeds bounded archive size')
    if type(artifact.get('size_in_bytes')) is not int or artifact['size_in_bytes'] != len(archive):
        raise ValueError('artifact API size mismatch')
    digest = 'sha256:' + hashlib.sha256(archive).hexdigest()
    if artifact.get('digest') != digest:
        raise ValueError('artifact archive digest does not match API')
    if type(artifact.get('id')) is not int or artifact['id'] < 1:
        raise ValueError('artifact ID is invalid')
    if artifact.get('expired') is not False or timestamp(artifact['expires_at']) <= now:
        raise ValueError('artifact expired or expiration unestablished')
    name = artifact.get('name', '')
    if not isinstance(name, str) or not re.fullmatch(name_pattern, name):
        raise ValueError('artifact name is not bound to API run attempt')
    workflow_run = artifact.get('workflow_run', {})
    if (not isinstance(workflow_run, dict) or workflow_run.get('id') != run['id'] or workflow_run.get('head_sha') != run['head_sha']
            or workflow_run.get('head_branch') != 'main'):
        raise ValueError('artifact API workflow binding mismatch')
    started, ended = timestamp(run['run_started_at']), timestamp(run['updated_at'])
    created = timestamp(artifact['created_at'])
    if not started <= created <= ended <= now:
        raise ValueError('artifact creation outside authoritative run-attempt window')
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            members = bundle.infolist()
            if len(members) != 1 or members[0].filename != member_name:
                raise ValueError(f'artifact must contain exactly {member_name}, no paths or duplicate members')
            member = members[0]
            if member.file_size > MAX_RECEIPT_BYTES or member.is_dir() or member.flag_bits & 1:
                raise ValueError('receipt member oversized, directory, or encrypted')
            # Reject Unix symlinks even though we never extract files to disk.
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('receipt member cannot be a symlink')
            with bundle.open(member) as stream:
                payload_bytes = stream.read(MAX_RECEIPT_BYTES + 1)
            if len(payload_bytes) > MAX_RECEIPT_BYTES:
                raise ValueError('receipt decompression exceeds bound')
            payload = json.loads(payload_bytes)
    except (zipfile.BadZipFile, UnicodeError, json.JSONDecodeError, RuntimeError) as error:
        raise ValueError('invalid receipt archive') from error
    return payload, digest


def bind_artifact(run, artifact, archive, known_cell_ids, now):
    """Bind one exact API artifact to its producer payload, then validate checks."""
    pattern = rf"iso-coverage-receipt-{run['id']}-{run['run_attempt']}-[A-Za-z0-9_-]+"
    payload, digest = _bound_payload(run, artifact, archive, now, 'receipt.json', pattern)
    started, ended = timestamp(run['run_started_at']), timestamp(run['updated_at'])
    if not isinstance(payload, dict) or set(payload) != PRODUCER_FIELDS:
        raise ValueError('producer payload schema mismatch; transport identity must come from API')
    if (payload['repository'] != REPOSITORY or payload['run_id'] != run['id']
            or payload['run_attempt'] != run['run_attempt'] or payload['workflow_sha'] != run['head_sha']):
        raise ValueError('producer payload does not match authenticated API identity')
    if not started <= timestamp(payload['finished_at']) <= ended:
        raise ValueError('receipt completion outside authoritative run attempt')
    receipt = dict(payload, artifact_id=artifact['id'], artifact_digest=digest,
                   evidence_available=True, evidence_expires_at=artifact['expires_at'])
    return validate_receipt(receipt, known_cell_ids, now)


def bind_plan(run, artifact, archive, inventory, now):
    """Authenticate expected attempts without accepting receipt-invented cells."""
    pattern = rf"iso-coverage-plan-{run['id']}-{run['run_attempt']}"
    payload, _ = _bound_payload(run, artifact, archive, now, 'coverage-plan.json', pattern)
    if (not isinstance(payload, dict) or type(payload.get('schema_version')) is not int
            or payload['schema_version'] != 1 or not isinstance(payload.get('selected'), list)):
        raise ValueError('plan payload schema mismatch')
    ready = payload.get('execution_ready', False)
    if type(ready) is not bool:
        raise ValueError('plan execution_ready must be boolean')
    known = {cell['id']: cell for cell in inventory}
    selected = []
    for cell in payload['selected']:
        if (not isinstance(cell, dict) or not isinstance(cell.get('id'), str)
                or cell['id'] not in known or not known[cell['id']].get('install_admitted')):
            raise ValueError('plan selected unknown or unadmitted cell')
        selected.append(cell['id'])
    if len(set(selected)) != len(selected) or len(selected) > 2:
        raise ValueError('plan selection duplicated or exceeds two-cell budget')
    return set(selected) if ready else set()


def discover_import(api, inventory, now, allowed_workflow_ids, max_runs=200,
                    max_artifacts=2000, lookback_days=90):
    """Discover immutable receipts, never expand the caller's inventory.

    API methods (all authenticated, repository scoped):
      list_runs(repository, workflow_id, branch, since, page, per_page)
        -> {total_count: int, workflow_runs: [GitHub run objects]}
      list_artifacts(repository, run_id, page, per_page)
        -> {total_count: int, artifacts: [GitHub artifact objects]}
      download_artifact(repository, artifact_id) -> archive bytes
      get_attempt(repository, run_id, attempt) -> authenticated GitHub attempt object

    Bounds cover ALL queried runs/artifacts, not only matching receipts. API
    failures, truncation, invalid/expired matching artifacts are visible errors;
    complete_history=False means the caller MUST NOT publish a green coverage
    summary or silently retain old freshness. No assumed GitHub pagination order.
    Only current attempt receipts enter qualification. Retained older attempts
    use separately authenticated API attempt windows, enter historical_attempts
    for scheduling age/quota ONLY, and never enter receipts/freshness. Lookup
    count is capped at ten historical attempts per run.
    Every producer run must have an authenticated plan. A terminal failed run
    lacking a planned cell receipt yields an explicit nonqualifying infra budget
    reservation (not proof tests started); success without receipts is incomplete.
    """
    now = utc_now(now)
    if (not allowed_workflow_ids or any(type(v) is not int or v < 1 for v in allowed_workflow_ids)
            or type(max_runs) is not int or max_runs < 1
            or type(max_artifacts) is not int or max_artifacts < 1
            or type(lookback_days) is not int or lookback_days < 28):
        raise ValueError('invalid discovery allowlist or bounds')
    known = {c['id'] for c in inventory}
    since = (now - timedelta(days=lookback_days)).isoformat().replace('+00:00', 'Z')
    receipts, rejected, skipped, recovered_attempts, historical_attempts = [], [], [], [], []
    scanned_runs = scanned_artifacts = 0
    seen_runs, seen_artifacts = set(), set()

    def reject(kind, identity, reason):
        rejected.append({'kind': kind, 'id': identity, 'reason': str(reason)})

    def pages(method, array_key, bound, *args):
        page, observed, expected_total = 1, 0, None
        while True:
            response = method(*args, page=page, per_page=min(50, bound))
            if not isinstance(response, dict) or type(response.get('total_count')) is not int or response['total_count'] < 0 or not isinstance(response.get(array_key), list):
                raise ValueError('malformed API pagination response')
            if expected_total is not None and response['total_count'] != expected_total:
                raise ValueError('API pagination changed during discovery; retry a consistent window')
            expected_total = response['total_count']
            records = response[array_key]
            if not records and observed < expected_total:
                raise ValueError('API pagination ended before declared total')
            if len(records) > bound - observed:
                raise ValueError('discovery bound exceeded; history is incomplete')
            observed += len(records)
            for record in records:
                yield record
            if observed >= expected_total:
                if observed != expected_total:
                    raise ValueError('API pagination exceeds declared total')
                break
            if observed >= bound:
                raise ValueError('discovery bound exceeded; history is incomplete')
            page += 1

    def validate_producer(run, workflow_id):
        if (run['repository']['full_name'] != REPOSITORY or run['workflow_id'] != workflow_id
                or run['head_branch'] != 'main' or run['status'] != 'completed'
                or run['event'] not in {'push', 'schedule', 'workflow_dispatch', 'workflow_run'}
                or run['head_repository']['full_name'] != REPOSITORY
                or type(run['run_attempt']) is not int or run['run_attempt'] < 1
                or not re.fullmatch(r'[0-9a-f]{40}', run['head_sha'])):
            raise ValueError('run not an allowed completed main producer')
        if not timestamp(since) <= timestamp(run['created_at']) <= now:
            raise ValueError('run outside requested discovery window')

    def reconcile(run, attempt_receipts, attempt_plans, historical=False):
        run_id = run['id']
        target = historical_attempts if historical else receipts
        target.extend(attempt_receipts)
        if not attempt_plans and not attempt_receipts and hasattr(api, 'list_jobs'):
            jobs = list(pages(api.list_jobs, 'jobs', 20, REPOSITORY, run_id, run['run_attempt']))
            if jobs and all(isinstance(job, dict) and job.get('run_id') == run_id
                            and job.get('status') == 'completed' and job.get('conclusion') == 'skipped'
                            and not job.get('steps') for job in jobs):
                skipped.append({'kind': 'run', 'id': run_id,
                                'reason': 'API proves every job skipped; no execution reservation'})
                return
        if len(attempt_plans) != 1:
            reject('run', run_id, 'exactly one authenticated plan artifact is required for attempt ' + str(run['run_attempt']))
        else:
            found = {r['cell_id'] for r in attempt_receipts if r['stage'] == 'legacy-luks' and r['mode'] == 'luks'}
            expected, plan_artifact = attempt_plans[0]
            unexpected = found - expected
            if unexpected:
                reject('run', run_id, 'receipts outside authenticated plan: ' + ', '.join(sorted(unexpected)))
            missing = expected - found
            if missing and run.get('conclusion') in {'failure', 'cancelled', 'timed_out'}:
                # Authenticated plan reservation + terminal API failure is
                # evidence of budget reservation, NOT that tests started.
                # Retain an explicitly nonqualifying infra attempt so the
                # same early-cancelled cells cannot monopolize scheduling.
                for cell_id in sorted(missing):
                    recovered = {
                        'schema_version': 1, 'cell_id': cell_id, 'stage': 'legacy-luks',
                        'mode': 'luks', 'status': 'infra', 'finished_at': run['updated_at'],
                        'source_sha': run['head_sha'], 'workflow_sha': run['head_sha'],
                        'source_digest': None, 'media_digest': None, 'installer_digest': None,
                        'repository': REPOSITORY, 'run_id': run_id, 'run_attempt': run['run_attempt'],
                        'artifact_id': plan_artifact['id'], 'artifact_digest': plan_artifact['digest'],
                        'evidence_available': True, 'evidence_expires_at': plan_artifact['expires_at'],
                        'checks': {key: False for key in required_checks('legacy-luks', 'luks')},
                    }
                    target.append(validate_receipt(recovered, known, now))
                    recovered_attempts.append({'cell_id': cell_id, 'run_id': run_id,
                        'run_attempt': run['run_attempt'], 'origin': 'api-plan-terminal-run',
                        'reason': 'nonqualifying budget reservation; test execution not established'})
            elif missing:
                reject('run', run_id, 'missing expected cell receipts: ' + ', '.join(sorted(missing)))

    for workflow_id in sorted(set(allowed_workflow_ids)):
        if scanned_runs >= max_runs:
            reject('discovery', workflow_id, 'run bound exhausted before all workflows')
            break
        try:
            runs = pages(api.list_runs, 'workflow_runs', max_runs - scanned_runs,
                         REPOSITORY, workflow_id, 'main', since)
            for run in runs:
                scanned_runs += 1
                try:
                    run_id = run['id']
                    if type(run_id) is not int or run_id < 1 or run_id in seen_runs:
                        raise ValueError('invalid/duplicate API run')
                    seen_runs.add(run_id)
                    validate_producer(run, workflow_id)
                    if scanned_artifacts >= max_artifacts:
                        raise ValueError('artifact bound exhausted before all runs')
                    artifacts = pages(api.list_artifacts, 'artifacts', max_artifacts - scanned_artifacts,
                                      REPOSITORY, run_id)
                    run_receipts, run_plans, old_attempts = [], [], {}
                    attempt_lookups = set()
                    for artifact in artifacts:
                        scanned_artifacts += 1
                        if not isinstance(artifact, dict):
                            reject('artifact', None, 'malformed API artifact object')
                            continue
                        artifact_id = artifact.get('id')
                        if type(artifact_id) is not int or artifact_id < 1 or artifact_id in seen_artifacts:
                            reject('artifact', artifact_id, 'invalid/duplicate API artifact')
                            continue
                        seen_artifacts.add(artifact_id)
                        name = str(artifact.get('name', ''))
                        if not name.startswith(('iso-coverage-receipt-', 'iso-coverage-plan-')):
                            continue
                        identity = re.fullmatch(r'iso-coverage-(receipt|plan)-(\d+)-(\d+)(?:-[A-Za-z0-9_-]+)?', name)
                        try:
                            binding_run, target_receipts, target_plans = run, run_receipts, run_plans
                            if identity and int(identity[2]) == run_id and int(identity[3]) < run['run_attempt']:
                                attempt = int(identity[3])
                                if attempt < 1:
                                    raise ValueError('invalid historical attempt')
                                if attempt not in old_attempts:
                                    if attempt in attempt_lookups:
                                        raise ValueError('historical attempt API lookup previously failed')
                                    if len(attempt_lookups) >= 10:
                                        raise ValueError('historical attempt lookup bound exceeded')
                                    attempt_lookups.add(attempt)
                                    previous = api.get_attempt(REPOSITORY, run_id, attempt)
                                    validate_producer(previous, workflow_id)
                                    if (previous['id'] != run_id or previous['run_attempt'] != attempt
                                            or previous['head_sha'] != run['head_sha']):
                                        raise ValueError('historical attempt API identity mismatch')
                                    old_attempts[attempt] = {'run': previous, 'receipts': [], 'plans': []}
                                previous = old_attempts[attempt]
                                binding_run = previous['run']
                                target_receipts, target_plans = previous['receipts'], previous['plans']
                                skipped.append({'kind': 'artifact', 'id': artifact_id,
                                                'reason': 'older authenticated attempt: scheduling only, never freshness'})
                            if type(artifact.get('size_in_bytes')) is not int or not 0 < artifact['size_in_bytes'] <= MAX_ARCHIVE_BYTES:
                                raise ValueError('artifact size exceeds download bound')
                            archive = api.download_artifact(REPOSITORY, artifact_id)
                            if name.startswith('iso-coverage-plan-'):
                                target_plans.append((bind_plan(binding_run, artifact, archive, inventory, now), artifact))
                            else:
                                target_receipts.append(bind_artifact(binding_run, artifact, archive, known, now))
                        except (ValueError, KeyError, TypeError, OSError) as error:
                            reject('artifact', artifact_id, error)
                    reconcile(run, run_receipts, run_plans)
                    for old in old_attempts.values():
                        reconcile(old['run'], old['receipts'], old['plans'], historical=True)
                except (ValueError, KeyError, TypeError, OSError) as error:
                    reject('run', run.get('id') if isinstance(run, dict) else None, error)
        except (ValueError, KeyError, TypeError, OSError) as error:
            reject('discovery', workflow_id, error)
    return {'schema_version': 1, 'receipts': receipts, 'rejected': rejected,
            'complete_history': not rejected, 'skipped': skipped, 'recovered_attempts': recovered_attempts, 'since': since,
            'historical_attempts': historical_attempts, 'scanned_runs': scanned_runs, 'scanned_artifacts': scanned_artifacts}
