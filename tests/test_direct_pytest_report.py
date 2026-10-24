"""Local direct diagnostic proposal preserves pytest semantics and privacy.

Falsification: messages, parameter values, invalid source names, setup errors,
collection errors or failed output writes must not change results or leak data.
"""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_plugin():
    spec = importlib.util.spec_from_file_location('direct_report', ROOT / 'scripts/compact_pytest_report.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tree(tmp_path, source):
    (tmp_path / 'scripts').mkdir()
    (tmp_path / 'tests').mkdir()
    for name in ('compact_pytest_report.py', 'summarize-test-failures.py'):
        shutil.copyfile(ROOT / 'scripts' / name, tmp_path / 'scripts' / name)
    (tmp_path / 'tests/test_sample.py').write_text(source)
    return tmp_path


def run(root, enabled, output='report.json'):
    args = [os.sys.executable, '-m', 'pytest', '-q', '--tb=short', 'tests']
    if enabled:
        args += ['-p', 'scripts.compact_pytest_report', '--compact-test-report=' + output]
    env = {k: v for k, v in os.environ.items() if not k.startswith('PYTEST_')}
    env['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
    return subprocess.run(args, cwd=root, env=env, text=True, capture_output=True, timeout=15)


def test_same_exit_and_console_with_private_parameters(tmp_path):
    root = tree(tmp_path, '''import pytest
@pytest.mark.parametrize('value', ['credential-secret-value'])
def test_failure(value):
    assert False, value
def test_pass(): pass
''')
    plain, reported = run(root, False), run(root, True)
    assert plain.returncode == reported.returncode == 1
    normalize = lambda text: re.sub(r'\b[0-9]+\.[0-9]+s\b', 'TIME', text)
    assert normalize(plain.stdout) == normalize(reported.stdout)
    assert plain.stderr == reported.stderr
    raw = (root / 'report.json').read_text()
    assert 'credential-secret-value' not in raw
    result = json.loads(raw)['pytest']
    assert result['tests'] == 2 and result['failures'] == 1 and result['exit_code'] == 1
    assert result['failure_details'] == [{'test': 'tests/test_sample.py::test_failure', 'kind': 'failure'}]


@pytest.mark.parametrize('source,exit_code', [
    ('import pytest\n@pytest.fixture\ndef bad(): raise RuntimeError("secret")\ndef test_setup(bad): pass\n', 1),
    ('raise RuntimeError("secret during collection")\n', 2),
    ('def broken syntax secret\n', 2),
])
def test_setup_and_collection_errors_are_visible(tmp_path, source, exit_code):
    root = tree(tmp_path, source)
    result = run(root, True)
    assert result.returncode == exit_code
    raw = (root / 'report.json').read_text()
    assert 'secret' not in raw
    report = json.loads(raw)['pytest']
    assert report['errors'] == 1 and report['exit_code'] == exit_code
    assert report['failure_details'][0]['test'].startswith('tests/test_sample.py::')


@pytest.mark.parametrize('kind', ['file', 'directory', 'symlink', 'fifo'])
def test_output_failure_does_not_change_pytest_result(tmp_path, kind):
    root = tree(tmp_path, 'def test_failure(): assert False\n')
    output = root / 'report.json'
    if kind == 'file': output.write_text('preserve')
    elif kind == 'directory': output.mkdir()
    elif kind == 'symlink': output.symlink_to(root / 'outside')
    else: os.mkfifo(output)
    before = output.lstat()
    result = run(root, True)
    assert result.returncode == 1
    assert output.lstat().st_ino == before.st_ino
    assert not list(root.glob('.test-summary-*'))


def test_assertion_payload_is_never_read_and_details_are_bounded(tmp_path):
    module = load_plugin()
    reporter = module.Reporter(tmp_path / 'report.json')
    class Report:
        when = 'call'
        failed = True
        skipped = False
        nodeid = 'tests/test_direct_pytest_report.py::test_same_exit_and_console_with_private_parameters[secret]'
        @property
        def longrepr(self): raise AssertionError('must not access giant/private payload')
    for _ in range(105): reporter.pytest_runtest_logreport(Report())
    reporter.pytest_sessionfinish(None, 1)
    raw = (tmp_path / 'report.json').read_text()
    assert 'secret' not in raw
    result = json.loads(raw)['pytest']
    assert result['failures'] == 105 and result['truncated']
    assert len(result['failure_details']) == 100
    assert 'direct-reporter-error' not in result['issues']


def test_setup_call_teardown_counts_and_xfail_xpass(tmp_path):
    root = tree(tmp_path, '''import pytest
@pytest.fixture
def teardown_error():
    yield
    raise RuntimeError("private teardown")
def test_both(teardown_error): assert False
@pytest.mark.xfail
def test_xfail(): assert False
@pytest.mark.xfail
def test_xpass(): pass
@pytest.mark.xfail(strict=True)
def test_strict_xpass(): pass
@pytest.mark.skip
def test_skip(): pass
''')
    result = run(root, True)
    assert result.returncode == 1
    summary = json.loads((root / 'report.json').read_text())['pytest']
    assert summary['tests'] == 5  # One setup report per collected/running item.
    assert summary['failures'] == 2  # Call failure and strict XPASS.
    assert summary['errors'] == 1  # Teardown error is a separate failed phase.
    assert summary['skipped'] == 2  # XFAIL and ordinary skip, matching pytest outcomes.
    assert {d['test'] for d in summary['failure_details']} == {
        'tests/test_sample.py::test_both', 'tests/test_sample.py::test_strict_xpass'}


def test_source_budget_exhaustion_keeps_failure_explicit(tmp_path, monkeypatch):
    module = load_plugin()
    monkeypatch.setattr(module._SUMMARY, 'MAX_TOTAL', 1)
    reporter = module.Reporter(tmp_path / 'report.json')
    report = SimpleNamespace(when='call', failed=True, skipped=False,
        nodeid='tests/test_direct_pytest_report.py::test_source_budget_exhaustion_keeps_failure_explicit[private]')
    reporter.pytest_runtest_logreport(report)
    reporter.pytest_sessionfinish(None, 1)
    result = json.loads((tmp_path / 'report.json').read_text())['pytest']
    assert result['failures'] == 1 and result['exit_code'] == 1
    assert result['failure_details'] == [{'test': 'unresolved-test', 'kind': 'failure'}]
    assert result['truncated']


def test_plugin_initialization_failure_preserves_exit_and_console(tmp_path):
    root = tree(tmp_path, 'def test_failure(): assert False\n')
    (root / 'scripts/summarize-test-failures.py').write_text('raise RuntimeError("private initialization")\n')
    result = run(root, True)
    assert result.returncode == 1
    assert 'private initialization' not in result.stdout + result.stderr
    assert not (root / 'report.json').exists()
    assert '1 failed' in result.stdout


def test_explicit_outer_options_are_not_inherited_by_nested_pytest(tmp_path):
    root = tree(tmp_path, '''import os, subprocess, sys
from pathlib import Path
def test_nested():
    Path('inner').mkdir()
    Path('inner/test_inner.py').write_text('def test_inner(): assert True\\n')
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q', 'inner'], capture_output=True)
    assert result.returncode == 0
    assert not Path('report.json').exists()
    assert 'PYTEST_ADDOPTS' not in os.environ
    assert 'PYTEST_PLUGINS' not in os.environ
''')
    result = run(root, True)
    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads((root / 'report.json').read_text())['pytest']
    assert summary['tests'] == 1 and summary['exit_code'] == 0


def test_error_reporting_failure_cannot_escape(tmp_path, monkeypatch):
    module = load_plugin()
    reporter = module.Reporter(tmp_path / 'report.json')
    def broken(*args): raise RuntimeError('private diagnostic failure')
    monkeypatch.setattr(reporter, 'record_failure', broken)
    monkeypatch.setattr(module._SUMMARY, 'issue', broken)
    reporter.pytest_runtest_logreport(SimpleNamespace(when='call', skipped=False, failed=True, nodeid='bad'))
    reporter.pytest_collectreport(SimpleNamespace(failed=True, nodeid='bad'))


def test_long_static_function_id_is_unresolved_without_truncating_name(tmp_path):
    root = tree(tmp_path, 'def test_' + 'a' * 600 + '(): assert False\n')
    result = run(root, True)
    assert result.returncode == 1
    summary = json.loads((root / 'report.json').read_text())['pytest']
    assert summary['failure_details'] == [{'test': 'unresolved-test', 'kind': 'failure'}]
    assert summary['truncated']


def test_class_scoped_same_name_methods_remain_distinct(tmp_path):
    root = tree(tmp_path, 'class TestOne:\n    def test_same(self): assert False\nclass TestTwo:\n    def test_same(self): assert False\n')
    result = run(root, True)
    assert result.returncode == 1
    report = json.loads((root / 'report.json').read_text())['pytest']
    assert [detail['test'] for detail in report['failure_details']] == [
        'tests/test_sample.py::TestOne::test_same', 'tests/test_sample.py::TestTwo::test_same']


def test_explicit_node_file_is_not_reinterpreted_as_class_named_module(tmp_path):
    root = tree(tmp_path, 'class TestOne:\n    def test_same(self): assert False\n')
    (root / 'tests/test_sample').mkdir()
    (root / 'tests/test_sample/TestOne.py').write_text('def test_same(): pass\n')
    result = run(root, True)
    assert result.returncode == 1
    report = json.loads((root / 'report.json').read_text())['pytest']
    assert report['failure_details'] == [{'test': 'tests/test_sample.py::TestOne::test_same', 'kind': 'failure'}]
