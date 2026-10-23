"""CI regressions: API failure/partial jobs must never look like old green."""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('build_health_fetch', ROOT / 'scripts/gen-build-health.py')
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)
NOW = datetime(2026, 10, 10, 20, tzinfo=timezone.utc)
SOURCE = 'a' * 40


def configuration():
    return {'variants': [{'id': 'albacore', 'flavors': [
        {'id': 'cosmic', 'build_image': True, 'platforms': ['linux/amd64/v2', 'linux/arm64']},
    ]}]}


def run(identity=1, status='completed'):
    return {'id': identity, 'run_attempt': 2, 'head_sha': SOURCE,
            'head_branch': 'main', 'path': '.github/workflows/build-albacore.yml',
            'event': 'schedule', 'status': status,
            'run_started_at': '2026-10-10T19:00:00Z',
            'head_repository': {'full_name': collector.REPOSITORY, 'fork': False},
            'repository': {'full_name': collector.REPOSITORY, 'private': False}}


def jobs(conclusion='success'):
    return [{'id': index, 'run_id': 1, 'run_attempt': 2, 'head_sha': SOURCE,
             'head_branch': 'main',
             'name': f'🐟-albacore / cosmic / {name}', 'status': 'completed',
             'conclusion': conclusion}
            for index, name in enumerate(['linux-amd64-v2', 'linux-arm64', 'Gate', 'Promote'], 1)]


def fetcher(observation=None, job_rows=None):
    observation = run() if observation is None else observation
    job_rows = jobs() if job_rows is None else job_rows

    def fetch(endpoint):
        if '/workflows/' in endpoint:
            return {'workflow_runs': [observation]}
        assert '/runs/1/attempts/2/jobs?' in endpoint
        return {'jobs': job_rows, 'total_count': len(job_rows)}
    return fetch


@pytest.mark.parametrize('raw', [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'not json'])
def test_strict_json_rejects_ambiguous_observations(raw):
    with pytest.raises(collector.CollectionError):
        collector.strict_json(raw)


def test_success_without_authenticated_receipts_is_blocked():
    document = collector.collect(configuration(), SOURCE, fetcher(), now=NOW)
    collector.validate(document, expected_kind='build-health', now=NOW)
    assert len(document['targets']) == 2
    assert document['collection']['status'] == 'available'
    for row in document['targets']:
        assert row['latestAttempt']['status'] == 'success'
        assert row['status'] == 'blocked'
        assert row['lastVerifiedPublication'] is None
        assert row['packageReadiness']['status'] != 'healthy'


def test_older_jobs_are_not_fetched_after_all_latest_targets_are_observed():
    calls = []

    def fetch(endpoint):
        if '/workflows/' in endpoint:
            older = run(identity=2)
            older['run_started_at'] = '2026-10-09T19:00:00Z'
            return {'workflow_runs': [run(), older]}
        calls.append(endpoint)
        assert '/runs/1/attempts/2/jobs?' in endpoint
        return {'jobs': jobs(), 'total_count': len(jobs())}

    result = collector.collect(configuration(), SOURCE, fetch, now=NOW)
    assert len(calls) == 1
    assert all(row['latestAttempt']['identity']['runId'] == 1 for row in result['targets'])


@pytest.mark.parametrize('phase', ['linux-amd64-v2', 'Gate', 'Promote'])
def test_failed_phase_survives_downstream_skipped_jobs(phase):
    observations = jobs('skipped')
    next(j for j in observations if j['name'].endswith('/ ' + phase))['conclusion'] = 'failure'
    document = collector.collect(configuration(), SOURCE, fetcher(job_rows=observations), now=NOW)
    intel = next(r for r in document['targets'] if r['target']['platform'] == 'linux/amd64/v2')
    assert intel['status'] == 'failed'


@pytest.mark.parametrize('conclusion,status', [('cancelled', 'blocked'), ('skipped', 'blocked')])
def test_cancelled_and_skipped_not_dropped(conclusion, status):
    result = collector.collect(configuration(), SOURCE, fetcher(job_rows=jobs(conclusion)), now=NOW)
    assert all(r['status'] == status for r in result['targets'])


def test_v2_never_borrows_plain_amd64_build():
    observations = jobs()
    observations[0]['name'] = '🐟-albacore / cosmic / linux-amd64'
    result = collector.collect(configuration(), SOURCE, fetcher(job_rows=observations), now=NOW)
    intel = next(r for r in result['targets'] if r['target']['platform'] == 'linux/amd64/v2')
    assert intel['latestAttempt']['status'] == 'missing'


def test_failed_api_is_degraded_not_available_empty_runs():
    def failed(_endpoint):
        raise collector.CollectionError('unavailable')
    result = collector.collect(configuration(), SOURCE, failed, now=NOW)
    assert result['collection']['status'] == 'degraded'
    assert len(result['targets']) == 2
    assert all('github-collection-unavailable' in r['reasons'] for r in result['targets'])


def test_empty_api_success_is_available_missing_coverage():
    result = collector.collect(configuration(), SOURCE, lambda _: {'workflow_runs': []}, now=NOW)
    assert result['collection']['status'] == 'available'
    assert all(r['status'] == 'missing' for r in result['targets'])


@pytest.mark.parametrize('field,value', [('run_attempt', True), ('head_sha', 'main'), ('head_branch', 'feature'),
                                        ('path', '.github/workflows/other.yml')])
def test_untrusted_run_is_collection_failure(field, value):
    observation = run()
    observation[field] = value
    result = collector.collect(configuration(), SOURCE, fetcher(observation), now=NOW)
    assert result['collection']['status'] == 'degraded'


def test_fork_run_not_trusted():
    observation = run()
    observation['head_repository']['fork'] = True
    with pytest.raises(collector.CollectionError):
        collector.main_run(observation, 'build-albacore.yml')


@pytest.mark.parametrize('field,value', [('run_attempt', 1), ('run_id', 3), ('head_sha', 'b' * 40)])
def test_job_attempt_and_source_must_match(field, value):
    observations = jobs()
    observations[0][field] = value
    result = collector.collect(configuration(), SOURCE, fetcher(job_rows=observations), now=NOW)
    assert result['collection']['status'] == 'degraded'


def test_job_pagination_is_complete_and_attempt_specific():
    first = jobs()[:1] * 100
    first = [dict(job, id=i + 1) for i, job in enumerate(first)]
    second = [dict(jobs()[0], id=101)]
    def fetch(endpoint):
        assert '/attempts/2/jobs?' in endpoint
        return {'total_count': 101, 'jobs': second if 'page=2' in endpoint else first}
    assert len(collector.fetch_jobs(fetch, run())) == 101


def test_missing_job_page_blocks_collection():
    with pytest.raises(collector.CollectionError):
        collector.fetch_jobs(lambda _: {'total_count': 2, 'jobs': jobs()[:1]}, run())


def test_unknown_known_flavor_job_prevents_success():
    observations = jobs() + [dict(jobs()[0], id=5, name='🐟-albacore / cosmic / Build future-format')]
    result = collector.collect(configuration(), SOURCE, fetcher(job_rows=observations), now=NOW)
    assert all(r['latestAttempt']['status'] == 'unknown' for r in result['targets'])


def test_real_configuration_preserves_every_required_target_on_api_failure():
    config = yaml.safe_load((ROOT / '.github/build-config.yml').read_text())
    def failed(_endpoint):
        raise collector.CollectionError('unavailable')
    result = collector.collect(config, SOURCE, failed, now=NOW)
    expected = collector.coverage_document(config)
    assert len(result['targets']) == len(expected['targets']) == 269
    assert result['coverageDigest'] == expected['coverageDigest']
    assert all(r['status'] != 'healthy' for r in result['targets'])


def test_running_build_precedes_old_completed_success():
    observation = jobs()
    observation[0]['status'] = 'in_progress'
    observation[0]['conclusion'] = None
    result = collector.collect(configuration(), SOURCE, fetcher(job_rows=observation), now=NOW)
    assert next(r for r in result['targets'] if r['target']['platform'] == 'linux/amd64/v2')['status'] == 'running'


def test_queued_no_jobs_does_not_invent_flavor_dispatch():
    result = collector.collect(configuration(), SOURCE, fetcher(run(status='queued'), []), now=NOW)
    assert all(r['latestAttempt']['status'] == 'unknown' for r in result['targets'])
