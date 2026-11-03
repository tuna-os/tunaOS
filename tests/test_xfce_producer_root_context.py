"""#3965 producer isolation: run workflow/recipe shell only through inert stubs.

Falsification: candidate namespace edits, disabled ordinary setup, or lost root
context across sudo must fail. No actual sudo, container, sysctl or host edit.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest
import yaml

from tests.test_expensive_builds_collapse_redundant_pr_runs import _evaluate
from tests.workflow_contracts import expression_body, tokens

ROOT=Path(__file__).resolve().parents[1]
WORKFLOW=yaml.safe_load((ROOT/'.github/workflows/live-iso-bootc.yml').read_text())
SETUP=next(s for s in WORKFLOW['jobs']['build']['steps'] if s.get('name','').startswith('Setup rootless podman'))


def enabled(condition,candidate):
    if type(condition) is bool:return condition
    return _evaluate(tokens(expression_body(condition)),{'inputs.candidate_xfce':candidate})


def policy(condition):
    assert enabled(condition,True) is False
    assert enabled(condition,False) is True
    assert enabled(condition,'') is True


@pytest.mark.parametrize('candidate',[True,False,''])
def test_actual_setup_is_omitted_for_candidate_and_preserved_for_ordinary(tmp_path,candidate):
    policy(SETUP.get('if',True))
    script='''
grep() { return 1; }
sysctl() { echo 1; }
sudo() {
 printf '%s\\n' "$*" >> "$TRACE"
 if [[ "$1" == tee ]]; then cat >/dev/null; else echo 0; fi
}
podman() { [[ "$*" == 'unshare true' ]] || exit 98; echo 'podman unshare true' >> "$TRACE"; }
'''
    # Model an existing AppArmor knob without touching the host's procfs.
    needle='[ -e /proc/sys/kernel/apparmor_restrict_unprivileged_userns ]'
    assert needle in SETUP['run']
    body=SETUP['run'].replace(needle,'true')
    if enabled(SETUP['if'],candidate):script+=body
    result=subprocess.run(['bash','-c',script],capture_output=True,text=True,timeout=3,
        env=dict(os.environ,TRACE=str(tmp_path/'trace'),GITHUB_STEP_SUMMARY=str(tmp_path/'summary'),USER='inert-runner'))
    assert result.returncode==0,result.stderr
    if candidate is True:assert not (tmp_path/'trace').exists()
    else:
        assert (tmp_path/'trace').read_text().splitlines()==[
            'tee -a /etc/subuid','tee -a /etc/subgid',
            'sysctl -w kernel.apparmor_restrict_unprivileged_userns=0','podman unshare true']


@pytest.mark.parametrize('condition',[True,False,'${{ inputs.candidate_xfce }}'])
def test_mutated_setup_policy_is_rejected(condition):
    with pytest.raises(AssertionError):policy(condition)


@pytest.mark.parametrize('context',['root','user'])
def test_nested_just_iso_sudo_preserves_context_without_running_builder(tmp_path,context):
    recipe=(ROOT/'Justfile').read_text().split("iso variant='skipjack'",1)[1].split('\n',1)[1].split('\n\n',1)[0]
    recipe=textwrap.dedent(recipe)
    for name,value in dict(variant='bonito',flavor='xfce',repo='local',tag='xfce',dev='0',platform='linux/amd64',just='forbidden-build').items():
        recipe=recipe.replace('{{ '+name+' }}',value)
    assert '{{' not in recipe
    binary=tmp_path/'sudo'
    binary.write_text('#!'+sys.executable+'\n'+'''import json,os,sys
assert sys.argv[1:3]==['-E','bash']
assert sys.argv[3]=='./scripts/build-iso-tacklebox.sh'
json.dump({'context':os.environ.get('TACKLEBOX_CONTEXT'),'args':sys.argv[4:]},open(os.environ['TRACE'],'w'))
''')
    binary.chmod(0o700)
    result=subprocess.run(['bash','-c',recipe],cwd=tmp_path,capture_output=True,text=True,timeout=3,
        env=dict(os.environ,PATH=str(tmp_path)+':'+os.environ['PATH'],TACKLEBOX_CONTEXT=context,TRACE=str(tmp_path/'trace')))
    assert result.returncode==0,result.stderr
    assert json.loads((tmp_path/'trace').read_text())==dict(context=context,args=['bonito','xfce','local','xfce','0','linux/amd64'])
