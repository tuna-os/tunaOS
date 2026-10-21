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
    (tmp_path / 'temp/tunaos-test-results').mkdir(parents=True)
    return binary, {**os.environ, 'TEST_REPORT_ROOT': str(tmp_path / 'temp/tunaos-test-results'), 'PATH': str(binary) + ':' + os.environ['PATH'], 'RUNNER_TEMP': str(tmp_path / 'temp')}


def test_pytest_wrapper_keeps_exit_and_stdout(tmp_path):
    binary, env = environment(tmp_path)
    fake(binary, 'python3', 'printf "%s\\n" "$@"; echo original-output; exit 7\n')
    result = subprocess.run(['bash', '-eo', 'pipefail', '-c', STEPS['Run pytest tests']['run']], env=env, cwd=tmp_path, text=True, capture_output=True)
    assert result.returncode == 7 and 'original-output' in result.stdout
    assert '--junitxml=' not in result.stdout
    assert (tmp_path / 'temp/tunaos-test-results/pytest.exit').read_text() == '7\n'
    assert 'PYTEST_ADDOPTS' not in STEPS['Run pytest tests']['run']


@pytest.mark.parametrize('bats_code,tee_code', [(9, 0), (0, 4), (9, 4)])
def test_bats_and_tee_failures_keep_gate(tmp_path, bats_code, tee_code):
    binary, env = environment(tmp_path)
    path = tmp_path / 'tests/bats/a.bats'
    path.parent.mkdir(parents=True)
    path.write_text('fixture')
    fake(binary, 'bats', f'echo "1..1"; echo "not ok 1 original-output"; exit {bats_code}\n')
    if tee_code:
        fake(binary, 'tee', f'cat; exit {tee_code}\n')
    result = subprocess.run(['bash', '-eo', 'pipefail', '-c', STEPS['Run BATS tests']['run']], env=env, cwd=tmp_path, text=True, capture_output=True)
    assert result.returncode == (1 if bats_code else 0) and 'original-output' in result.stdout
    code = (tmp_path / 'temp/tunaos-test-results/bats/tests/bats/a.bats.tap.exit').read_text()
    assert int(code) == bats_code
    if tee_code:
        assert 'BATS diagnostic output could not be saved' in result.stdout


def test_workflow_upload_is_narrow_and_pinned():
    upload = STEPS['Archive test failure summary']
    assert upload['if'] == "failure() && steps.test_failure_summary.outcome == 'success'"
    assert STEPS['Summarize test failures']['id'] == 'test_failure_summary'
    assert upload['uses'] == STEPS['Archive Python coverage']['uses']
    assert upload['with']['path'] == '${{ steps.test_diagnostics.outputs.report_root }}/failures.json'
    assert upload['with']['retention-days'] == 7
    assert STEPS['Run pytest tests']['if'] == 'always()'
    assert STEPS['Run BATS tests']['if'] == 'always()'
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
    output = tmp_path / 'failures.json'
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
                            cwd=ROOT, env={**os.environ, 'RUNNER_TEMP': str(tmp_path), 'TEST_REPORT_ROOT': str(tmp_path)},
                            capture_output=True, timeout=5)
    assert result.returncode != 0
    assert (output.lstat().st_mode, output.lstat().st_ino) == (before.st_mode, before.st_ino)
    assert protected.read_text() == 'credential-do-not-upload'
    assert "steps.test_failure_summary.outcome == 'success'" in STEPS['Archive test failure summary']['if']
    assert not list(tmp_path.glob('.test-summary-*'))


def test_workflow_publishes_only_a_regular_complete_summary(tmp_path):
    reports(tmp_path)
    result = subprocess.run(['bash', '-eo', 'pipefail', '-c', STEPS['Summarize test failures']['run']],
                            cwd=ROOT, env={**os.environ, 'RUNNER_TEMP': str(tmp_path), 'TEST_REPORT_ROOT': str(tmp_path)},
                            capture_output=True, timeout=5)
    assert result.returncode == 0, result.stderr
    output = tmp_path / 'failures.json'
    assert output.is_file() and not output.is_symlink()
    assert json.loads(output.read_text())['pytest']['exit_code'] == 1
    assert 'missing-direct-summary' in json.loads(output.read_text())['pytest']['issues']
    assert '[[ -f ' in STEPS['Summarize test failures']['run']
    assert '&& ! -L ' in STEPS['Summarize test failures']['run']


@pytest.mark.parametrize('content,code', [
    (b'\xff', 'invalid-utf8-junit'),
    (b'<broken', 'invalid-xml-junit'),
    (b'<arbitrary/>', 'unexpected-junit-root'),
    (b'<!DOCTYPE x><testsuite/>', 'forbidden-xml-declaration-or-nul'),
    (b'<testsuite>' + b'<a>' * 65 + b'</a>' * 65 + b'</testsuite>', 'xml-structure-limit'),
])
def test_junit_rejection_reason_is_fixed_and_content_free(tmp_path, content, code):
    root = reports(tmp_path)
    (root / 'pytest.xml').write_bytes(content)
    result = module.summarize(root)['pytest']
    assert result['issues'] == [code]
    assert result['exit_code'] == 1


def test_missing_and_oversized_junit_are_distinct_without_raising_limits(tmp_path, monkeypatch):
    root = reports(tmp_path)
    report = root / 'pytest.xml'
    report.unlink()
    assert module.summarize(root)['pytest']['issues'] == ['missing-junit']
    monkeypatch.setattr(module, 'MAX_FILE', 16)
    report.write_bytes(b'credential-never-publish' * 2)
    result = module.summarize(root)['pytest']
    assert result['issues'] == ['oversized-report']
    assert result['report_size_bytes'] == report.stat().st_size
    assert 'credential' not in json.dumps(result)
    assert module.MAX_FILE == 16


def test_changed_junit_has_fixed_reason_and_original_exit(tmp_path, monkeypatch):
    root = reports(tmp_path)
    original = module.read_report
    def changed(root, relative, budget):
        if relative == 'pytest.xml':
            raise module.ReportError('report-changed-during-read', 123)
        return original(root, relative, budget)
    monkeypatch.setattr(module, 'read_report', changed)
    result = module.summarize(root)['pytest']
    assert result['issues'] == ['report-changed-during-read']
    assert result['report_size_bytes'] == 123
    assert result['exit_code'] == 1


def direct_document():
    result = module.empty()
    result.update(tests=1, failures=1, exit_code=1,
                  failure_details=[{'test': 'tests/sample.py::test_failure', 'kind': 'failure'}])
    return {'schema_version': 1, 'kind': 'pytest-static-summary', 'pytest': result}


def test_direct_summary_recovers_ids_with_invalid_junit_but_keeps_issue(tmp_path):
    root = reports(tmp_path)
    (root / 'pytest.xml').unlink()
    (root / 'pytest-static.json').write_text(json.dumps(direct_document()))
    result = module.summarize(root, direct=True)
    assert result['pytest_source'] == 'direct'
    assert 'junit_issues' not in result
    assert result['pytest']['failure_details'] == direct_document()['pytest']['failure_details']
    assert result['pytest']['exit_code'] == 1


@pytest.mark.parametrize('change', [
    lambda d: d.update(secret='credential'),
    lambda d: d.update(schema_version=True),
    lambda d: d.update(kind='untrusted'),
    lambda d: d['pytest'].update(tests=True),
    lambda d: d['pytest'].update(failures=-1),
    lambda d: d['pytest'].update(exit_code=0),
    lambda d: d['pytest'].update(truncated=1),
    lambda d: d['pytest'].update(issues=['credential']),
    lambda d: d['pytest'].update(message='credential'),
    lambda d: d['pytest']['failure_details'][0].update(message='credential'),
    lambda d: d['pytest']['failure_details'][0].update(test='../secret.py::test_failure'),
    lambda d: d['pytest']['failure_details'][0].update(test='tests/missing.py::test_failure'),
    lambda d: d['pytest']['failure_details'][0].update(test='tests/sample.py::test_missing'),
    lambda d: d['pytest']['failure_details'][0].update(test='tests/sample.py::test_failure[credential]'),
    lambda d: d['pytest']['failure_details'][0].update(kind='credential'),
    lambda d: d['pytest'].update(failures=0),
    lambda d: d['pytest'].update(failure_details=[{'test': 'unresolved-test', 'kind': 'failure'}] * 101),
])
def test_direct_summary_is_strict_and_never_echoes_invalid_values(tmp_path, change):
    root = reports(tmp_path)
    document = direct_document()
    change(document)
    (root / 'pytest-static.json').write_text(json.dumps(document))
    result = module.summarize(root, direct=True)
    assert result.get('pytest_source') != 'direct'
    assert result['pytest']['exit_code'] == 1
    assert any('direct' in code for code in result['pytest']['issues'])
    assert 'credential' not in json.dumps(result)


def test_missing_direct_output_never_infers_pass(tmp_path):
    root = reports(tmp_path)
    result = module.summarize(root, direct=True)
    assert 'missing-direct-summary' in result['pytest']['issues']
    assert result['pytest']['exit_code'] == 1


def test_direct_duplicate_json_keys_are_rejected(tmp_path):
    root = reports(tmp_path)
    text = json.dumps(direct_document()).replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1')
    (root / 'pytest-static.json').write_text(text)
    assert 'invalid-direct-summary' in module.summarize(root, direct=True)['pytest']['issues']


def test_direct_output_size_and_incomplete_counts_are_rejected(tmp_path, monkeypatch):
    root = reports(tmp_path)
    document = direct_document()
    document['pytest']['failure_details'] = []
    (root / 'pytest-static.json').write_text(json.dumps(document))
    assert 'incomplete-direct-summary' in module.summarize(root, direct=True)['pytest']['issues']
    monkeypatch.setattr(module, 'MAX_OUTPUT', 16)
    assert 'oversized-direct-summary' in module.summarize(root, direct=True)['pytest']['issues']


def test_collection_id_does_not_require_valid_python_but_rejects_symlink(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    (source / 'tests').mkdir(parents=True)
    (source / 'tests/test_broken.py').write_text('def invalid syntax\n')
    monkeypatch.setattr(module, 'SOURCE_ROOT', source)
    identifier = 'tests/test_broken.py::unresolved-test'
    assert module.source_collection_id('tests/test_broken.py', [0]) == identifier
    document = direct_document()
    document['pytest']['failure_details'][0]['test'] = identifier
    assert module.parse_direct_summary(json.dumps(document), 1, [0])['failure_details'][0]['test'] == identifier
    (source / 'tests/test_link.py').symlink_to(source / 'tests/test_broken.py')
    assert module.source_collection_id('tests/test_link.py', [0]) == 'unresolved-test'
    document['pytest']['failure_details'][0]['test'] = 'tests/test_link.py::unresolved-test'
    with pytest.raises(module.ReportError, match='invalid-direct-source-id'):
        module.parse_direct_summary(json.dumps(document), 1, [0])


def test_direct_validation_has_priority_over_junit_source_budget(tmp_path, monkeypatch):
    root = reports(tmp_path)
    document = direct_document()
    (root / 'pytest-static.json').write_text(json.dumps(document))
    original = module.parse_junit
    def exhaust(text, result, budget):
        original(text, result, budget)
        budget[0] = module.MAX_TOTAL
    monkeypatch.setattr(module, 'parse_junit', exhaust)
    result = module.summarize(root, direct=True)
    assert result['pytest_source'] == 'direct'
    assert result['pytest']['failure_details'] == document['pytest']['failure_details']


def test_recursive_source_ast_cannot_break_summary(tmp_path, monkeypatch):
    root = reports(tmp_path)
    source = tmp_path / 'source'
    (source / 'tests').mkdir(parents=True)
    (source / 'tests/sample.py').write_text('def test_failure(): pass\nx=' + '1+' * 10000 + '1\n')
    monkeypatch.setattr(module, 'SOURCE_ROOT', source)
    (root / 'pytest-static.json').write_text(json.dumps(direct_document()))
    result = module.summarize(root, direct=True)
    assert 'invalid-direct-source-id' in result['pytest']['issues']
    assert result['pytest']['exit_code'] == 1


def test_direct_does_not_read_intentionally_absent_junit(tmp_path, monkeypatch):
    root = reports(tmp_path)
    (root / 'pytest-static.json').write_text(json.dumps(direct_document()))
    original = module.read_report
    def no_junit(root, relative, budget):
        assert relative != 'pytest.xml'
        return original(root, relative, budget)
    monkeypatch.setattr(module, 'read_report', no_junit)
    result = module.summarize(root, direct=True)
    assert result['pytest_source'] == 'direct'
    assert not result['pytest']['issues']


def test_workflow_activates_direct_reporter_only_on_outer_command(tmp_path):
    binary, env = environment(tmp_path)
    env.pop('PYTEST_ADDOPTS', None)
    env.pop('PYTEST_PLUGINS', None)
    fake(binary, 'python3', '''[[ -z "${PYTEST_ADDOPTS+x}" && -z "${PYTEST_PLUGINS+x}" ]] || exit 92
printf '%s\\n' "$@"
echo original-console
exit 7
''')
    result = subprocess.run(['bash', '-eo', 'pipefail', '-c', STEPS['Run pytest tests']['run']],
                            env=env, cwd=tmp_path, text=True, capture_output=True)
    assert result.returncode == 7
    assert 'original-console' in result.stdout
    assert '-p\nscripts.compact_pytest_report\n' in result.stdout
    assert '--compact-test-report=' + env['RUNNER_TEMP'] + '/tunaos-test-results/pytest-static.json' in result.stdout
    assert (tmp_path / 'temp/tunaos-test-results/pytest.exit').read_text() == '7\n'
    assert '--direct' in STEPS['Summarize test failures']['run']
    for step in STEPS.values():
        assert 'PYTEST_ADDOPTS' not in step.get('env', {})
        assert 'PYTEST_PLUGINS' not in step.get('env', {})
    assert 'PYTEST_ADDOPTS' not in WORKFLOW.get('env', {})
    assert 'PYTEST_PLUGINS' not in WORKFLOW.get('env', {})
    for job in WORKFLOW['jobs'].values():
        assert 'PYTEST_ADDOPTS' not in job.get('env', {})
        assert 'PYTEST_PLUGINS' not in job.get('env', {})


def test_class_scope_is_validated_and_preserved(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    (source / 'tests').mkdir(parents=True)
    (source / 'tests/sample.py').write_text('class TestOne:\n    def test_same(self): pass\nclass TestTwo:\n    def test_same(self): pass\n')
    monkeypatch.setattr(module, 'SOURCE_ROOT', source)
    for name in ('TestOne', 'TestTwo'):
        identifier = 'tests/sample.py::' + name + '::test_same'
        assert module.source_test_id('tests.sample.' + name, 'test_same', [0]) == identifier
        document = direct_document()
        document['pytest']['failure_details'][0]['test'] = identifier
        assert module.parse_direct_summary(json.dumps(document), 1, [0])['failure_details'][0]['test'] == identifier
    assert module.source_test_id('tests.sample.Unknown', 'test_same', [0]) == 'tests/sample.py::unresolved-test'
    document['pytest']['failure_details'][0]['test'] = 'tests/sample.py::Unknown::test_same'
    with pytest.raises(module.ReportError, match='invalid-direct-source-id'):
        module.parse_direct_summary(json.dumps(document), 1, [0])


def test_direct_validator_uses_explicit_file_boundary(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    (source / 'tests/sample').mkdir(parents=True)
    (source / 'tests/sample.py').write_text('class TestOne:\n    def test_same(self): pass\n')
    (source / 'tests/sample/TestOne.py').write_text('def test_same(): pass\n')
    monkeypatch.setattr(module, 'SOURCE_ROOT', source)
    document = direct_document()
    identifier = 'tests/sample.py::TestOne::test_same'
    document['pytest']['failure_details'][0]['test'] = identifier
    assert module.parse_direct_summary(json.dumps(document), 1, [0])['failure_details'][0]['test'] == identifier


def test_junit_competing_module_and_class_paths_stay_unresolved(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    (source / 'tests/sample').mkdir(parents=True)
    (source / 'tests/sample.py').write_text('class TestOne:\n    def test_same(self): pass\n')
    (source / 'tests/sample/TestOne.py').write_text('def test_same(): pass\n')
    monkeypatch.setattr(module, 'SOURCE_ROOT', source)
    result = module.empty()
    module.parse_junit('<testsuite><testcase classname="tests.sample.TestOne" name="test_same"><failure/></testcase></testsuite>', result, [0])
    assert result['failure_details'] == [{'test': 'unresolved-test', 'kind': 'failure'}]


def test_junit_long_static_name_is_not_silently_shortened(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    (source / 'tests').mkdir(parents=True)
    name = 'test_' + 'a' * 600
    (source / 'tests/sample.py').write_text('def ' + name + '(): pass\n')
    monkeypatch.setattr(module, 'SOURCE_ROOT', source)
    result = module.empty()
    module.parse_junit('<testsuite><testcase classname="tests.sample" name="' + name + '"><failure/></testcase></testsuite>', result, [0])
    assert result['failure_details'] == [{'test': 'unresolved-test', 'kind': 'failure'}]
    assert result['truncated']


def test_long_bats_identity_keeps_case_unknown_instead_of_shortening():
    result = module.empty()
    module.failure(result, 'tests/' + 'a' * 500 + '.bats::case-123', 'failure')
    assert result['failure_details'] == [{'test': 'unresolved-test', 'kind': 'failure'}]
    assert result['truncated']


def test_junit_candidate_budget_failure_cannot_select_wrong_interpretation(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    (source / 'tests/sample').mkdir(parents=True)
    (source / 'tests/sample.py').write_text('class TestOne:\n    def test_same(self): pass\n')
    (source / 'tests/sample/TestOne.py').write_text('def test_same(): pass\n')
    monkeypatch.setattr(module, 'SOURCE_ROOT', source)
    monkeypatch.setattr(module, 'MAX_TOTAL', 40)
    assert module.source_test_id('tests.sample.TestOne', 'test_same', [0]) == 'unresolved-test'


def test_junit_overlong_candidate_path_cannot_hide_competing_interpretation(monkeypatch):
    def must_not_guess(*args, **kwargs):
        raise AssertionError('must reject before interpreting partial source paths')
    monkeypatch.setattr(module, 'source_node_id', must_not_guess)
    classname = 'tests.' + 'a' * 200 + '.' + 'b' * 200 + '.' + 'c' * 73
    assert len(classname) == 481
    assert module.source_test_id(classname, 'test_same', [0]) == 'unresolved-test'


@pytest.mark.parametrize('status', [0, 2, 7])
def test_failed_pytest_status_write_preserves_original_exit(tmp_path, status):
    binary, env = environment(tmp_path)
    path = tmp_path / 'temp/tunaos-test-results/pytest.exit'
    path.mkdir(parents=True)
    fake(binary, 'python3', f'echo original-output; exit {status}\n')
    result = subprocess.run(['bash', '-eo', 'pipefail', '-c', STEPS['Run pytest tests']['run']],
                            env=env, cwd=tmp_path, text=True, capture_output=True)
    assert result.returncode == status
    assert 'original-output' in result.stdout
    assert path.is_dir()


@pytest.mark.parametrize('status', [0, 9])
def test_failed_bats_status_write_does_not_skip_later_suites(tmp_path, status):
    binary, env = environment(tmp_path)
    directory = tmp_path / 'tests/bats'
    directory.mkdir(parents=True)
    for name in ('a.bats', 'b.bats'):
        (directory / name).write_text('fixture')
    path = tmp_path / 'temp/tunaos-test-results/bats/tests/bats/a.bats.tap.exit'
    path.mkdir(parents=True)
    fake(binary, 'bats', f'echo "1..1"; echo "ok 1 original-output"; echo "$*" >> "{tmp_path}/calls"; exit {status}\n')
    result = subprocess.run(['bash', '-eo', 'pipefail', '-c', STEPS['Run BATS tests']['run']],
                            env=env, cwd=tmp_path, text=True, capture_output=True)
    assert result.returncode == (1 if status else 0)
    assert len((tmp_path / 'calls').read_text().splitlines()) == 2
    assert path.is_dir()


@pytest.mark.parametrize('failure', ['mktemp', 'output'])
def test_diagnostic_setup_failure_never_suppresses_core_tests(tmp_path, failure):
    binary, env = environment(tmp_path)
    output = tmp_path / 'step-output'
    if failure == 'mktemp':
        fake(binary, 'mktemp', 'exit 1\n')
    else:
        output.mkdir()
    env['GITHUB_OUTPUT'] = str(output)
    setup = subprocess.run(['bash', '-eo', 'pipefail', '-c', STEPS['Prepare test diagnostics']['run']],
                           env=env, cwd=tmp_path, text=True, capture_output=True)
    assert setup.returncode == 0
    assert not output.is_file() or not output.read_text()
    env['TEST_REPORT_ROOT'] = ''
    fake(binary, 'python3', 'printf "%s\\n" "$@"; echo original-pytest; exit 7\n')
    path = tmp_path / 'tests/bats'
    path.mkdir(parents=True)
    (path / 'a.bats').write_text('fixture')
    fake(binary, 'bats', 'echo original-bats; exit 9\n')
    py = subprocess.run(['bash', '-eo', 'pipefail', '-c', STEPS['Run pytest tests']['run']],
                        env=env, cwd=tmp_path, text=True, capture_output=True)
    bats = subprocess.run(['bash', '-eo', 'pipefail', '-c', STEPS['Run BATS tests']['run']],
                          env=env, cwd=tmp_path, text=True, capture_output=True)
    assert py.returncode == 7 and 'original-pytest' in py.stdout
    assert '--compact-test-report' not in py.stdout and '--junitxml' not in py.stdout
    assert bats.returncode == 1 and 'original-bats' in bats.stdout
    assert not list((tmp_path / 'temp').glob('tunaos-test-results.*'))


def test_unique_report_root_and_cleanup_preserve_other_paths(tmp_path):
    _, env = environment(tmp_path)
    output = tmp_path / 'step-output'
    env['GITHUB_OUTPUT'] = str(output)
    stale = tmp_path / 'temp/tunaos-test-results.stale'
    stale.mkdir()
    (stale / 'preserve').write_text('unchanged')
    setup = subprocess.run(['bash', '-eo', 'pipefail', '-c', STEPS['Prepare test diagnostics']['run']],
                           env=env, cwd=tmp_path, capture_output=True)
    assert setup.returncode == 0
    root = Path(output.read_text().strip().split('=', 1)[1])
    assert root.parent == tmp_path / 'temp' and root != stale
    (root / 'owned-report').write_text('fixture')
    env['TEST_REPORT_ROOT'] = str(root)
    cleanup = subprocess.run(['bash', '-eo', 'pipefail', '-c', STEPS['Clean up test diagnostics']['run']],
                             env=env, cwd=tmp_path, capture_output=True)
    assert cleanup.returncode == 0 and not root.exists()
    assert (stale / 'preserve').read_text() == 'unchanged'
    names = list(STEPS)
    assert names.index('Archive test failure summary') < names.index('Clean up test diagnostics')
    assert "steps.test_diagnostics.outputs.report_root != ''" in STEPS['Summarize test failures']['if']


def test_bats_report_directory_failure_still_runs_all_suites(tmp_path):
    binary, env = environment(tmp_path)
    path = tmp_path / 'tests/bats'
    path.mkdir(parents=True)
    for name in ('a.bats', 'b.bats'):
        (path / name).write_text('fixture')
    fake(binary, 'mkdir', 'exit 1\n')
    fake(binary, 'bats', f'echo "$*" >> "{tmp_path}/calls"; exit 9\n')
    result = subprocess.run(['bash', '-eo', 'pipefail', '-c', STEPS['Run BATS tests']['run']],
                            env=env, cwd=tmp_path, capture_output=True)
    assert result.returncode == 1
    assert len((tmp_path / 'calls').read_text().splitlines()) == 2


@pytest.mark.parametrize('kind', ['outside', 'nested', 'symlink'])
def test_cleanup_rejects_unowned_paths(tmp_path, kind):
    _, env = environment(tmp_path)
    protected = tmp_path / 'protected'
    protected.mkdir()
    (protected / 'keep').write_text('unchanged')
    if kind == 'outside':
        root = protected
    elif kind == 'nested':
        parent = tmp_path / 'temp/tunaos-test-results.parent'
        parent.mkdir()
        root = parent / '../../protected'
    else:
        root = tmp_path / 'temp/tunaos-test-results.link'
        root.symlink_to(protected, target_is_directory=True)
    env['TEST_REPORT_ROOT'] = str(root)
    result = subprocess.run(['bash', '-eo', 'pipefail', '-c', STEPS['Clean up test diagnostics']['run']],
                            env=env, cwd=tmp_path, capture_output=True)
    assert result.returncode == 0
    assert (protected / 'keep').read_text() == 'unchanged'
