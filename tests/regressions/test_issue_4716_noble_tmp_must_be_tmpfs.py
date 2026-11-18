"""tunaOS#4716: gurnard:pantheon installed boot: /tmp must be a tmpfs on apt images.

iso-builder run 43800611170 (gurnard:pantheon, both legs): the installed noble
system printed `bootc: Inspecting filesystem /: Read-only file system` for
`bootc status` and `Failed to setup working directory: Read-only file system`
for `systemd-analyze verify`, and the plain leg stopped at a tty1 login prompt
(lightdm's X server cannot create /tmp/.X11-unix). Ubuntu 24.04 keeps /tmp on
the root filesystem; a bootc root is read-only. Fedora, CentOS and Ubuntu 26.04
mount a tmpfs on /tmp, so only noble failed.

Falsification: behavioural. Run the real build_scripts/apt-runtime-defaults.sh
against an empty root (noble ships no tmp.mount in the image): drop the unit
block and the unit file and the local-fs.target.wants link are missing, so the
tests fail. A root that already carries tmp.mount keeps its own copy.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "build_scripts" / "apt-runtime-defaults.sh"


def _apply(tree: Path) -> None:
    (tree / "etc").mkdir(exist_ok=True)  # every image has one; the locale block writes into it
    subprocess.run(["bash", str(SCRIPT)], check=True, env={**os.environ, "ROOT": str(tree)})


def test_tmp_is_mounted_as_tmpfs_at_boot(tmp_path):
    _apply(tmp_path)
    unit = tmp_path / "usr/lib/systemd/system/tmp.mount"
    text = unit.read_text()
    assert "Where=/tmp" in text and "Type=tmpfs" in text and "mode=1777" in text
    link = tmp_path / "usr/lib/systemd/system/local-fs.target.wants/tmp.mount"
    assert link.is_symlink() and os.readlink(link) == "../tmp.mount"


def test_a_shipped_tmp_mount_is_kept_and_enabled(tmp_path):
    shipped = tmp_path / "usr/lib/systemd/system/tmp.mount"
    shipped.parent.mkdir(parents=True)
    shipped.write_text("[Mount]\nWhat=tmpfs\nWhere=/tmp\nType=tmpfs\n# vendor\n")
    _apply(tmp_path)
    assert shipped.read_text().endswith("# vendor\n")
    assert (tmp_path / "usr/lib/systemd/system/local-fs.target.wants/tmp.mount").is_symlink()


def test_a_second_layer_changes_nothing(tmp_path):
    _apply(tmp_path)
    before = (tmp_path / "usr/lib/systemd/system/tmp.mount").read_text()
    _apply(tmp_path)
    assert (tmp_path / "usr/lib/systemd/system/tmp.mount").read_text() == before
