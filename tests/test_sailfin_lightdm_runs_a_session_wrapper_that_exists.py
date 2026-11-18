"""sailfin's LightDM must name session scripts that exist after /usr/etc is gone.

Tumbleweed's 50-suse-defaults.conf names /usr/etc/X11/xdm/{Xsession,Xstartup}.
Containerfile.opensuse moves /usr/etc into /etc and deletes it, so every LightDM
login ran a missing wrapper. The sailfin:xfce live session sat at the greeter
with no xfce4-session (iso-builder run 43439582829).

Falsification: remove the repoint-usr-etc.sh RUN from Containerfile.opensuse,
or make the script skip the rewrite; these tests fail.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "build_scripts/bootc/repoint-usr-etc.sh"
CONTAINERFILE = (ROOT / "Containerfile.opensuse").read_text()

# /usr/share/lightdm/lightdm.conf.d/50-suse-defaults.conf as shipped by
# openSUSE Factory's lightdm package.
SUSE_DEFAULTS = """[Seat:*]
pam-service = lightdm
pam-autologin-service = lightdm-autologin
pam-greeter-service = lightdm-greeter
xserver-command=/usr/bin/X
session-wrapper=/usr/etc/X11/xdm/Xsession
greeter-setup-script=/usr/etc/X11/xdm/Xsetup
session-setup-script=/usr/etc/X11/xdm/Xstartup
session-cleanup-script=/usr/etc/X11/xdm/Xreset
"""


def _tree(tmp_path: Path, present=("Xsession", "Xsetup", "Xstartup", "Xreset")) -> Path:
    conf = tmp_path / "usr/share/lightdm/lightdm.conf.d/50-suse-defaults.conf"
    conf.parent.mkdir(parents=True)
    conf.write_text(SUSE_DEFAULTS)
    xdm = tmp_path / "etc/X11/xdm"
    xdm.mkdir(parents=True)
    for name in present:
        (xdm / name).write_text("#!/bin/sh\n")
    return conf


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SCRIPT), str(tmp_path)], capture_output=True, text=True, check=True)


def test_every_xdm_script_is_repointed_at_etc(tmp_path):
    conf = _tree(tmp_path)
    _run(tmp_path)
    text = conf.read_text()
    assert "/usr/etc" not in text
    for key, name in (("session-wrapper", "Xsession"), ("session-setup-script", "Xstartup"),
                      ("greeter-setup-script", "Xsetup"), ("session-cleanup-script", "Xreset")):
        assert f"{key}=/etc/X11/xdm/{name}\n" in text
    assert "pam-service = lightdm\n" in text


def test_a_reference_with_no_etc_copy_stays_and_warns(tmp_path):
    conf = _tree(tmp_path, present=("Xsession",))
    result = _run(tmp_path)
    text = conf.read_text()
    assert "session-wrapper=/etc/X11/xdm/Xsession\n" in text
    assert "session-setup-script=/usr/etc/X11/xdm/Xstartup\n" in text
    assert "Xstartup does not exist" in result.stderr


def test_the_desktop_stage_runs_it_after_usr_etc_is_removed():
    removal = CONTAINERFILE.rindex("rm -rf /usr/etc")
    call = CONTAINERFILE.index("build_scripts/bootc/repoint-usr-etc.sh")
    assert removal < call
    assert CONTAINERFILE.index("install-desktop.sh") < call
