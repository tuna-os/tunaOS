"""Inert command boundaries for the bounded XFCE workflow branches.

Falsification: lose exported KVM selection, broaden candidate source/target, or
swallow the strict command's failure and these real workflow-step fixtures fail.
No VM, image tool, network client or privileged command executes.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

ROOT=Path(__file__).parents[1]
LIVE=yaml.safe_load((ROOT/'.github/workflows/live-iso-bootc.yml').read_text())
E2E=yaml.safe_load((ROOT/'.github/workflows/iso-e2e.yml').read_text())


def step(name):
    return next(s for job in E2E['jobs'].values() for s in job.get('steps',[]) if s.get('name')==name)


@pytest.mark.parametrize('event',['pull_request','workflow_dispatch'])
@pytest.mark.parametrize('candidate',[False,True])
@pytest.mark.parametrize('kvm',[False,True])
@pytest.mark.parametrize('status',[0,19])
def test_real_strict_step_preserves_capability_and_failure(tmp_path,event,candidate,kvm,status):
    script=step('Run strict offline GUI qualification')['run']
    probe='[[ -r /dev/kvm && -w /dev/kvm ]]'
    assert script.count(probe)==1
    script=script.replace(probe, 'true' if kvm else 'false')
    shims=tmp_path/'bin';shims.mkdir()
    capture=tmp_path/'command.json'
    sudo=shims/'sudo';sudo.write_text('#!'+sys.executable+'''\nimport json,os,sys
if sys.argv[1]=='chown':raise SystemExit(0)
with open(os.environ['CAPTURE'],'w') as stream:
    json.dump({'args':sys.argv[1:],'kvm':os.environ.get('KVM_FLAG')},stream)
raise SystemExit(int(os.environ['STATUS']))
''');sudo.chmod(0o755)
    result=subprocess.run(['bash','-e','-c',script],cwd=tmp_path,capture_output=True,text=True,
        env=dict(os.environ,PATH=str(shims)+':'+os.environ['PATH'],CAPTURE=str(capture),STATUS=str(status),
            CANDIDATE_XFCE=str(candidate).lower(),ISO_PATH='/inert/bonito.iso',GITHUB_EVENT_NAME=event,
            GITHUB_OUTPUT=str(tmp_path/'output'),USER='inert'))
    observed=json.loads(capture.read_text())
    assert result.returncode==status
    assert observed['kvm']==('' if candidate or kvm else '--no-kvm')
    command=observed['args'][1:]
    if candidate:
        assert command[:2]==['python3','scripts/run-xfce-candidate.py']
    else:
        assert command[:1]==['./scripts/iso-e2e.sh'] and '--strict-offline-gui' in command
        assert ('--no-kvm' in command) is (not kvm)


@pytest.mark.parametrize('source,variant,flavor,platform,parallel,ok',[
    ('native-artifact','bonito','xfce','linux/amd64','1',True),
    ('native-artifact','bonito','xfce','linux/amd64','2',True),
    ('native-artifact','bonito','xfce','linux/amd64','3',False),
    ('build','bonito','xfce','linux/amd64','1',False),
    ('r2-latest','bonito','xfce','linux/amd64','1',False),
    ('native-artifact','grouper','xfce','linux/amd64','1',False),
    ('native-artifact','bonito','xfce-nvidia','linux/amd64','1',False),
    ('native-artifact','bonito','xfce','linux/arm64','1',False),
    ('native-artifact','bonito','all','linux/amd64','1',False),
])
def test_real_candidate_matrix_preflight(tmp_path,source,variant,flavor,platform,parallel,ok):
    output=tmp_path/'output'
    result=subprocess.run(['bash','-c',step('Build the cell list')['run']],cwd=ROOT,capture_output=True,text=True,
        env=dict(os.environ,CANDIDATE_XFCE='true',ISO_SOURCE=source,DISPATCH_VARIANT=variant,
            DISPATCH_FLAVORS=flavor,REQUESTED_PLATFORM=platform,MAX_PARALLEL=parallel,GITHUB_OUTPUT=str(output)))
    assert (result.returncode==0) is ok,result.stderr
    matrices=[line for line in output.read_text().splitlines() if line.startswith('matrix=')] if output.exists() else []
    if ok:
        assert len(json.loads(matrices[0][7:])['include'])==1
    else:
        assert not matrices


def test_candidate_has_no_implicit_trigger_and_preserves_strict_gates():
    assert LIVE[True]['workflow_dispatch']['inputs']['candidate_xfce']['default'] is False
    assert 'schedule' not in LIVE[True]
    call=LIVE['jobs']['qualify-native-iso']['with']
    assert call['source']=='native-artifact' and call['max_parallel']==1
    assert call['candidate_xfce']=='${{ inputs.candidate_xfce || false }}'
    assert step('Run strict offline GUI qualification')['if']=="steps.filter.outputs.skip != 'true' && inputs.source == 'native-artifact'"
    from tests.test_a_job_budget_covers_its_own_steps import _budgets,_step_total
    job=E2E['jobs']['e2e']
    assert max(_budgets(job['timeout-minutes']))>=_step_total(job['steps'])
    with pytest.raises(AssertionError):_budgets('${{ inputs.unreviewed_timeout }}')


@pytest.mark.parametrize('event,variant,flavor,platform,candidate,allowed',[
    ('workflow_dispatch','bonito','xfce','linux/amd64',True,True),
    ('workflow_dispatch','bonito','xfce','linux/amd64',False,False),
    ('pull_request','bonito','xfce','linux/amd64',True,False),
    ('schedule','bonito','xfce','linux/amd64',True,False),
    ('workflow_dispatch','grouper','xfce','linux/amd64',True,False),
    ('workflow_dispatch','bonito','xfce','linux/arm64',True,False),
    ('workflow_dispatch','bonito','kde','linux/amd64',True,False),
    ('workflow_dispatch','skipjack','gnome','linux/amd64',False,True),
    ('pull_request','skipjack','gnome','linux/amd64',False,False),
])
def test_merged_caller_condition_is_bounded(event,variant,flavor,platform,candidate,allowed):
    # Evaluate only this exact, reviewed boolean expression grammar.
    expression=LIVE['jobs']['qualify-native-iso']['if']
    expected="github.event_name == 'workflow_dispatch' && ((github.event.inputs.flavor || 'gnome') == 'gnome' || (inputs.candidate_xfce && inputs.variant == 'bonito' && inputs.flavor == 'xfce' && inputs.platform == 'linux/amd64'))"
    assert expression==expected
    replacements={'github.event.inputs.flavor':flavor,'github.event_name':event,
        'inputs.candidate_xfce':candidate,'inputs.variant':variant,'inputs.flavor':flavor,'inputs.platform':platform}
    for name,value in replacements.items(): expression=expression.replace(name,repr(value))
    assert bool(eval(expression.replace('&&',' and ').replace('||',' or '),{'__builtins__':{}})) is allowed


def test_candidate_summary_reads_candidate_fragments(tmp_path):
    script=step('Report strict leg verdicts')['run']
    fake=tmp_path/'bin';fake.mkdir()
    python=fake/'python3';python.write_text('#!/bin/sh\nprintf "%s\\n" "$*"\n');python.chmod(0o755)
    for candidate,path in [('true','iso-e2e-out/xfce-candidate xfce'),('false','iso-e2e-out')]:
        summary=tmp_path/candidate
        result=subprocess.run(['bash','-eu','-c',script],cwd=tmp_path,capture_output=True,text=True,
            env=dict(os.environ,PATH=str(fake)+':'+os.environ['PATH'],CANDIDATE_XFCE=candidate,GITHUB_STEP_SUMMARY=str(summary)))
        assert result.returncode==0
        assert summary.read_text().strip()=='scripts/summarize-strict-legs.py '+path
