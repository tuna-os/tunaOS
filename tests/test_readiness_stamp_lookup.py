"""The gate must read the stamp where flatpak actually puts it.

Runs 63-68 of installer-smoke all failed with "running but never reported a
window". Every one was a false negative. Run 32445454947 settled it: the
installer's own log records

    readiness stamp written: /run/user/1000/tuna-installer-ready (BootcWindow)

-- a correct stamp, naming the wizard -- and a `find` across /run/user
located the file at

    /run/user/1000/.flatpak/org.bootcinstaller.Installer/xdg-run/
      tuna-installer-ready

Inside the sandbox $XDG_RUNTIME_DIR reads as /run/user/<uid>, but it is a
bind mount and the host path differs. The gate read only
/run/user/<uid>/app/<app-id>/ and /run/user/<uid>/, so it never saw the file.

What made this durable rather than obvious: flatpak still CREATES
app/<app-id>/, so listing it showed an empty directory, which reads as
confirmation that nothing was written rather than as a wrong path.

These tests pin all three read locations, because dropping the new one
silently restores a gate that fails on working installers.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "installer-smoke.yml"

# The layout current flatpak actually uses, measured in run 32445454947.
SANDBOX_HOST_PATH = "/run/user/*/.flatpak/${APP}/xdg-run/tuna-installer-ready"
# Older flatpak layout; kept because it costs nothing.
LEGACY_APP_PATH = "/run/user/*/app/${APP}/tuna-installer-ready"
# An unsandboxed frontend writes here directly.
UNSANDBOXED_PATH = "/run/user/*/tuna-installer-ready"


def stamp_read_line() -> str:
    for line in WORKFLOW.read_text().splitlines():
        if "STAMP=$(" in line and "tuna-installer-ready" in line:
            return line
    raise AssertionError("no stamp-reading line found in installer-smoke.yml")


def test_the_sandbox_host_path_is_read() -> None:
    """The regression: this is the only path the file is actually at."""
    assert SANDBOX_HOST_PATH in stamp_read_line(), (
        "the gate does not read /run/user/*/.flatpak/<app>/xdg-run/, which is "
        "where flatpak backs $XDG_RUNTIME_DIR -- runs 63-68 failed on working "
        "installers for exactly this reason"
    )


def test_the_legacy_and_unsandboxed_paths_are_still_read() -> None:
    line = stamp_read_line()
    assert LEGACY_APP_PATH in line
    assert UNSANDBOXED_PATH in line


def test_the_sandbox_path_is_read_first() -> None:
    """Newest layout first, so the common case does not depend on fallbacks."""
    line = stamp_read_line()
    assert line.index(SANDBOX_HOST_PATH) < line.index(LEGACY_APP_PATH)


def test_the_failure_branch_locates_a_misplaced_stamp() -> None:
    """A stamp outside all three reads is precisely the defect just fixed.

    Without this, the next path change reproduces the same multi-run hunt.
    """
    body = WORKFLOW.read_text()
    assert re.search(r"find /run/user -name tuna-installer-ready", body), (
        "the failure branch must search for the stamp, not just list the "
        "directories it already assumes are right"
    )


def test_the_failure_branch_lists_the_sandbox_dir() -> None:
    body = WORKFLOW.read_text()
    assert "/run/user/*/.flatpak/*/xdg-run/" in body


# ── The second copy of the same lookup ──────────────────────────────────────
# scripts/e2e-installer-gui-checks.sh is the ISO harness's version of this
# gate. It carried the pre-fix two-path lookup long after installer-smoke.yml
# was corrected, and nothing noticed, because the script resolved its
# e2e-assert.sh helper from the wrong directory: check() was undefined, every
# assertion was a no-op, and the harness reported bash's 127 as a failure
# COUNT on healthy and broken images alike. A gate that cannot pass or fail
# hides the bugs in itself, so both copies are pinned here together.
GUI_CHECKS = ROOT / "scripts" / "e2e-installer-gui-checks.sh"


def gui_stamp_lookup() -> str:
    """The `for d in ...; do` list the script iterates to find the stamp."""
    body = GUI_CHECKS.read_text()
    m = re.search(r"for d in\s*(.*?);\s*do", body, re.S)
    assert m, "no stamp lookup loop found in e2e-installer-gui-checks.sh"
    # Fold the line continuations so ordering can be compared as one string.
    return " ".join(m.group(1).split())


def _shell(path: str) -> str:
    """The pinned path as the shell script spells it (quoted expansion)."""
    return path.replace("${APP}", '"${APP}"')


def test_gui_gate_reads_the_sandbox_host_path() -> None:
    assert _shell(SANDBOX_HOST_PATH) in gui_stamp_lookup(), (
        "scripts/e2e-installer-gui-checks.sh does not read "
        "/run/user/*/.flatpak/<app>/xdg-run/ -- the same false negative "
        "installer-smoke.yml was already fixed for"
    )


def test_gui_gate_keeps_the_legacy_and_unsandboxed_paths() -> None:
    lookup = gui_stamp_lookup()
    assert _shell(LEGACY_APP_PATH) in lookup
    assert _shell(UNSANDBOXED_PATH) in lookup


def test_gui_gate_reads_the_sandbox_path_first() -> None:
    lookup = gui_stamp_lookup()
    assert lookup.index(_shell(SANDBOX_HOST_PATH)) < lookup.index(
        _shell(LEGACY_APP_PATH)
    )


def test_gui_gate_failure_branch_searches_for_a_misplaced_stamp() -> None:
    body = GUI_CHECKS.read_text()
    assert re.search(r"find /run/user -name tuna-installer-ready", body)
    assert "/run/user/*/.flatpak/*/xdg-run/" in body
