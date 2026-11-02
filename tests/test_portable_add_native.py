"""Opt-in real authoring/transaction scenario; no acquisition or runner mocks.

Set TUNAOS_PORTABLE_TRANSACTION_IMAGES to a JSON object mapping base/kde/xfce
(or their full target IDs) to preloaded, digest-pinned Flounder image references.
This test uses HTTPS/GnuPG and local Podman. It never pulls, builds or commits a
native transaction, and does not give installed-image or all-base acceptance.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
IMAGES_ENV = 'TUNAOS_PORTABLE_TRANSACTION_IMAGES'
FLAVORS = ('base', 'kde', 'xfce')

pytestmark = pytest.mark.skipif(
    not os.environ.get(IMAGES_ENV),
    reason=f'set {IMAGES_ENV} to run the real local Flounder transaction scenario',
)


def test_config_only_derivative_portable_write_and_real_transactions(tmp_path):
    import tomlkit

    images = json.loads(os.environ[IMAGES_ENV])
    assert isinstance(images, dict), f'{IMAGES_ENV} must be a JSON object'
    images = {f'flounder:{key}:linux/amd64' if key in FLAVORS else key: value
              for key, value in images.items()}
    expected = {f'flounder:{flavor}:linux/amd64' for flavor in FLAVORS}
    assert set(images) == expected, 'supply exactly the three supported Flounder targets'
    sys.path.insert(0, str(ROOT / 'scripts'))
    from lib import portable_add, tunaos_config

    for target, image in images.items():
        assert isinstance(image, str) and portable_add.IMAGE.fullmatch(image), target
        inspected = subprocess.run(
            ['podman', 'image', 'inspect', image], text=True, capture_output=True, timeout=30)
        assert inspected.returncode == 0, inspected.stderr
        metadata = json.loads(inspected.stdout)[0]
        assert (metadata['Os'], metadata['Architecture']) == ('linux', 'amd64'), target

    # Copy only the existing source-binding prerequisites, not a second parser or
    # synthesized observation. The derivative edits only its primary TOML.
    for directory in ('config', 'build_scripts'):
        shutil.copytree(ROOT / directory, tmp_path / directory)
    (tmp_path / 'scripts').mkdir()
    for relative in ('Containerfile.debian', 'image-versions.yaml', 'scripts/build-image-inner.sh'):
        shutil.copyfile(ROOT / relative, tmp_path / relative)
    config = tmp_path / 'tunaos.toml'
    edited = tomlkit.parse((ROOT / 'tunaos.toml').read_text())
    for flavor in edited['variants']['flounder']['flavors']:
        enabled = flavor['id'] in FLAVORS
        flavor['build_image'] = enabled
        flavor['platforms'] = ['linux/amd64']
        if not enabled:
            flavor['build_iso'] = False
            flavor['build_qcow2'] = False
    config.write_text(tomlkit.dumps(edited))
    before = config.read_bytes()
    command = [sys.executable, str(ROOT / 'scripts/config-packages.py'), 'plan', 'htop',
               '--config', str(config), '--variant', 'flounder']

    def invoke(arguments, name):
        result = subprocess.run(arguments, text=True, capture_output=True, timeout=900)
        (tmp_path / f'{name}.json').write_text(result.stdout)
        (tmp_path / f'{name}.stderr').write_text(result.stderr)
        assert result.returncode == 0, f'{name}: {result.stderr}\n{result.stdout}'
        return json.loads(result.stdout), result.stderr

    preview, stderr = invoke(command, 'preview')
    assert config.read_bytes() == before
    assert preview['emission'] == {
        'status': 'ready', 'scope': 'variants', 'additions': {'flounder': ['htop']}}
    assert 'Dry run; use --write to apply.' in stderr
    assert '+add = ["htop"]' in stderr
    written, stderr = invoke([*command, '--write'], 'written-plan')
    assert 'Written atomically.' in stderr
    updated = tunaos_config.load(config)
    assert tunaos_config.image_packages(updated)['flounder']['add'] == ['htop']
    after = config.read_bytes()
    assert after != before
    _, stderr = invoke([*command, '--write'], 'repeated-plan')
    assert config.read_bytes() == after
    assert 'No change.' in stderr
    assert {row['target'] for row in written['targets']} == expected
    for row in written['targets']:
        assert row['index_availability']['status'] == 'present'
        assert row['transaction'] == row['installed_image'] == {'status': 'not-run'}
        sources = row['index_availability']['sources']
        assert {source['role'] for source in sources} == {'base', 'build'}
        assert all(source['signers'] for source in sources)
        for source in sources:
            if source['role'] == 'build':
                assert source['declaration_sha256'] and source['remote_keyring_sha256']
            else:
                assert 'declaration_sha256' not in source
                assert 'remote_keyring_sha256' not in source

    for target, image in sorted(images.items()):
        result, _ = invoke([
            sys.executable, str(ROOT / 'scripts/config-packages.py'), 'verify-transaction', 'htop',
            '--config', str(config), '--plan', str(tmp_path / 'written-plan.json'),
            '--image-target', target, '--image', image,
        ], 'transaction-' + target.split(':')[1])
        assert result['transaction']['status'] in ('solvable', 'already-installed')
        assert result['transaction']['removals'] == []
        assert result['installed_image'] == {'status': 'not-run'}
        assert result['image_binding'] == 'operator-supplied; not authenticated against the target'
    assert config.read_bytes() == after
    print(f'Native authoring/transaction evidence: {tmp_path}')
