"""Source contracts for #2412; fixtures must not read or write the host image."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / 'build_scripts/lib.sh'
REPORTING = ROOT / 'build_scripts/lib/reporting.sh'
FLAGS = '''IS_FEDORA IS_HUMMINGBIRD IS_ELN IS_RHEL IS_ALMALINUX
IS_ALMALINUXKITTEN IS_CENTOS IS_UBUNTU IS_DEBIAN IS_ARCH IS_OPENSUSE IS_GENTOO'''.split()
# Public functions measured on upstream/main at 216273e5, including service policy.
FUNCTIONS = '''_derive_name _yq_array apt_install_available copy_systemfiles_for
 detect_fedora_ver detected_os dnf_retry emit_packages_manifest install_available
 install_dnf_plugin_providers install_from_copr install_rawhide_tolerant is_x86_64_v2
 kde_dm_unit lint_image pkg_clean pkg_install pkg_refresh pkg_remove print_debug_info
 rawhide_rpmdb_probe record_package_wishlist record_unsatisfied_requests
 rpmdb_stage2_guard run_buildscripts_for safe_disable safe_enable
 tunaos_guard_login_banners warn_on_fail zypper_retry'''.split()


def bash(script, *, env=None):
    return subprocess.run(
        ['/bin/bash', '-c', script], text=True, capture_output=True,
        env=env, check=True,
    )


@pytest.mark.parametrize('base,os_id,version,flag,manager,name', [
    ('quay.io/fedora/fedora-bootc:44', 'fedora', '44', 'IS_FEDORA', 'dnf', 'bonito'),
    ('debian:13', 'debian', '13', 'IS_DEBIAN', 'apt', 'flounder'),
    ('archlinux:latest', 'arch', 'rolling', 'IS_ARCH', 'pacman', 'marlin'),
    ('opensuse/tumbleweed:latest', 'opensuse-tumbleweed', '20261103', 'IS_OPENSUSE', 'zypper', 'sailfin'),
    ('gentoo/stage3:latest', 'gentoo', '2.18', 'IS_GENTOO', 'emerge', 'guppy'),
])
def test_facade_source_contract(tmp_path, base, os_id, version, flag, manager, name):
    """Snapshot cold and cached functions, flags, and metadata."""
    shutil.copytree(ROOT / 'build_scripts/lib', tmp_path / 'lib')
    release = tmp_path / 'os-release'
    release.write_text(f'ID={os_id}\nVERSION_ID={version}\n')
    image_info = tmp_path / 'image-info.json'
    image_info.write_text(json.dumps({'base-image': base}))
    cache = tmp_path / 'cache'
    source = LIB.read_text().replace('/tmp/tunaos-build-env', str(cache))
    for path in ('/etc/os-release', '/usr/lib/os-release'):
        source = source.replace(path, str(release))
    source = source.replace('/usr/share/ublue-os/image-info.json', str(image_info))
    fixture = tmp_path / 'lib.sh'
    fixture.write_text(source)
    env = {'PATH': os.environ['PATH'], 'BASE_IMAGE': base}
    probe = f'''
set -euo pipefail
source '{fixture}' >/dev/null
printf 'FUNCTIONS\n'
declare -F | cut -d' ' -f3 | sort
printf 'ENV\n'
export -p
printf 'FLAGS\n'
for flag in {' '.join(FLAGS)}; do printf '%s=%s\n' "$flag" "${{!flag}}"; done
printf 'META\n%s\n%s\n%s\n%s\n' "$BASE_IMAGE" "$MAJOR_VERSION_NUMBER" "$PKG_MGR" "$IMAGE_NAME"
'''
    cold = bash(probe, env=env).stdout
    assert cache.exists()
    # Prove the warm path uses the cache, rather than re-reading the fixture.
    release.unlink()
    image_info.unlink()
    warm = bash(probe, env=env).stdout
    # _derive_name is defined inside the cold detection branch in the legacy
    # contract. Cached sources expose only the remaining functions.
    assert warm == cold.replace('_derive_name\n', '', 1)
    functions, rest = cold.removeprefix('FUNCTIONS\n').split('ENV\n')
    assert functions.splitlines() == sorted(FUNCTIONS)
    exports, rest = rest.split('FLAGS\n')
    flags, meta = rest.split('META\n')
    assert flags.splitlines() == [f'{key}={str(key == flag).lower()}' for key in FLAGS]
    assert meta.splitlines() == [base, version.split('.')[0], manager, name]
    # IS_ELN was not exported by the original facade; preserve that contract.
    for key in [key for key in FLAGS if key != 'IS_ELN'] + [
        'BASE_IMAGE', 'MAJOR_VERSION_NUMBER', 'PKG_MGR', 'IMAGE_NAME',
        'IMAGE_PRETTY_NAME', 'SCRIPTS_PATH', 'DESKTOP_FLAVOR',
    ]:
        assert f'declare -x {key}=' in exports


def test_reporting_source_has_no_initialization():
    result = bash(f'''
set -euo pipefail
before=$(set +o)
source '{REPORTING}'
[[ "$before" == "$(set +o)" ]]
[[ -z "${{PKG_MGR+x}}${{BASE_IMAGE+x}}${{IS_FEDORA+x}}${{_TUNAOS_ENV_CACHE+x}}" ]]
declare -F | cut -d' ' -f3 | sort
''', env={'PATH': os.environ['PATH']})
    assert result.stdout.splitlines() == ['emit_packages_manifest', 'lint_image', 'warn_on_fail']


def test_reporting_boundary():
    """The facade loads reporting; reporting cannot grow detection or package policy."""
    assert 'source "$(realpath "$(dirname "${BASH_SOURCE[0]}")")/lib/reporting.sh"' in LIB.read_text()
    for name in ('warn_on_fail', 'lint_image', 'emit_packages_manifest'):
        assert f'{name}()' not in LIB.read_text()
    assert 'source ' not in REPORTING.read_text()
    assert '/os-release' not in REPORTING.read_text()


@pytest.mark.parametrize('fatal,expected', [('0', 0), ('1', 17)])
def test_lint_reporting_preserves_output_and_status(tmp_path, fatal, expected):
    summary = tmp_path / 'summary'
    result = bash(f'''
set -euo pipefail
source '{REPORTING}'
bootc() {{ echo 'fixture lint failure'; return 17; }}
export IMAGE_NAME=flounder MAJOR_VERSION_NUMBER=13 BOOTC_LINT_FATAL={fatal}
export GITHUB_STEP_SUMMARY='{summary}'
rc=0
lint_image || rc=$?
printf 'STATUS=%s\n' "$rc"
''')
    assert 'fixture lint failure' in result.stdout
    assert f'STATUS={expected}' in result.stdout
    assert 'fixture lint failure' in summary.read_text()
    assert ('::error' if expected else '::warning') in result.stdout


def test_manifest_reporting_preserves_schema(tmp_path):
    # Redirect only the output paths; execute the real manifest implementation.
    module = tmp_path / 'reporting.sh'
    target = tmp_path / 'image'
    module.write_text(REPORTING.read_text().replace(
        'local target_dir="/usr/share/tunaos"', f'local target_dir="{target}"'
    ).replace('/tmp/packages.json.tmp', str(tmp_path / 'packages.json.tmp')))
    bash(f'''
set -euo pipefail
source '{module}'
rpm() {{ printf 'alpha\\t1.0-2\\nzeta\\t3.0-1\\n'; }}
IMAGE_NAME=bonito DESKTOP_FLAVOR=kde PKG_MGR=dnf emit_packages_manifest
''')
    manifest = target / 'packages.json'
    assert json.loads(manifest.read_text()) == {
        'image': 'bonito', 'flavor': 'kde', 'pkg_manager': 'dnf', 'count': 2,
        'packages': [{'name': 'alpha', 'version': '1.0-2'}, {'name': 'zeta', 'version': '3.0-1'}],
    }
    assert manifest.stat().st_mode & 0o777 == 0o644
