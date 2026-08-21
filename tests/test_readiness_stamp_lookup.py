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


# --- the window class (the designed-but-unread field) -----------------------


def assert_step() -> str:
    doc = yaml.safe_load(WORKFLOW.read_text())
    for job in doc["jobs"].values():
        for step in (job.get("steps") or []):
            if "Assert live desktop" in str(step.get("name", "")):
                return step["run"]
    raise AssertionError("assert step not found")


def test_the_window_class_is_actually_read() -> None:
    """readiness.py carries it precisely so this check can exist.

    Its own words: "A CI VM sized just under the RAM threshold would show the
    not-enough-RAM screen and pass every check we currently run." app_id
    proves which frontend stamped and signal proves a surface reached the
    screen; neither tells the wizard from the too-small-VM screen.
    """
    assert re.search(r"STAMP_WINDOW=\$\(", code_of(assert_step())), (
        "the stamp's window field is written by every frontend and read by "
        "nothing; a RAM/CPU/UEFI window would pass the gate"
    )


def code_of(run: str) -> str:
    """Executable lines only. Comments and echo text name these classes for
    documentation, and matching those made the first version of these tests
    pass against a gate that had stopped checking anything."""
    out = []
    for line in run.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#") or stripped.startswith("echo "):
            continue
        out.append(line)
    return "\n".join(out)


def case_patterns(run: str) -> set[str]:
    """The patterns of every `case` arm, e.g. {"BootcRamWindow", ...}."""
    patterns = set()
    for line in code_of(run).splitlines():
        m = re.match(r"\s*([A-Za-z0-9_|\"*-]+)\)\s*$", line)
        if m:
            patterns.update(p.strip('"') for p in m.group(1).split("|"))
    return patterns


@pytest.mark.parametrize(
    "klass", ["BootcRamWindow", "BootcCpuWindow", "BootcUnsupportedWindow"]
)
def test_the_non_wizard_windows_are_rejected(klass) -> None:
    """Must appear as a `case` PATTERN, not merely somewhere in the text."""
    assert klass in case_patterns(assert_step()), (
        f"{klass} is not matched by any case arm, so a VM that presents it "
        "passes the gate"
    )


def test_the_check_is_a_denylist_not_an_allowlist() -> None:
    """The wizard class differs per frontend -- BootcWindow on gnome,
    ApplicationWindow on niri -- so an allowlist would fail green cells
    every time a fork renamed a class."""
    # Comments may name the per-frontend classes -- that is documentation.
    # What must not happen is a `case` PATTERN matching one.
    code = code_of(assert_step())
    assert "ApplicationWindow" not in code, (
        "the gate matches on a per-frontend wizard class, which makes it an "
        "allowlist that will fail cells when a fork renames one"
    )
    assert "BootcWindow" not in code, (
        "same, for gnome's wizard class"
    )
