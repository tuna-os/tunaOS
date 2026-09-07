"""A failure inside customize-live.sh must END the build, not wedge it.

customize-live.sh forks a system dbus-daemon so flatpak has a bus. A forked
bus OUTLIVES the script, and the stdout it inherited keeps the build's output
pipe open -- so when the script exits non-zero, whatever is reading that pipe
keeps waiting.

Measured on tunaOS iso-e2e run 32866334376 (hummingbird:base). The script
printed a correct, specific diagnosis and exited:

    15:35:46  dnf5 install -y flatpak -> No match for argument: flatpak
    15:35:46  ERROR: flatpak not installed and could not be installed
    15:35:46  + exit 1
      ...     (not one line of output for 57 minutes)
    16:32:26  ##[error]The action 'Build the ISO on this runner' has timed
              out after 60 minutes.

Three and a half minutes of signal became an hour of dead air, and the
failure GitHub reported was a timeout rather than the missing package.

The cost is not just a confusing message. `build_artifacts_s2` allows an ISO
cell 90 minutes, so ANY failure below the fork -- today's missing flatpak, or
whatever fails next once flatpak lands -- consumes the cell's whole budget
and then misattributes itself.

These tests run the script's OWN bus helpers against a fake dbus-daemon that
daemonizes a long-lived child holding stdout, which is what a real bus does.
Asserting that the file contains the word `trap` would pass just as happily
with a reaper that reaps nothing -- and "captures a pid that is already gone"
is the specific way this fix can be silently inert, so it is what the fake is
built to expose.
"""
from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "live-iso" / "common" / "src" / "customize-live.sh"

# Long enough that a wedge is unmistakable, short enough not to slow the suite.
FAKE_BUS_LIFETIME = 25
WEDGE_TIMEOUT = 10
FAST_ENOUGH = 5.0


def bus_helpers() -> str:
    """The real `_live_bus_pids` / `_reap_live_buses` / `_start_bus` block.

    Extracted from the script rather than copied, so a rename or a rewrite
    breaks this file loudly instead of leaving it testing a stale duplicate.
    """
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index("\t_live_bus_pidfiles=()")
    end = text.index("\tmkdir -p /var/lib/dbus", start)
    block = text[start:end]
    for name in ("_reap_live_buses", "_start_bus", "trap _reap_live_buses EXIT"):
        assert name in block, f"bus helper block no longer defines {name}"
    # The block is indented inside `if [[ -n "${INSTALLER_APP}" ]]`.
    return "\n".join(line[1:] if line.startswith("\t") else line
                     for line in block.splitlines())


def fake_dbus_daemon(tmp_path: Path) -> Path:
    """A stand-in for `dbus-daemon --fork`.

    The realistic part is that the daemonized child INHERITS whatever stdout
    the caller gave it and outlives the caller — which is precisely how a real
    bus can pin the build's output pipe.

    It speaks the real binary's option set, not a convenient one. The first
    version of this fake honoured `--pidfile=FILE`, an option dbus-daemon does
    not have (its only pidfile switch is `--nopidfile`; the path is config
    syntax), so the suite proved the reaper worked against a bus the real
    daemon refused to start, and every live customize from 2026-08-25 to
    2026-09-02 died at the session bus (runs 32875192246, 33594824101). Now
    `--pidfile` is a usage error exactly as it is for dbus 1.14, and the pid
    is delivered the way the real one delivers it: `--print-pid=FD`.
    """
    binder = tmp_path / "bin"
    binder.mkdir(exist_ok=True)
    shim = binder / "dbus-daemon"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        "fd=\n"
        'for arg in "$@"; do\n'
        '  case "$arg" in\n'
        '    --print-pid=*) fd="${arg#--print-pid=}" ;;\n'
        '    --pidfile=*) echo "dbus-daemon [--version] [--session] ... [--nopidfile]" >&2; exit 1 ;;\n'
        "  esac\n"
        "done\n"
        f"sleep {FAKE_BUS_LIFETIME} &\n"
        'child=$!\n'
        '[[ -n "$fd" ]] && echo "$child" >&"$fd"\n'
        "exit 0\n"
    )
    shim.chmod(0o755)
    return binder


def run_failing_customize(tmp_path: Path, helpers: str) -> tuple[float, int]:
    """Start a bus, then fail -- and time how long the READER waits."""
    script = tmp_path / "harness.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -uo pipefail\n"
        f"{helpers}\n"
        "_start_bus \"$HOME/bus.pid\" --system || true\n"
        "echo 'ERROR: something failed after the bus started' >&2\n"
        "exit 1\n"
    )
    script.chmod(0o755)
    env = {"PATH": f"{fake_dbus_daemon(tmp_path)}:/usr/bin:/bin", "HOME": str(tmp_path)}
    started = time.monotonic()
    try:
        # Capturing output is exactly what the build does, and is what blocks
        # on a pipe an orphaned daemon still holds.
        proc = subprocess.run(["bash", str(script)], capture_output=True,
                              text=True, env=env, timeout=WEDGE_TIMEOUT)
        return time.monotonic() - started, proc.returncode
    except subprocess.TimeoutExpired:
        return time.monotonic() - started, -1


def test_the_script_reaps_its_bus_so_a_failure_ends_the_build(tmp_path) -> None:
    elapsed, code = run_failing_customize(tmp_path, bus_helpers())
    assert code == 1, (
        f"harness did not fail cleanly (rc={code}); after {elapsed:.1f}s the "
        "reader was still waiting on a pipe the forked bus holds open — this "
        "is the 57-minute wedge from run 32866334376"
    )
    assert elapsed < FAST_ENOUGH, (
        f"the failure took {elapsed:.1f}s to surface; it must be immediate, "
        "or an ISO cell burns its 90-minute budget and reports a timeout "
        "instead of the real cause"
    )


def test_the_wedge_is_real_without_the_reaper(tmp_path) -> None:
    """Guard the guard: prove the fixture reproduces the bug it claims to.

    Without this, the test above passes on any machine where the fake bus
    fails to start at all — measuring nothing, which is the exact defect
    class the fix is about.
    """
    # Remove the redirection, which is the load-bearing half: without it the
    # forked bus inherits the build's stdout and pins the pipe open.
    real = 'dbus-daemon "$@" --fork --nopidfile --print-pid=3 3>"$_pidfile" >/dev/null 2>&1'
    helpers = bus_helpers()
    assert real in helpers, "the _start_bus line changed; update this mutation with it"
    crippled = helpers.replace(
        real,
        'dbus-daemon "$@" --fork --nopidfile --print-pid=3 3>"$_pidfile"',
    ).replace("trap _reap_live_buses EXIT", "true")
    elapsed, code = run_failing_customize(tmp_path, crippled)
    assert code == -1, (
        f"with the reaper removed the harness still returned in {elapsed:.1f}s "
        "(rc=%s), so the fixture does not reproduce the wedge and the test "
        "above proves nothing" % code
    )


def test_the_fix_keeps_the_bus_off_the_build_pipe(tmp_path) -> None:
    """Pin the two properties that make this work, and one that would break it."""
    block = bus_helpers()
    assert ">/dev/null 2>&1" in block, (
        "the forked bus inherits the build's stdout again, which is what pins "
        "the output pipe open and turns a fast failure into a step timeout"
    )
    # Comments are allowed to quote the wrong forms; only the code is pinned.
    code = "\n".join(l for l in block.splitlines() if not l.lstrip().startswith("#"))
    assert "$(dbus-daemon" not in code and "`dbus-daemon" not in code, (
        "`_pid=$(dbus-daemon ... --print-pid)` cannot be used here: command "
        "substitution waits for the pipe to close, which is exactly what a "
        "forked daemon holds, so it hangs AT THE FORK -- earlier and harder "
        "than the bug being fixed. The first version of this fix did that and "
        "this suite caught it. `--print-pid=FD` with FD opened on a FILE is "
        "the way that does not wait, and it is the only pid delivery the real "
        "binary offers."
    )
    assert "--pidfile=" not in code, (
        "dbus-daemon has no --pidfile option (only --nopidfile; the path is "
        "config-file syntax). Passing it is a usage error, exit 1, on the "
        "stderr this helper discards: no bus starts and the session-bus call "
        "kills the customize under set -eu. That is what every live-ISO build "
        "did from 886444e3 until 2026-09-02."
    )
