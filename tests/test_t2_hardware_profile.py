"""The Apple T2 profile is data: it validates and generates the kernel swap,
packages, kargs and checks that build_scripts/overlay/hardware-profile.sh
applies (formerly the hand-written overlay/t2.sh)."""

from __future__ import annotations

import importlib.util
import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / 'build_scripts' / 'lib' / 'hardware-profiles.json'

_spec = importlib.util.spec_from_file_location('t2_profile_config', ROOT / 'scripts/lib/tunaos_config.py')
config_lib = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(config_lib)


def _generated() -> dict:
    return json.loads(GENERATED.read_text(encoding='utf-8'))['profiles']


def test_the_t2_profile_validates_and_the_generated_json_is_current():
    config = config_lib.load()  # raises ConfigError on any contract violation
    assert 't2' in config['hardware']
    result = subprocess.run([sys.executable, 'scripts/config.py', 'check-hardware-profiles'],
                            cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_t2_profile_swaps_to_the_t2linux_kernel():
    t2 = _generated()['t2']
    assert t2['architectures'] == ['x86_64']
    assert t2['package_managers'] == ['dnf']
    assert t2['kernel'] == {'dnf': 'kernel', 'repo': 'copr:sharpenedblade/t2linux'}
    assert t2['repos']['dnf'] == ['copr:sharpenedblade/t2linux']


def test_the_t2_profile_installs_its_userspace_and_forbids_broadcom_wl():
    t2 = _generated()['t2']
    assert t2['packages']['dnf'] == ['t2linux-release', 'iwd']
    assert not t2.get('kargs')
    assert t2['conflicts'] == {'dnf': ['broadcom-wl']}
    assert t2['require']['modules'] == ['brcmfmac']


def test_gnome_t2_resolves_to_the_generic_hardware_overlay():
    proc = subprocess.run([str(ROOT / 'scripts/resolve-flavor.sh'), 'bonito', 'gnome-t2'],
                          cwd=ROOT, check=True, text=True, capture_output=True)
    values = {}
    for line in proc.stdout.splitlines():
        key, raw = line.split('=', 1)
        parts = shlex.split(raw)
        values[key] = parts[0] if parts else ''
    assert values['OVERLAY_TYPE'] == 'hardware'
    assert values['HARDWARE_PROFILE'] == 't2'
    assert values['PARENT_FLAVOR'] == 'gnome'


def test_a_t2_flavor_on_a_non_dnf_variant_is_rejected():
    # flounder routes to Containerfile.debian (apt); T2 is dnf-only.
    config = config_lib.parse((ROOT / 'tunaos.toml').read_text(encoding='utf-8'))
    config['variants']['flounder']['flavors'].append(
        {'id': 'gnome-t2', 'hardware': 't2', 'parent': 'gnome', 'stage': 3, 'platforms': ['linux/amd64']})
    with pytest.raises(config_lib.ConfigError):
        config_lib.validate(config)
