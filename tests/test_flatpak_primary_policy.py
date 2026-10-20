"""Image defaults have one editable owner and preserve the existing declaration set.

Falsification: changing a common app/branch breaks the frozen fixture, editing
an exported adapter causes drift, and duplicate builder defaults are rejected.
"""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f'scripts/lib/{name}.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


primary = module('tunaos_config')
policy = module('flatpak_preinstall')
builder = module('iso_builder_config')
COMMON = [('io.github.kolunmi.Bazaar', 'stable'), ('org.mozilla.firefox', 'stable')]
GNOME = COMMON + [('com.mattjakeman.ExtensionManager', 'stable')]


def test_exact_previous_recipe_intent_and_no_editor_defaults():
    source = primary.load()
    for desktop in ['gnome', 'kde', 'cosmic', 'niri', 'xfce', 'tuna', 'pantheon', 'desktop']:
        expected = GNOME if desktop == 'gnome' else COMMON
        assert [(app['id'], app['branch']) for app in policy.apps(source, desktop)] == expected
    for desktop in builder.project(source)['desktops']:
        expected = GNOME if desktop['id'] == 'gnome' else COMMON
        assert desktop['default_flatpaks'] == [app for app, _ in expected]
    assert all('default_flatpaks' not in item for item in source['iso_builder']['desktops'])


def test_generated_policy_and_browser_artifacts_are_exact():
    source = primary.load()
    assert (ROOT / 'build_scripts/desktop/flatpak-preinstall.tsv').read_text() == policy.render(source)
    assert json.loads((ROOT / 'docs/iso-builder.config.json').read_text()) == builder.project(source)
    subprocess.run(['python3', str(ROOT / 'scripts/config.py'), 'check-flatpak-policy'], check=True)


@pytest.mark.parametrize('change', [
    lambda p: p.update(unknown=True),
    lambda p: p.update(schema_version=True),
    lambda p: p.update(common='bad'),
    lambda p: p['common'].append(copy.deepcopy(p['common'][0])),
    lambda p: p['common'][0].update(id='bad'),
    lambda p: p['common'][0].update(branch='../stable'),
    lambda p: p['common'][0].update(branch='beta'),
    lambda p: p['common'][0].update(remote='https://example.invalid/'),
    lambda p: p['desktop_additions'].update(unknown=[]),
    lambda p: p['desktop_additions'].update({'gnome-debian': []}),
    lambda p: p['desktop_additions'].update(gnome=copy.deepcopy(p['common'])),
])
def test_invalid_primary_policy_fails_closed(change):
    source = primary.load()
    change(source['flatpak_preinstall'])
    with pytest.raises(primary.ConfigError):
        primary.validate(source)


def test_duplicate_builder_default_owner_rejected():
    source = primary.load()
    source['iso_builder']['desktops'][0]['default_flatpaks'] = []
    with pytest.raises(primary.ConfigError):
        primary.validate(source)


def test_recipe_outputs_exact_frozen_declarations(tmp_path):
    for desktop in ['gnome', 'kde', 'tuna']:
        output = tmp_path / desktop
        result = subprocess.run(['bash', str(ROOT / 'build_scripts/desktop/flatpak-preinstall.sh')],
                                env={'PATH': '/usr/bin:/bin', 'DESKTOP_FLAVOR': desktop,
                                     'TUNAOS_PREINSTALL_DIR': str(output),
                                     'TUNAOS_SYSTEMD_SYSTEM_DIR': str(tmp_path / 'no-unit')},
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        expected = GNOME if desktop == 'gnome' else COMMON
        assert (output / f'tunaos-{desktop}.preinstall').read_text() == ''.join(
            f'[Flatpak Preinstall {app}]\nBranch={branch}\nIsRuntime=false\n\n' for app, branch in expected)
        assert 'source' not in (output / f'tunaos-{desktop}.preinstall').read_text().lower()


def test_drift_and_symlink_refused(tmp_path):
    artifact = tmp_path / 'adapter.tsv'
    artifact.write_text('wrong\n')
    cmd = ['python3', str(ROOT / 'scripts/config.py'), 'check-flatpak-policy', '--output', str(artifact)]
    assert subprocess.run(cmd, capture_output=True).returncode != 0
    link = tmp_path / 'link.tsv'
    link.symlink_to(artifact)
    assert subprocess.run(cmd[:-1] + [str(link)], capture_output=True).returncode != 0


def test_explicit_empty_policy_stays_empty_without_stock_fallback():
    source = primary.load()
    source['flatpak_preinstall']['common'] = []
    source['flatpak_preinstall']['desktop_additions'] = {}
    primary.validate(source)
    assert policy.apps(source, 'gnome') == []
    assert all(item['default_flatpaks'] == [] for item in builder.project(source)['desktops'])


@pytest.mark.parametrize('branch', ['stable', 'beta', ''])
def test_image_verifier_checks_exact_declared_branch(tmp_path, branch):
    source = (ROOT / 'build_scripts/checks/verify-desktop-experience.sh').read_text()
    start = source.index('awk -v header="[Flatpak Preinstall ${_fp_app}]"')
    command = source[start:source.index('; then', start)]
    command = command.replace('/usr/share/flatpak/preinstall.d', str(tmp_path))
    (tmp_path / 'app.preinstall').write_text(f'[Flatpak Preinstall org.mozilla.firefox]\nBranch={branch}\n')
    result = subprocess.run(['bash', '-c', '_fp_app=org.mozilla.firefox; _fp_branch=stable;\n' + command])
    assert (result.returncode == 0) == (branch == 'stable')


def test_missing_policy_fails_before_installed_policy_changes(tmp_path):
    script = tmp_path / 'flatpak-preinstall.sh'
    script.write_bytes((ROOT / 'build_scripts/desktop/flatpak-preinstall.sh').read_bytes())
    installed = tmp_path / 'tunaos-preinstall-policy.tsv'
    installed.write_text('preserve prior policy\n')
    result = subprocess.run(['bash', str(script)], env={
        'PATH': '/usr/bin:/bin', 'TUNAOS_PREINSTALL_DIR': str(tmp_path / 'preinstall.d'),
        'TUNAOS_SYSTEMD_SYSTEM_DIR': str(tmp_path / 'no-unit')}, capture_output=True)
    assert result.returncode != 0
    assert installed.read_text() == 'preserve prior policy\n'
    assert not list((tmp_path / 'preinstall.d').glob('*.preinstall'))


def test_empty_generated_policy_declares_no_apps(tmp_path):
    script = tmp_path / 'flatpak-preinstall.sh'
    script.write_bytes((ROOT / 'build_scripts/desktop/flatpak-preinstall.sh').read_bytes())
    source = primary.load()
    source['flatpak_preinstall']['common'] = []
    source['flatpak_preinstall']['desktop_additions'] = {}
    (tmp_path / 'flatpak-preinstall.tsv').write_text(policy.render(source))
    result = subprocess.run(['bash', str(script)], env={
        'PATH': '/usr/bin:/bin', 'TUNAOS_PREINSTALL_DIR': str(tmp_path / 'preinstall.d'),
        'TUNAOS_SYSTEMD_SYSTEM_DIR': str(tmp_path / 'no-unit')}, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / 'tunaos-preinstall-policy.tsv').read_text() == ''
    assert not list((tmp_path / 'preinstall.d').glob('*.preinstall'))


def test_materialization_receipt_includes_declaration_source_and_adapter():
    spec = importlib.util.spec_from_file_location('flatpak_receipt', ROOT / 'scripts/resolve-fork-config.py')
    compiler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(compiler)
    paths = compiler.source_paths(ROOT)
    for name in ('tunaos.toml', 'scripts/lib/flatpak_preinstall.py',
                 'build_scripts/desktop/flatpak-preinstall.tsv', 'build_scripts/desktop/flatpak-preinstall.sh'):
        assert name in paths


def test_recipe_refuses_linked_installed_policy(tmp_path):
    protected = tmp_path / 'protected'
    protected.write_text('preserve\n')
    (tmp_path / 'tunaos-preinstall-policy.tsv').symlink_to(protected)
    result = subprocess.run(['bash', str(ROOT / 'build_scripts/desktop/flatpak-preinstall.sh')], env={
        'PATH': '/usr/bin:/bin', 'TUNAOS_PREINSTALL_DIR': str(tmp_path / 'preinstall.d'),
        'TUNAOS_SYSTEMD_SYSTEM_DIR': str(tmp_path / 'no-unit')}, capture_output=True)
    assert result.returncode != 0
    assert protected.read_text() == 'preserve\n'


def test_kcm_cannot_bypass_the_primary_declaration_list():
    source = primary.load()
    for profile in source['desktops'].values():
        operations = profile.get('after_install', [])
        if 'kcm-ublue' in operations:
            assert operations.index('kcm-ublue') < operations.index('flatpak-preinstall')
    assert '[Flatpak Preinstall ' not in (ROOT / 'build_scripts/desktop/kcm-ublue.sh').read_text()


@pytest.mark.parametrize('sourced', [False, True])
@pytest.mark.parametrize('failure', ['missing-policy', 'linked-policy'])
def test_recipe_failure_is_nonzero_in_both_hook_contexts(tmp_path, sourced, failure):
    script = tmp_path / 'flatpak-preinstall.sh'
    script.write_bytes((ROOT / 'build_scripts/desktop/flatpak-preinstall.sh').read_bytes())
    protected = tmp_path / 'protected'
    protected.write_text('preserve\n')
    if failure == 'linked-policy':
        (tmp_path / 'flatpak-preinstall.tsv').write_bytes(
            (ROOT / 'build_scripts/desktop/flatpak-preinstall.tsv').read_bytes())
        (tmp_path / 'tunaos-preinstall-policy.tsv').symlink_to(protected)
    command = ['bash', '-c', 'source "$1"', 'hook-test', str(script)] if sourced else ['bash', str(script)]
    result = subprocess.run(command, env={
        'PATH': '/usr/bin:/bin', 'TUNAOS_PREINSTALL_DIR': str(tmp_path / 'preinstall.d'),
        'TUNAOS_SYSTEMD_SYSTEM_DIR': str(tmp_path / 'no-unit')}, capture_output=True)
    assert result.returncode == 1
    assert protected.read_text() == 'preserve\n'
    assert not list((tmp_path / 'preinstall.d').glob('*.preinstall'))
