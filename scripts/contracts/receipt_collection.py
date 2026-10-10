"""Authenticate explicit GitHub receipt artifacts; artifacts are not trust inputs.

Archives may be downloaded by a caller, but API identity and cryptographic
verification are always obtained here. No native snapshot or successful job
stands in for a canonical receipt. Missing production receipts stay missing.
"""
from __future__ import annotations
import hashlib
import io
import json
import re
import resource
import stat
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from .evidence import EvidenceError, loads, validate

MAX_BYTES = 8 * 1024 * 1024
MAX_ARCHIVE = 16 * 1024 * 1024
MAX_PAGES = 5
REPOSITORIES = {'image-receipt': 'tuna-os/tunaOS', 'factory-receipt': 'tuna-os/tunaos-packages'}


def integer(value):
    if type(value) is not int or value < 1:
        raise EvidenceError('invalid receipt API integer')
    return value


def utc(value, now):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', value):
        raise EvidenceError('invalid receipt API UTC time')
    try:
        measured = datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise EvidenceError('invalid receipt API UTC time') from exc
    if measured > now:
        raise EvidenceError('future receipt observation')
    return value


def bounded_command(command):
    with tempfile.TemporaryFile() as output:
        def bound():
            resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_BYTES, MAX_BYTES))
        try:
            result = subprocess.run(command, stdout=output, stderr=subprocess.DEVNULL,
                                    timeout=120, check=False, preexec_fn=bound)
            if result.returncode:
                raise EvidenceError('receipt authentication command unavailable')
            output.seek(0)
            raw = output.read(MAX_BYTES + 1)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise EvidenceError('receipt authentication unavailable') from exc
    if len(raw) > MAX_BYTES:
        raise EvidenceError('receipt verification response exceeds bound')
    try:
        return json.loads(raw, object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(EvidenceError('nonfinite API JSON')))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise EvidenceError('malformed receipt authentication JSON') from exc


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise EvidenceError('duplicate receipt API JSON key')
        result[key] = value
    return result


def api(endpoint, version):
    if not re.fullmatch(r'\d{4}-\d\d-\d\d', version):
        raise EvidenceError('explicit GitHub API version required')
    if not any(endpoint.startswith('repos/' + repo + '/actions/') for repo in REPOSITORIES.values()) or any(c in endpoint for c in '\r\n'):
        raise EvidenceError('receipt API endpoint outside policy')
    return bounded_command(['gh', 'api', '--hostname', 'github.com', endpoint,
                            '-H', 'X-GitHub-Api-Version: ' + version])


def discovery(repository, run_id, version):
    """Return bounded candidate metadata, never authenticated receipts."""
    if repository not in REPOSITORIES.values():
        raise EvidenceError('receipt repository outside policy')
    integer(run_id)
    result, seen = [], set()
    total = None
    for page in range(1, MAX_PAGES + 1):
        body = api(f'repos/{repository}/actions/runs/{run_id}/artifacts?per_page=30&page={page}', version)
        if not isinstance(body, dict) or not isinstance(body.get('artifacts'), list):
            raise EvidenceError('malformed artifact listing')
        count = body.get('total_count')
        if type(count) is not int or count < 0 or count > 30 * MAX_PAGES or len(body['artifacts']) > 30:
            raise EvidenceError('artifact listing exceeds bound')
        if total is not None and total != count:
            raise EvidenceError('artifact listing changed')
        total = count
        for artifact in body['artifacts']:
            if not isinstance(artifact, dict):
                raise EvidenceError('malformed artifact observation')
            identity = integer(artifact.get('id'))
            if identity in seen:
                raise EvidenceError('duplicate artifact identity')
            seen.add(identity); result.append(artifact)
        if len(result) == total:
            return result
        if len(body['artifacts']) < 30:
            raise EvidenceError('incomplete artifact listing')
    raise EvidenceError('artifact discovery exhausted')


def archive_bytes(path):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise EvidenceError('unsafe receipt archive path')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_ARCHIVE:
        raise EvidenceError('unsafe or oversized receipt archive')
    with path.open('rb') as stream:
        raw = stream.read(MAX_ARCHIVE + 1)
    if len(raw) > MAX_ARCHIVE:
        raise EvidenceError('receipt archive exceeds bound')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            files = archive.infolist()
            if len(files) != 2 or {f.filename for f in files} != {'receipt.json', 'bundle.jsonl'}:
                raise EvidenceError('receipt archive requires exact receipt and attestation bundle')
            output = {}
            for entry in files:
                mode = entry.external_attr >> 16
                if entry.flag_bits & 1 or entry.is_dir() or (stat.S_IFMT(mode) and not stat.S_ISREG(mode)) or entry.file_size > MAX_BYTES:
                    raise EvidenceError('unsafe or oversized receipt archive member')
                with archive.open(entry) as stream:
                    data = stream.read(MAX_BYTES + 1)
                if len(data) != entry.file_size or len(data) > MAX_BYTES:
                    raise EvidenceError('receipt archive member exceeds bound')
                output[entry.filename] = data
            return raw, output
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        raise EvidenceError('invalid receipt archive') from exc


def verify_provenance(results, digest, expected):
    """Only called on successful gh cryptographic verification output."""
    uri = 'https://github.com/' + expected['repository']
    invocation = f"{uri}/actions/runs/{expected['runId']}/attempts/{expected['runAttempt']}"
    if not isinstance(results, list) or not results:
        raise EvidenceError('missing verified receipt provenance')
    for result in results:
        try:
            verified = result['verificationResult']
            cert = verified['signature']['certificate']
            statement = verified['statement']
            if (cert['issuer'] == 'https://token.actions.githubusercontent.com'
                and cert['sourceRepositoryURI'] == uri
                and cert['sourceRepositoryDigest'] == expected['sourceRevision']
                and cert['sourceRepositoryRef'] == 'refs/heads/main'
                and cert['buildSignerURI'] == uri + '/' + expected['signerWorkflow'] + '@refs/heads/main'
                and cert['buildSignerDigest'] == expected['sourceRevision']
                and cert['runInvocationURI'] == invocation
                and statement['predicateType'] == 'https://slsa.dev/provenance/v1'
                and len(statement['subject']) == 1
                and statement['subject'][0]['digest'] == {'sha256': digest}):
                return
        except (KeyError, TypeError):
            continue
    raise EvidenceError('verified receipt does not bind exact producer and subject')


def authenticate(archive, artifact_id, expected, target, kind, version, *, now=None):
    """Expected identity is reviewed caller policy, never read from the artifact."""
    now = now or datetime.now(timezone.utc)
    fields = {'repository', 'workflow', 'signerWorkflow', 'runId', 'runAttempt', 'sourceRevision'}
    if not isinstance(expected, dict) or set(expected) != fields or expected['repository'] != REPOSITORIES.get(kind):
        raise EvidenceError('invalid expected receipt identity')
    integer(expected['runId']); integer(expected['runAttempt']); integer(artifact_id)
    if not isinstance(expected['sourceRevision'], str) or not re.fullmatch('[0-9a-f]{40}', expected['sourceRevision']):
        raise EvidenceError('invalid expected receipt source')
    for field in ('workflow', 'signerWorkflow'):
        if not isinstance(expected[field], str) or not re.fullmatch(r'\.github/workflows/[^/\\\s?#]+\.ya?ml', expected[field]):
            raise EvidenceError('invalid expected receipt workflow')
    repo = expected['repository']
    run = api(f"repos/{repo}/actions/runs/{expected['runId']}/attempts/{expected['runAttempt']}", version)
    artifact = api(f'repos/{repo}/actions/artifacts/{artifact_id}', version)
    if (not isinstance(run, dict) or not isinstance(artifact, dict)
        or not isinstance(run.get('repository'), dict) or not isinstance(run.get('head_repository'), dict)
        or not isinstance(artifact.get('workflow_run'), dict)):
        raise EvidenceError('malformed receipt API identity')
    if (type(run.get('id')) is not int or type(run.get('run_attempt')) is not int
        or run.get('id') != expected['runId'] or run.get('run_attempt') != expected['runAttempt']
        or run.get('head_sha') != expected['sourceRevision'] or run.get('path') != expected['workflow']
        or run.get('repository', {}).get('full_name') != repo or run.get('repository', {}).get('private') is not False
        or run.get('head_repository', {}).get('full_name') != repo or run.get('head_repository', {}).get('fork') is not False
        or run.get('head_branch') != 'main' or run.get('event') not in {'push', 'schedule', 'workflow_dispatch', 'workflow_call'}):
        raise EvidenceError('receipt API producer outside exact public main policy')
    if (type(artifact['workflow_run'].get('id')) is not int
        or type(artifact.get('size_in_bytes')) is not int or not 1 <= artifact['size_in_bytes'] <= MAX_ARCHIVE
        or type(artifact.get('id')) is not int or artifact.get('id') != artifact_id or artifact.get('expired') is not False
        or artifact.get('workflow_run', {}).get('id') != expected['runId']
        or artifact.get('workflow_run', {}).get('head_sha') != expected['sourceRevision']):
        raise EvidenceError('receipt artifact does not bind expected run and source')
    measured = utc(artifact.get('created_at'), now)
    started = utc(run.get('run_started_at'), now)
    if measured < started:
        raise EvidenceError('artifact predates expected attempt')
    raw, files = archive_bytes(archive)
    if artifact.get('digest') != 'sha256:' + hashlib.sha256(raw).hexdigest():
        raise EvidenceError('downloaded receipt archive differs from GitHub artifact digest')
    try:
        receipt = loads(files['receipt.json'].decode('utf-8'))
    except UnicodeError as exc:
        raise EvidenceError('invalid receipt UTF-8') from exc
    validate(receipt, kind, now=now)
    identity = {k: expected[k] for k in ('repository', 'workflow', 'runId', 'runAttempt', 'sourceRevision')}
    identity['startedAt'] = started
    if receipt['target'] != target or receipt['attemptIdentity'] != identity:
        raise EvidenceError('receipt differs from exact expected target or attempt')
    with tempfile.TemporaryDirectory(prefix='tunaos-receipt-') as directory:
        subject, bundle = Path(directory) / 'receipt.json', Path(directory) / 'bundle.jsonl'
        subject.write_bytes(files['receipt.json']); bundle.write_bytes(files['bundle.jsonl'])
        results = bounded_command(['gh', 'attestation', 'verify', str(subject), '--hostname', 'github.com',
            '--repo', repo, '--signer-workflow', repo + '/' + expected['signerWorkflow'],
            '--signer-digest', expected['sourceRevision'], '--source-digest', expected['sourceRevision'],
            '--source-ref', 'refs/heads/main', '--deny-self-hosted-runners', '--bundle', str(bundle), '--format', 'json'])
        verify_provenance(results, hashlib.sha256(files['receipt.json']).hexdigest(), expected)
    return {'receipt': receipt, 'measuredAt': measured,
            'artifactId': artifact_id, 'producer': identity}
