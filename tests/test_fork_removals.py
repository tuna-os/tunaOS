"""Qualification candidate dispatch tests, not native solver evidence."""
import os
from pathlib import Path
import subprocess

import pytest

HELPER = Path(__file__).resolve().parents[1] / "build_scripts/lib/fork-removals.sh"


def run(tmp_path, manager, packages, *, fail="", enabled=True):
    log = tmp_path / "log"
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    for name in ("rpm", "dpkg", "dpkg-query", "pacman"):
        path = bindir / name
        path.write_text('''#!/bin/bash
printf '%s:%s\\n' "${0##*/}" "$*" >> "$LOG"
[[ -z "$FAIL" || "$*" != *"$FAIL"* ]] || exit 41
[[ "${0##*/}" != dpkg-query ]] || printf installed
''')
        path.chmod(0o755)
    result = subprocess.run(["/bin/bash", "-c",
                             'source "$1"; shift; tunaos_qualify_fork_removals "$@"',
                             "test", str(HELPER), manager, *packages],
                            env=dict(os.environ, PATH=f"{bindir}:/usr/bin:/bin", LOG=str(log), FAIL=fail,
                                     TUNAOS_FORK_REMOVAL_QUALIFICATION="1" if enabled else "0"),
                            text=True, capture_output=True)
    return result, log.read_text().splitlines() if log.exists() else []


@pytest.mark.parametrize("manager", ["apt", "dnf", "zypper", "pacman"])
def test_no_opt_in_never_touches_manager(tmp_path, manager):
    result, log = run(tmp_path, manager, ["example"], enabled=False)
    assert result.returncode != 0
    assert not log


@pytest.mark.parametrize("package", ["systemd", "NetworkManager", "linux-image-amd64", "kernel-core",
                                    "grub2-efi", "ca-certificates", "cryptsetup", "libc6", "libpam0g",
                                    "openssh", "--nodeps", "example*", "example;id", "repo/package"])
def test_protected_or_expression_rejected_before_query(tmp_path, package):
    # openssh is a security-sensitive remote-access package too.
    result, log = run(tmp_path, "dnf", ["example", package])
    assert result.returncode != 0
    assert not log


@pytest.mark.parametrize("manager", ["emerge", "unknown"])
def test_no_deselect_fallback(tmp_path, manager):
    result, log = run(tmp_path, manager, ["example"])
    assert result.returncode != 0
    assert not log


@pytest.mark.parametrize("manager,expected", [
    ("dnf", ["rpm:-q -- example", "rpm:-e --test -- example", "rpm:-e -- example"]),
    ("zypper", ["rpm:-q -- example", "rpm:-e --test -- example", "rpm:-e -- example"]),
    ("apt", ["dpkg-query:-W -f=${db:Status-Status} -- example", "dpkg:--dry-run --remove -- example",
             "dpkg:--remove -- example"]),
    ("pacman", ["pacman:-Q -- example", "pacman:-R --noconfirm -- example"]),
])
def test_exact_nonrecursive_dispatch(tmp_path, manager, expected):
    result, log = run(tmp_path, manager, ["example"])
    assert result.returncode == 0, result.stderr
    assert log == expected


@pytest.mark.parametrize("manager,fail,count", [("dnf", "-q", 1), ("dnf", "--test", 2),
                                              ("apt", "--dry-run", 2), ("pacman", "-R", 2)])
def test_failure_stops_and_propagates(tmp_path, manager, fail, count):
    result, log = run(tmp_path, manager, ["example"], fail=fail)
    assert result.returncode != 0
    assert len(log) == count
