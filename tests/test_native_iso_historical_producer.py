"""Historical native ISO admission must prove and retain the producer attempt."""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ADAPTER = load_module('historical_native_artifact', 'scripts/fetch-native-iso-artifact.py')
QUALIFICATION = load_module('historical_native_qualification', 'scripts/native-iso-qualification.py')
RUN_ID = 123456
ATTEMPT = 2
ARTIFACT_ID = 654321
SOURCE_SHA = 'a' * 40
ARCHIVE = b'historical producer archive'
ARCHIVE_DIGEST = 'sha256:' + hashlib.sha256(ARCHIVE).hexdigest()


def records():
    args = argparse.Namespace(repository='tuna-os/tunaOS', run_id=RUN_ID,
        artifact_id=ARTIFACT_ID, attempt=ATTEMPT, source_sha=SOURCE_SHA,
        archive_digest=ARCHIVE_DIGEST, variant='skipjack', flavor='gnome')
    run = dict(id=RUN_ID, run_attempt=ATTEMPT, status='completed', conclusion='success',
        head_sha=SOURCE_SHA, path='.github/workflows/live-iso-bootc.yml',
        run_started_at='2026-10-20T10:00:00Z',
        repository=dict(full_name=args.repository), head_repository=dict(full_name=args.repository))
    artifact = dict(id=ARTIFACT_ID, expired=False,
        name=f'{args.variant}-{args.flavor}-live-iso-attempt-{ATTEMPT}',
        created_at='2026-10-20T11:30:00Z', digest=ARCHIVE_DIGEST,
        workflow_run=dict(id=RUN_ID, head_sha=SOURCE_SHA),
        size_in_bytes=len(ARCHIVE))
    builder = dict(id=998877, name='build', run_id=RUN_ID, run_attempt=ATTEMPT,
        head_sha=SOURCE_SHA, status='completed', conclusion='success',
        started_at='2026-10-20T11:00:00Z', completed_at='2026-10-20T12:00:00Z')
    jobs = dict(total_count=1, jobs=[builder])
    return args, run, artifact, jobs


def test_historical_run_requires_its_exact_successful_build_job():
    args, run, artifact, jobs = records()
    proof = ADAPTER.validate(run, artifact, args, jobs)
    assert proof == {'build_job': 998877, 'producer_run': RUN_ID,
                     'producer_attempt': ATTEMPT}

def test_same_run_still_requires_the_current_repository_and_attempt(monkeypatch):
    args, run, artifact, jobs = records()
    args.attempt = 0
    run['status'] = 'in_progress'
    run['conclusion'] = None
    monkeypatch.setenv('NATIVE_SAME_RUN', 'true')
    monkeypatch.setenv('GITHUB_RUN_ID', str(RUN_ID))
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT', str(ATTEMPT))
    monkeypatch.setenv('GITHUB_REPOSITORY', args.repository)
    assert ADAPTER.validate(run, artifact, args, jobs)['producer_attempt'] == ATTEMPT
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT', str(ATTEMPT + 1))
    with pytest.raises(ValueError, match='current producer attempt'):
        ADAPTER.validate(run, artifact, args, jobs)


@pytest.mark.parametrize('mutation', [
    'missing_jobs', 'missing_build', 'failed_build', 'wrong_build_run',
    'wrong_build_attempt', 'wrong_build_sha', 'wrong_run_id',
    'wrong_run_attempt', 'wrong_source_sha', 'wrong_artifact_id',
    'wrong_artifact_run', 'wrong_artifact_attempt', 'wrong_artifact_digest',
    'wrong_artifact_name', 'artifact_outside_build',
])
def test_historical_run_rejects_incomplete_or_mismatched_producer_proof(mutation):
    args, run, artifact, jobs = records()
    run, artifact, jobs = copy.deepcopy((run, artifact, jobs))
    if mutation == 'missing_jobs':
        jobs = None
    elif mutation == 'missing_build':
        jobs = {'total_count': 0, 'jobs': []}
    elif mutation == 'failed_build':
        jobs['jobs'][0]['conclusion'] = 'failure'
    elif mutation == 'wrong_build_run':
        jobs['jobs'][0]['run_id'] += 1
    elif mutation == 'wrong_build_attempt':
        jobs['jobs'][0]['run_attempt'] += 1
    elif mutation == 'wrong_build_sha':
        jobs['jobs'][0]['head_sha'] = 'b' * 40
    elif mutation == 'wrong_run_id':
        run['id'] += 1
    elif mutation == 'wrong_run_attempt':
        run['run_attempt'] += 1
    elif mutation == 'wrong_source_sha':
        args.source_sha = 'b' * 40
    elif mutation == 'wrong_artifact_id':
        artifact['id'] += 1
    elif mutation == 'wrong_artifact_run':
        artifact['workflow_run']['id'] += 1
    elif mutation == 'wrong_artifact_attempt':
        artifact['workflow_run']['run_attempt'] = ATTEMPT + 1
    elif mutation == 'wrong_artifact_digest':
        artifact['digest'] = 'sha256:' + 'b' * 64
    elif mutation == 'wrong_artifact_name':
        artifact['name'] = 'albacore-gnome-live-iso-attempt-2'
    elif mutation == 'artifact_outside_build':
        artifact['created_at'] = '2026-10-20T12:01:00Z'
    with pytest.raises(ValueError):
        ADAPTER.validate(run, artifact, args, jobs)


def test_historical_fetch_exports_only_the_validated_producer_run_and_attempt(monkeypatch, tmp_path):
    args, run, artifact, jobs = records()
    output = tmp_path / 'native-iso-input'
    env_file = tmp_path / 'github-env'
    env_file.write_text('')
    argv = ['fetch-native-iso-artifact.py', '--repository', args.repository,
        '--run-id', str(args.run_id), '--artifact-id', str(args.artifact_id),
        '--attempt', str(args.attempt), '--source-sha', args.source_sha,
        '--archive-digest', args.archive_digest, '--variant', args.variant,
        '--flavor', args.flavor, '--output', str(output)]
    monkeypatch.setattr(sys, 'argv', argv)
    monkeypatch.setenv('GITHUB_ENV', str(env_file))
    monkeypatch.setenv('GITHUB_RUN_ID', '999999')
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT', '1')
    monkeypatch.setenv('NATIVE_SAME_RUN', 'false')
    calls = []

    def api(repository, suffix):
        calls.append(suffix)
        if suffix == f'actions/runs/{RUN_ID}/attempts/{ATTEMPT}':
            return run
        if suffix == f'actions/artifacts/{ARTIFACT_ID}':
            return artifact
        if suffix == f'actions/runs/{RUN_ID}/attempts/{ATTEMPT}/jobs?per_page=100':
            return jobs
        raise AssertionError(f'unexpected API request: {suffix}')

    monkeypatch.setattr(ADAPTER, 'api', api)
    monkeypatch.setattr(ADAPTER, 'download_archive',
        lambda command, target, size, timeout, idle_timeout: target.write(ARCHIVE))

    def extract(archive, destination, variant, flavor):
        iso = destination / f'{variant}-{flavor}-live.iso'
        iso.write_bytes(b'historical ISO bytes')
        return iso

    monkeypatch.setattr(ADAPTER, 'extract', extract)

    def bounded_command(command, destination, limit, timeout, idle_timeout=None, progress=None):
        assert command == ['git', 'rev-parse', 'HEAD']
        destination.write(SOURCE_SHA.encode())

    monkeypatch.setattr(ADAPTER, 'bounded_command', bounded_command)
    ADAPTER.main()

    binding = json.loads((output / 'artifact-binding.json').read_text())
    env = env_file.read_text()
    assert calls == [f'actions/runs/{RUN_ID}/attempts/{ATTEMPT}',
        f'actions/artifacts/{ARTIFACT_ID}',
        f'actions/runs/{RUN_ID}/attempts/{ATTEMPT}/jobs?per_page=100']
    assert binding['producer_run'] == RUN_ID
    assert binding['producer_attempt'] == ATTEMPT
    assert binding['producer_build_job'] == 998877
    assert binding['producer_build_conclusion'] == 'success'
    assert f'TUNAOS_NATIVE_PRODUCER_RUN_ID={RUN_ID}\n' in env
    assert f'TUNAOS_NATIVE_PRODUCER_ATTEMPT={ATTEMPT}\n' in env
    assert 'TUNAOS_NATIVE_PRODUCER_RUN_ID=999999' not in env


def test_qualification_rejects_consumer_run_and_accepts_producer_identity_until_qemu(monkeypatch, tmp_path):
    binding = dict(repository='tuna-os/tunaOS', producer_run=RUN_ID,
        producer_attempt=ATTEMPT, harness_sha=SOURCE_SHA, media_digest='sha256:' + 'c' * 64,
        artifact_id=ARTIFACT_ID, archive_digest=ARCHIVE_DIGEST, producer_sha=SOURCE_SHA)
    path = tmp_path / 'binding.json'
    path.write_text(json.dumps(binding))
    monkeypatch.setattr(QUALIFICATION.subprocess, 'check_output',
        lambda *args, **kwargs: SOURCE_SHA)
    common = dict(command='emit', binding=path, repository='tuna-os/tunaOS',
        media=binding['media_digest'], artifact_id=ARTIFACT_ID,
        archive_digest=ARCHIVE_DIGEST, source_sha=SOURCE_SHA,
        qemu='qemu-test', variant='skipjack', flavor='gnome', platform='linux/amd64')
    with pytest.raises(ValueError, match='validated producer run and attempt'):
        QUALIFICATION.emit(argparse.Namespace(**common, run_id=999999, attempt=1))
    monkeypatch.setattr(QUALIFICATION.shutil, 'which', lambda command: None)
    with pytest.raises(ValueError, match='invoked QEMU executable missing'):
        QUALIFICATION.emit(argparse.Namespace(**common, run_id=RUN_ID, attempt=ATTEMPT))


def test_historical_checkout_and_shell_handoff_use_producer_identity():
    workflow = (ROOT / '.github/workflows/iso-e2e.yml').read_text()
    harness = (ROOT / 'scripts/iso-e2e.sh').read_text()
    producer_checkout = "ref: ${{ inputs.source == 'native-artifact' && inputs.native_source_sha || github.sha }}"
    assert workflow.count(producer_checkout) == 2
    assert '--run-id "${TUNAOS_NATIVE_PRODUCER_RUN_ID:?validated producer run is required}"' in harness
    assert '--attempt "${TUNAOS_NATIVE_PRODUCER_ATTEMPT:?validated producer attempt is required}"' in harness
