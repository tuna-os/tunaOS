"""Hummingbird run38014578380 removed installed GDM links at first boot."""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / 'build_scripts/desktop/install-desktop.sh'


def helper(tmp_path):
    source = INSTALL.read_text()
    match = re.search(r'^write_display_manager_preset\(\) \{.*?^\}', source, re.M | re.S)
    assert match
    return match.group().replace('/usr/lib/systemd/system-preset', str(tmp_path / 'presets'))


@pytest.mark.parametrize('unit', ['gdm.service', 'gdm3.service', 'sddm.service', 'plasmalogin.service',
    'lightdm.service', 'greetd.service', 'cosmic-greeter.service'])
def test_exact_selected_greeter_has_preset_before_vendor_disable(tmp_path, unit):
    result = subprocess.run(['bash', '-c', helper(tmp_path) + '\nwrite_display_manager_preset "$1"',
                             'test', unit], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    preset = tmp_path / 'presets/50-tunaos-desktop.preset'
    assert preset.read_text() == 'enable ' + unit + '\n'
    assert preset.name < '99-default.preset'
    assert len(list(preset.parent.glob('*.preset'))) == 1


@pytest.mark.parametrize('unit', ['../gdm.service', 'display-manager-legacy.service', 'gdm.service\nenable evil.service'])
def test_unknown_or_injected_manager_cannot_write_policy(tmp_path, unit):
    result = subprocess.run(['bash', '-c', helper(tmp_path) + '\nwrite_display_manager_preset "$1"',
                             'test', unit], text=True, capture_output=True)
    assert result.returncode != 0
    assert not (tmp_path / 'presets/50-tunaos-desktop.preset').exists()


def test_installer_preserves_actual_native_alias_selection():
    source = INSTALL.read_text()
    assert '_TD_PRESET_DM="$(basename "$(readlink -f "${_TD_ALIAS}")")"' in source
    assert 'write_display_manager_preset "${_TD_PRESET_DM}"' in source
