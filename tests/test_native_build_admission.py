"""Ordinary native production is independent of strict GUI-driver admission."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('name', ['Validate explicit target before building', 'Resolve canonical native platform'])
@pytest.mark.parametrize('flavor', ['gnome', 'kde', 'cosmic', 'niri', 'xfce'])
def test_real_native_workflow_admits_configured_desktop_builds(tmp_path, name, flavor):
    workflow = yaml.safe_load((ROOT / '.github/workflows/live-iso-bootc.yml').read_text())
    steps = [step for job in workflow['jobs'].values() for step in job.get('steps', [])]
    body = next(step['run'] for step in steps if step.get('name') == name)
    result = subprocess.run(['bash', '-eu', '-c', body], cwd=ROOT,
        env=dict(os.environ, VARIANT='skipjack', FLAVOR=flavor, PLATFORM='linux/amd64',
                 REQUESTED_PLATFORM='linux/amd64', CANDIDATE_XFCE='false',
                 GITHUB_ENV=str(tmp_path/'env')), text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['result'] == 'unrun'


@pytest.mark.parametrize('args,ok', [
    (['--target', 'skipjack:kde:linux/amd64'], False),
    (['--target', 'skipjack:gnome:linux/amd64'], True),
    (['--build-only', '--target', 'yellowfin:gnome:linux/amd64/v2'], True),
    (['--build-only', '--target', 'skipjack:kde:linux/amd64', '--max-parallel', '3'], False),
    (['--build-only', '--target', 'skipjack:missing:linux/amd64'], False),
    (['--build-only', '--target', 'skipjack:kde:linux/arm64'], False),
    (['--build-only', '--target', 'skipjack:kde:linux/amd64/v2'], False),
    (['--build-only', '--target', 'grouper:gnome:linux/amd64'], False),
    (['--build-only', '--candidate-xfce', '--target', 'skipjack:xfce:linux/amd64'], False),
    (['--build-only', '--candidate-xfce', '--target', 'bonito:xfce:linux/amd64'], True),
])
def test_build_admission_does_not_relax_qualification_or_candidate_scope(args, ok):
    result = subprocess.run([sys.executable, 'scripts/plan-iso-qualification.py', *args],
                            cwd=ROOT, text=True, capture_output=True, timeout=20)
    assert (result.returncode == 0) is ok, result.stdout + result.stderr
