"""COSMIC on EL10 comes from tunaOS's own Tideforge tier. Not from a COPR.

#3132 moved cosmic.yaml's el10 section off COPR `yselkowitz/cosmic-epel` onto
repo.tunaos.org/repo/10-stream-x86_64 (tuna-os/tunaos-packages phases 0-3).
That tier is x86_64 only -- repo/10-stream-aarch64 does not exist, and
install-desktop.sh writes every manifest repo with skip_if_unavailable=False --
so an arm64 EL10 cosmic leg cannot install its desktop. The manifest and
build-config must keep agreeing on that:

  * every EL10 cosmic-family flavor that builds is pinned to linux/amd64. The
    pin is repeated per variant and per flavor (cosmic, cosmic-hwe,
    cosmic-nvidia), so one copy silently regaining arm64 is the failure this
    guards. Whoever re-adds linux/arm64 deletes the variant from PINNED below
    in the same change -- the reviewable claim that the aarch64 tier exists.
  * the COSMIC stack is a required install from the tier, not a best-effort
    COPR block.

Same shape as tests/test_el10_gnome_comes_from_the_github_built_tier.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
COSMIC = ROOT / "manifests" / "desktops" / "cosmic.yaml"
CONFIG = ROOT / ".github" / "build-config.yml"

TIER = "https://repo.tunaos.org/repo/10-stream-x86_64/"
# EL10 variants whose cosmic cells are amd64-only until the tier has aarch64.
PINNED = ("yellowfin", "albacore", "skipjack")
AMD64 = ["linux/amd64"]
# What the desktop contract (verify-desktop-experience.sh) and a usable login
# need; these must never fall back to `optional:`.
REQUIRED = (
    "cosmic-session",
    "cosmic-comp",
    "cosmic-files",
    "cosmic-greeter",
    "greetd",
    "xdg-desktop-portal-cosmic",
)


@pytest.fixture(scope="module")
def el10() -> dict:
    return yaml.safe_load(COSMIC.read_text())["packages"]["el10"]


@pytest.fixture(scope="module")
def variants() -> dict:
    cfg = yaml.safe_load(CONFIG.read_text())
    return {v["id"]: v for v in cfg["variants"]}


def test_no_copr_in_the_el10_cosmic_section(el10):
    assert "copr" not in el10, (
        "a COPR is back as the EL10 COSMIC source; the Tideforge tier is the source"
    )


def test_the_tier_is_the_x86_64_tideforge_repo(el10):
    urls = [r.get("baseurl") for r in el10.get("repos") or []]
    assert TIER in urls, f"{TIER} is not declared in cosmic.yaml's el10 repos"


def test_the_stack_is_a_required_install(el10):
    packages = el10.get("packages") or []
    optional = el10.get("optional") or []
    for name in REQUIRED:
        assert name in packages, f"{name} is not a required el10 package"
        assert name not in optional, f"{name} is best-effort on el10"


@pytest.mark.parametrize("variant", PINNED)
def test_el10_cosmic_is_amd64_only_until_the_tier_has_aarch64(variants, variant):
    cosmic = [
        f
        for f in variants[variant]["flavors"]
        if f["id"].startswith("cosmic") and f.get("build_image", True)
    ]
    assert {f["id"] for f in cosmic} >= {"cosmic", "cosmic-hwe"}, (
        f"{variant} no longer builds cosmic/cosmic-hwe; update PINNED"
    )
    for flavor in cosmic:
        declared = flavor.get("platforms", variants[variant]["platforms"])
        assert declared == AMD64, (
            f"{variant}:{flavor['id']} declares {declared}; re-adding arm64 "
            "requires an aarch64 Tideforge COSMIC index and removing the "
            "variant from PINNED in the same change"
        )


# ── Login integration the COPR packages used to supply ───────────────────────
#
# The factory greetd ships only the daemon and greetd.service: no
# /etc/greetd/config.toml and no PAM services. cosmic-greeter.service carries
# its own config (`greetd --config /etc/greetd/cosmic-greeter.toml`), but its
# RPM claims no display-manager.service alias, and its PAM file is Debian's
# (`@include common-auth`), which EL does not have.


def test_el10_selects_cosmic_greeter_as_the_display_manager(el10):
    assert el10.get("display_manager") == "cosmic-greeter", (
        "a bare greetd.service has no config.toml on EL10; cosmic-greeter.service "
        "is the greetd unit that carries one"
    )


def test_the_factory_greetd_gets_its_system_integration():
    post = yaml.safe_load(COSMIC.read_text()).get("post_install") or []
    assert "greetd-system-integration.sh" in post, (
        "nothing installs the greetd-greeter PAM service or the greetd SELinux labels"
    )
    assert post.index("greetd-system-integration.sh") < post.index("greetd-gtkgreet.sh")


def test_the_debian_pam_file_is_replaced_where_el_lacks_common_auth():
    inline = " ".join(yaml.safe_load(COSMIC.read_text()).get("post_install_inline") or [])
    assert "/etc/pam.d/cosmic-greeter" in inline and "common-auth" in inline
