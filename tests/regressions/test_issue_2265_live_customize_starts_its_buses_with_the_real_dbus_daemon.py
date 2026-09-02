"""tunaOS#2265: the live customize must start its buses with the dbus-daemon
that ships, not the one a fake accepts.

What shipped: 886444e3 made `_start_bus` run
`dbus-daemon "$@" --fork --pidfile="$_pidfile"`. dbus-daemon has no
`--pidfile` option (only `--nopidfile`; the path is config-file syntax), so
the call is a usage error, exit 1, on a stderr the helper discards. The
system-bus call hid behind `|| true`; the session-bus call did not, and the
script runs under `set -eu`.

What was measured: every live-iso-bootc.yml run from that commit on ended
`live customize for skipjack-gnome: ... exit status 1` right after the
session-bus line (runs 32875192246, 33594824101). The last green run on the
same branch, 32829777966, is the commit before. The suite stayed green
because tests/test_a_failing_live_customize_fails_fast.py exercises the
helper against a fake bus that honoured the option the real binary rejects.

What this holds: the script's OWN `_start_bus`, run under `set -eu` against
the REAL dbus-daemon, starts a session bus that answers a method call and
leaves a pidfile naming a live process. No fake is involved on purpose; the
fake is what let this ship. Skipped, loudly, where dbus-daemon is absent.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "live-iso" / "common" / "src" / "customize-live.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("dbus-daemon") is None,
    reason="dbus-daemon is not installed; this test exists to run the real one",
)


def bus_helpers() -> str:
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index("\t_live_bus_pidfiles=()")
    end = text.index("\tmkdir -p /var/lib/dbus", start)
    block = text[start:end]
    assert "_start_bus" in block
    return "\n".join(line[1:] if line.startswith("\t") else line
                     for line in block.splitlines())


def run_session_bus(tmp_path: Path, helpers: str) -> subprocess.CompletedProcess:
    sock = tmp_path / "session-bus.sock"
    pidfile = tmp_path / "live-session-bus.pid"
    harness = tmp_path / "harness.sh"
    harness.write_text(
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        f"{helpers}\n"
        # Exactly the script's own two calls, the first tolerated the same way.
        f'_start_bus "{tmp_path}/live-system-bus.pid" --system || true\n'
        f'_start_bus "{pidfile}" --session --address="unix:path={sock}"\n'
        f'export DBUS_SESSION_BUS_ADDRESS="unix:path={sock}"\n'
        f'read -r _pid <"{pidfile}"\n'
        'kill -0 "$_pid"\n'
        "echo \"pid=$_pid\"\n"
        + (
            "dbus-send --session --dest=org.freedesktop.DBus --type=method_call "
            "--print-reply /org/freedesktop/DBus org.freedesktop.DBus.ListNames "
            ">/dev/null\n"
            if shutil.which("dbus-send") else ""
        )
    )
    return subprocess.run(["bash", str(harness)], capture_output=True, text=True,
                          timeout=20, env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})


def test_the_session_bus_starts_under_set_eu_with_the_real_daemon(tmp_path) -> None:
    proc = run_session_bus(tmp_path, bus_helpers())
    assert proc.returncode == 0, (
        "the customize's own _start_bus could not start a session bus with the "
        f"installed dbus-daemon (rc={proc.returncode}); this is the exit that "
        "killed every live-ISO build from 886444e3 to 2026-09-02\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
    assert "pid=" in proc.stdout, proc.stdout


def test_the_shipped_helper_fails_against_the_real_daemon(tmp_path) -> None:
    """Guard the guard: the tree that shipped #2265 must fail this file."""
    shipped = bus_helpers().replace(
        'dbus-daemon "$@" --fork --nopidfile --print-pid=3 3>"$_pidfile" >/dev/null 2>&1',
        'dbus-daemon "$@" --fork --pidfile="$_pidfile" >/dev/null 2>&1',
    )
    assert shipped != bus_helpers(), "the _start_bus line changed; update this mutation"
    proc = run_session_bus(tmp_path, shipped)
    assert proc.returncode != 0, (
        "the 886444e3 form of _start_bus started a bus with this dbus-daemon, so "
        "the real binary has grown a --pidfile option and this test no longer "
        "reproduces the incident; re-read #2265 before deleting it"
    )
