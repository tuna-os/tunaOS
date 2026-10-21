"""Synthetic transport/admission tests; these do not boot a VM."""
import argparse
import importlib.util
from pathlib import Path
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('native_artifact', ROOT / 'scripts/fetch-native-iso-artifact.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def records():
    args = argparse.Namespace(repository='tuna-os/tunaOS', run_id=1, artifact_id=2, attempt=0,
                              source_sha='a' * 40, archive_digest='sha256:' + 'b' * 64,
                              variant='skipjack', flavor='gnome')
    run = dict(id=1, status='completed', conclusion='success', head_sha=args.source_sha,
               path='.github/workflows/live-iso-bootc.yml',
               repository=dict(full_name=args.repository), head_repository=dict(full_name=args.repository))
    artifact = dict(id=2, expired=False, name='skipjack-gnome-live-iso',
                    digest=args.archive_digest, workflow_run=dict(id=1, head_sha=args.source_sha), size_in_bytes=32)
    return args, run, artifact


def test_exact_producer():
    args, run, artifact = records()
    module.validate(run, artifact, args)


@pytest.mark.parametrize('field,value', [('head_sha', 'c'*40), ('conclusion', 'failure'),
                                         ('status', 'in_progress'), ('path', 'other.yml')])
def test_wrong_producer(field, value):
    args, run, artifact = records()
    run[field] = value
    with pytest.raises(ValueError):
        module.validate(run, artifact, args)


@pytest.mark.parametrize('field,value', [('id', 3), ('expired', True), ('name', 'albacore-gnome-live-iso'),
                                        ('digest', 'sha256:'+'c'*64), ('size_in_bytes', 0),
                                        ('workflow_run', dict(id=3, head_sha='a'*40))])
def test_wrong_artifact(field, value):
    args, run, artifact = records()
    artifact[field] = value
    with pytest.raises(ValueError):
        module.validate(run, artifact, args)


@pytest.mark.parametrize('names', [['../bad.iso'], ['skipjack-gnome-a.iso', 'extra.iso'],
                                 ['albacore-gnome-a.iso'], ['skipjack-gnome-a.txt']])
def test_invalid_archive(tmp_path, names):
    archive = tmp_path / 'input.zip'
    with zipfile.ZipFile(archive, 'w') as bundle:
        for name in names:
            bundle.writestr(name, b'fake iso')
    with pytest.raises(ValueError):
        module.extract(archive, tmp_path, 'skipjack', 'gnome')


def test_exact_media_hash(tmp_path):
    archive = tmp_path / 'input.zip'
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr('skipjack-gnome-a.iso', b'fake iso')
    iso = module.extract(archive, tmp_path, 'skipjack', 'gnome')
    assert iso.read_bytes() == b'fake iso'
    assert module.digest(iso) != module.digest(archive)
    assert iso.stat().st_mode & 0o222 == 0


def test_workflow_keeps_qualification_separate():
    workflow = (ROOT / '.github/workflows/iso-e2e.yml').read_text()
    assert 'Native artifact live boot and installer GUI smoke (not qualification)' in workflow
    assert workflow.index('id: native_smoke') < workflow.index('name: Resolve immutable ISO qualification inputs')
    assert 'inputs.source != \'build\'' in workflow
    assert 'native-iso-input/artifact-binding.json' in workflow
    assert '"$MEDIA_DIGEST" != "$NATIVE_MEDIA_DIGEST"' in workflow


def test_native_measures_executable():
    helper = (ROOT / 'scripts/lib/tacklebox.sh').read_text()
    assert 'sha256sum "$bin"' in helper
    assert helper.index('sha256sum "$bin"') < helper.index('tb=("$bin")')


def test_same_run_requires_exact_environment(monkeypatch):
    args, run, artifact = records()
    run.update(status='in_progress', conclusion=None, run_attempt=1, run_started_at='2026-10-21T12:00:00Z')
    artifact.update(name='skipjack-gnome-live-iso-attempt-1', created_at='2026-10-21T12:01:00Z')
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT', '1')
    monkeypatch.setenv('NATIVE_SAME_RUN', 'true')
    monkeypatch.setenv('GITHUB_RUN_ID', '2')
    with pytest.raises(ValueError):
        module.validate(run, artifact, args)
    monkeypatch.setenv('GITHUB_RUN_ID', '1')
    module.validate(run, artifact, args)


@pytest.mark.parametrize('identity_lines', [1, 0, 2])
def test_invoked_binary_hash_reaches_wrapper(tmp_path, identity_lines):
    import subprocess
    cache = tmp_path / 'cache'
    cache.mkdir()
    binary = cache / 'tacklebox'
    binary.write_text('#!/bin/sh\nif [ "$1" = version ]; then echo aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa; fi\n')
    binary.chmod(0o755)
    out = tmp_path / 'out'
    wrapper = out / 'live-customize/customize-live.sh'
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text('export TUNA_LIVE_ENGINE_DIGEST=unknown\n' * identity_lines + 'echo customize\n')
    recipe = tmp_path / 'recipe.json'
    recipe.write_text('{}')
    import os
    env = dict(os.environ, TACKLEBOX_FROM_SOURCE='1', TACKLEBOX_SHA='a'*40, TACKLEBOX_CACHE=str(cache))
    result = subprocess.run(['bash', '-c', 'source "$1"; tunaos_run_tacklebox "$2" "$3" "$4"',
                    'test', str(ROOT / 'scripts/lib/tacklebox.sh'), str(recipe), str(out),
                    str(tmp_path / 'result.iso')], env=env, check=False)
    if identity_lines != 1:
        assert result.returncode != 0
        return
    assert result.returncode == 0
    assert wrapper.read_text().splitlines()[0] == 'export TUNA_LIVE_ENGINE_DIGEST=' + module.digest(binary)


@pytest.mark.parametrize('code,limit,timeout', [
    ('import sys; sys.stdout.buffer.write(b"x" * 128)', 32, 5),
    ('import time; time.sleep(5)', 32, 0.05),
])
def test_transfer_is_bounded(code, limit, timeout):
    import io
    import sys
    output = io.BytesIO()
    with pytest.raises(ValueError):
        module.bounded_command([sys.executable, '-c', code], output, limit, timeout)
    assert len(output.getvalue()) <= limit


def test_transfer_exact_limit():
    import io
    import sys
    output = io.BytesIO()
    assert module.bounded_command([sys.executable, '-c', 'print("123", end="")'], output, 3, 5) == 3
    assert output.getvalue() == b'123'


def test_zip_nul_original_name_rejected(tmp_path):
    archive = tmp_path / 'input.zip'
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr('skipjack-gnome-a.isoXhidden', b'fake iso')
    archive.write_bytes(archive.read_bytes().replace(b'.isoXhidden', b'.iso\0hidden'))
    with pytest.raises(ValueError):
        module.extract(archive, tmp_path, 'skipjack', 'gnome')


@pytest.mark.parametrize('kind', [0o010000, 0o060000, 0o120000])
def test_zip_nonregular_member_rejected(tmp_path, kind):
    archive = tmp_path / 'input.zip'
    member = zipfile.ZipInfo('skipjack-gnome-a.iso')
    member.external_attr = (kind | 0o644) << 16
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr(member, b'fake iso')
    with pytest.raises(ValueError):
        module.extract(archive, tmp_path, 'skipjack', 'gnome')


def test_same_run_rejects_old_attempt_artifact(monkeypatch):
    args, run, artifact = records()
    run.update(status='in_progress', conclusion=None, run_attempt=2, run_started_at='2026-10-21T12:00:00Z')
    artifact.update(name='skipjack-gnome-live-iso-attempt-2', created_at='2026-10-21T11:00:00Z')
    monkeypatch.setenv('NATIVE_SAME_RUN', 'true')
    monkeypatch.setenv('GITHUB_RUN_ID', '1')
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT', '2')
    with pytest.raises(ValueError):
        module.validate(run, artifact, args)


def test_completed_historical_attempt_name():
    args, run, artifact = records()
    args.attempt = 2
    run.update(run_attempt=2, run_started_at='2026-10-21T12:00:00Z')
    artifact.update(name='skipjack-gnome-live-iso-attempt-2', created_at='2026-10-21T12:01:00Z')
    module.validate(run, artifact, args)


def test_failed_acquisition_cannot_reuse_stale_executable(tmp_path):
    import os
    import subprocess
    cache = tmp_path / 'cache'
    cache.mkdir()
    (cache / '.git').mkdir()
    binary = cache / 'tacklebox'
    old = '#!/bin/sh\necho stale-binary\n'
    binary.write_text(old)
    binary.chmod(0o755)
    fake = tmp_path / 'commands'
    fake.mkdir()
    (fake / 'git').write_text('#!/bin/sh\nexit 1\n')
    (fake / 'git').chmod(0o755)
    env = dict(os.environ, TACKLEBOX_SHA='a'*40, TACKLEBOX_CACHE=str(cache), PATH=f'{fake}:' + os.environ['PATH'])
    result = subprocess.run(['bash', '-c', 'source "$1"; bin="$(tunaos_tacklebox_source_binary)" || exit $?; echo "$bin"',
                             'test', str(ROOT / 'scripts/lib/tacklebox.sh')], env=env, capture_output=True)
    assert result.returncode != 0
    assert binary.read_text() == old
    assert not result.stdout


def test_directory_allocation_bounded_before_zipfile(tmp_path, monkeypatch):
    import struct
    archive = tmp_path / 'input.zip'
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr('skipjack-gnome-a.iso', b'fake iso')
    data = bytearray(archive.read_bytes())
    struct.pack_into('<L', data, len(data) - 22 + 12, 1024**3)
    archive.write_bytes(data)
    monkeypatch.setattr(module.zipfile, 'ZipFile', lambda *a: pytest.fail('directory allocated before bounds check'))
    with pytest.raises(ValueError):
        module.extract(archive, tmp_path, 'skipjack', 'gnome')


@pytest.mark.parametrize('sentinels', [True, False])
def test_small_zip64_directory(tmp_path, sentinels):
    import struct
    archive = tmp_path / 'input.zip'
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr('skipjack-gnome-a.iso', b'fake iso')
    data = archive.read_bytes()
    fields = struct.unpack('<4s4H2LH', data[-22:])
    record = struct.pack('<4sQ2H2L4Q', b'PK\x06\x06', 44, 45, 45, 0, 0, 1, 1, fields[5], fields[6])
    locator = struct.pack('<4sLQL', b'PK\x06\x07', 0, len(data)-22, 1)
    end = struct.pack('<4s4H2LH', b'PK\x05\x06', 0, 0, 65535, 65535, 0xffffffff, 0xffffffff, 0) if sentinels else data[-22:]
    archive.write_bytes(data[:-22] + record + locator + end)
    iso = module.extract(archive, tmp_path, 'skipjack', 'gnome')
    assert iso.read_bytes() == b'fake iso'


def test_nonsentinel_zip64_cannot_override_directory_bound(tmp_path):
    import struct
    archive = tmp_path / 'input.zip'
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr('skipjack-gnome-a.iso', b'fake iso')
    data = archive.read_bytes()
    fields = struct.unpack('<4s4H2LH', data[-22:])
    record = struct.pack('<4sQ2H2L4Q', b'PK\x06\x06', 44, 45, 45, 0, 0, 1, 1, 1024**3, fields[6])
    locator = struct.pack('<4sLQL', b'PK\x06\x07', 0, len(data)-22, 1)
    archive.write_bytes(data[:-22] + record + locator + data[-22:])
    with pytest.raises(ValueError):
        module.check_zip_directory(archive)


def test_native_platform_resolution_from_clean_checkout(tmp_path):
    """The primary TOML is tracked; the old matrix adapter is generated."""
    import os
    import shutil
    import subprocess
    import yaml

    shutil.copytree(ROOT / 'scripts', tmp_path / 'scripts')
    shutil.copy2(ROOT / 'tunaos.toml', tmp_path / 'tunaos.toml')
    assert not (tmp_path / '.github/build-config.yml').exists()
    workflow = yaml.safe_load((ROOT / '.github/workflows/live-iso-bootc.yml').read_text())
    script = next(step['run'] for step in workflow['jobs']['build']['steps']
                  if step.get('name') == 'Resolve canonical native platform')
    envfile = tmp_path / 'github-env'
    result = subprocess.run(['bash', '-euc', script], cwd=tmp_path, capture_output=True,
                            text=True, env={**os.environ, 'VARIANT': 'skipjack',
                                            'FLAVOR': 'gnome', 'GITHUB_ENV': str(envfile)})
    assert result.returncode == 0, result.stderr
    assert envfile.read_text() == 'PLATFORM=linux/amd64/v2\n'
    e2e = yaml.safe_load((ROOT / '.github/workflows/iso-e2e.yml').read_text())
    matrix = next(step['run'] for step in e2e['jobs']['generate-matrix']['steps']
                  if step.get('id') == 'gen')
    out = tmp_path / 'github-output'
    result = subprocess.run(['bash', '-euc', matrix], cwd=tmp_path, capture_output=True,
                            text=True, env={**os.environ, 'DISPATCH_VARIANT': 'skipjack',
                                            'DISPATCH_FLAVORS': 'gnome', 'GITHUB_OUTPUT': str(out)})
    assert result.returncode == 0, result.stderr
    assert 'linux/amd64/v2' in out.read_text()


def test_strict_installed_boot_uses_primary_config_resolver():
    script = (ROOT / 'scripts/iso-e2e.sh').read_text()
    assert 'TUNAOS_BUILD_CONFIG="${SCRIPT_DIR}/../.github/build-config.yml"' not in script
    assert '"${SCRIPT_DIR}/published-image-ref.sh" "${VARIANT:-}" "${FLAVOR:-}" ghcr' in script


def test_iso_filename_probes_override_customized_image_entrypoint(tmp_path):
    import os
    import subprocess

    # Model a customized overlay with ENTRYPOINT=/usr/bin/sh: any implicit
    # command would be interpreted by that shell as an input filename.
    podman = tmp_path / 'podman'
    podman.write_text('''#!/usr/bin/env python3
import sys
args = sys.argv[1:]
if '--entrypoint' not in args:
    sys.exit(126)
i = args.index('--entrypoint')
entrypoint, image, *command = args[i+1:]
assert image == 'localhost/overlay@sha256:' + 'a'*64
if entrypoint == '/bin/sh':
    assert command[0] == '-c' and 'os-release' in command[1]
    print('10.0')
elif entrypoint == '/usr/bin/uname':
    assert command == ['-m']
    print('x86_64')
else:
    sys.exit(127)
''')
    podman.chmod(0o755)
    script = (ROOT / 'scripts/build-iso-tacklebox.sh').read_text()
    probes = script[script.index('VERSION_ID=$(podman'):script.index('if [[ -n "$PLATFORM" ]]', script.index('VERSION_ID=$(podman'))]
    result = subprocess.run(['bash', '-euc', probes + '\nprintf "%s %s\\n" "$VERSION_ID" "$ARCH"'],
                            capture_output=True, text=True,
                            env={**os.environ, 'PATH': str(tmp_path) + ':' + os.environ['PATH'],
                                 'IMAGE_REF': 'localhost/overlay@sha256:' + 'a'*64})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == '10.0 x86_64'
