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


def test_the_journal_capture_covers_every_display_manager():
    """gnome and kde are the two top-priority flavors and the two the capture
    could not see.

    The journal line named only `greetd` and `cosmic-greeter`. cosmic, niri and
    xfce all run under greetd and additionally wrap their session command in
    `systemd-cat -t tunaos-live-session`, so their compositor stderr is
    reachable two ways. gnome and kde do neither: gnome autologins through gdm
    and kde through plasmalogin, so for those two the capture named no unit at
    all and the session's own words went unrecorded.

    That is why kde's only diagnosis on file is a second-hand
    `plasmalogin-helper exited with 5` from run 30234237855, attributed to a
    render-node theory the xfce evidence has since contradicted.
    """
    body = capture_step()
    m = re.search(r"journalctl (-u \S+ )+--no-pager", body)
    assert m, "no display-manager journalctl invocation found in the capture step"
    units = set(re.findall(r"-u (\S+)", m.group(0)))
    for dm in ("greetd", "cosmic-greeter", "plasmalogin", "gdm"):
        assert dm in units, f"{dm} is not captured; units are {sorted(units)}"
    # systemd-logind is the one that survives the session it describes.
    # `loginctl` is read minutes after the compositor died and greetd gave up,
    # so it reports whatever is left -- the SSH login and the user manager,
    # both of which legitimately have no seat. logind's journal records "New
    # session N of user ..." WITH the seat and VT at the moment the session was
    # created, which is the only post-mortem-proof answer to whether the
    # compositor's session was ever seated.
    assert "systemd-logind" in units, (
        "systemd-logind is not captured; without it the seat question can only "
        "be answered from post-mortem loginctl output, which cannot see the "
        f"session that already exited. units are {sorted(units)}"
    )


# ── The installer's own log, looked for under one flavor's app id ───────────
#
# The capture step calls this file "the thing that answers it directly": it
# records do_activate being called, which window class was constructed, "Main
# window created", and any traceback. Its own comment says "running but never
# reported a window" has stayed undiagnosable across runs 63-66 without it.
#
# It was read from ~/.var/app/org.bootcinstaller.Installer/... — a hardcoded
# app id that only GNOME uses. kde runs org.tunaos.InstallerKde, and
# cosmic/niri/xfce their own. So on four of five flavors the step printed
#
#     (no installer-debug.log found)
#
# and nobody noticed, because that string reads like a fact about the guest
# rather than a fact about the path. kde run 32704425971 is the proof: the
# frontend launched (org.tunaos.InstallerKde asserted OK), the readiness stamp
# was absent, and the one file that would say why was sought under gnome's id.

INSTALLER_APPS = [
    "org.bootcinstaller.Installer",
    "org.tunaos.InstallerKde",
    "org.tunaos.InstallerCosmic",
    "org.tunaos.InstallerNiri",
    "org.tunaos.InstallerXfce",
]


def debug_log_payload() -> str:
    body = capture_step()
    m = re.search(r"\$SSH 'found=0;.*?' 2>/dev/null \|\| true", body, re.S)
    assert m, "the installer-debug.log capture is not in the expected shape"
    return m.group(0)[len("$SSH '") : -len("' 2>/dev/null || true")]


def test_the_debug_log_payload_is_valid_shell(tmp_path):
    f = tmp_path / "p.sh"
    f.write_text(debug_log_payload(), encoding="utf-8")
    proc = subprocess.run(["bash", "-n", str(f)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("app", INSTALLER_APPS)
def test_every_frontend_app_id_is_searched(tmp_path, app):
    """Run it with only THIS flavor's log present. All five must be found."""
    import os as _os

    home = tmp_path / app
    d = home / ".var/app" / app / "cache/bootc-installer"
    d.mkdir(parents=True)
    (d / "installer-debug.log").write_text("do_activate called\n", encoding="utf-8")

    script = tmp_path / f"p-{app}.sh"
    script.write_text(debug_log_payload(), encoding="utf-8")
    proc = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        env=dict(_os.environ, HOME=str(home)),
    )
    assert proc.returncode == 0, proc.stderr
    assert "do_activate called" in proc.stdout, (
        f"{app}'s installer-debug.log was not found; output was {proc.stdout!r}"
    )
    assert "no installer-debug.log" not in proc.stdout, proc.stdout


def test_a_genuinely_absent_log_says_what_is_there_instead(tmp_path):
    """"Not found" must be distinguishable from "looked in the wrong place"."""
    import os as _os

    home = tmp_path / "empty"
    (home / ".var/app/org.tunaos.InstallerNiri").mkdir(parents=True)
    script = tmp_path / "p.sh"
    script.write_text(debug_log_payload(), encoding="utf-8")
    proc = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        env=dict(_os.environ, HOME=str(home)),
    )
    assert proc.returncode == 0, proc.stderr
    assert "no installer-debug.log under any known app id" in proc.stdout
    # The listing is the half that makes the negative result actionable.
    assert "org.tunaos.InstallerNiri" in proc.stdout, proc.stdout
