#!/usr/bin/env python3
"""A failed installed-system assertion must print why it failed.

gurnard:pantheon installed boots failed on both legs (run 43640584827) with
only `not ok - bootc status succeeds` on the serial console: no stderr, no
mount state, no display-manager journal. The VM powers off after the run, so
nothing else survives. check() now sends the first lines of the failing
command's output to the same channel, and a failing run prints the mounts
and the display manager's own warnings.

Falsification: behavioural -- put `"$@" >/dev/null 2>&1` back in check() in
build_scripts/checks/e2e-runtime-checks.sh and
test_a_failing_check_prints_the_command_output fails, because the reason
line is never emitted. Drop the findmnt call or the journalctl call and the
two static tests fail.
"""

import re
import subprocess
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "build_scripts"
    / "checks"
    / "e2e-runtime-checks.sh"
)


def _check_function() -> str:
    text = SCRIPT.read_text()
    m = re.search(r"^check\(\) \{\n.*?^\}\n", text, re.S | re.M)
    assert m, "check() not found in e2e-runtime-checks.sh"
    return m.group(0)


def _run(body: str) -> list[str]:
    prog = (
        "PASS=0; FAIL=0\n"
        'emit() { echo "$1"; }\n'
        + _check_function()
        + body
    )
    out = subprocess.run(
        ["bash", "-c", prog], capture_output=True, text=True, check=True
    )
    return out.stdout.splitlines()


def test_a_failing_check_prints_the_command_output() -> None:
    lines = _run(
        "check 'bootc status succeeds' bash -c "
        "'echo \"Failed to setup working directory: Read-only file system\" >&2; exit 1'\n"
    )
    assert lines[0] == "not ok - bootc status succeeds"
    assert any("Read-only file system" in line and line.startswith("#") for line in lines[1:])


def test_a_failing_check_output_is_bounded() -> None:
    lines = _run("check 'noisy' bash -c 'seq 1 100; exit 1'\n")
    assert lines[0] == "not ok - noisy"
    assert len(lines) == 1 + 6


def test_a_passing_check_stays_one_line() -> None:
    lines = _run("check 'fine' bash -c 'echo chatter; exit 0'\n")
    assert lines == ["ok - fine"]


def test_the_mount_state_is_printed() -> None:
    text = SCRIPT.read_text()
    # findmnt takes one target per call; a list of targets prints nothing.
    assert re.search(r'for mount_target in / /sysroot /var /etc /tmp;', text)
    assert re.search(r'findmnt .* -T "\$mount_target"', text)


def test_the_display_manager_journal_is_printed_on_failure() -> None:
    assert "journalctl -b -u display-manager.service" in SCRIPT.read_text()
