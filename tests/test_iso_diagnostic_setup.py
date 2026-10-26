"""Inert setup contracts: fake sudo only, ordinary files, no package operations."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('setup_failure', ROOT / 'scripts/record-diagnostic-setup-failure.py')
failure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(failure)
STEPS = yaml.safe_load((ROOT / '.github/workflows/iso-e2e.yml').read_text())['jobs']['e2e']['steps']
LOCK = ROOT / 'requirements-iso-diagnostic-apt.txt'


def step(name):
    return next(item for item in STEPS if item.get('id') == name)


def test_qemu_install_uses_reviewed_signed_noble_package_closure():
    packages = LOCK.read_text().splitlines()
    assert packages == [
        'qemu-system-x86=1:8.2.2+ds-0ubuntu1.18',
        'qemu-system-common=1:8.2.2+ds-0ubuntu1.18',
        'qemu-system-data=1:8.2.2+ds-0ubuntu1.18',
        'qemu-utils=1:8.2.2+ds-0ubuntu1.18']
    for name in ('diagnostic-host-tools', 'diagnostic-inspector'):
        body = step(name)['run']
        assert 'mapfile -t qemu_packages < requirements-iso-diagnostic-apt.txt' in body
        assert 'verify-diagnostic-qemu-closure.py' in body
        assert 'dpkg-query -W -f=' in body
        assert '"${qemu_packages[@]}"' in body
        assert 'allow-unauthenticated' not in body
    verifier = (ROOT / 'scripts/verify-diagnostic-qemu-closure.py').read_text()
    assert "['apt-cache', 'show', package]" in verifier
    assert "['apt-get', '--simulate', 'install'" in verifier
    assert "'--version'" in (ROOT / 'scripts/prepare-installed-boot-diagnostic.py').read_text()


def test_qemu_closure_uses_signed_candidates_and_rejects_mixed_release():
    spec = importlib.util.spec_from_file_location(
        'verify_qemu_closure', ROOT / 'scripts/verify-diagnostic-qemu-closure.py')
    closure = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(closure)
    version = '1:8.2.2+ds-0ubuntu1.18'
    packages = LOCK.read_text().splitlines()
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        if command[0] == 'apt-cache':
            return subprocess.CompletedProcess(command, 0, stdout='Package: qemu\n', stderr='')
        names = [package.partition('=')[0] for package in packages]
        plan = ''.join('Inst '+name+' ('+version+' noble-updates [amd64])\n' for name in names)
        return subprocess.CompletedProcess(command, 0, stdout=plan, stderr='')

    result = closure.verify(run=run)
    assert result['resolved_qemu_packages'] == sorted(package.split('=', 1)[0] for package in packages)
    assert all(command[0] == 'apt-cache' for command in commands[:4])
    assert commands[4][0:3] == ['apt-get', '--simulate', 'install']

    def mixed(command, **kwargs):
        if command[0] == 'apt-cache':
            return subprocess.CompletedProcess(command, 0, stdout='Package: qemu\n', stderr='')
        plan = 'Inst qemu-system-common (1:8.2.2+ds-0ubuntu1.19 noble-updates [amd64])\n'
        return subprocess.CompletedProcess(command, 0, stdout=plan, stderr='')

    with pytest.raises(ValueError, match='not 1:8.2.2'):
        closure.verify(run=mixed)


def test_diagnostic_host_grants_are_runner_scoped_and_refuse_without_acl_support():
    live = yaml.safe_load((ROOT / '.github/workflows/live-iso-bootc.yml').read_text())
    preflight = live['jobs']['diagnostic-preflight']['steps'][0]['run']
    assert 'MODE="0666"' not in preflight and 'chmod' not in preflight
    assert '/dev/kvm' in preflight and 'getent group kvm' in preflight
    strict_kvm = next(item for item in STEPS if item.get('name') == 'Enable KVM group permissions')
    assert '!inputs.installed_boot_diagnostic' in strict_kvm['if']
    assert 'MODE="0666"' in strict_kvm['run']
    helper = (ROOT / 'scripts/diagnostic-host-access.sh').read_text()
    assert 'u:${runner_uid}:r' in helper and 'u:${runner_uid}:rX' in helper
    assert 'no device-mode change is allowed' in helper
    assert 'sudo -n setfacl' in helper and 'sudo chmod' not in helper
    assert 'Revoke temporary supermin ACLs' in (ROOT / '.github/workflows/iso-e2e.yml').read_text()


def test_host_access_helper_refuses_root_without_mutating_permissions(tmp_path):
    bin_dir = tmp_path/'bin'
    bin_dir.mkdir()
    identity = bin_dir/'id'
    identity.write_text('#!/bin/sh\necho 0\n')
    identity.chmod(0o700)
    result = subprocess.run(
        ['bash', str(ROOT/'scripts/diagnostic-host-access.sh'), 'prepare'],
        env={**os.environ, 'PATH': str(bin_dir)+':'+os.environ['PATH']},
        capture_output=True, text=True, timeout=5)
    assert result.returncode == 77
    assert 'must run as the non-root runner' in result.stderr


def test_host_access_refuses_when_acl_tools_are_missing(tmp_path):
    bin_dir = tmp_path/'bin'
    bin_dir.mkdir()
    identity = bin_dir/'id'; identity.write_text('#!/bin/sh\necho 12345\n'); identity.chmod(0o700)
    kernel = bin_dir/'uname'; kernel.write_text('#!/bin/sh\necho fixture-kernel\n'); kernel.chmod(0o700)
    result = subprocess.run(
        ['/bin/bash', str(ROOT/'scripts/diagnostic-host-access.sh'), 'prepare'],
        env={**os.environ, 'PATH': str(bin_dir), 'RUNNER_TEMP': str(tmp_path)},
        capture_output=True, text=True, timeout=5)
    assert result.returncode == 77
    assert 'ACL tools are unavailable' in result.stderr


@pytest.mark.parametrize('mode,rc', [('true', 0), ('false', 0), ('true', 100)])
def test_actual_host_setup_passes_package_selection_and_propagates_apt_failure(tmp_path, mode, rc):
    # Execute only the setup prefix, before hashing the QEMU executable. Every
    # privileged command is intercepted; the fake QEMU file is never executed.
    body = step('diagnostic-host-tools')['run'].split('          {')[0]
    body = body.split('\n{', 1)[0]
    bin_dir = tmp_path / 'bin'; bin_dir.mkdir()
    sudo = bin_dir / 'sudo'
    sudo.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$CALLS"\nif [[ "$*" == *install* ]]; then exit "$APT_RC"; fi\n')
    sudo.chmod(0o700)
    apt_cache = bin_dir / 'apt-cache'
    apt_cache.write_text('#!/bin/bash\nprintf "apt-cache %s\\n" "$*" >> "$CALLS"\necho "Package: qemu"\n')
    apt_cache.chmod(0o700)
    apt_get = bin_dir / 'apt-get'
    apt_get.write_text('#!/bin/bash\nfor package in qemu-system-x86 qemu-system-common qemu-system-data qemu-utils; do echo \"Inst $package (1:8.2.2+ds-0ubuntu1.18 noble-updates [amd64])\"; done\n')
    apt_get.chmod(0o700)
    dpkg_query = bin_dir / 'dpkg-query'
    dpkg_query.write_text('#!/bin/bash\necho "1:8.2.2+ds-0ubuntu1.18"\n')
    dpkg_query.chmod(0o700)
    qemu = bin_dir / 'qemu-system-x86_64'; qemu.write_text('never execute'); qemu.chmod(0o700)
    calls = tmp_path / 'calls'
    result = subprocess.run(['bash', '-euo', 'pipefail', '-c', body], cwd=ROOT,
        env={**os.environ, 'PATH': str(bin_dir)+':'+os.environ['PATH'], 'CALLS': str(calls),
             'APT_RC': str(rc), 'PLATFORM': 'linux/amd64/v2', 'DIAGNOSTIC_MODE': mode},
        capture_output=True, text=True, timeout=5)
    assert result.returncode == rc, result.stderr
    commands = calls.read_text()
    if rc == 0 and mode == 'true':
        assert all(package in commands for package in LOCK.read_text().splitlines())
        assert 'apt-cache show qemu-system-common=1:8.2.2+ds-0ubuntu1.18' in commands
        assert '1:8.2.2+ds-0ubuntu1.18' in commands
    elif rc == 0:
        assert 'qemu-system-x86 qemu-utils ovmf' in commands and '=1:' not in commands
    else:
        assert 'install' in commands and all(package in commands for package in LOCK.read_text().splitlines())

@pytest.mark.parametrize('outcome', ['failure', 'cancelled', 'skipped', '', 'success'])
def test_missing_evidence_never_becomes_success(tmp_path, outcome):
    target = tmp_path / 'evidence'
    failure.record(target, {'DIAGNOSTIC_OUTCOME': outcome, 'HOST_TOOLS_OUTCOME': 'failure',
                           'PASSWORD': 'do-not-copy', 'INPUT_ARTIFACT_ID': '12617774015',
                           'INPUT_ARCHIVE_DIGEST': 'sha256:'+'a'*64})
    raw = (target / 'report.json').read_bytes(); report = json.loads(raw)
    assert len(raw) <= 4096 and b'do-not-copy' not in raw
    assert report['qualified'] is False and report['status'] == 'evidence_unavailable'
    assert report['label'] == 'fresh reproduction, not the disk from run 40093907774'
    assert report['reference_run'] == 40093907774
    assert report['stop_proof'] == 'not_established'
    assert report['declared_inputs_unverified']['input_artifact_id'] == '12617774015'
    manifest = json.loads((target / 'manifest.json').read_text())
    assert manifest['files'] == [{'name': 'report.json', 'bytes': len(raw),
                                 'sha256': 'sha256:'+hashlib.sha256(raw).hexdigest()}]
    assert sorted(p.name for p in target.iterdir()) == ['manifest.json', 'report.json']


def test_existing_evidence_is_preserved(tmp_path):
    failure.record(tmp_path / 'evidence', {})
    before = {p.name: p.read_bytes() for p in (tmp_path / 'evidence').iterdir()}
    failure.record(tmp_path / 'evidence', {'DIAGNOSTIC_OUTCOME': 'success'})
    assert before == {p.name: p.read_bytes() for p in (tmp_path / 'evidence').iterdir()}


@pytest.mark.parametrize('kind', ['partial', 'symlink', 'oversized'])
def test_broken_existing_evidence_is_not_replaced(tmp_path, kind):
    target = tmp_path / 'evidence'; target.mkdir()
    (target / 'report.json').write_text('existing')
    if kind == 'symlink':
        (target / 'manifest.json').symlink_to(target / 'report.json')
    elif kind == 'oversized':
        (target / 'manifest.json').write_bytes(b'x' * (1024 * 1024 + 1))
    with pytest.raises(ValueError):
        failure.record(target, {})
    assert (target / 'report.json').read_text() == 'existing'


def test_untrusted_values_are_not_copied(tmp_path):
    failure.record(tmp_path / 'evidence', {'INPUT_ARCHIVE_DIGEST': 'private text'*1000})
    assert 'private text' not in (tmp_path / 'evidence/report.json').read_text()
    with pytest.raises(ValueError):
        failure.record(tmp_path / 'other', {'DIAGNOSTIC_OUTCOME': 'private text'})


def test_finalizer_is_always_before_upload_and_uses_stdlib(tmp_path):
    finalizer = next(s for s in STEPS if s.get('name') == 'Record missing diagnostic evidence')
    upload = next(s for s in STEPS if s.get('name') == 'Upload bounded installed boot diagnostic')
    assert finalizer['if'] == 'always() && inputs.installed_boot_diagnostic'
    assert STEPS.index(finalizer) < STEPS.index(upload)
    assert upload['with']['if-no-files-found'] == 'error'
    result = subprocess.run(['/usr/bin/python3', '-I', '-S', str(ROOT / 'scripts/record-diagnostic-setup-failure.py')],
                            env={'RUNNER_TEMP': str(tmp_path)}, capture_output=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / 'installed-boot-run/installed-boot-diagnostic/report.json').is_file()


@pytest.mark.parametrize('dangling', [False, True])
def test_symlink_ancestor_or_target_is_refused(tmp_path, dangling):
    outside = tmp_path / 'outside'
    outside.mkdir()
    alias = tmp_path / 'alias'
    alias.symlink_to(outside / 'absent' if dangling else outside)
    with pytest.raises(ValueError, match='unsafe evidence path'):
        failure.record(alias if dangling else alias / 'evidence', {})
    assert list(outside.iterdir()) == []
