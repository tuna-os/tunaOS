"""Observed package intent retains failures and never invents readiness evidence."""
from copy import deepcopy
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.contracts import evidence, ledger

SPEC = importlib.util.spec_from_file_location('package_requests', ROOT / 'build_scripts/package_requests.py')
recorder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recorder)
NOW = dt.datetime(2026, 10, 10, 12, tzinfo=dt.timezone.utc)
TARGET = {'variant': 'yellowfin', 'flavor': 'cosmic', 'platform': 'linux/amd64/v2',
          'cpuBaseline': 'x86-64-v2', 'hardwareScope': 'generic'}
DIGEST = 'sha256:' + '2' * 64
REVISION = '1' * 40
REQUEST_ID = 'a' * 32
PROOF = [{'url': 'https://example.org/native.json', 'digest': DIGEST}]


def event(**updates):
    value = {'schemaVersion': 1, 'kind': 'package-request', 'requestId': REQUEST_ID,
             'target': TARGET, 'phase': 'desktop', 'scope': 'final', 'required': True,
             'origin': {'path': 'build_scripts/desktop.sh', 'line': 21},
             'startedAt': '2026-10-10T10:00:00Z', 'manager': 'dnf', 'operation': 'install',
             'requests': ['cosmic-session'], 'options': ['-y'], 'coverageGaps': []}
    value.update(updates)
    return value


def result(**updates):
    value = {'schemaVersion': 1, 'kind': 'package-result', 'requestId': REQUEST_ID,
             'finishedAt': '2026-10-10T10:01:00Z', 'exitCode': 0}
    value.update(updates)
    return value


def read(tmp_path, events):
    path = tmp_path / 'requests.jsonl'
    path.write_text(''.join(json.dumps(item) + '\n' for item in events))
    return ledger.read_ledger(path, TARGET, now=NOW)


@pytest.mark.parametrize('manager,args,expression', [
    ('dnf5', ['install', '-y', 'cosmic-session'], 'cosmic-session'),
    ('apt-get', ['install', '-y', 'cosmic-session=1.0-1'], 'cosmic-session=1.0-1'),
    ('pacman', ['-S', '--needed', 'cosmic-session'], 'cosmic-session'),
    ('zypper', ['in', '--non-interactive', 'cosmic-session'], 'cosmic-session'),
    ('emerge', ['--oneshot', 'gui-wm/cosmic-session'], 'gui-wm/cosmic-session')])
def test_native_requests_preserve_constraints(manager, args, expression):
    normalized = recorder.normalize(manager, args)
    assert normalized['requests'] == [expression]
    assert normalized['coverageGaps'] == []


@pytest.mark.parametrize('manager,args', [('dnf', ['repoquery', 'foo']), ('apt', ['update']),
                                         ('rpm', ['-q', 'foo']), ('dpkg', ['--print-architecture'])])
def test_queries_are_not_mutating_requests(manager, args):
    assert recorder.normalize(manager, args) is None


@pytest.mark.parametrize('args', [['install', '--password', 'super-secret', 'foo'],
                                  ['install', 'https://user:super-secret@example.org/x.rpm'],
                                  ['install', '--setopt=proxy_password=super-secret']])
def test_secrets_are_not_retained_and_unknown_inputs_block(args):
    normalized = recorder.normalize('dnf', args)
    assert 'super-secret' not in json.dumps(normalized)
    assert normalized['coverageGaps']


def test_unknown_operation_cannot_retain_unclassified_operands():
    normalized = recorder.normalize('dnf', ['mystery', 'super-secret'])
    assert normalized['operation'] == 'unknown'
    assert normalized['requests'] == []
    assert normalized['coverageGaps'] == ['unknown-manager-operation']


@pytest.mark.parametrize('events', [[event(), event()], [result()], [event(), result(), result()],
                                   [event(), result(finishedAt='2026-10-10T09:00:00Z')],
                                   [event(startedAt='2026-10-11T10:00:00Z')],
                                   [event(startedAt='2026-10-10T10:00:00+00:00')],
                                   [event(target={**TARGET, 'flavor': 'gnome'})],
                                   [event(), result(exitCode=True)]])
def test_inconsistent_ledger_is_rejected(tmp_path, events):
    with pytest.raises((evidence.EvidenceError, ValueError)):
        read(tmp_path, events)


def test_incomplete_or_missing_recording_remains_a_gap(tmp_path):
    assert read(tmp_path, [])['coverageGaps'] == ['missing-package-requests']
    assert read(tmp_path, [event()])['coverageGaps'] == ['unfinished-package-request']
    (tmp_path / 'requests.jsonl.gaps').write_text('request-recorder-unavailable\n')
    value = read(tmp_path, [event(target=None), result()])
    assert value['coverageGaps'] == ['missing-contract-target', 'request-recording-failed']


def test_lifecycle_origins_and_failed_requests_are_preserved(tmp_path):
    value = read(tmp_path, [event(required=False), result(exitCode=42),
                           event(requestId='b' * 32, scope='transient', phase='build'),
                           result(requestId='b' * 32)])
    assert value['requests'][0]['result']['exitCode'] == 42
    requirements = ledger.observed_requirements(value)
    assert {(r['scope'], r['required']) for r in requirements} == {('final', False), ('transient', True)}
    assert {r['origins'][0]['phase'] for r in requirements} == {'desktop', 'build'}


@pytest.mark.parametrize('enabled,rc', [(False, 0), (False, 42), (True, 0), (True, 42)])
def test_wrapper_runs_real_stub_preserves_rc_and_optin(tmp_path, enabled, rc):
    binary = tmp_path / 'bin'
    binary.mkdir()
    native = binary / 'dnf'
    native.write_text('#!/bin/bash\nprintf "%s\\n" "$*" > "$CALLS"\nexit "$NATIVE_RC"\n')
    native.chmod(0o755)
    path = tmp_path / 'requests.jsonl'
    env = {**os.environ, 'PATH': str(binary) + ':/tmp/tunaos-contract-tools/bin:/usr/bin:/bin',
           'CALLS': str(tmp_path / 'calls'), 'NATIVE_RC': str(rc),
           'TUNAOS_RECORD_PACKAGE_REQUESTS': '1' if enabled else '0',
           'TUNAOS_PACKAGE_LEDGER': str(path), 'TUNAOS_PACKAGE_RECORDER': str(ROOT / 'build_scripts/package_requests.py'),
           'TUNAOS_CONTRACT_TARGET': json.dumps(TARGET), 'TUNAOS_PACKAGE_PHASE': 'desktop'}
    run = subprocess.run(['/bin/bash', '-c', 'source "$1"; dnf install -y cosmic-session', 'test',
                          str(ROOT / 'build_scripts/package-recording.sh')], env=env, capture_output=True)
    assert run.returncode == rc
    assert (tmp_path / 'calls').read_text() == 'install -y cosmic-session\n'
    if enabled:
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        assert [row['kind'] for row in rows] == ['package-request', 'package-result']
        assert rows[0]['target'] == TARGET
        assert rows[1]['exitCode'] == rc
    else:
        assert not path.exists()


def test_missing_native_tool_stays_unavailable(tmp_path):
    run = subprocess.run(['/bin/bash', '-c', 'source "$1"; command -v zypper', 'test',
                          str(ROOT / 'build_scripts/package-recording.sh')],
                         env={**os.environ, 'PATH': str(tmp_path), 'TUNAOS_RECORD_PACKAGE_REQUESTS': '1'},
                         capture_output=True)
    assert run.returncode != 0


def contract(requirements):
    value = {'schemaVersion': 1, 'kind': 'consumer-contract', 'target': TARGET, 'sourceRevision': REVISION,
             'baseReference': 'quay.io/example/base@' + DIGEST, 'baseDigest': DIGEST,
             'baseResolution': {'configuredReference': 'quay.io/example/base@' + DIGEST,
                               'reference': 'quay.io/example/base@' + DIGEST, 'indexDigest': DIGEST,
                               'childDigest': DIGEST, 'platform': 'linux/amd64/v2', 'cpuBaseline': 'x86-64-v2',
                               'baselineEvidence': PROOF, 'configDigest': DIGEST,
                               'observedPlatform': {'os': 'linux', 'architecture': 'amd64', 'variant': 'v2'}},
             'packageManager': 'dnf', 'adapter': 'almalinux-kitten-10',
             'packageRequirements': requirements, 'approvedSources': [], 'sourceDeclarations': [],
             'nativeGroups': [], 'nativeExcludes': [], 'nativeVersionLocks': [], 'hooks': [],
             'inputs': [{'path': 'manifest.yaml', 'digest': DIGEST}],
             'requiredChecks': ['native-install'], 'resolution': {'status': 'incomplete', 'unresolved': []},
             'sourcePolicy': {'inherited': [], 'forbiddenNew': [], 'policyRevision': REVISION, 'baselineDigest': DIGEST}}
    value['contractDigest'] = evidence.contract_digest(value)
    return value


def inventory_digest(records):
    body = json.dumps(sorted(records, key=lambda r: json.dumps(r, sort_keys=True, separators=(',', ':'))),
                      sort_keys=True, separators=(',', ':')).encode()
    return 'sha256:' + hashlib.sha256(body).hexdigest()


def reconciliation_fixture(tmp_path, scope='final', required=True, status='satisfied'):
    observed = read(tmp_path, [event(scope=scope, required=required), result()])
    requirement = {'nativeExpression': 'cosmic-session', 'name': 'cosmic-session', 'manager': 'dnf',
                   'scope': scope, 'required': required, 'origins': [{'path': 'manifest.yaml', 'phase': 'desktop'}]}
    document = contract([requirement])
    package = {'name': 'cosmic-session', 'version': '1.0', 'architecture': 'x86_64', 'digest': DIGEST}
    final = [package] if status == 'satisfied' else []
    proof = {'target': TARGET, 'sourceRevision': REVISION, 'baseDigest': DIGEST,
             'contractDigest': document['contractDigest'], 'requestLedgerDigest': observed['digest'],
             'baseInventoryDigest': inventory_digest([]), 'finalInventoryDigest': inventory_digest(final),
             'requirements': [{'nativeExpression': 'cosmic-session', 'manager': 'dnf', 'scope': scope,
                               'status': status, 'packages': [package], 'evidence': PROOF}],
             'requestDispositions': {REQUEST_ID: status},
             'checks': [{'name': name, 'status': 'pass', 'evidence': PROOF} for name in
                        ['request-coverage', 'native-constraints', 'provider-origins', 'package-signatures',
                         'dependency-closure', 'cpu-baseline']], 'resolvedInputs': []}
    return document, observed, [], final, proof


@pytest.mark.parametrize('scope,required,status', [('final', True, 'satisfied'),
                                                  ('final', False, 'optional-missing'),
                                                  ('transient', True, 'transient-removed')])
def test_measured_lifecycle_reconciliation(tmp_path, scope, required, status):
    assert ledger.reconcile(*reconciliation_fixture(tmp_path, scope, required, status))['status'] == 'complete'


@pytest.mark.parametrize('binding', ['target', 'sourceRevision', 'baseDigest', 'contractDigest',
                                    'requestLedgerDigest', 'baseInventoryDigest', 'finalInventoryDigest'])
def test_native_evidence_must_bind_exact_input(tmp_path, binding):
    args = reconciliation_fixture(tmp_path)
    args[-1][binding] = 'wrong'
    with pytest.raises(evidence.EvidenceError, match=binding):
        ledger.reconcile(*args)


@pytest.mark.parametrize('mutation,reason', [
    (lambda a: a[-1]['checks'].pop(), 'missing-native-cpu-baseline'),
    (lambda a: a[-1]['requirements'][0].update(evidence=[]), 'missing-native-requirement-evidence'),
    (lambda a: a[-1]['requestDispositions'].clear(), 'unresolved-package-request'),
    (lambda a: a[1]['coverageGaps'].append('unsupported-manager-option'), 'unsupported-manager-option'),
    (lambda a: a[-1]['requirements'][0].update(packages=[]), 'unsatisfied-final-package-requirement')])
def test_missing_native_coverage_blocks(tmp_path, mutation, reason):
    args = reconciliation_fixture(tmp_path)
    mutation(args)
    result = ledger.reconcile(*args)
    assert result['status'] == 'blocked'
    assert reason in result['reasons']


def test_inventory_digest_independent_of_order_and_sensitive_to_package_version():
    records = [{'name': 'a', 'version': '1'}, {'name': 'b', 'version': '2'}]
    assert ledger.inventory_digest(records) == inventory_digest(records)
    assert ledger.inventory_digest(list(reversed(records))) == inventory_digest(records)
    changed = deepcopy(records)
    changed[0]['version'] = '3'
    assert ledger.inventory_digest(changed) != inventory_digest(records)


@pytest.mark.parametrize('manager,args', [('rpm', ['-i', '--secret', 'super-secret']),
                                         ('dpkg', ['-i', '--secret', 'super-secret'])])
def test_local_installer_unknown_flag_cannot_expose_secret(manager, args):
    normalized = recorder.normalize(manager, args)
    assert 'super-secret' not in json.dumps(normalized)
    assert 'unsupported-manager-option' in normalized['coverageGaps']


def test_unavailable_recorder_preserves_native_failure_and_records_gap(tmp_path):
    binary = tmp_path / 'bin'
    binary.mkdir()
    native = binary / 'dnf'
    native.write_text('#!/bin/bash\nexit 42\n')
    native.chmod(0o755)
    path = tmp_path / 'requests.jsonl'
    run = subprocess.run(['/bin/bash', '-c', 'source "$1"; dnf install cosmic-session', 'test',
                          str(ROOT / 'build_scripts/package-recording.sh')], capture_output=True,
                         env={**os.environ, 'PATH': str(binary) + ':/usr/bin:/bin',
                              'TUNAOS_RECORD_PACKAGE_REQUESTS': '1', 'TUNAOS_PACKAGE_LEDGER': str(path),
                              'TUNAOS_PACKAGE_RECORDER': str(tmp_path / 'missing.py')})
    assert run.returncode == 42
    assert path.with_name(path.name + '.gaps').read_text() == 'request-recorder-unavailable\n'
    assert not path.exists()


@pytest.mark.parametrize('field,value', [('checks', None), ('checks', {}), ('requirements', None),
                                        ('requirements', 'unmeasured'), ('requestDispositions', []),
                                        ('resolvedInputs', None)])
def test_invalid_native_collection_is_explicit_error(tmp_path, field, value):
    args = reconciliation_fixture(tmp_path)
    args[-1][field] = value
    with pytest.raises(evidence.EvidenceError):
        ledger.reconcile(*args)


def test_failed_request_requires_disposition_not_old_installed_package(tmp_path):
    args = reconciliation_fixture(tmp_path)
    args[1]['requests'][0]['result']['exitCode'] = 42
    args[-1]['requestDispositions'].clear()
    result = ledger.reconcile(*args)
    assert result['status'] == 'blocked'
    assert 'unresolved-package-request' in result['reasons']


def test_static_unresolved_hook_needs_exact_origin_proof(tmp_path):
    args = reconciliation_fixture(tmp_path)
    args[0]['resolution']['unresolved'] = [{'code': 'native-hook-required', 'origin': 'manifest.yaml',
                                          'detail': 'run measured hook'}]
    args[0]['contractDigest'] = evidence.contract_digest(args[0])
    args[-1]['contractDigest'] = args[0]['contractDigest']
    args[-1]['resolvedInputs'] = [{'code': 'native-hook-required', 'origin': 'other.yaml', 'evidence': PROOF}]
    assert 'native-hook-required' in ledger.reconcile(*args)['reasons']
    args[-1]['resolvedInputs'][0]['origin'] = 'manifest.yaml'
    assert ledger.reconcile(*args)['status'] == 'complete'


def test_unexplained_observed_demand_is_blocked(tmp_path):
    args = reconciliation_fixture(tmp_path)
    args[1]['requests'][0]['requests'].append('unexplained-package')
    result = ledger.reconcile(*args)
    assert result['status'] == 'blocked'
    assert 'unexplained-observed-package-request' in result['reasons']


def test_recording_io_failure_cannot_prevent_native_command_with_errexit(tmp_path):
    binary = tmp_path / 'bin'
    binary.mkdir()
    native = binary / 'dnf'
    native.write_text('#!/bin/bash\nprintf called > "$CALLS"\nexit 42\n')
    native.chmod(0o755)
    run = subprocess.run(['/bin/bash', '-c', 'set -e; source "$1"; dnf install cosmic-session', 'test',
                          str(ROOT / 'build_scripts/package-recording.sh')], capture_output=True,
                         env={**os.environ, 'PATH': str(binary) + ':/tmp/tunaos-contract-tools/bin:/usr/bin:/bin',
                              'CALLS': str(tmp_path / 'calls'), 'TUNAOS_RECORD_PACKAGE_REQUESTS': '1',
                              'TUNAOS_PACKAGE_LEDGER': '/dev/null/requests.jsonl',
                              'TUNAOS_PACKAGE_RECORDER': str(ROOT / 'build_scripts/package_requests.py')})
    assert run.returncode == 42
    assert (tmp_path / 'calls').read_text() == 'called'


@pytest.mark.parametrize('code', ['missing-policy-revision', 'forbidden-new-package-source',
                                  'unsupported-repository-condition', 'missing-manifest'])
def test_forged_resolution_cannot_waive_hard_input_failure(tmp_path, code):
    args = reconciliation_fixture(tmp_path)
    args[0]['resolution']['unresolved'] = [{'code': code, 'origin': 'manifest.yaml',
                                          'detail': 'required input absent or rejected'}]
    args[0]['contractDigest'] = evidence.contract_digest(args[0])
    args[-1]['contractDigest'] = args[0]['contractDigest']
    args[-1]['resolvedInputs'] = [{'code': code, 'origin': 'manifest.yaml', 'evidence': PROOF}]
    value = ledger.reconcile(*args)
    assert value['status'] == 'blocked'
    assert code in value['reasons']


@pytest.mark.parametrize('policy,reason', [
    ({'inherited': [], 'forbiddenNew': ['el10.copr: forbidden new provider'],
      'policyRevision': REVISION, 'baselineDigest': DIGEST}, 'forbidden-new-package-source'),
    ({'inherited': [], 'forbiddenNew': [], 'policyRevision': None, 'baselineDigest': None},
     'missing-policy-revision')])
def test_policy_failure_blocks_even_without_static_gap_record(tmp_path, policy, reason):
    args = reconciliation_fixture(tmp_path)
    args[0]['sourcePolicy'] = policy
    args[0]['contractDigest'] = evidence.contract_digest(args[0])
    args[-1]['contractDigest'] = args[0]['contractDigest']
    args[-1]['resolvedInputs'] = [{'code': reason, 'origin': 'manifest.yaml', 'evidence': PROOF}]
    value = ledger.reconcile(*args)
    assert value['status'] == 'blocked'
    assert reason in value['reasons']


def test_disabled_recording_preserves_native_command_identity(tmp_path):
    binary = tmp_path / 'dnf'
    binary.write_text('#!/bin/bash\nexit 0\n')
    binary.chmod(0o755)
    run = subprocess.run(['/bin/bash', '-c', 'source "$1"; command -v dnf; type -t dnf', 'test',
                          str(ROOT / 'build_scripts/package-recording.sh')], capture_output=True, text=True,
                         env={**os.environ, 'PATH': str(tmp_path), 'TUNAOS_RECORD_PACKAGE_REQUESTS': '0'})
    assert run.returncode == 0
    assert run.stdout.splitlines() == [str(binary), 'file']


def test_disabled_recording_preserves_existing_shell_function(tmp_path):
    binary = tmp_path / 'dnf'
    binary.write_text('#!/bin/bash\nprintf native\n')
    binary.chmod(0o755)
    run = subprocess.run(['/bin/bash', '-c', 'dnf() { printf existing-function; }; source "$1"; dnf',
                          'test', str(ROOT / 'build_scripts/package-recording.sh')],
                         capture_output=True, text=True,
                         env={**os.environ, 'PATH': str(tmp_path), 'TUNAOS_RECORD_PACKAGE_REQUESTS': '0'})
    assert run.returncode == 0
    assert run.stdout == 'existing-function'
