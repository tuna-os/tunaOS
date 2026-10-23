"""Only API-bound producer artifacts can enter the coverage ledger."""
import copy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from lib.iso_coverage_artifacts import bind_artifact, discover_import
from lib.iso_coverage_receipts import required_checks

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
CELLS = [{'id': 'skipjack:gnome:linux/amd64', 'install_admitted': True}]
RUN = {'id': 100, 'run_attempt': 2, 'workflow_id': 7, 'head_branch': 'main',
       'repository': {'full_name': 'tuna-os/tunaOS'}, 'head_repository': {'full_name': 'tuna-os/tunaOS'},
       'event': 'schedule', 'head_sha': 'a' * 40,
       'status': 'completed', 'conclusion': 'success',
       'created_at': '2026-10-22T10:00:00Z', 'run_started_at': '2026-10-22T10:00:00Z',
       'updated_at': '2026-10-22T12:00:00Z'}
PAYLOAD = {'schema_version': 1, 'cell_id': CELLS[0]['id'], 'stage': 'legacy-luks',
           'mode': 'luks', 'status': 'pass', 'finished_at': '2026-10-22T11:00:00Z',
           'source_sha': 'b' * 40, 'workflow_sha': 'a' * 40,
           'source_digest': 'sha256:' + 'c' * 64, 'media_digest': 'sha256:' + 'd' * 64,
           'installer_digest': 'sha256:' + 'e' * 64, 'repository': 'tuna-os/tunaOS',
           'run_id': 100, 'run_attempt': 2,
           'checks': {key: True for key in required_checks('legacy-luks', 'luks')}}


def bundle(payload=None, name='receipt.json', extras=()):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr(name, json.dumps(PAYLOAD if payload is None else payload))
        for extra in extras:
            archive.writestr(extra, '{}')
    return buffer.getvalue()


def artifact(data):
    return {'id': 200, 'name': 'iso-coverage-receipt-100-2-skipjack-gnome',
            'size_in_bytes': len(data), 'digest': 'sha256:' + hashlib.sha256(data).hexdigest(),
            'expired': False, 'expires_at': '2027-01-20T12:00:00Z',
            'created_at': '2026-10-22T11:30:00Z',
            'workflow_run': {'id': 100, 'head_sha': 'a' * 40, 'head_branch': 'main'}}


class API:
    def __init__(self, runs=None, data=None, artifacts=None, plan=True, plan_ready=True):
        self.runs = [copy.deepcopy(RUN)] if runs is None else runs
        self.data = bundle() if data is None else data
        self.artifacts = [artifact(self.data)] if artifacts is None else artifacts
        self.plan_data = bundle({'schema_version': 1, 'execution_ready': plan_ready, 'selected': CELLS}, name='coverage-plan.json')
        if plan:
            self.artifacts.append(dict(artifact(self.plan_data), id=300, name='iso-coverage-plan-100-2'))
        self.extra_data = {}
        self.attempts = {1: dict(RUN, run_attempt=1)}
        self.calls = []

    def list_runs(self, repo, workflow, branch, since, page, per_page):
        self.calls.append(('runs', repo, workflow, branch, page))
        assert repo == 'tuna-os/tunaOS' and branch == 'main'
        return {'total_count': len(self.runs), 'workflow_runs': self.runs[(page-1)*per_page:page*per_page]}

    def list_artifacts(self, repo, run, page, per_page):
        self.calls.append(('artifacts', run, page))
        return {'total_count': len(self.artifacts), 'artifacts': self.artifacts[(page-1)*per_page:page*per_page]}

    def download_artifact(self, repo, artifact_id):
        self.calls.append(('download', artifact_id))
        return self.extra_data.get(artifact_id, self.plan_data if artifact_id == 300 else self.data)

    def get_attempt(self, repo, run_id, attempt):
        self.calls.append(('attempt', run_id, attempt))
        return self.attempts[attempt]


def discover(api, **kwargs):
    return discover_import(api, CELLS, NOW, [7], **kwargs)


def test_valid_bound_artifact_imports_with_api_transport_fields():
    result = discover(API())
    assert result['complete_history']
    assert len(result['receipts']) == 1
    receipt = result['receipts'][0]
    assert receipt['artifact_id'] == 200
    assert receipt['evidence_available'] is True
    assert receipt['artifact_digest'].startswith('sha256:')


def test_workflow_success_without_receipt_is_not_qualification():
    result = discover(API(artifacts=[]))
    assert not result['complete_history']
    assert result['receipts'] == []
    assert any('missing expected' in item['reason'] for item in result['rejected'])


def test_failed_workflow_can_record_failed_measured_stage():
    payload = copy.deepcopy(PAYLOAD)
    payload['status'] = 'fail'
    payload['checks']['installed_boot'] = False
    run = dict(RUN, conclusion='failure')
    result = discover(API(runs=[run], data=bundle(payload)))
    assert result['complete_history']
    assert result['receipts'][0]['status'] == 'fail'


@pytest.mark.parametrize('change', [
    {'head_branch': 'untrusted'}, {'workflow_id': 8}, {'head_sha': 'main'},
    {'repository': {'full_name': 'attacker/tunaOS'}}, {'run_attempt': True},
    {'created_at': '2025-01-01T00:00:00Z'}, {'status': 'in_progress'},
    {'event': 'pull_request_target'}, {'head_repository': {'full_name': 'attacker/tunaOS'}},
])
def test_api_run_identity_failures_never_import(change):
    run = copy.deepcopy(RUN)
    run.update(change)
    result = discover(API(runs=[run]))
    assert not result['complete_history']
    assert not result['receipts']


@pytest.mark.parametrize('change', [
    {'digest': 'sha256:' + '0' * 64}, {'size_in_bytes': 1}, {'expired': True},
    {'expires_at': '2026-10-23T11:00:00Z'}, {'name': 'iso-coverage-receipt-100-1-old'},
    {'created_at': '2026-10-21T00:00:00Z'},
    {'workflow_run': {'id': 999, 'head_sha': 'a' * 40, 'head_branch': 'main'}},
])
def test_bad_api_artifact_or_expired_evidence_is_visible(change):
    api = API()
    api.artifacts[0].update(change)
    result = discover(api)
    assert not result['complete_history']
    assert not result['receipts']


@pytest.mark.parametrize('change', [
    {'run_id': 999}, {'run_attempt': 1}, {'workflow_sha': 'f' * 40},
    {'repository': 'attacker/tunaOS'}, {'artifact_digest': 'sha256:' + 'f' * 64},
    {'cell_id': 'invented:gnome:linux/amd64'}, {'finished_at': '2026-10-21T00:00:00Z'},
    {'checks': {}},
])
def test_payload_cannot_override_producer_identity_or_claim_unchecked_pass(change):
    payload = copy.deepcopy(PAYLOAD)
    payload.update(change)
    result = discover(API(data=bundle(payload)))
    assert not result['complete_history']
    assert not result['receipts']


@pytest.mark.parametrize('member,extras', [('../receipt.json', ()), ('/receipt.json', ()),
                                         ('receipt.json', ('extra.txt',)), ('nested/receipt.json', ())])
def test_archive_paths_and_extra_members_rejected(member, extras):
    result = discover(API(data=bundle(name=member, extras=extras)))
    assert not result['complete_history']
    assert not result['receipts']


def test_archive_limit_prevents_download():
    api = API()
    api.artifacts[0]['size_in_bytes'] = 10 ** 9
    assert not discover(api)['complete_history']
    assert ('download', 200) not in api.calls


def test_bounded_run_discovery_is_explicitly_incomplete():
    api = API(runs=[dict(RUN, id=100), dict(RUN, id=101)])
    result = discover(api, max_runs=1)
    assert not result['complete_history']
    assert any('bound' in r['reason'] for r in result['rejected'])


def test_bounded_artifact_discovery_and_missing_page_are_incomplete():
    api = API()
    api.artifacts.append(dict(api.artifacts[0], id=201))
    result = discover(api, max_artifacts=1)
    assert not result['complete_history']
    class MissingPage(API):
        def list_runs(self, *args, **kwargs):
            return {'total_count': 1, 'workflow_runs': []}
    assert not discover(MissingPage())['complete_history']


def test_api_outage_does_not_become_empty_success():
    class Down(API):
        def list_runs(self, *args, **kwargs):
            raise OSError('API unavailable')
    result = discover(Down())
    assert not result['complete_history']
    assert result['rejected']


def test_duplicate_pagination_and_allowlist_bounds_fail_closed():
    api = API(runs=[copy.deepcopy(RUN), copy.deepcopy(RUN)])
    assert not discover(api)['complete_history']
    with pytest.raises(ValueError):
        discover_import(api, CELLS, NOW, [])
    with pytest.raises(ValueError):
        discover(api, lookback_days=27)


def test_malformed_api_artifact_objects_are_visible_not_exceptions():
    assert not discover(API(artifacts=[42]))['complete_history']
    api = API()
    api.artifacts[0]['workflow_run'] = 'malformed'
    assert not discover(api)['complete_history']


def test_api_bound_early_infra_attempt_imports_without_fabricated_digests():
    payload = copy.deepcopy(PAYLOAD)
    payload['status'] = 'infra'
    payload['checks'] = {key: False for key in payload['checks']}
    for field in ('source_digest', 'media_digest', 'installer_digest'):
        payload[field] = None
    result = discover(API(data=bundle(payload)))
    assert result['complete_history']
    assert result['receipts'][0]['status'] == 'infra'
    assert result['receipts'][0]['source_digest'] is None


def test_plan_only_run_requires_no_receipts_and_creates_no_qualification():
    result = discover(API(artifacts=[], plan_ready=False))
    assert result['complete_history']
    assert not result['receipts']


def test_missing_plan_is_incomplete_but_cancelled_planned_execution_is_infra():
    result = discover(API(plan=False))
    assert not result['complete_history']
    assert any('plan artifact' in item['reason'] for item in result['rejected'])
    result = discover(API(runs=[dict(RUN, conclusion='cancelled')], artifacts=[]))
    assert result['complete_history']
    assert result['receipts'][0]['status'] == 'infra'
    assert result['recovered_attempts'][0]['origin'] == 'api-plan-terminal-run'


def add_previous_attempt(api, receipt_status='pass', conclusion='success', include_receipt=True):
    payload = dict(PAYLOAD, run_attempt=1, status=receipt_status)
    payload['checks'] = {key: receipt_status == 'pass' for key in payload['checks']}
    old_data = bundle(payload)
    old_plan_data = bundle({'schema_version': 1, 'execution_ready': True, 'selected': CELLS}, name='coverage-plan.json')
    old_plan = dict(artifact(old_plan_data), id=198, name='iso-coverage-plan-100-1')
    api.artifacts.append(old_plan)
    api.extra_data[198] = old_plan_data
    api.attempts[1]['conclusion'] = conclusion
    if include_receipt:
        api.artifacts.append(dict(artifact(old_data), id=199, name='iso-coverage-receipt-100-1-skipjack-gnome'))
        api.extra_data[199] = old_data


def test_rerun_preserves_old_authenticated_attempt_only_for_scheduling():
    api = API()
    add_previous_attempt(api)
    result = discover(api)
    assert result['complete_history']
    assert len(result['receipts']) == 1
    assert len(result['historical_attempts']) == 1
    assert result['historical_attempts'][0]['run_attempt'] == 1
    assert result['receipts'][0]['run_attempt'] == 2
    assert {item['id'] for item in result['skipped']} == {198, 199}
    assert api.calls.count(('attempt', 100, 1)) == 1


def test_blocked_rerun_retains_previous_budget_attempt_without_freshness():
    api = API(artifacts=[], plan_ready=False)
    add_previous_attempt(api)
    result = discover(api)
    assert result['complete_history']
    assert result['receipts'] == []
    assert len(result['historical_attempts']) == 1
    assert result['historical_attempts'][0]['status'] == 'pass'
    assert result['historical_attempts'][0]['run_attempt'] == 1


def test_older_cancelled_plan_recovers_historical_reservation_only():
    api = API(artifacts=[], plan_ready=False)
    add_previous_attempt(api, conclusion='cancelled', include_receipt=False)
    result = discover(api)
    assert result['complete_history']
    assert result['receipts'] == []
    assert result['historical_attempts'][0]['status'] == 'infra'
    assert result['historical_attempts'][0]['media_digest'] is None


@pytest.mark.parametrize('mutation', [{'head_sha': 'f' * 40}, {'run_attempt': 2}, {'id': 999}, {'head_branch': 'fork'}])
def test_old_attempt_api_identity_is_not_taken_from_artifact_name(mutation):
    api = API(artifacts=[], plan_ready=False)
    add_previous_attempt(api)
    api.attempts[1].update(mutation)
    result = discover(api)
    assert not result['complete_history']
    assert not result['historical_attempts']


def test_authenticated_plan_missing_one_cell_does_not_become_green():
    extra = {'id': 'bonito:kde:linux/amd64', 'install_admitted': True}
    api = API()
    api.plan_data = bundle({'schema_version': 1, 'execution_ready': True,
                           'selected': [*CELLS, extra]}, name='coverage-plan.json')
    api.artifacts[-1] = dict(artifact(api.plan_data), id=300, name='iso-coverage-plan-100-2')
    result = discover_import(api, [*CELLS, extra], NOW, [7])
    assert not result['complete_history']
    assert any(extra['id'] in item['reason'] for item in result['rejected'])


def test_plan_cannot_invent_unknown_or_image_only_cell():
    api = API()
    api.plan_data = bundle({'schema_version': 1, 'execution_ready': True,
                           'selected': [{'id': 'invented:kde:linux/amd64'}]}, name='coverage-plan.json')
    api.artifacts[-1] = dict(artifact(api.plan_data), id=300, name='iso-coverage-plan-100-2')
    assert not discover(api)['complete_history']


def test_default_bounds_cover_ninety_days_of_five_artifacts_each():
    from datetime import timedelta
    cells = [*CELLS, {'id': 'bonito:kde:linux/amd64', 'install_admitted': True}]
    class FleetAPI:
        def __init__(self):
            self.runs, self.artifacts, self.archives = [], {}, {}
            for offset in range(90):
                day = NOW - timedelta(days=offset)
                started = day.replace(hour=8).isoformat().replace('+00:00', 'Z')
                finished = day.replace(hour=9).isoformat().replace('+00:00', 'Z')
                uploaded = day.replace(hour=10).isoformat().replace('+00:00', 'Z')
                ended = day.replace(hour=11).isoformat().replace('+00:00', 'Z')
                run_id = 1000 + offset
                run = dict(RUN, id=run_id, created_at=started, run_started_at=started, updated_at=ended)
                self.runs.append(run)
                artifacts = []
                for index in range(5):
                    if index == 0:
                        data = bundle({'schema_version': 1, 'execution_ready': True, 'selected': cells}, name='coverage-plan.json')
                        name = f'iso-coverage-plan-{run_id}-2'
                    elif index < 3:
                        payload = dict(PAYLOAD, run_id=run_id, cell_id=cells[index-1]['id'], finished_at=finished)
                        data = bundle(payload)
                        name = f'iso-coverage-receipt-{run_id}-2-cell{index}'
                    else:
                        data, name = b'legacy log bytes', f'legacy-logs-{index}'
                    artifact_id = run_id * 10 + index
                    metadata = dict(artifact(data), id=artifact_id, name=name, created_at=uploaded,
                                    workflow_run={'id': run_id, 'head_sha': 'a' * 40, 'head_branch': 'main'})
                    artifacts.append(metadata)
                    self.archives[artifact_id] = data
                self.artifacts[run_id] = artifacts
        def list_runs(self, *args, page, per_page):
            return {'total_count': len(self.runs), 'workflow_runs': self.runs[(page-1)*per_page:page*per_page]}
        def list_artifacts(self, repo, run_id, page, per_page):
            records = self.artifacts[run_id]
            return {'total_count': len(records), 'artifacts': records[(page-1)*per_page:page*per_page]}
        def download_artifact(self, repo, artifact_id):
            return self.archives[artifact_id]
    result = discover_import(FleetAPI(), cells, NOW, [7])
    assert result['complete_history'], result['rejected']
    assert result['scanned_runs'] == 90
    assert result['scanned_artifacts'] == 450
    assert len(result['receipts']) == 180


def test_cancelled_two_cell_plan_recovers_only_nonqualifying_reservations_and_advances_queue():
    from lib.iso_coverage_receipts import assess_coverage, select_catchup
    cells = [*CELLS, {'id': 'bonito:kde:linux/amd64', 'install_admitted': True},
             {'id': 'yellowfin:cosmic:linux/amd64', 'install_admitted': True}]
    api = API(runs=[dict(RUN, conclusion='cancelled')], artifacts=[])
    api.plan_data = bundle({'schema_version': 1, 'execution_ready': True, 'selected': cells[:2]}, name='coverage-plan.json')
    api.artifacts[-1] = dict(artifact(api.plan_data), id=300, name='iso-coverage-plan-100-2')
    result = discover_import(api, cells, NOW, [7])
    assert result['complete_history']
    assert len(result['receipts']) == 2
    assert len(result['recovered_attempts']) == 2
    for record in result['receipts']:
        assert record['status'] == 'infra'
        assert record['source_digest'] is None
        assert record['media_digest'] is None
        assert record['installer_digest'] is None
        assert not any(record['checks'].values())
        assert record['artifact_id'] == 300
    expected = {cell['id']: {key: PAYLOAD[key] for key in
                ('source_sha', 'workflow_sha', 'source_digest', 'media_digest', 'installer_digest')} for cell in cells}
    report = assess_coverage(cells, result['receipts'], expected, NOW, 'legacy-luks', 'luks')
    assert not any(row['status'] == 'fresh' for row in report['cells'])
    assert select_catchup(report, 1)['selected'][0]['cell_id'] == cells[2]['id']


def test_historical_attempt_api_calls_are_bounded_per_run():
    api = API(runs=[dict(RUN, run_attempt=12)], artifacts=[], plan_ready=False)
    api.artifacts[0]['name'] = 'iso-coverage-plan-100-12'
    for attempt in range(1, 12):
        data = bundle({'schema_version': 1, 'execution_ready': False, 'selected': CELLS}, name='coverage-plan.json')
        artifact_id = 400 + attempt
        api.artifacts.append(dict(artifact(data), id=artifact_id, name=f'iso-coverage-plan-100-{attempt}'))
        api.extra_data[artifact_id] = data
        api.attempts[attempt] = dict(RUN, run_attempt=attempt)
    result = discover(api)
    assert not result['complete_history']
    assert any('lookup bound' in item['reason'] for item in result['rejected'])
    assert sum(call[0] == 'attempt' for call in api.calls) == 10


def test_disabled_cron_all_skipped_jobs_does_not_poison_activation():
    class SkippedAPI:
        def list_runs(self, *args, **kwargs):
            return {'total_count': 1, 'workflow_runs': [RUN]}
        def list_artifacts(self, *args, **kwargs):
            return {'total_count': 0, 'artifacts': []}
        def list_jobs(self, *args, **kwargs):
            return {'total_count': 2, 'jobs': [
                {'run_id': RUN['id'], 'status': 'completed', 'conclusion': 'skipped', 'steps': []},
                {'run_id': RUN['id'], 'status': 'completed', 'conclusion': 'skipped', 'steps': []}]}
    report = discover_import(SkippedAPI(), CELLS, NOW, [7])
    assert report['complete_history']
    assert not report['receipts'] and not report['historical_attempts']
    assert 'every job skipped' in report['skipped'][0]['reason']


def test_missing_plan_cannot_be_ignored_when_a_job_ran():
    class RanAPI:
        def list_runs(self, *args, **kwargs):
            return {'total_count': 1, 'workflow_runs': [RUN]}
        def list_artifacts(self, *args, **kwargs):
            return {'total_count': 0, 'artifacts': []}
        def list_jobs(self, *args, **kwargs):
            return {'total_count': 1, 'jobs': [
                {'run_id': RUN['id'], 'status': 'completed', 'conclusion': 'success', 'steps': []}]}
    assert not discover_import(RanAPI(), CELLS, NOW, [7])['complete_history']
