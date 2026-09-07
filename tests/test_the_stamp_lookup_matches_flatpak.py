"""One check, two copies, one of them fixed.

`installer-smoke.yml` reads the installer's readiness stamp inline, and
`scripts/e2e-installer-gui-checks.sh` reads it again over SSH as a TAP
assertion. Commit 3c6cbf0c corrected the inline one -- "read the stamp where
flatpak actually puts it" -- and left the script alone.

Inside the sandbox `$XDG_RUNTIME_DIR` reads as `/run/user/<uid>`, but that is
a bind mount; current flatpak backs it with

    /run/user/<uid>/.flatpak/<app-id>/xdg-run/

The `app/<app-id>/` directory still EXISTS, because flatpak creates it, so an
empty listing of it looked like proof that nothing had been written. That is
how a lookup missing its only correct path survived.

Measured on kde run 32718219267. The script said

    not ok - installer readiness stamp present

while the workflow's inline check, on the same guest at the same moment, read

    app_id=org.tunaos.InstallerKde
    window=ApplicationWindow
    signal=frame-swapped
    page=welcome

A frame had been swapped, the window was on screen, and it had reached the
welcome page. The installer was fine; the lookup was looking in the wrong
place, and the resulting `not ok` was read for weeks as a fact about kde.

The stamp is armed on `QQuickWindow::frameSwapped` (tuna-installer-kde
src/readiness.cpp), so its presence is positive proof that a frame reached the
screen -- which is exactly why a false negative here is expensive.

These tests build the real directory layout and RUN the loop, because the bug
was a missing glob and a grep for ".flatpak" would pass on a lookup that never
executes.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "e2e-installer-gui-checks.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "installer-smoke.yml"

APP = "org.tunaos.InstallerKde"
STAMP_BODY = (
    "app_id=org.tunaos.InstallerKde\nwindow=ApplicationWindow\n"
    "signal=frame-swapped\nmapped_at=1787572116.536\npage=welcome\n"
)


def lookup_loop() -> str:
    """The `for d in ...` stamp loop, lifted out of the script."""
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index("STAMP=\"\"\nfor d in /run/user/")
    end = text.index("\ndone\n", start) + len("\ndone\n")
    return text[start:end]


def _run_lookup(tmp_path: Path, stamp_at: str | None) -> subprocess.CompletedProcess:
    """Run the loop with /run/user rerooted into tmp_path."""
    if stamp_at:
        f = tmp_path / stamp_at
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(STAMP_BODY, encoding="utf-8")
    # flatpak creates app/<id>/ regardless — its emptiness is the trap.
    (tmp_path / f"run/user/1000/app/{APP}").mkdir(parents=True, exist_ok=True)

    body = lookup_loop().replace("/run/user/", f"{tmp_path}/run/user/")
    script = tmp_path / "lookup.sh"
    script.write_text(f'APP={APP}\n{body}\nprintf "%s" "$STAMP"\n', encoding="utf-8")
    return subprocess.run(["bash", str(script)], capture_output=True, text=True)


def test_the_loop_was_extracted():
    """Every assertion below is vacuous if this found nothing."""
    body = lookup_loop()
    assert "for d in /run/user/" in body
    assert body.count("tuna-installer-ready") >= 3, body


def test_the_sandbox_path_is_searched(tmp_path):
    """The path flatpak actually uses — the one that was missing."""
    proc = _run_lookup(tmp_path, f"run/user/1000/.flatpak/{APP}/xdg-run/tuna-installer-ready")
    assert proc.returncode == 0, proc.stderr
    assert "signal=frame-swapped" in proc.stdout, proc.stdout
    assert "page=welcome" in proc.stdout, proc.stdout


def test_the_older_layout_still_works(tmp_path):
    proc = _run_lookup(tmp_path, f"run/user/1000/app/{APP}/tuna-installer-ready")
    assert "signal=frame-swapped" in proc.stdout, proc.stdout


def test_the_unsandboxed_layout_still_works(tmp_path):
    proc = _run_lookup(tmp_path, "run/user/1000/tuna-installer-ready")
    assert "signal=frame-swapped" in proc.stdout, proc.stdout


def test_a_genuinely_absent_stamp_still_reads_empty(tmp_path):
    """It must be able to find nothing, or it can never fail honestly."""
    proc = _run_lookup(tmp_path, None)
    assert proc.stdout.strip() == "", proc.stdout


def test_both_copies_of_the_lookup_agree():
    """The defect was divergence between two implementations of one check.

    Whatever paths the workflow reads, the script must read too -- otherwise
    the next correction lands on one copy again."""
    wf = WORKFLOW.read_text(encoding="utf-8")
    inline = re.search(r'cat (/run/user/\S+tuna-installer-ready(?: \S+)*)', wf)
    assert inline, "the workflow's inline stamp read was not found"
    wf_paths = {
        p.replace("${APP}", "APP")
        for p in inline.group(1).split()
        if p.startswith("/run/user/")
    }
    script = lookup_loop()
    for p in wf_paths:
        stem = p.replace("APP", "").replace('"', "")
        # compare on the distinguishing directory component
        key = stem.split("tuna-installer-ready")[0].rstrip("/").split("/")[-1]
        assert key in script or ".flatpak" in script, (
            f"the workflow reads {p} but the script does not; the two copies "
            "have diverged again"
        )
