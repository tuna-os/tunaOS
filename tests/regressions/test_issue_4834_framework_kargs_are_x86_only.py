"""tunaOS#4834: common's Intel Framework karg must not reach arm64 images.

projectbluefin/common ships /usr/lib/bootc/kargs.d/framework-intel.toml with
`kargs = ["module_blacklist=hid_sensor_hub"]` and no match-architectures, so
bootc applied it on every architecture: bonito:gnome-x13s (aarch64) carried it,
and tacklebox's X13s live mode stopped the ISO build with "driver blacklist
arguments are unsupported in X13s mode" (tunaOS#4834).
install-tunaos-overrides.sh, which runs after the common copy, scopes it to
x86_64.

Falsification: behavioural -- delete the framework_kargs block from
build_scripts/install-tunaos-overrides.sh and the first test fails.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "build_scripts/install-tunaos-overrides.sh"
COMMON = ('# Blacklist hid_sensor_hub to fix keyboard interrupt conflict on Intel Framework laptops\n'
          'kargs = ["module_blacklist=hid_sensor_hub"]\n')


def run(root: Path) -> None:
    subprocess.run(["bash", str(SCRIPT)], env=os.environ | {"TUNAOS_OVERRIDE_ROOT": str(root)},
                   check=True, capture_output=True, text=True)


def test_the_common_framework_karg_is_scoped_to_x86_64(tmp_path):
    kargs = tmp_path / "usr/lib/bootc/kargs.d/framework-intel.toml"
    kargs.parent.mkdir(parents=True)
    kargs.write_text(COMMON)
    run(tmp_path)
    run(tmp_path)  # the overlay and desktop stages run it again
    text = kargs.read_text()
    assert text.startswith(COMMON)
    assert text.count("match-architectures") == 1
    assert text.endswith('match-architectures = ["x86_64"]\n')


def test_an_already_scoped_file_and_a_missing_file_are_left_alone(tmp_path):
    kargs = tmp_path / "usr/lib/bootc/kargs.d/framework-intel.toml"
    kargs.parent.mkdir(parents=True)
    scoped = COMMON + 'match-architectures = ["x86_64"]\n'
    kargs.write_text(scoped)
    run(tmp_path)
    assert kargs.read_text() == scoped
    kargs.unlink()
    run(tmp_path)
    assert not kargs.exists()
