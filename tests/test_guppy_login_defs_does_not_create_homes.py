"""guppy must not let useradd create a home under a sysroot with no /var/home.

Gentoo's sys-apps/shadow ebuild runs `set_login_opt CREATE_HOME yes`. The
installer (fisherman, composefs branch) runs `useradd --root <deploy> --shell
/bin/bash --comment <name> --groups wheel,dialout <user>` and deliberately drops
--create-home: /home is a symlink to a /var/home that does not exist under
--root. The target's login.defs then creates the home anyway and useradd fails:

    useradd: cannot create directory /var            (exit status 12)
    Installation failed, step "configure", code "user_failed"

Seen on guppy-xfce, iso-builder run 43562471545 (plain and LUKS legs). The GNOME
installer creates no account, so guppy-gnome never hit it. Callers that want a
home pass --create-home or -m explicitly, so the image default can be `no`.

Falsification: delete the CREATE_HOME RUN from Containerfile.gentoo; the test
fails.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTAINERFILE = (ROOT / "Containerfile.gentoo").read_text()


def _create_home_run() -> str:
    match = re.search(r"^RUN sed -i [^\n]*CREATE_HOME[^\n]*\n(?:    [^\n]*\n?)*", CONTAINERFILE, re.M)
    assert match, "no RUN in Containerfile.gentoo sets CREATE_HOME"
    return match.group(0)


def test_login_defs_is_set_to_no_and_checked_in_the_desktop_stage():
    run = _create_home_run()
    assert "s/^CREATE_HOME[[:space:]].*/CREATE_HOME no/" in run
    assert "grep -qx 'CREATE_HOME no' /etc/login.defs" in run
    desktop = CONTAINERFILE.index("FROM desktop-build AS desktop")
    final_targets = CONTAINERFILE.index("FROM desktop AS gnome")
    assert desktop < CONTAINERFILE.index(run) < final_targets


def test_the_sed_rewrites_a_gentoo_style_login_defs():
    sample = "UID_MIN 1000\nCREATE_HOME\tyes\nUMASK 077\n"
    out = re.sub(r"(?m)^CREATE_HOME\s.*", "CREATE_HOME no", sample)
    assert "CREATE_HOME no\n" in out and "yes" not in out
