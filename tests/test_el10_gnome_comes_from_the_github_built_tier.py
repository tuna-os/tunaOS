"""GNOME on EL10 comes from tunaOS's own factory tier. Not from a COPR.

Maintainer directives, 2026-09-03: nothing below GNOME 50 ships, and "no more
COPR -- we build in GitHub like utah-packages". tuna-os/tunaos-packages already
builds the GNOME 50 stack for CentOS Stream 10 in GitHub Actions (mock,
build-order-gnome50) and publishes it, signed, at
repo.tunaos.org/gnome50/10-stream-x86_64: 466 binary names measured
2026-09-03, gnome-shell 50.0-3.el10, mutter 50.0-4, gtk4 4.22.1, glib2
2.88.0-4, gnome50-el10-compat, selinux-policy 43. That is the source; the
`jreilly1821/c10s-gnome-50` COPR entries are gone from gnome.yaml.

Two facts the manifest and build-config must keep agreeing on:

  * the tier is x86_64 only (the aarch64 path 404s), and the floor is 50, so
    an arm64 GNOME leg on EL10 would be the base's 49 -- not allowed to ship.
    The EL10 gnome flavors are pinned to amd64 until the tier grows an
    aarch64 index, exactly as xfce's tier pins xfce and as hummingbird's
    desktops are pinned (tests/test_hummingbird_arm64_honesty.py). Whoever
    re-adds linux/arm64 deletes the variant from PINNED below in the same
    change -- the reviewable claim that the aarch64 tier now exists.
  * install-desktop.sh honours the section-level `pre_install:` the tier
    needs (glib2/fontconfig/gjs/gobject-introspection first, then
    gnome50-el10-compat), and runs it before the group install.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
GNOME = ROOT / "manifests" / "desktops" / "gnome.yaml"
CONFIG = ROOT / ".github" / "build-config.yml"
SCRIPT = ROOT / "build_scripts" / "desktop" / "install-desktop.sh"
POLICY = ROOT / "PACKAGE-SOURCING.md"

TIER = "https://repo.tunaos.org/gnome50/10-stream-x86_64/"
EL10_VARIANTS = ("yellowfin", "albacore", "skipjack")
# EL10 variants whose gnome cells are amd64-only until the tier has aarch64.
PINNED = {"yellowfin", "albacore", "skipjack"}
AMD64 = ["linux/amd64", "linux/amd64/v2"]


@pytest.fixture(scope="module")
def el10() -> dict:
    return yaml.safe_load(GNOME.read_text())["packages"]["el10"]


@pytest.fixture(scope="module")
def variants() -> dict:
    cfg = yaml.safe_load(CONFIG.read_text())
    return {v["id"]: v for v in cfg["variants"]}


# ── The source ───────────────────────────────────────────────────────────────


def test_no_copr_in_the_el10_gnome_section(el10):
    assert "copr" not in el10, (
        "a COPR is back as the EL10 GNOME source; the factory tier is the source"
    )


def test_the_tier_is_declared_at_priority_one(el10):
    repos = el10.get("repos") or []
    tier = [r for r in repos if r.get("baseurl") == TIER]
    assert tier, f"{TIER} is not declared in gnome.yaml's el10 repos"
    assert tier[0].get("priority") == 1, (
        "the tier must sit at priority 1 so its gnome-shell 50 beats EL 10.2's own 49 for every name it carries"
    )
    assert not tier[0].get("unsigned"), (
        "the https tier is signed; unsigned is for digest-pinned file:// only"
    )


def test_the_pre_install_moves_the_platform_before_the_stack(el10):
    pre = el10.get("pre_install") or []
    joined = " ".join(pre)
    for pkg in ("glib2", "fontconfig", "gobject-introspection", "gjs"):
        assert pkg in joined, f"{pkg} is not upgraded before the group install"
    assert "gnome50-el10-compat" in joined
    assert joined.index("glib2") < joined.index("gnome50-el10-compat"), (
        "glib2 must move first; the compat package assumes the new GLib"
    )


def test_nothing_in_the_tree_still_names_the_gnome_copr():
    offenders = []
    for path in list((ROOT / "manifests").rglob("*.yaml")) + list(
        (ROOT / "build_scripts").rglob("*.sh")
    ):
        text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if "c10s-gnome-5" in line and not line.lstrip().startswith("#"):
                offenders.append(f"{path.relative_to(ROOT)}: {line.strip()}")
    assert not offenders, "\n".join(offenders)


# ── The script honours what the manifest declares ────────────────────────────


def test_section_pre_install_runs_before_the_group_install():
    src = SCRIPT.read_text()
    assert ".packages.${_TD_OS}.pre_install[]" in src, (
        "pre_install is declared by the manifest and read by nothing"
    )
    pre = src.index("# Section-level pre_install")
    groups = src.index("\t# Install groups\n")
    assert pre < groups


def test_the_script_no_longer_treats_a_copr_as_a_stack_source():
    src = SCRIPT.read_text()
    assert "extra_repos" not in src
    assert "_TD_COPR_LIVE" not in src


# ── Architecture honesty ─────────────────────────────────────────────────────


@pytest.mark.parametrize("variant", sorted(PINNED))
def test_el10_gnome_is_amd64_only_until_the_tier_has_aarch64(variants, variant):
    flavors = {f["id"]: f for f in variants[variant]["flavors"]}
    for fid in ("gnome", "gnome-hwe"):
        assert flavors[fid].get("platforms") == AMD64, (
            f"{variant}:{fid} declares {flavors[fid].get('platforms', variants[variant]['platforms'])}; "
            "re-adding arm64 requires an aarch64 index at repo.tunaos.org/gnome50/ and removing the "
            "variant from PINNED in the same change"
        )
    asahi = flavors.get("gnome-asahi")
    if asahi is not None:
        assert asahi.get("build_image") is False, (
            f"{variant}:gnome-asahi is the arm64 leg of gnome and cannot build while gnome is amd64-only"
        )


def test_the_other_desktops_keep_their_arches(variants):
    """The pin is about the GNOME tier, not the variant: kde/cosmic/niri and
    base are untouched."""
    for variant in PINNED:
        flavors = {f["id"]: f for f in variants[variant]["flavors"]}
        assert "platforms" not in flavors["base"]
        assert "platforms" not in flavors["kde"]


# ── The policy record ────────────────────────────────────────────────────────


def test_the_sourcing_policy_records_the_retirement():
    text = POLICY.read_text()
    assert re.search(r"~~COPR `jreilly1821/c10s-gnome-50-fresh`", text), (
        "PACKAGE-SOURCING.md must list the GNOME 50 COPR as migrated, with the tier that replaced it"
    )
    assert "gnome50/10-stream-x86_64" in text
