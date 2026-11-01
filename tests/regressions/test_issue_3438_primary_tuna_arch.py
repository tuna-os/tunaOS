"""Tuna GDM policy has one editable owner: primary TOML (issue #3438).

Falsification: removing the Arch override breaks its native GDM policy;
removing the shared profile migration breaks GDM on other admitted bases.
"""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from lib import tunaos_config, tunaos_packages


def test_native_gdm_override_retains_session_hook_order():
    primary = tunaos_config.load()
    document = {key: primary[key] for key in ('package_groups', 'desktops')}
    actual = tunaos_packages.legacy_profiles(document)['tuna-arch']
    assert actual['display_manager'] == 'gdm'
    assert 'gdm' in actual['packages']['pacman']
    assert not {'greetd', 'greetd-gtkgreet', 'cage'} & set(actual['packages']['pacman'])
    hooks = actual['post_install']
    assert hooks.index('tuna-gdm-theme.sh') < hooks.index('tuna-gdm-default-session.sh')
    assert hooks.index('tuna-gdm-default-session.sh') < hooks.index('tuna-hide-other-sessions.sh')
    assert hooks.index('tuna-flatpak-remote.sh') < hooks.index('flatpak-preinstall.sh')


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
    assert 'tuna-hide-other-sessions' in resolved['after_install']


def test_adapter_is_regenerated_and_not_tracked(tmp_path):
    (tmp_path / 'tunaos.toml').write_bytes((ROOT / 'tunaos.toml').read_bytes())
    tunaos_config.prepare(tmp_path)
    target = tmp_path / 'manifests/desktops/tuna-arch.yaml'
    generated = json.loads(target.read_text())
    assert generated['display_manager'] == 'gdm'
    assert 'gdm' in generated['packages']['pacman']
    target.write_text('{"display_manager": "greetd"}')
    tunaos_config.prepare(tmp_path)
    assert json.loads(target.read_text()) == generated
    tracked = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '--', 'manifests/desktops'], text=True)
    assert tracked == ''


