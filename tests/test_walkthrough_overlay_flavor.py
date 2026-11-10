"""Overlay flavors take their desktop family's measured strict driver.

skipjack:gnome-hwe and skipjack:gnome-nvidia (iso-builder run 42686358529 and
42686400245) fell through to the legacy click-through walker because the
dispatch compared the flavor to "gnome" exactly. That walker kept pressing
keys past the finished screen and powered the VM off. The overlays ship the
same desktop and the same bundled installer as their base, so they must reach
scripts/lib/gnome_installer_driver.py like gnome does.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

STUB = '''
import json, os
def image_ref_from_environment(env):
    return "stub"
def drive(outdir, *args, flavor="gnome", **kw):
    with open(os.path.join(outdir, "dispatched.json"), "w") as f:
        json.dump({"driver": "gnome_installer_driver", "flavor": flavor}, f)
    return 0
'''


def dispatch(tmp_path, flavor, extra=()):
    scripts = tmp_path / "scripts"
    (scripts / "lib").mkdir(parents=True)
    shutil.copy(ROOT / "scripts/installer-walkthrough.py", scripts)
    (scripts / "lib/__init__.py").write_text("")
    (scripts / "lib/gnome_installer_driver.py").write_text(STUB)
    out = tmp_path / "out"
    out.mkdir()
    proc = subprocess.run(
        [sys.executable, str(scripts / "installer-walkthrough.py"), str(tmp_path / "mon.sock"),
         str(out), "0", flavor, "--strict", "--mode=plain", *extra],
        capture_output=True, text=True, timeout=30,
        env={"PATH": "/usr/bin:/bin", "TUNAOS_QUAL_INSTALLER_DIGEST": "sha256:0"},
    )
    path = out / "dispatched.json"
    return proc, (json.loads(path.read_text()) if path.exists() else None)


@pytest.mark.parametrize("flavor", ["gnome", "gnome-hwe", "gnome-nvidia", "gnome-nvidia-hwe"])
def test_gnome_overlays_use_the_gnome_driver(tmp_path, flavor):
    proc, seen = dispatch(tmp_path, flavor)
    assert proc.returncode == 0, proc.stderr
    assert seen == {"driver": "gnome_installer_driver", "flavor": "gnome"}


def test_other_desktops_do_not_reach_the_gnome_driver(tmp_path):
    _, seen = dispatch(tmp_path, "kde")
    assert seen is None
