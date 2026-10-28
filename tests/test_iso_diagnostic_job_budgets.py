"""Inert workflow graph and documented budget contract; no workflow execution."""
import copy
from pathlib import Path
import re

import pytest
import yaml
from tests.test_a_job_budget_covers_its_own_steps import _budgets
from tests.test_iso_diagnostic_consumer_graph import context, enabled

ROOT = Path(__file__).resolve().parents[1]


def documents():
    return {name: yaml.safe_load((ROOT / '.github/workflows' / name).read_text())
            for name in ('live-iso-bootc.yml', 'iso-e2e.yml')}


def campaign(workflows):
    result = {}
    seen = set()

    def visit(name):
        assert name not in seen, 'cyclic or duplicate reusable workflow'
        seen.add(name)
        for key, job in workflows[name]['jobs'].items():
            if name == 'live-iso-bootc.yml' and not enabled(
                    workflows[name]['jobs'], key, context(),
                    {job_name: 'success' for job_name in workflows[name]['jobs']}):
                continue
            if 'uses' in job:
                assert job['uses'].startswith('./.github/workflows/')
                assert job['with']['installed_boot_diagnostic'] == '${{ inputs.installed_boot_diagnostic || false }}'
                assert job['with']['source'] == 'native-artifact'
                visit(job['uses'].removeprefix('./.github/workflows/'))
                continue
            value = job['timeout-minutes']  # missing bounds must fail
            choices = _budgets(value)  # reject unknown/unbounded expression leaves
            if isinstance(value, str):
                match = re.fullmatch(r'\$\{\{ inputs\.installed_boot_diagnostic && ([1-9][0-9]*) \|\| .+ \}\}', value)
                assert match, 'unknown diagnostic timeout selector'
                minutes = int(match[1])
            else:
                minutes = value
            assert type(minutes) is int and 0 < minutes <= 120
            assert minutes in choices
            result[name + '/' + key] = minutes
    visit('live-iso-bootc.yml')
    return result


def test_every_diagnostic_job_has_a_bound_matching_documented_sum():
    workflows = documents()
    expected = campaign(workflows)
    text = (ROOT / 'docs/INSTALLED-INITRAMFS-DIAGNOSTIC-PLAN.md').read_text()
    rows = dict((job, int(minutes)) for job, minutes in re.findall(
        r'^\| ([\w.-]+\.yml/[\w-]+) \| (\d+) \|$', text, re.M))
    assert rows == expected
    total = re.search(r'Total job budget: \*\*(\d+) minutes\*\*\. This excludes queue time\.', text)
    assert total and int(total[1]) == sum(expected.values()) == 248
    assert _budgets(workflows['iso-e2e.yml']['jobs']['generate-matrix']['timeout-minutes']) == [5]


@pytest.mark.parametrize('value', [None, '${{ inputs.timeout }}', '${{ inputs.installed_boot_diagnostic && 0 || 360 }}'])
def test_missing_or_unprovable_job_timeout_is_rejected(value):
    workflows = copy.deepcopy(documents())
    job = workflows['iso-e2e.yml']['jobs']['generate-matrix']
    if value is None:
        del job['timeout-minutes']
    else:
        job['timeout-minutes'] = value
    with pytest.raises((AssertionError, KeyError)):
        campaign(workflows)


def test_new_executed_job_cannot_hide_outside_the_budget():
    workflows = documents()
    workflows['iso-e2e.yml']['jobs']['extra'] = {'runs-on': 'ubuntu-24.04', 'steps': []}
    with pytest.raises(KeyError):
        campaign(workflows)


def test_budgeted_dispatch_generates_exactly_one_consumer_cell(tmp_path):
    import json
    import os
    import subprocess
    workflows = documents()
    call = workflows['live-iso-bootc.yml']['jobs']['qualify-native-iso']['with']
    assert call['variant'] == "${{ github.event.inputs.variant || 'skipjack' }}"
    assert call['flavors'] == "${{ github.event.inputs.flavor || 'gnome' }}"
    steps = workflows['iso-e2e.yml']['jobs']['generate-matrix']['steps']
    body = next(step['run'] for step in steps if step.get('id') == 'gen')
    # Inspected shell only reads config, runs jq and writes this temporary output.
    output = tmp_path / 'output'
    subprocess.run(['bash', '-c', body], cwd=ROOT, check=True,
                   env={**os.environ, 'DISPATCH_VARIANT': 'skipjack',
                        'DISPATCH_FLAVORS': 'gnome', 'GITHUB_OUTPUT': str(output),
                        'INSTALLED_BOOT_DIAGNOSTIC': 'true', 'CANDIDATE_XFCE': 'false',
                        'ISO_SOURCE': 'native-artifact', 'REQUESTED_PLATFORM': 'linux/amd64', 'MAX_PARALLEL': '1'},
                   capture_output=True, timeout=10)
    assert json.loads(dict(line.split('=', 1) for line in output.read_text().splitlines())['matrix']) == {
        'include': [{'variant': 'skipjack', 'flavor': 'gnome', 'platform': 'linux/amd64'}]}


def test_candidate_preflight_must_stay_outside_diagnostic_budget():
    workflows = documents()
    workflows['live-iso-bootc.yml']['jobs']['preflight'].pop('if')
    assert sum(campaign(workflows).values()) == 253


@pytest.mark.parametrize('candidate,platform,parallel', [
    ('true', 'linux/amd64', '1'), ('false', 'linux/amd64/v2', '1'),
    ('false', 'linux/amd64', '2'),
])
def test_diagnostic_matrix_refuses_mixed_or_obsolete_targets(tmp_path, candidate, platform, parallel):
    import os
    import subprocess
    steps = documents()['iso-e2e.yml']['jobs']['generate-matrix']['steps']
    body = next(step['run'] for step in steps if step.get('id') == 'gen')
    result = subprocess.run(['bash', '-c', body], cwd=ROOT,
        env={**os.environ, 'INSTALLED_BOOT_DIAGNOSTIC': 'true', 'CANDIDATE_XFCE': candidate,
             'DISPATCH_VARIANT': 'skipjack', 'DISPATCH_FLAVORS': 'gnome',
             'REQUESTED_PLATFORM': platform, 'MAX_PARALLEL': parallel,
             'ISO_SOURCE': 'native-artifact', 'GITHUB_OUTPUT': str(tmp_path/'output')},
        capture_output=True, timeout=10)
    assert result.returncode != 0
