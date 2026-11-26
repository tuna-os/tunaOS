"""The zirconium payload copy leaves /etc at 0755.

The payload is a `git archive` tarball: each directory in it is 0775. tar as
root kept that mode and `cp -a` gave it to /etc. bonito:niri d11611b66c66
shipped /etc as drwxrwxr-x, and sshd refused every key with "bad ownership or
modes for directory /etc" (tunaOS run 45627175940). Measured in a Fedora 44
container: the old script left /etc, /etc/greetd and /etc/profile.d at 775;
this one leaves them at 755.
"""
import re
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "build_scripts" / "install-zirconium.sh"


def test_the_tarball_goes_through_the_umask():
    """Falsification: `tar -xz` as root keeps the archive's 0775 directories."""
    text = SCRIPT.read_text()
    assert re.search(r"^umask 022$", text, re.M)
    tar = re.search(r"^\s*tar -x[^\n]*", text, re.M)
    assert tar and "--no-same-permissions" in tar.group(0), tar


def test_the_build_fails_on_a_writable_etc_directory():
    """Falsification: without the check, a new copy path can bring 0775 back silently."""
    text = SCRIPT.read_text()
    copy = text.index('cp -av "$SRC/usr/share/factory/etc/." /etc/')
    check = text.index("-perm /022", copy)
    assert "exit 1" in text[check:check + 600]
