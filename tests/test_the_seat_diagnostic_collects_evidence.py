"""Why four of five desktops fail, and the one line that will settle it.

Run 32691426582's xfce leg produced the first compositor stderr this project
has ever captured, and it points somewhere nobody was looking:

    INFO  xfwl4::backend::udev: Using renderD128 as primary GPU
    INFO  xfwl4::core::state: Listening on wayland socket name="wayland-1"
    WARN  smithay::backend::drm::device::fd: Unable to become drm master,
          assuming unprivileged mode
    INFO  smithay::backend::egl::display: EGL Initialized
    WARN  xfwl4::backend::udev::device: failed to initialize gpu err=NoRenderNode
    ERROR xfwl4: Failed to initialize primary GPU node

NoRenderNode for a device it had already selected and NAMED. /dev/dri in the
same guest confirms the node is there and world readable:

    crw-rw----+ 1 root video  226,   1 card1
    crw-rw-rw-. 1 root render 226, 128 renderD128

The unifying fact is in loginctl, from the same capture:

    SESSION  UID USER     SEAT LEADER CLASS   TTY IDLE SINCE
          2 1000 liveuser -    1273   manager -   no   -
         24 1000 liveuser -    3469   user    -   no   -

EVERY session has an empty SEAT and an empty TTY. logind hands DRM master to
the active session ON A SEAT; with no seat there is no DRM master, which is
precisely what the compositor reports one line before it dies. It also fits
the matrix: gnome -- the only flavor that works -- is the only one on gdm
rather than greetd.

So "cosmic, niri, xfwl4 and kde need a DRM render node" is contradicted by the
render node being present and named. WHY the seat is missing is NOT settled,
and this file does not encode a guess about it. It pins the DIAGNOSTIC that
will settle it: greetd's PAM stack, and per-session Seat/VTNr/Active.

The payload is asserted by RUNNING it with loginctl shimmed, because its trap
is quoting -- an `awk "{print \\$1}"` nested inside a single-quoted ssh
argument inside a YAML block scalar. A grep for "loginctl" in the workflow
would pass on a loop that silently iterates over nothing, which is the exact
defect class this branch keeps finding.
"""
from __future__ import annotations

import os
import re
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "installer-smoke.yml"


def capture_step() -> str:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for s in doc["jobs"]["smoke"]["steps"]:
        if "Capture installer stderr" in s.get("name", ""):
            return s["run"]
    raise AssertionError("capture step not found")


def seat_payload() -> str:
    """The inner ssh command, unwrapped so it can be executed directly."""
    body = capture_step()
    m = re.search(
        r"\$SSH 'echo \"-- /etc/pam\.d/greetd --\".*?' 2>/dev/null \|\| true", body, re.S
    )
    assert m, "the seat diagnostic is not in the capture step"
    inner = m.group(0)[len("$SSH '") : -len("' 2>/dev/null || true")]
    return inner.replace("\\\n", "\n")


def test_the_capture_step_is_valid_shell(tmp_path):
    f = tmp_path / "cap.sh"
    f.write_text(capture_step(), encoding="utf-8")
    proc = subprocess.run(["bash", "-n", str(f)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def _run_payload(tmp_path, sessions: str):
    shims = tmp_path / "bin"
    shims.mkdir()
    (shims / "loginctl").write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        f"  list-sessions) {sessions};;\n"
        '  show-session)  echo "Id=$2"; echo "Seat="; echo "VTNr=0"; echo "Active=no";;\n'
        '  list-seats)    echo "seat0";;\n'
        "esac\n",
        encoding="utf-8",
    )
    (shims / "loginctl").chmod(0o755)
    script = tmp_path / "p.sh"
    script.write_text(seat_payload(), encoding="utf-8")
    env = dict(os.environ, PATH=f"{shims}:/usr/bin:/bin")
    return subprocess.run(
        ["bash", str(script)], capture_output=True, text=True, env=env
    )


def test_the_payload_actually_iterates_sessions(tmp_path):
    """The quoting trap: a loop that reads no session ids prints no seats."""
    proc = _run_payload(
        tmp_path, 'echo "      2 1000 liveuser -    1273   manager -   no   -"'
    )
    assert proc.returncode == 0, proc.stderr
    assert "session 2:" in proc.stdout, proc.stdout
    # The three fields that decide it must all be reported.
    assert "Seat=" in proc.stdout, proc.stdout
    assert "VTNr=" in proc.stdout, proc.stdout
    assert "Active=" in proc.stdout, proc.stdout


def test_the_payload_reads_the_pam_stack(tmp_path):
    """greetd's PAM config is the leading candidate; it must be printed, and
    its absence must be stated rather than rendering as blank."""
    proc = _run_payload(tmp_path, "true")
    assert "/etc/pam.d/greetd" in proc.stdout, proc.stdout
    assert "(absent)" in proc.stdout, proc.stdout


def test_the_reasoning_is_recorded_next_to_the_diagnostic():
    """The next reader must not have to re-derive why seats are suspected."""
    body = capture_step()
    assert "NoRenderNode" in body
    assert "DRM master" in body
    # And it must NOT assert a cause it has not measured.
    assert "pam_systemd" in body, "the candidate should be named as a candidate"
    assert "NOT established" in body or "not guessed" in body, (
        "the comment must mark the cause as unestablished; this branch has "
        "been wrong five times by asserting one"
    )
