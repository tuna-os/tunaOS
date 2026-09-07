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

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
GNOME = ROOT / "manifests" / "desktops" / "gnome.yaml"
CONFIG = ROOT / ".github" / "build-config.yml"
SCRIPT = ROOT / "build_scripts" / "desktop" / "install-desktop.sh"
POLICY = ROOT / "PACKAGE-SOURCING.md"
IMAGE_VERSIONS = ROOT / "image-versions.yaml"
REGISTRY_MAP = ROOT / "registry-map.yaml"
RESOLVE = ROOT / "scripts" / "resolve-image.sh"
INNER = ROOT / "scripts" / "build-image-inner.sh"
CONTAINERFILE = ROOT / "Containerfile.el10"

# One string in four places: the image-versions.yaml pin, the registry-map
# entry, the resolve-image.sh role, and the /run path Containerfile.el10
# mounts at -- which is what gnome.yaml's baseurl names. The nightly pin
# checker's FILE_REPO_RE turns file:///run/NAME back into the pin called NAME,
# so renaming one and not the others is an unresolvable pin, not a fallback.
PIN = "gnome50-el10-packages"
IMAGE = "ghcr.io/tuna-os/tunaos-packages"
TAG = "gnome50-el10-x86_64"
MOUNT = f"/run/{PIN}"
TIER = f"file://{MOUNT}"
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
    assert tier[0].get("unsigned") is True, (
        "the repository is bind-mounted out of an image pinned by digest; the "
        "digest is the signature, and install-desktop.sh allows unsigned only "
        "for a file:// baseurl"
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
            "re-adding arm64 requires an aarch64 cell in tunaos-packages and removing the "
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
    assert f"{IMAGE}:{TAG}" in text, (
        "the row must name the image that replaced the COPR, not just say a tier did"
    )


# ── The pin, and the plumbing that carries it ────────────────────────────────


@pytest.fixture(scope="module")
def pin() -> dict:
    images = yaml.safe_load(IMAGE_VERSIONS.read_text())["images"]
    by_name = {i["name"]: i for i in images}
    assert PIN in by_name, f"image-versions.yaml has no {PIN} pin"
    return by_name[PIN]


def test_the_pin_is_a_digest_on_the_factory_image(pin):
    assert pin["image"] == IMAGE
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", pin["digest"]), (
        f"{PIN} is not pinned to a digest: {pin.get('digest')!r}"
    )
    assert pin.get("tag") == TAG, (
        "Renovate's image-versions block matches `name/image/tag/digest` in "
        "that order; without the tag the digest is never bumped, and the tag "
        "is what says which build chain published it"
    )


def test_registry_map_names_it():
    images = yaml.safe_load(REGISTRY_MAP.read_text())["images"]
    assert images[PIN]["path"] == IMAGE.split("/", 1)[1]
    assert images[PIN]["registry"] == "ghcr"


def test_resolve_image_has_a_role_for_it(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    yq = bindir / "yq"
    yq.write_text(
        "#!/usr/bin/env bash\n"
        f'case "$*" in *{PIN}*) echo sha256:{"cd" * 32} ;; '
        '*) echo unexpected-query >&2; exit 1 ;; esac\n'
    )
    yq.chmod(yq.stat().st_mode | stat.S_IEXEC)
    out = subprocess.run(
        ["bash", str(RESOLVE), "yellowfin", PIN],
        capture_output=True, text=True, cwd=ROOT,
        env={**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "YQ": str(yq)},
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == f"{IMAGE}@sha256:{'cd' * 32}"


def test_an_unknown_role_still_lists_this_one():
    """The error message is how the next person finds the role; one that
    resolves but is not named there is a role nobody discovers."""
    out = subprocess.run(
        ["bash", str(RESOLVE), "yellowfin", "no-such-role"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert out.returncode != 0
    assert PIN in out.stderr


def test_the_build_engine_passes_the_ref_as_a_build_arg():
    text = INNER.read_text()
    assert f'select(.name == "{PIN}") | .digest' in text
    assert '"GNOME50_EL10_PACKAGES_IMAGE_REF=${gnome50_el10_packages_ref}"' in text


def test_the_containerfile_declares_the_stage_and_mounts_it_on_gnome_only():
    text = CONTAINERFILE.read_text()
    assert (
        f'ARG GNOME50_EL10_PACKAGES_IMAGE_REF="{IMAGE}:unpinned-must-override"'
        in text
    ), (
        "the default must be a tag that cannot resolve, like COMMON/BREW/UTAH, "
        "so a bare `podman build` fails loudly instead of pulling an unpinned repo"
    )
    assert f"FROM ${{GNOME50_EL10_PACKAGES_IMAGE_REF}} AS {PIN}" in text
    mount = f"--mount=type=bind,from={PIN},source=/repository,target={MOUNT}"
    stages = re.split(r"^FROM ", text, flags=re.M)
    mounted = [s.split("\n", 1)[0] for s in stages if mount in s]
    assert mounted == ["base-no-de AS gnome"], mounted
    assert f"COPY --from={PIN}" not in text, (
        "the repository is hundreds of MB of RPMs; it is bind-mounted for one "
        "RUN, never copied into an image"
    )


def test_the_pin_checker_resolves_the_manifest_baseurl_to_the_image():
    """gnome.yaml says file:///run/NAME and nothing on the network answers
    that. check-package-repo-pins.py maps it back through image-versions.yaml
    and probes the registry instead -- but only while the two names agree."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "crpp", ROOT / "scripts" / "check-package-repo-pins.py"
    )
    crpp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(crpp)

    collected = crpp.collect(
        yaml.safe_load(GNOME.read_text()), crpp.oci_pins(str(IMAGE_VERSIONS))
    )
    kinds = {url: kind for kind, url in collected}
    ref = next(u for u in kinds if u.startswith(IMAGE + "@"))
    assert kinds[ref] == "oci", (
        f"{TIER} did not resolve to a pinned image; it would be reported "
        "oci-unpinned and fail the nightly check"
    )
    assert "oci-unpinned" not in set(kinds.values())
