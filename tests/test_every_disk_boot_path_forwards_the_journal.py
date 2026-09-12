"""A disk built to be watched over serial must send unit stderr there too.

`boots` is scored by a QEMU boot whose only surviving channel is the serial
console: the gate reaches the guest over SSH for diagnostics, and the failures
worth diagnosing are the ones that stop SSH from working. dbus-broker fails, so
systemd-logind fails, so sshd cannot open a PAM session, and the collector
records one line:

    WARNING: guest SSH unavailable; could not collect boot diagnostics

leaving systemd's terse status line as the whole evidence base:

    [FAILED] Failed to start dbus-broker.service - D-Bus System Message Bus.
    See 'systemctl status dbus-broker.service' for details.

-- a command nobody can run, on a guest nobody can reach. Measured 2026-09-11 on
yellowfin:gnome, skipjack:gnome and wahoo:gnome, nine cells between them once
the -hwe and -nvidia flavors are counted, with kde green on the same images.

systemd.journald.forward_to_console=1 is the fix, and tunaOS#2465 adding it to
scripts/iso-e2e.sh was not enough: the Gate does not install through that
script. It builds the disk with `just qcow2` and boots the result, so the karg
was absent exactly where `boots` is decided.

So the property here is not "the karg is in one file" -- #2465 already
satisfied that while the gate stayed blind. It is: any install that bakes a
serial console in order to be WATCHED over it must also put the journal there,
because the status lines the console carries by default name a failure without
naming its cause.

Scoped by `console=ttyS0` on purpose, rather than by every `bootc install
to-disk` in the tree. A disk nobody watches over serial (scripts/build-qcow2.sh,
which bakes no console kargs at all -- local builds and the weekly screenshot
job) has no serial log for the karg to improve, and sweeping it in would make
this file an unrelated style rule instead of a gate on evidence.
"""
from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

KARG = "systemd.journald.forward_to_console=1"
SEARCH_ROOTS = ("scripts", "just", "build_scripts", ".github")


def _strip_comments(text: str) -> str:
    """Drop whole-line comments.

    This repo's prose quotes the very kargs these tests search for, so an
    un-stripped match passes with the flag deleted from the command.
    """
    return "\n".join(
        line for line in text.splitlines()
        if not line.lstrip().startswith("#"))


def _serial_watched_installers() -> list[pathlib.Path]:
    """Files that install a disk AND bake a serial console to watch it on."""
    hits = []
    for root in SEARCH_ROOTS:
        base = ROOT / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            try:
                code = _strip_comments(path.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, OSError):
                continue
            if re.search(r"bootc install to-disk", code) and "console=ttyS0" in code:
                hits.append(path)
    return hits


def test_the_search_finds_the_paths_we_know_about():
    """Guard the selector: a discovery that matched nothing would make the
    real assertion below vacuously true (tunaOS#1730)."""
    found = {p.relative_to(ROOT).as_posix() for p in _serial_watched_installers()}
    for known in ("scripts/iso-e2e.sh", "just/qcow2-build.just"):
        assert known in found, (
            f"{known} installs a disk and bakes console=ttyS0, but the "
            f"discovery missed it -- found {sorted(found)}. Fix the search "
            "before trusting the assertion below."
        )


@pytest.mark.parametrize(
    "path", _serial_watched_installers(), ids=lambda p: p.name)
def test_a_serial_watched_disk_also_forwards_its_journal(path: pathlib.Path):
    code = _strip_comments(path.read_text(encoding="utf-8"))
    assert KARG in code, (
        f"{path.relative_to(ROOT)} bakes console=ttyS0 so a boot can be "
        f"watched over serial, but does not pass --karg {KARG}.\n"
        "The console carries systemd's status lines; a unit's own stderr goes "
        "to the journal, and the journal is unreachable once sshd is "
        "downstream of whatever broke. Without this the serial log names the "
        "failed unit and never its cause. Add the karg alongside the console= "
        "ones."
    )
