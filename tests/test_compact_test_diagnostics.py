"""Compact diagnostics retain failing exit codes and bound report input.

Falsification: make the wrapper swallow a failing command, allow XML entities,
or follow a report symlink; the behavioural tests below must fail.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('diagnostics', ROOT / 'scripts/summarize-test-failures.py')
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
WORKFLOW = yaml.safe_load((ROOT / '.github/workflows/test.yml').read_text())
STEPS = {step.get('name'): step for step in WORKFLOW['jobs']['unit-tests']['steps']} if 'unit-tests' in WORKFLOW['jobs'] else {step.get('name'): step for job in WORKFLOW['jobs'].values() for step in job.get('steps', [])}


@pytest.fixture(autouse=True)
def static_source(tmp_path, monkeypatch):
    root = tmp_path / 'static-source'
    (root / 'tests/bats').mkdir(parents=True)
    (root / 'tests/other').mkdir()
    (root / 'tests/sample.py').write_text('def test_failure(): pass\ndef test_error(): pass\n')
    for relative in ('tests/bats/example.bats', 'tests/other/example.bats'):
        (root / relative).write_text('@test "static case" { true; }\n')
    monkeypatch.setattr(module, 'SOURCE_ROOT', root)


def reports(tmp_path):
    (tmp_path / 'bats/tests/bats').mkdir(parents=True)
    (tmp_path / 'pytest.xml').write_text('<testsuites><testsuite><testcase name="pass"/><testcase classname="tests.sample" name="test_failure"><failure message="assert x"/></testcase><testcase classname="tests.sample" name="test_error"><error>bad fixture</error></testcase><testcase name="skip"><skipped/></testcase></testsuite></testsuites>')
    (tmp_path / 'pytest.exit').write_text('1\n')
    (tmp_path / 'bats/tests/bats/example.bats.tap').write_text('1..3\nok 1 first\nnot ok 2 broken\nok 3 later # skip unavailable\n')
    (tmp_path / 'bats/tests/bats/example.bats.tap.exit').write_text('1\n')
    return tmp_path


def test_counts_and_unique_file_identity(tmp_path):
    result = module.summarize(reports(tmp_path))
    assert result['pytest']['tests'] == 4
    assert result['pytest']['failures'] == result['pytest']['errors'] == result['pytest']['skipped'] == 1
    assert result['pytest']['exit_code'] == 1
    assert result['bats']['tests'] == 3
    assert result['bats']['failures'] == result['bats']['skipped'] == 1
    assert result['bats']['failure_details'][0]['test'] == 'tests/bats/example.bats::case-2'
    assert not result['pytest']['issues'] and not result['bats']['issues']


@pytest.mark.parametrize('xml', ['<broken', '<arbitrary/>', '<!DOCTYPE x [<!ENTITY a "secret">]><testsuite>&a;</testsuite>', '<!DOCTYPE x SYSTEM "file:///etc/passwd"><testsuite/>', '<testsuite>' + '<a>' * 65 + '</a>' * 65 + '</testsuite>'])
def test_invalid_xml_cannot_look_successful(tmp_path, xml):
    root = reports(tmp_path)
    (root / 'pytest.xml').write_text(xml)
    assert module.summarize(root)['pytest']['issues']


def test_missing_reports_are_explicit(tmp_path):
    result = module.summarize(tmp_path)
    assert result['pytest']['issues'] and result['bats']['issues']
    assert 'exit_code' not in result['pytest']


@pytest.mark.parametrize('directory', [False, True])
def test_symlink_reports_refused(tmp_path, directory):
    root = reports(tmp_path / 'reports')
    if directory:
        link = tmp_path / 'link'
        link.symlink_to(root, target_is_directory=True)
        result = module.summarize(link)
    else:
        target = root / 'pytest.xml'
        target.unlink()
        target.symlink_to('/etc/passwd')
        result = module.summarize(root)
    assert result['pytest']['issues']


def test_directory_as_report_refused(tmp_path):
    root = reports(tmp_path)
    (root / 'pytest.xml').unlink()
    (root / 'pytest.xml').mkdir()
    assert module.summarize(root)['pytest']['issues']


def test_size_budget_and_failure_truncation(tmp_path, monkeypatch):
    root = reports(tmp_path)
    monkeypatch.setattr(module, 'MAX_FILE', 16)
    assert module.summarize(root)['pytest']['issues']
    monkeypatch.setattr(module, 'MAX_FILE', 8192)
    monkeypatch.setattr(module, 'MAX_TOTAL', 8)
    assert module.summarize(root)['pytest']['issues']
    monkeypatch.setattr(module, 'MAX_TOTAL', 8192)
    monkeypatch.setattr(module, 'MAX_FAILURES', 1)
    result = module.summarize(root)['pytest']
    assert result['failures'] + result['errors'] == 2
    assert len(result['failure_details']) == 1 and result['truncated']
    assert 'message' not in result['failure_details'][0]


@pytest.mark.parametrize('tap', ['ok 1 missing plan\n', '1..2\nok 1 incomplete\n', '1..0\nBail out! failed\n', '1..0\n1..0\n'])
def test_incomplete_tap_is_reported(tmp_path, tap):
    root = reports(tmp_path)
    (root / 'bats/tests/bats/example.bats.tap').write_text(tap)
    assert module.summarize(root)['bats']['issues']


def fake(root, name, body):
    path = root / name
    path.write_text('#!/bin/bash\n' + body)
    path.chmod(0o755)


def environment(tmp_path):
    binary = tmp_path / 'bin'
    binary.mkdir()
    return binary, {**os.environ, 'PATH': str(binary) + ':' + os.environ['PATH'], 'RUNNER_TEMP': str(tmp_path / 'temp')}


def test_pytest_wrapper_keeps_exit_and_stdout(tmp_path):
    binary, env = environment(tmp_path)
    fake(binary, 'python3', 'printf "%s\\n" "$@"; echo original-output; exit 7\n')
    result = subprocess.run(['bash', '-eo', 'pipefail', '-c', STEPS['Run pytest tests']['run']], env=env, cwd=tmp_path, text=True, capture_output=True)
    assert result.returncode == 7 and 'original-output' in result.stdout
    assert '--junitxml=' in result.stdout
    assert (tmp_path / 'temp/tunaos-test-results/pytest.exit').read_text() == '7\n'
    assert 'PYTEST_ADDOPTS' not in STEPS['Run pytest tests']['run']


@pytest.mark.parametrize('bats_code,tee_code', [(9, 0), (0, 4)])
def test_bats_and_tee_failures_keep_gate(tmp_path, bats_code, tee_code):
    binary, env = environment(tmp_path)
    path = tmp_path / 'tests/bats/a.bats'
    path.parent.mkdir(parents=True)
    path.write_text('fixture')
    fake(binary, 'bats', f'echo "1..1"; echo "not ok 1 original-output"; exit {bats_code}\n')
    if tee_code:
        fake(binary, 'tee', f'cat; exit {tee_code}\n')
    result = subprocess.run(['bash', '-eo', 'pipefail', '-c', STEPS['Run BATS tests']['run']], env=env, cwd=tmp_path, text=True, capture_output=True)
    assert result.returncode == 1 and 'original-output' in result.stdout
    code = (tmp_path / 'temp/tunaos-test-results/bats/tests/bats/a.bats.tap.exit').read_text()
    assert int(code) == (tee_code or bats_code)


def test_workflow_upload_is_narrow_and_pinned():
    upload = STEPS['Archive test failure summary']
    assert upload['if'] == "failure() && steps.test_failure_summary.outcome == 'success'"
    assert STEPS['Summarize test failures']['id'] == 'test_failure_summary'
    assert upload['uses'] == STEPS['Archive Python coverage']['uses']
    assert upload['with']['path'] == '${{ runner.temp }}/tunaos-test-failures.json'
    assert upload['with']['retention-days'] == 7
    assert STEPS['Run pytest tests']['if'] == 'always()'
    assert STEPS['Run BATS tests']['shell'] == 'bash'  # GitHub's explicit bash enables pipefail.
    assert not any(step.get('continue-on-error') for step in STEPS.values())


def test_cli_only_writes_bounded_summary(tmp_path):
    root = reports(tmp_path / 'reports')
    output = tmp_path / 'summary.json'
    result = subprocess.run([os.sys.executable, str(ROOT / 'scripts/summarize-test-failures.py'), '--reports', str(root), '--output', str(output)], capture_output=True)
    assert result.returncode == 0
    assert output.stat().st_size < module.MAX_OUTPUT
    assert json.loads(output.read_text())['pytest']['exit_code'] == 1


def test_same_basename_keeps_repository_identity(tmp_path):
    root = reports(tmp_path)
    other = root / 'bats/tests/other/example.bats.tap'
    other.parent.mkdir(parents=True)
    other.write_text('1..1\nnot ok 1 another failure\n')
    other.with_name(other.name + '.exit').write_text('1\n')
    result = module.summarize(root)['bats']
    assert len(result['exit_codes']) == 2
    assert len({item['test'] for item in result['failure_details']}) == 2


def test_report_count_limit_is_explicit(tmp_path, monkeypatch):
    root = reports(tmp_path)
    folder = root / 'bats'
    for name in ('one', 'two', 'three'):
        (folder / (name + '.tap')).write_text('1..0\n')
        (folder / (name + '.tap.exit')).write_text('0\n')
    monkeypatch.setattr(module, 'MAX_REPORTS', 2)
    result = module.summarize(root)['bats']
    assert result['truncated']
    assert len(result['exit_codes']) <= 2


def test_exit_status_without_failure_record_is_preserved(tmp_path):
    root = reports(tmp_path)
    (root / 'pytest.xml').write_text('<testsuite/>')
    (root / 'pytest.exit').write_text('5\n')
    result = module.summarize(root)['pytest']
    assert result['tests'] == 0 and result['exit_code'] == 5


def test_reader_rejects_parent_symlink_and_traversal(tmp_path):
    root = reports(tmp_path / 'reports')
    (root / 'alias').symlink_to(root / 'bats', target_is_directory=True)
    with pytest.raises(OSError):
        module.read_report(root, 'alias/tests/bats/example.bats.tap', [0])
    with pytest.raises(ValueError):
        module.read_report(root, '../secret', [0])


def test_credentials_messages_parameters_and_bats_labels_never_upload(tmp_path):
    secret = 'credential_PRIVATE_7bf8d12'
    root = reports(tmp_path)
    (root / 'pytest.xml').write_text(f'<testsuite><testcase classname="tests.sample" name="test_failure[{secret}]"><failure message="password={secret}">{secret}</failure><system-out>{secret}</system-out></testcase><testcase classname="{secret}" name="test_failure"><error>{secret}</error></testcase><testcase classname="tests.sample" name="{secret}"><failure/></testcase></testsuite>')
    (root / 'bats/tests/bats/example.bats.tap').write_text(f'1..1\nnot ok 1 password={secret}\n# {secret}\n')
    result = module.summarize(root)
    encoded = json.dumps(result)
    assert secret not in encoded and 'password=' not in encoded
    assert result['pytest']['failure_details'][0] == {'test': 'tests/sample.py::test_failure', 'kind': 'failure'}
    assert result['bats']['failure_details'][0]['test'] == 'tests/bats/example.bats::case-1'
    assert all('message' not in item for framework in ('pytest', 'bats') for item in result[framework]['failure_details'])


def test_unrecognized_report_filename_and_parse_errors_do_not_leak(tmp_path):
    secret = 'private_token_54ab'
    root = reports(tmp_path)
    (root / 'pytest.xml').write_text(f'<testsuite>&{secret};</testsuite>')
    (root / f'bats/tests/bats/{secret}.bats.tap').write_text('1..0\n')
    assert secret not in json.dumps(module.summarize(root))


def test_summary_failure_cannot_erase_original_pytest_failure(tmp_path):
    binary, env = environment(tmp_path)
    fake(binary, 'python3', 'echo original-output; exit 7\n')
    test_result = subprocess.run(['bash', '-e', '-c', STEPS['Run pytest tests']['run']], env=env, cwd=tmp_path, capture_output=True)
    assert test_result.returncode == 7
    fake(binary, 'python3', 'exit 11\n')
    summary_result = subprocess.run(['bash', '-e', '-c', STEPS['Summarize test failures']['run']], env=env, cwd=tmp_path, capture_output=True)
    assert summary_result.returncode == 11
    assert (tmp_path / 'temp/tunaos-test-results/pytest.exit').read_text() == '7\n'
    assert not STEPS['Run pytest tests'].get('continue-on-error')


@pytest.mark.parametrize('kind', ['fifo', 'directory', 'symlink', 'regular'])
def test_output_never_opens_or_overwrites_existing_target(tmp_path, kind):
    output = tmp_path / 'summary.json'
    outside = tmp_path / 'outside'
    outside.write_bytes(b'preserve')
    if kind == 'fifo':
        os.mkfifo(output)
    elif kind == 'directory':
        output.mkdir()
    elif kind == 'symlink':
        output.symlink_to(outside)
    else:
        output.write_bytes(b'existing')
    result = subprocess.run([os.sys.executable, str(ROOT / 'scripts/summarize-test-failures.py'), '--reports', str(tmp_path / 'missing'), '--output', str(output)], capture_output=True, timeout=5)
    assert result.returncode != 0
    assert outside.read_bytes() == b'preserve'
    assert not list(tmp_path.glob('.test-summary-*'))
    if kind == 'regular':
        assert output.read_bytes() == b'existing'
    elif kind == 'fifo':
        import stat
        assert stat.S_ISFIFO(output.lstat().st_mode)


def test_unresolvable_source_identifiers_are_not_guessed(tmp_path):
    root = reports(tmp_path)
    (root / 'pytest.xml').write_text('<testsuite><testcase classname="tests.missing" name="test_missing"><failure/></testcase><testcase classname="tests.sample" name="test_dynamic"><failure/></testcase></testsuite>')
    details = module.summarize(root)['pytest']['failure_details']
    assert details == [{'test': 'unresolved-test', 'kind': 'failure'},
                       {'test': 'tests/sample.py::unresolved-test', 'kind': 'failure'}]


@pytest.mark.parametrize('kind', ['directory', 'symlink', 'fifo', 'file'])
def test_workflow_preserves_existing_output_and_cannot_enable_upload(tmp_path, kind):
    output = tmp_path / 'tunaos-test-failures.json'
    protected = tmp_path / 'protected'
    protected.write_text('credential-do-not-upload')
    if kind == 'directory':
        output.mkdir()
        (output / 'secret').write_text(protected.read_text())
    elif kind == 'symlink':
        output.symlink_to(protected)
    elif kind == 'fifo':
        os.mkfifo(output)
    else:
        output.write_text(protected.read_text())
    before = output.lstat()
    result = subprocess.run(['bash', '-eo', 'pipefail', '-c', STEPS['Summarize test failures']['run']],
                            cwd=ROOT, env={**os.environ, 'RUNNER_TEMP': str(tmp_path)},
                            capture_output=True, timeout=5)
    assert result.returncode != 0
    assert (output.lstat().st_mode, output.lstat().st_ino) == (before.st_mode, before.st_ino)
    assert protected.read_text() == 'credential-do-not-upload'
    assert "steps.test_failure_summary.outcome == 'success'" in STEPS['Archive test failure summary']['if']
    assert not list(tmp_path.glob('.test-summary-*'))


def test_workflow_publishes_only_a_regular_complete_summary(tmp_path):
    reports(tmp_path / 'tunaos-test-results')
    result = subprocess.run(['bash', '-eo', 'pipefail', '-c', STEPS['Summarize test failures']['run']],
                            cwd=ROOT, env={**os.environ, 'RUNNER_TEMP': str(tmp_path)},
                            capture_output=True, timeout=5)
    assert result.returncode == 0, result.stderr
    output = tmp_path / 'tunaos-test-failures.json'
    assert output.is_file() and not output.is_symlink()
    assert json.loads(output.read_text())['pytest']['exit_code'] == 1
    assert '[[ -f ' in STEPS['Summarize test failures']['run']
    assert '&& ! -L ' in STEPS['Summarize test failures']['run']
