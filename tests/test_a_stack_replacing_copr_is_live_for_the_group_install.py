"""A `packages: []` COPR entry is enabled BEFORE the group install, not after.

manifests/desktops/gnome.yaml has said "GNOME 50 on EL10" since the manifest
refactor. The published images said otherwise -- measured 2026-09-03 from the
`.packages` artifacts: yellowfin gnome-shell 49.5, albacore 49.4, skipjack
49.5, all from AlmaLinux 10.2's own AppStream. The build log for yellowfin
gnome (run 33728906010) shows exactly why:

    + dnf -y copr enable jreilly1821/c10s-gnome-50-fresh
    + dnf -y copr disable jreilly1821/c10s-gnome-50-fresh
    Enabled jreilly1821/c10s-gnome-50-fresh (no packages listed -- repo
    enabled for a later --enablerepo)
    ...
    Adding versionlock on: gnome-shell-0:49.5-13.el10.alma.12.*

The COPR block ran after the groups, enabled the repo and disabled it in the
same breath, and nothing ever named it in --enablerepo. The manifest's
`extra_repos:` and `pre_install:` keys were read by no code at all. So the
group install resolved the base's GNOME 49, and the version lock pinned it.

install-desktop.sh now treats `packages: []` as what the manifest meant: a
repo the groups and packages must resolve against. These tests pin the shape
of that fix in the script and the shape of the manifest that relies on it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "build_scripts" / "desktop" / "install-desktop.sh"
GNOME = ROOT / "manifests" / "desktops" / "gnome.yaml"


@pytest.fixture(scope="module")
def src() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _index(src: str, needle: str) -> int:
    assert src.count(needle) == 1, f"expected exactly one {needle!r}, found {src.count(needle)}"
    return src.index(needle)


# ── The script reads every key the manifest writes ───────────────────────────


def test_extra_repos_are_read(src):
    assert ".copr[$i].extra_repos[]" in src


def test_copr_pre_install_is_read_and_run(src):
    assert ".copr[$i].pre_install[]" in src
    assert 'eval "${_TD_CMD}"' in src


def test_section_pre_install_is_read_and_run(src):
    assert ".packages.${_TD_OS}.pre_install[]" in src


# ── The order: enable, pre_install, groups, packages, disable, lock ─────────


def test_the_stack_replacing_copr_goes_live_before_the_group_install(src):
    live = _index(src, "# ── COPR repos that replace part of the base")
    groups = _index(src, "\t# Install groups\n")
    assert live < groups, "the stack-replacing COPR block must precede the group install"


def test_pre_install_runs_before_the_group_install(src):
    pre = _index(src, "# Section-level pre_install")
    groups = _index(src, "\t# Install groups\n")
    assert pre < groups


def test_the_live_repos_are_disabled_only_before_the_version_locks(src):
    disable = _index(src, "The stack-replacing COPRs have done their job")
    packages = _index(src, "\t# Install packages\n")
    locks = _index(src, "# ── Version locks")
    assert packages < disable < locks


def test_the_enable_only_idiom_that_named_no_later_block_is_gone(src):
    assert "repo enabled for a later --enablerepo" not in src, (
        "the old idiom enabled the repo, disabled it at once, and nothing ever "
        "used it -- that is how EL10 shipped GNOME 49 under a GNOME 50 manifest"
    )


def test_an_add_on_copr_entry_keeps_the_old_shape(src):
    """niri-git, wlroots-epel and cosmic-epel list packages; they must still be
    enabled, disabled at once, and installed with --enablerepo, unchanged."""
    addon = src[_index(src, "# COPR add-on packages (EL10 primarily)") :]
    addon = addon[: addon.index("# Optional packages")]
    assert 'dnf -y copr enable "${_TD_COPR_REPO}"' in addon
    assert 'dnf -y copr disable "${_TD_COPR_REPO}" || true' in addon
    assert '--enablerepo="${_TD_REPO_ID}"' in addon


def test_an_unset_extra_repos_does_not_trip_set_u(src):
    """The script runs under `set -u`; expanding an empty array by name is an
    error on bash < 4.4 and a habit worth not relying on at all."""
    assert '${_TD_COPR_EXTRA[@]+"${_TD_COPR_EXTRA[@]}"}' in src
    assert '${_TD_COPR_LIVE[@]+"${_TD_COPR_LIVE[@]}"}' in src


# ── The manifest relies on exactly this ─────────────────────────────────────


def test_gnome_el10_declares_a_stack_replacing_copr_with_the_gnome_50_stack():
    doc = yaml.safe_load(GNOME.read_text())
    entries = doc["packages"]["el10"]["copr"]
    stack = [e for e in entries if e.get("packages") == []]
    assert len(stack) == 1, (
        "gnome.yaml's el10 section should carry exactly one stack-replacing copr entry"
    )
    entry = stack[0]
    assert "c10s-gnome-50" in entry["repo"]
    assert any("c10s-gnome-50" in r for r in entry.get("extra_repos", []))
    pre = " ".join(entry.get("pre_install", []))
    assert "gnome50-el10-compat" in pre, (
        "the compat package that lets GNOME 50 sit on EL10 is not installed"
    )
    assert "glib2" in pre, "GNOME 50 needs the COPR glib2 before the group install"


def test_gnome_el10_locks_the_stack_it_installs():
    doc = yaml.safe_load(GNOME.read_text())
    locks = set(doc["versionlock"])
    for pkg in ("gnome-shell", "mutter", "gtk4", "libadwaita", "glib2"):
        assert pkg in locks, (
            f"{pkg} is not version-locked; the base's 49 could come back on the next dnf upgrade"
        )


def test_the_manifest_states_the_floor_the_fix_serves():
    doc = yaml.safe_load(GNOME.read_text())
    assert doc.get("minimum_version") == 50


def test_the_script_documents_the_measurement():
    """The comment must keep the numbers that justified the change."""
    text = SCRIPT.read_text()
    assert re.search(r"yellowfin 49\.5, albacore 49\.4, skipjack 49\.5", text)
