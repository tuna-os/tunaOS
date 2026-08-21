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
