"""Inert CI contracts: execute shell control flow with Docker/package stubs."""
import fnmatch
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((ROOT / '.github/workflows/test.yml').read_text())
JOB = WORKFLOW['jobs']['bootc-candidate-compile']
COMMAND = JOB['steps'][-1]['run']


def run_job(family, directory=ROOT, docker_status=0):
    stub = f'''timeout() {{
      [ "$1" = 3000 ] || return 98
      shift
      [ "$1" = docker ] || return 99
      printf '%s\\n' "$@"
      return {docker_status}
    }}
    '''
    return subprocess.run(['/bin/bash', '-c', stub + COMMAND], cwd=directory,
                          env=dict(os.environ, CANDIDATE_FAMILY=family),
                          capture_output=True, text=True)


def test_job_scope_permissions_and_bounds():
    assert JOB['permissions'] == {'contents': 'read'}
    assert JOB['timeout-minutes'] == 60
    assert JOB['strategy']['max-parallel'] == 1
    assert JOB['strategy']['matrix'] == {'family': ['arch', 'debian']}
    assert 'workflow_dispatch' in JOB['if'] and 'pull_request' in JOB['if']
    assert 'refs/heads/candidate/composefs-bootstrap' in JOB['if']
    assert "github.head_ref == 'candidate/composefs-bootstrap'" in JOB['if']
    assert 'push' not in JOB['if']
    triggers = WORKFLOW.get('on', WORKFLOW.get(True))
    assert 'workflow_dispatch' in triggers and 'pull_request' in triggers
    for path in ('Containerfile.arch', 'toolchain/Containerfile.debian',
                 'scripts/bootc-candidate.py', 'tests/test_bootc_candidate_ci.py'):
        assert any(fnmatch.fnmatch(path, pattern) for pattern in triggers['pull_request']['paths'])
    assert WORKFLOW['concurrency']['cancel-in-progress'] is True
    checkout = JOB['steps'][0]
    assert re.fullmatch(r'actions/checkout@[0-9a-f]{40}', checkout['uses'])
    assert checkout['with']['persist-credentials'] is False
    content = json.dumps(JOB)
    for denied in ('secrets.', 'packages: write', 'upload-artifact', '--privileged',
                   '--security-opt', '--mount', '--volume', 'docker push', 'docker login', 'sudo '):
        assert denied not in content


@pytest.mark.parametrize(('family', 'file', 'target'), [
    ('arch', 'Containerfile.arch', 'bootc-builder'),
    ('debian', 'toolchain/Containerfile.debian', 'builder'),
])
def test_actual_job_command_selects_candidate_and_pinned_base(family, file, target):
    result = run_job(family)
    assert result.returncode == 0, result.stderr
    args = result.stdout.splitlines()
    assert args[:2] == ['docker', 'build']
    assert args[args.index('--file') + 1] == file
    assert args[args.index('--target') + 1] == target
    assert 'TUNAOS_BOOTC_CANDIDATE=1' in args
    assert 'BOOTUPD_VERSION=v0.3.2' in args
    assert args[-3:] == ['--tag', f'localhost/bootc-candidate:{family}', '.']
    assert not any(arg.startswith('BASE_IMAGE=') for arg in args)
    source = (ROOT / file).read_text()
    assert re.search(r'^ARG BASE_IMAGE=.*@sha256:[0-9a-f]{64}', source, re.M)
    if family == 'debian':
        assert 'BUILD_OSTREE=1' in args
        assert 'OSTREE_VERSION=v2026.5' in args
        assert 'COMPOSEFS_VERSION=v1.0.8' in args
    assert run_job(family, docker_status=7).returncode == 7


def test_unknown_family_and_bad_pin_stop_before_docker():
    result = run_job('hummingbird')
    assert result.returncode != 0 and not result.stdout
    with tempfile.TemporaryDirectory() as name:
        directory = Path(name)
        (directory / 'image-versions.yaml').write_text('  bootupd: "bad"\n')
        result = run_job('arch', directory)
        assert result.returncode != 0 and not result.stdout


def run_debian(value, failed=''):
    text = (ROOT / 'toolchain/Containerfile.debian').read_text()
    body = text.split('# ── bootc from source', 1)[1].split('RUN ', 1)[1].split('\n\n# ── bootupd', 1)[0]
    # Keep real set -e control flow; replace only the environment-file source.
    body = body.replace('. "${RUSTUP_HOME}/env";', ':;').replace('\\\n', ' ')
    stubs = []
    for tool in ('git', 'mkdir', 'python3', 'cp', 'cd', 'make'):
        status = 8 if tool == failed else 0
        stubs.append(f'{tool}() {{ printf "%s\\n" "{tool} $*"; return {status}; }}')
    with tempfile.TemporaryDirectory() as name:
        apt = Path(name) / 'apt-get'
        status = 8 if failed == 'apt-get' else 0
        apt.write_text(f'#!/bin/sh\nprintf "%s\\n" "apt-get $*"\nexit {status}\n')
        apt.chmod(0o755)
        return subprocess.run(['/bin/sh', '-c', '\n'.join(stubs) + '\n' + body],
                              env=dict(os.environ, PATH=name + os.pathsep + os.environ['PATH'],
                                       TUNAOS_BOOTC_CANDIDATE=value, BOOTC_VERSION='v1.16.10'),
                              capture_output=True, text=True)


def test_debian_candidate_preserves_selinux_and_existing_libostree_tree():
    result = run_debian('1')
    assert result.returncode == 0, result.stderr
    assert '--branch v1.17.1' in result.stdout
    assert 'libselinux1-dev libsystemd-dev libclang-dev' in result.stdout
    assert '--destination /bootc-candidate-output --family debian' in result.stdout
    assert 'cp -a /bootc-candidate-output/. /output/' in result.stdout
    for failed in ('apt-get', 'git', 'python3'):
        result = run_debian('1', failed)
        assert result.returncode != 0
        assert 'cp -a' not in result.stdout


def test_debian_default_and_invalid_values():
    result = run_debian('0')
    assert result.returncode == 0, result.stderr
    assert '--branch v1.16.10' in result.stdout
    assert 'make install-all DESTDIR=/output' in result.stdout
    assert 'apt-get' not in result.stdout and 'bootstrap' not in result.stdout
    assert run_debian('true').returncode != 0
    source = (ROOT / 'toolchain/Containerfile.debian').read_text()
    assert 'ARG TUNAOS_BOOTC_CANDIDATE=0' in source
    assert 'then BOOTC_VERSION=v1.17.1; fi;' in source
