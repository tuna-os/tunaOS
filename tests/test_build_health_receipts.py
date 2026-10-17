"""Authenticated receipt boundary; live producer proof remains a CI obligation."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scripts.contracts import receipt_collection as collector
from scripts.contracts.evidence import EvidenceError
from test_contract_evidence import IMAGE, TARGET, NOW


@pytest.fixture
def source(tmp_path):
    expected = {'repository': 'tuna-os/tunaOS', 'workflow': '.github/workflows/build-yellowfin.yml',
        'signerWorkflow': '.github/workflows/build-image.yml', 'runId': 42, 'runAttempt': 2,
        'sourceRevision': '1' * 40}
    run = {'id': 42, 'run_attempt': 2, 'head_sha': '1' * 40, 'path': expected['workflow'],
        'repository': {'full_name': 'tuna-os/tunaOS', 'private': False},
        'head_repository': {'full_name': 'tuna-os/tunaOS', 'fork': False},
        'head_branch': 'main', 'event': 'push', 'run_started_at': '2026-10-10T10:00:00Z'}
    receipt = copy.deepcopy(IMAGE)
    receipt['attemptIdentity'] = {key: expected[key] for key in
        ('repository', 'workflow', 'runId', 'runAttempt', 'sourceRevision')}
    receipt['attemptIdentity']['startedAt'] = run['run_started_at']
    raw = json.dumps(receipt, sort_keys=True).encode()
    path = tmp_path / 'receipt.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('receipt.json', raw)
        archive.writestr('bundle.jsonl', b'cryptographic bundle verified by external gh command')
    artifact = {'id': 71, 'expired': False, 'workflow_run': {'id': 42, 'head_sha': '1' * 40},
        'size_in_bytes': path.stat().st_size, 'created_at': '2026-10-10T10:30:00Z',
        'digest': 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()}
    uri = 'https://github.com/tuna-os/tunaOS'
    verification = [{'verificationResult': {'signature': {'certificate': {
        'issuer': 'https://token.actions.githubusercontent.com', 'sourceRepositoryURI': uri,
        'sourceRepositoryDigest': '1' * 40, 'sourceRepositoryRef': 'refs/heads/main',
        'buildSignerURI': uri + '/.github/workflows/build-image.yml@refs/heads/main',
        'buildSignerDigest': '1' * 40, 'runInvocationURI': uri + '/actions/runs/42/attempts/2'}},
        'statement': {'predicateType': 'https://slsa.dev/provenance/v1',
            'subject': [{'digest': {'sha256': hashlib.sha256(raw).hexdigest()}}]}}}]
    return expected, run, artifact, path, verification


def install_transport(monkeypatch, source, *, reject=False):
    expected, run, artifact, path, verification = source
    calls = []
    def process(command, **kwargs):
        calls.append(command)
        if command[1] == 'api':
            value = run if '/runs/' in command[4] else artifact
        else:
            if reject:
                return subprocess.CompletedProcess(command, 1)
            value = verification
        kwargs['stdout'].write(json.dumps(value).encode())
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(collector.subprocess, 'run', process)
    return calls


def authenticate(source):
    expected, _, _, path, _ = source
    return collector.authenticate(path, 71, expected, TARGET, 'image-receipt', '2026-03-10', now=NOW)


def test_actual_admission_invokes_cryptographic_verifier(monkeypatch, source):
    calls = install_transport(monkeypatch, source)
    observation = authenticate(source)
    assert observation['measuredAt'] == '2026-10-10T10:30:00Z'
    assert observation['producer']['runAttempt'] == 2
    assert observation['receipt']['imageDigest'] == IMAGE['imageDigest']
    assert len(calls) == 3
    command = calls[-1]
    assert command[:3] == ['gh', 'attestation', 'verify']
    assert '--deny-self-hosted-runners' in command
    assert command[command.index('--source-ref') + 1] == 'refs/heads/main'
    assert command[command.index('--signer-workflow') + 1] == 'tuna-os/tunaOS/.github/workflows/build-image.yml'


def test_verifier_failure_cannot_authenticate_json_claim(monkeypatch, source):
    install_transport(monkeypatch, source, reject=True)
    with pytest.raises(EvidenceError, match='authentication'):
        authenticate(source)


@pytest.mark.parametrize('field,value', [('id', True), ('run_attempt', 1), ('head_sha', '2' * 40),
    ('path', '.github/workflows/other.yml'), ('head_branch', 'feature'), ('event', 'pull_request'),
    ('repository', {'full_name': 'tuna-os/tunaOS', 'private': True}),
    ('head_repository', {'full_name': 'attacker/fork', 'fork': False}),
    ('head_repository', {'full_name': 'tuna-os/tunaOS', 'fork': True})])
def test_api_producer_mismatch_rejected_before_crypto(monkeypatch, source, field, value):
    source[1][field] = value
    calls = install_transport(monkeypatch, source)
    with pytest.raises(EvidenceError): authenticate(source)
    assert len(calls) == 2


@pytest.mark.parametrize('field,value', [('expired', True), ('id', True), ('size_in_bytes', True),
    ('size_in_bytes', 16 * 1024 * 1024 + 1), ('digest', 'sha256:' + 'f' * 64),
    ('workflow_run', {'id': 41, 'head_sha': '1' * 40}),
    ('created_at', '2026-10-10T09:59:59Z'), ('created_at', '2026-10-10T12:00:01Z')])
def test_artifact_mismatch_or_unsafe_time_rejected(monkeypatch, source, field, value):
    source[2][field] = value
    install_transport(monkeypatch, source)
    with pytest.raises(EvidenceError): authenticate(source)


@pytest.mark.parametrize('field,value', [('issuer', 'https://attacker.invalid'),
    ('sourceRepositoryURI', 'https://github.com/attacker/fork'), ('sourceRepositoryDigest', '2' * 40),
    ('sourceRepositoryRef', 'refs/pull/4/merge'), ('buildSignerDigest', '2' * 40),
    ('buildSignerURI', 'https://github.com/tuna-os/tunaOS/.github/workflows/other.yml@refs/heads/main'),
    ('runInvocationURI', 'https://github.com/tuna-os/tunaOS/actions/runs/42/attempts/1')])
def test_verified_certificate_must_bind_every_identity(monkeypatch, source, field, value):
    source[4][0]['verificationResult']['signature']['certificate'][field] = value
    install_transport(monkeypatch, source)
    with pytest.raises(EvidenceError, match='exact producer'): authenticate(source)


def test_verified_subject_digest_mismatch_rejected(monkeypatch, source):
    source[4][0]['verificationResult']['statement']['subject'][0]['digest']['sha256'] = 'f' * 64
    install_transport(monkeypatch, source)
    with pytest.raises(EvidenceError): authenticate(source)


@pytest.mark.parametrize('names', [['receipt.json', 'receipt.json'],
    ['receipt.json', '../bundle.jsonl'], ['receipt.json', 'bundle.jsonl', 'private.key']])
def test_archive_extra_duplicate_and_unsafe_members_rejected(tmp_path, names):
    path = tmp_path / 'artifact.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        for name in names: archive.writestr(name, b'{}')
    with pytest.raises(EvidenceError): collector.archive_bytes(path)


def test_discovery_preserves_missing_as_empty(monkeypatch):
    monkeypatch.setattr(collector.subprocess, 'run', lambda command, **kwargs: (
        kwargs['stdout'].write(b'{"total_count":0,"artifacts":[]}'),
        subprocess.CompletedProcess(command, 0))[1])
    assert collector.discovery('tuna-os/tunaOS', 42, '2026-03-10') == []


@pytest.mark.parametrize('raw', [b'{"id":42,"id":43}', b'{"id":NaN}', b'\xff'])
def test_api_ambiguous_json_rejected(monkeypatch, raw):
    def process(command, **kwargs):
        kwargs['stdout'].write(raw)
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(collector.subprocess, 'run', process)
    with pytest.raises(EvidenceError):
        collector.api('repos/tuna-os/tunaOS/actions/runs/42', '2026-03-10')


def test_discovery_exhaustion_never_becomes_empty(monkeypatch):
    calls = []
    def process(command, **kwargs):
        calls.append(command)
        kwargs['stdout'].write(b'{"total_count":151,"artifacts":[]}')
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(collector.subprocess, 'run', process)
    with pytest.raises(EvidenceError):
        collector.discovery('tuna-os/tunaOS', 42, '2026-03-10')
    assert len(calls) == 1
