"""Local proposal: collect bounded static failure IDs without assertion text.

Load explicitly on the outer invocation with -p scripts.compact_pytest_report
and --compact-test-report=PATH. No PYTEST_ADDOPTS or inherited plugin setting.

Counts describe reports: tests counts setup phases, failures counts failed call
phases, errors counts failed setup/teardown/collection phases, and skipped counts
skipped phases (including xfail). Non-strict xpass succeeds; strict xpass fails.
One test can have both a call failure and a teardown error. Collection failures
can have a verified module ID without a function. Unresolvable IDs stay unknown
and mark the summary truncated; no identifier is guessed.
"""
import importlib.util
import json
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    'compact_summary', Path(__file__).with_name('summarize-test-failures.py'))
try:
    _SUMMARY = importlib.util.module_from_spec(_SPEC)
    _SPEC.loader.exec_module(_SUMMARY)
except Exception:
    _SUMMARY = None  # The collector must report missing direct output explicitly.


class Reporter:
    def __init__(self, output):
        self.output = Path(output)
        self.result = _SUMMARY.empty()
        self.source_budget = [0]

    def record_failure(self, nodeid, kind):
        self.result['failures' if kind == 'failure' else 'errors'] += 1
        if len(self.result['failure_details']) >= _SUMMARY.MAX_FAILURES:
            self.result['truncated'] = True
            return
        # Discard parameter values before any name processing or output.
        parts = nodeid.split('[', 1)[0].split('::')
        name = parts[-1] if len(parts) > 1 else 'unresolved_test'
        identifier = (_SUMMARY.source_collection_id(parts[0], self.source_budget)
                      if len(parts) == 1 else
                      _SUMMARY.source_node_id(parts[0], parts[1:-1], name, self.source_budget))
        if len(identifier.encode('utf-8')) > 512:
            identifier = 'unresolved-test'
        if identifier == 'unresolved-test' or identifier.endswith('::unresolved-test'):
            self.result['truncated'] = True
        _SUMMARY.failure(self.result, identifier, kind)

    def report_error(self):
        try:
            _SUMMARY.issue(self.result, 'direct-reporter-error')
        except Exception:
            pass  # Even a defective fallback must not escape into pytest.

    def pytest_runtest_logreport(self, report):
        # Do not access longrepr, caplog, capstdout, capstderr or parameter values.
        try:
            if report.when == 'setup':
                self.result['tests'] += 1
            if report.skipped:
                self.result['skipped'] += 1
            if report.failed:
                self.record_failure(report.nodeid, 'failure' if report.when == 'call' else 'error')
        except Exception:
            # A diagnostic defect must not alter pytest's result.
            self.report_error()

    def pytest_collectreport(self, report):
        try:
            if report.failed:
                self.record_failure(report.nodeid, 'error')
        except Exception:
            self.report_error()

    def pytest_sessionfinish(self, session, exitstatus):
        try:
            self.result['exit_code'] = int(exitstatus)
            payload = {'schema_version': 1, 'kind': 'pytest-static-summary', 'pytest': self.result}
            _SUMMARY.write_summary(self.output, (json.dumps(payload, sort_keys=True) + '\n').encode())
        except Exception:
            # Missing output is diagnosed by the separate collector. Preserve
            # pytest's original exit status and its existing console rendering.
            pass


def pytest_addoption(parser):
    try:
        parser.addoption('--compact-test-report', default=None)
    except Exception:
        pass  # Reporting initialization must not replace the test outcome.


def pytest_configure(config):
    try:
        output = config.getoption('--compact-test-report')
        if output:
            config.pluginmanager.register(Reporter(output), 'bounded-static-test-reporter')
    except Exception:
        pass  # No artifact means missing diagnostics, never a successful test run.
