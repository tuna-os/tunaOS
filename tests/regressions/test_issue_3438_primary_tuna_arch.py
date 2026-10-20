"""The Marlin GDM override has one editable owner, primary TOML (issue #3438)."""
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


def test_complete_ordered_gdm_override_matches_previous_source():
    primary = tunaos_config.load()
    document = {key: primary[key] for key in ('package_groups', 'desktops')}
    actual = tunaos_packages.legacy_profiles(document)['tuna-arch']
    assert actual == expected()
    assert actual['packages']['pacman'][0] == 'tunaos/tuna-desktop=1.0.0beta.1-1'
    assert 'gdm' in actual['packages']['pacman']
    assert not {'greetd', 'greetd-gtkgreet', 'cage'} & set(actual['packages']['pacman'])
    assert actual['post_install'] == ['tuna-flatpak-remote.sh', 'flatpak-preinstall.sh']


def test_native_resolution_selects_gdm_only_for_arch():
    primary = tunaos_config.load()
    document = {key: primary[key] for key in ('package_groups', 'desktops')}
    arch = tunaos_packages.resolve(document, 'tuna', manager='pacman', os_id='arch')
    assert arch['profile'] == 'tuna-arch'
    assert arch['display_manager'] == 'gdm'
    assert arch['sections'][-1][1]['required'] == expected()['packages']['pacman']
    assert arch['after_install'] == ['tuna-flatpak-remote', 'flatpak-preinstall']
    rpm = tunaos_packages.resolve(document, 'tuna', manager='dnf', os_id='almalinux', el10=True)
    assert rpm['profile'] == 'tuna'
    assert rpm['display_manager'] == 'greetd'
    assert 'greetd-gtkgreet' in rpm['after_install']


def test_adapter_is_regenerated_and_source_receipt_excludes_it(tmp_path):
    (tmp_path / 'tunaos.toml').write_bytes((ROOT / 'tunaos.toml').read_bytes())
    tunaos_config.prepare(tmp_path)
    target = tmp_path / 'manifests/desktops/tuna-arch.yaml'
    assert json.loads(target.read_text()) == expected()
    tracked = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '--', 'manifests/desktops'], text=True)
    assert tracked == ''
    spec = importlib.util.spec_from_file_location('source_receipt_3438', ROOT / 'scripts/resolve-fork-config.py')
    compiler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(compiler)
    receipt = compiler.source_receipt(ROOT)
    assert 'tunaos.toml' in receipt['files']
    assert not any(path.startswith('manifests/desktops/') for path in receipt['files'])
