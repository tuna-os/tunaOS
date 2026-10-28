"""Static Actions graph model, including implicit success over transitive needs.

No host preflight, build, workflow, or privileged helper is executed.
"""
import copy
from pathlib import Path
import re
import subprocess
import os

import pytest
import yaml

from tests.test_expensive_builds_collapse_redundant_pr_runs import _evaluate
from tests.workflow_contracts import tokens, expression_body

ROOT = Path(__file__).resolve().parents[1]
CONSUMER = 'qualify-native-iso'


def jobs():
    return yaml.safe_load((ROOT/'.github/workflows/live-iso-bootc.yml').read_text())['jobs']


def dependencies(graph, name):
    needs = graph[name].get('needs', [])
    return [needs] if isinstance(needs, str) else needs


def ancestors(graph, name):
    result = set()
    for parent in dependencies(graph, name):
        result.add(parent)
        result.update(ancestors(graph, parent))
    return result


def enabled(graph, name, context, results, cancelled=False):
    """Expand known status functions; otherwise inject success over all ancestors."""
    before = ancestors(graph, name)
    successful = all(results.get(parent) == 'success' for parent in before)
    condition = graph[name].get('if', 'true')
    condition = expression_body(condition) if condition.startswith('${{') else condition
    status = {'success':successful, 'failure':any(results.get(p) == 'failure' for p in before),
              'cancelled':cancelled, 'always':True}
    matches = re.findall(r'\b(success|failure|cancelled|always)\(\)', condition)
    for function in matches:
        condition = condition.replace(function+'()', str(status[function]).lower())
    # Reuse the bounded evaluator via simple aliases for multi-segment names.
    values = dict(context)
    for parent in dependencies(graph, name):
        values['needs.'+parent+'.result'] = results.get(parent, '')
    aliases = {}
    for index, (key, value) in enumerate(sorted(values.items(), key=lambda pair:-len(pair[0]))):
        alias = 'fixture.v'+str(index)
        condition = re.sub(r'(?<![\w.-])'+re.escape(key)+r'(?![\w.-])', alias, condition)
        aliases[alias] = value
    declared = bool(_evaluate(tokens(condition), aliases))
    return declared and (bool(matches) or successful)


def context(mode='diagnostic', event='workflow_dispatch'):
    candidate = mode == 'candidate'
    values = {'installed_boot_diagnostic':mode in ('diagnostic','mixed'),
              'descriptor_scan_probe':mode == 'probe',
              'candidate_xfce':candidate or mode == 'mixed',
              'variant':'bonito' if candidate else 'skipjack',
              'flavor':'xfce' if candidate else 'gnome', 'platform':'linux/amd64'}
    if event == 'pull_request':
        values = {key:'' for key in values}
    return {'github.event_name':event, 'github.event.inputs.flavor':values['flavor'],
            **{'inputs.'+key:value for key,value in values.items()}}


def completed(mode):
    return {'diagnostic-preflight':'success' if mode == 'diagnostic' else 'skipped',
            'preflight':'skipped' if mode == 'diagnostic' else 'success', 'build':'success'}


@pytest.mark.parametrize('mode', ['diagnostic','ordinary','candidate'])
def test_valid_dispatch_crosses_intentionally_skipped_ancestor(mode):
    graph = jobs()
    state = completed(mode)
    assert enabled(graph,'build',context(mode),state)
    assert enabled(graph,CONSUMER,context(mode),state)
    assert not enabled(graph,CONSUMER,context(mode),state,cancelled=True)


def test_original_input_only_condition_reproduces_build_only_run():
    graph = copy.deepcopy(jobs())
    graph[CONSUMER]['needs'] = 'build'
    graph[CONSUMER]['if'] = "github.event_name == 'workflow_dispatch' && ((github.event.inputs.flavor || 'gnome') == 'gnome')"
    state = completed('diagnostic')
    assert 'preflight' in ancestors(graph,CONSUMER)
    assert enabled(graph,'build',context(),state)
    assert not enabled(graph,CONSUMER,context(),state)
    # Workflow/build success cannot serve as evidence that the consumer ran.
    consumer_result = 'success' if enabled(graph,CONSUMER,context(),state) else 'skipped'
    diagnostic_state = 'not-run' if consumer_result == 'skipped' else 'not-collected'
    assert diagnostic_state == 'not-run'
    assert diagnostic_state != 'collected'


@pytest.mark.parametrize('mode', ['diagnostic','ordinary','candidate'])
@pytest.mark.parametrize('result', ['failure','skipped','cancelled',''])
@pytest.mark.parametrize('prerequisite', ['required-preflight','build'])
def test_required_prerequisite_cannot_be_bypassed(mode, result, prerequisite):
    graph = jobs()
    state = completed(mode)
    key = ('diagnostic-preflight' if mode == 'diagnostic' else 'preflight') if prerequisite == 'required-preflight' else 'build'
    state[key] = result
    # Keep build success for preflight cases: the consumer must independently
    # refuse even this inconsistent state, not merely trust its parent gate.
    assert not enabled(graph,CONSUMER,context(mode),state)
    if prerequisite == 'required-preflight':
        assert not enabled(graph,'build',context(mode),state)


def test_pr_build_retained_but_qualification_excluded():
    graph = jobs()
    state = completed('ordinary')
    ctx = context('ordinary','pull_request')
    assert enabled(graph,'preflight',ctx,{})
    assert not enabled(graph,'diagnostic-preflight',ctx,{})
    assert enabled(graph,'build',ctx,state)
    assert not enabled(graph,CONSUMER,ctx,state)


def test_mixed_modes_refuse_before_host_checks_and_block_graph():
    graph = jobs()
    body = graph['diagnostic-preflight']['steps'][0]['run']
    stubs = '\n'.join(name+'() { echo FORBIDDEN; exit 99; }'
                     for name in ('test','getent','stat','uname','command','sudo','systemctl'))
    result = subprocess.run(['bash','-c',stubs+'\n'+body],
                            env={'PATH':'/usr/bin:/bin','CANDIDATE_XFCE':'true'},
                            capture_output=True,text=True,timeout=5)
    assert result.returncode == 1 and not result.stdout and not result.stderr
    state = {'diagnostic-preflight':'failure','preflight':'skipped','build':'skipped'}
    assert not enabled(graph,'build',context('mixed'),state)
    assert not enabled(graph,CONSUMER,context('mixed'),state)


@pytest.mark.parametrize('upstream', ['success', 'failure', 'skipped'])
@pytest.mark.parametrize('event', ['workflow_dispatch', 'pull_request', 'schedule'])
def test_probe_cannot_start_build_or_guest_even_with_forged_prerequisite_success(upstream, event):
    graph = jobs()
    ctx = context('probe')
    ctx['github.event_name'] = event
    state = {name: upstream for name in graph}
    assert enabled(graph, 'root-scan-readiness', ctx, {}) is (event == 'workflow_dispatch')
    for name in ('preflight', 'diagnostic-preflight', 'build', CONSUMER):
        assert not enabled(graph, name, ctx, state)


@pytest.mark.parametrize('diagnostic,candidate', [('true', 'false'), ('false', 'true')])
def test_probe_rejects_mixed_modes_before_any_host_command(diagnostic, candidate):
    body = jobs()['root-scan-readiness']['steps'][0]['run']
    result = subprocess.run(['/bin/bash', '-e', '-c', body],
                            env={'PATH': '/nonexistent', 'FULL_DIAGNOSTIC': diagnostic,
                                 'CANDIDATE_XFCE': candidate}, capture_output=True, timeout=5)
    assert result.returncode == 1 and result.stdout == result.stderr == b''


@pytest.mark.parametrize('mode,variant,flavor,platform', [
    ('diagnostic','skipjack','gnome','linux/amd64/v2'),
    ('diagnostic','bonito','gnome','linux/amd64'),
    ('candidate','bonito','xfce','linux/arm64'),
    ('candidate','skipjack','xfce','linux/amd64'),
])
def test_unsupported_consumer_targets_refuse_before_work(tmp_path, mode, variant, flavor, platform):
    document = yaml.safe_load((ROOT/'.github/workflows/iso-e2e.yml').read_text())
    body = next(step['run'] for step in document['jobs']['generate-matrix']['steps'] if step.get('id') == 'gen')
    # Actual matrix validator only reads repository config and writes fixture output.
    result = subprocess.run(['bash','-c',body],cwd=ROOT,env={**os.environ,
        'INSTALLED_BOOT_DIAGNOSTIC':str(mode == 'diagnostic').lower(),
        'CANDIDATE_XFCE':str(mode == 'candidate').lower(),
        'DISPATCH_VARIANT':variant,'DISPATCH_FLAVORS':flavor,
        'REQUESTED_PLATFORM':platform,'MAX_PARALLEL':'1','ISO_SOURCE':'native-artifact',
        'GITHUB_OUTPUT':str(tmp_path/'output')},capture_output=True,text=True,timeout=10)
    assert result.returncode != 0
