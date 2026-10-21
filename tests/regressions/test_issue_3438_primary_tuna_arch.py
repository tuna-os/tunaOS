"""Tuna GDM policy has one editable owner: primary TOML (issue #3438).

Falsification: removing the Arch override breaks its historical package set;
removing the shared profile migration breaks GDM on the other admitted bases.
"""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from lib import tunaos_config, tunaos_packages


def expected():
    return json.loads((ROOT / 'tests/fixtures/primary-packages/tuna-arch-at-aa9810e9.json').read_text())


def expected_with_theme():
    profile = expected()
    profile['post_install'].insert(1, 'tuna-gdm-theme.sh')
    profile['post_install'].insert(2, 'tuna-gdm-default-session.sh')
    return profile


def test_complete_ordered_gdm_override_preserves_the_previous_package_set():
    primary = tunaos_config.load()
    document = {key: primary[key] for key in ('package_groups', 'desktops')}
    actual = tunaos_packages.legacy_profiles(document)['tuna-arch']
    assert actual == expected_with_theme()
    assert actual['packages']['pacman'][0] == 'tunaos/tuna-desktop=1.0.0beta.1-1'
    assert 'gdm' in actual['packages']['pacman']
    assert not {'greetd', 'greetd-gtkgreet', 'cage'} & set(actual['packages']['pacman'])
    assert actual['post_install'] == [
        'tuna-flatpak-remote.sh',
        'tuna-gdm-theme.sh',
        'tuna-gdm-default-session.sh',
        'flatpak-preinstall.sh',
    ]


def test_native_resolution_selects_gdm_for_every_tuna_base_family():
    primary = tunaos_config.load()
    document = {key: primary[key] for key in ('package_groups', 'desktops')}
    targets = [
        ('pacman', {'os_id': 'arch'}, 'tuna-arch', 'pacman', 'gdm'),
        ('dnf', {'os_id': 'almalinux', 'el10': True}, 'tuna', 'el10', 'gdm'),
        ('dnf', {'os_id': 'fedora', 'fedora': True}, 'tuna', 'fedora', 'gdm'),
        ('dnf', {'os_id': 'fedora', 'eln': True}, 'tuna', 'eln', 'gdm'),
        ('dnf', {'os_id': 'fedora', 'fedora': True, 'rawhide': True}, 'tuna', 'rawhide', 'gdm'),
        ('apt', {'os_id': 'ubuntu'}, 'tuna', 'apt', 'gdm3'),
        ('zypper', {'os_id': 'opensuse'}, 'tuna', 'zypper', 'gdm'),
    ]
    removed = {'greetd', 'greetd-gtkgreet', 'gtkgreet', 'cage'}
    for manager, target, profile, family, package in targets:
        resolved = tunaos_packages.resolve(document, 'tuna', manager=manager, **target)
        assert resolved['profile'] == profile
        assert resolved['family'] == family
        assert resolved['display_manager'] == 'gdm'
        required = set(resolved['sections'][-1][1]['required'])
        assert package in required
        assert removed.isdisjoint(required)
    assert 'tuna-gdm-theme' in resolved['after_install']
    assert 'tuna-gdm-default-session' in resolved['after_install']


def test_adapter_is_regenerated_and_source_receipt_excludes_it(tmp_path):
    (tmp_path / 'tunaos.toml').write_bytes((ROOT / 'tunaos.toml').read_bytes())
    tunaos_config.prepare(tmp_path)
    target = tmp_path / 'manifests/desktops/tuna-arch.yaml'
    assert json.loads(target.read_text()) == expected_with_theme()
    tracked = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '--', 'manifests/desktops'], text=True)
    assert tracked == ''
    spec = importlib.util.spec_from_file_location('source_receipt_3438', ROOT / 'scripts/resolve-fork-config.py')
    compiler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(compiler)
    receipt = compiler.source_receipt(ROOT)
    assert 'tunaos.toml' in receipt['files']
    assert not any(path.startswith('manifests/desktops/') for path in receipt['files'])


