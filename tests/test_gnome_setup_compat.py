"""The gnome-setup compat set for GTK before 4.16 (gurnard:pantheon).

GtkBuilder before GTK 4.16 rejects <constant translatable="yes">, and
gnome-setup aborted on its welcome page on Ubuntu 24.04 (run 45931354235).
The owner approved one compat patch for that cell only. These tests hold the
gate (the cell, not the desktop), the two checks that fail loudly, and the
msgids that the patch must keep.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPAT = ROOT / "installer-medium/frontends/gnome-setup/compat"
PATCHES = sorted((COMPAT / "gtk-4.14").glob("*.patch"))


def run(*args: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(a) for a in args], capture_output=True, text=True, check=False)


@pytest.mark.parametrize(
    ("cell", "want"),
    [
        ("gurnard:pantheon", "gtk-4.14"),
        ("bonito:gnome", ""),
        ("albacore:gnome", ""),
        ("bonito:tuna", ""),
        # The gate is the cell: Tuna on the same Ubuntu base is not listed.
        ("gurnard:tuna", ""),
    ],
)
def test_the_compat_set_is_chosen_by_cell(cell: str, want: str) -> None:
    proc = run(COMPAT / "for-cell", cell)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == want


def fake_root(tmp_path: Path, gtk: str | None, marker: str | None, setup: bool = True) -> Path:
    root = tmp_path / "root"
    (root / "usr/bin").mkdir(parents=True)
    (root / "usr/lib/x86_64-linux-gnu").mkdir(parents=True)
    if setup:
        (root / "usr/bin/gnome-setup").write_text("")
        (root / "usr/bin/gnome-setup").chmod(0o755)
    if gtk:
        (root / f"usr/lib/x86_64-linux-gnu/libgtk-4.so.1.{gtk}").write_text("")
    if marker:
        (root / "usr/share/medium-live").mkdir(parents=True)
        (root / "usr/share/medium-live/gnome-setup-compat").write_text(marker + "\n")
    return root


@pytest.mark.parametrize(
    ("gtk", "marker", "setup", "ok"),
    [
        ("1400.5", "gtk-4.14", True, True),  # gurnard:pantheon today
        ("1600.0", "gtk-4.14", True, False),  # retire the compat set
        ("1400.5", None, True, False),  # aborts on the welcome page
        ("1800.3", None, True, True),  # GNOME and Tuna cells
        ("1400.5", None, False, True),  # no gnome-setup in this image
    ],
)
def test_the_live_image_checks_the_gtk_of_the_cell(tmp_path, gtk, marker, setup, ok) -> None:
    proc = run("bash", COMPAT / "check-target-gtk", fake_root(tmp_path, gtk, marker, setup))
    assert (proc.returncode == 0) == ok, proc.stdout + proc.stderr
    if not ok:
        assert "check-target-gtk:" in proc.stderr


def test_the_build_check_finds_a_translatable_constant(tmp_path) -> None:
    """gtk4-rs embeds the compiled templates in the binary: the check reads it."""
    binary = tmp_path / "usr/bin/gnome-setup"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(
        b'\x7fELF\x00<template class="SetupWelcomePage"><constant translatable="yes">Welcome</constant>\x00'
    )
    assert run(COMPAT / "check-ui", tmp_path).returncode == 1
    binary.write_bytes(
        b'\x7fELF\x00<template class="SetupWelcomePage"><constant type="gchararray">Welcome</constant>\x00'
    )
    assert run(COMPAT / "check-ui", tmp_path).returncode == 0
    assert run(COMPAT / "check-ui", tmp_path / "empty").returncode == 1


def test_the_patch_keeps_every_msgid_and_translates_in_code() -> None:
    """Each _("...") the patch takes out of a closure comes back as the same
    "..." string, so translations keep their msgid, and apply_osinfo (which
    the three closures call) runs it through gettext."""
    assert len(PATCHES) == 1
    text = PATCHES[0].read_text()
    literal = re.compile(r'"(?:[^"\\]|\\.)*"')
    removed = [
        m
        for line in text.splitlines()
        if line.startswith("-") and not line.startswith("---")
        for m in re.findall(r'_\(("(?:[^"\\]|\\.)*")\)', line)
    ]
    added = [
        m
        for line in text.splitlines()
        if line.startswith("+") and not line.startswith("+++") and ".blp" not in line
        for m in literal.findall(line)
    ]
    assert removed, "the patch converts no closure argument"
    for msgid in removed:
        assert msgid in added, msgid
    assert "gettext(string)" in text
    assert "string.is_empty()" in text  # gettext("") returns the catalog header


def test_the_medium_build_passes_the_compat_set() -> None:
    live = (ROOT / "installer-medium/Containerfile.live").read_text()
    assert "ARG GNOME_SETUP_COMPAT=" in live
    assert "check-target-gtk" in live[live.index("FROM ${SOURCE_IMAGE}") :]
    build = (ROOT / "installer-medium/build-live-image.sh").read_text()
    assert '--build-arg "GNOME_SETUP_COMPAT=${GNOME_SETUP_COMPAT}"' in build
    recipe = (ROOT / "installer-medium/frontends/gnome/build.sh").read_text()
    assert "compat/check-ui" in recipe and "gnome-setup-compat" in recipe
