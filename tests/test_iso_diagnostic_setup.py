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


def test_qemu_family_is_pinned_together():
    pins = dict(line.split('=', 1) for line in LOCK.read_text().splitlines())
    assert set(pins) == {'qemu-system-x86', 'qemu-system-common', 'qemu-system-data', 'qemu-utils'}
    assert set(pins.values()) == {'1:8.2.2+ds-0ubuntu1.18'}
    for name in ('diagnostic-host-tools', 'diagnostic-inspector'):
        assert 'mapfile -t qemu_packages < requirements-iso-diagnostic-apt.txt' in step(name)['run']
        assert '"${qemu_packages[@]}"' in step(name)['run']


@pytest.mark.parametrize('mode,rc', [('true', 0), ('false', 0), ('true', 100)])
def test_actual_host_setup_passes_pins_and_propagates_apt_failure(tmp_path, mode, rc):
    # Execute only the setup prefix, before hashing the QEMU executable. Every
    # privileged command is intercepted; the fake QEMU file is never executed.
    body = step('diagnostic-host-tools')['run'].split('          {')[0]
    body = body.split('\n{', 1)[0]
    bin_dir = tmp_path / 'bin'; bin_dir.mkdir()
    sudo = bin_dir / 'sudo'
    sudo.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$CALLS"\nif [[ "$*" == *install* ]]; then exit "$APT_RC"; fi\n')
    sudo.chmod(0o700)
    qemu = bin_dir / 'qemu-system-x86_64'; qemu.write_text('never execute'); qemu.chmod(0o700)
    calls = tmp_path / 'calls'
    result = subprocess.run(['bash', '-euo', 'pipefail', '-c', body], cwd=ROOT,
        env={**os.environ, 'PATH': str(bin_dir)+':'+os.environ['PATH'], 'CALLS': str(calls),
             'APT_RC': str(rc), 'PLATFORM': 'linux/amd64/v2', 'DIAGNOSTIC_MODE': mode},
        capture_output=True, text=True, timeout=5)
    assert result.returncode == rc, result.stderr
    commands = calls.read_text()
    if rc == 0 and mode == 'true':
        assert all(pin in commands for pin in LOCK.read_text().splitlines())
    elif rc == 0:
        assert 'qemu-system-x86 qemu-utils ovmf' in commands and '=1:' not in commands
    else:
        assert 'install' in commands and all(pin in commands for pin in LOCK.read_text().splitlines())


@pytest.mark.parametrize('outcome', ['failure', 'cancelled', 'skipped', '', 'success'])
def test_missing_evidence_never_becomes_success(tmp_path, outcome):
    target = tmp_path / 'evidence'
    failure.record(target, {'DIAGNOSTIC_OUTCOME': outcome, 'HOST_TOOLS_OUTCOME': 'failure',
                           'PASSWORD': 'do-not-copy', 'INPUT_ARTIFACT_ID': '12617774015',
                           'INPUT_ARCHIVE_DIGEST': 'sha256:'+'a'*64})
    raw = (target / 'report.json').read_bytes(); report = json.loads(raw)
    assert len(raw) <= 4096 and b'do-not-copy' not in raw
    assert report['qualified'] is False and report['status'] == 'evidence_unavailable'
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
