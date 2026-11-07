"""guppy:gnome ships GNOME Initial Setup and a branded Plymouth (tunaOS#4426).

::gentoo has no gnome-initial-setup ebuild, so the in-repo gentoo-overlay/
carries one, and sys-boot/plymouth was never emerged. Strict ISO
qualification needs both: first-boot account creation through GNOME Initial
Setup, and the variant's splash drawing the LUKS passphrase prompt.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "gentoo-overlay"
GIS = OVERLAY / "gnome-extra" / "gnome-initial-setup"
GIS_VERSION = "50.1"
# download.gnome.org/sources/gnome-initial-setup/50/gnome-initial-setup-50.1.sha256sum
GIS_SHA256 = "b2ed05235896f47f552498ab5ab29f5501e6a8c41ee645f2a918620b1de91e60"


def _code(path: Path) -> str:
    return "\n".join(
        line for line in path.read_text().splitlines() if not line.lstrip().startswith("#")
    )


def test_overlay_is_a_named_repository_on_top_of_gentoo() -> None:
    assert (OVERLAY / "profiles" / "repo_name").read_text().strip() == "tunaos"
    layout = (OVERLAY / "metadata" / "layout.conf").read_text()
    assert re.search(r"^masters = gentoo$", layout, re.MULTILINE)
    hashes = re.search(r"^manifest-required-hashes = (.*)$", layout, re.MULTILINE)
    assert hashes and "SHA256" in hashes.group(1).split()


def test_gis_tarball_is_pinned_to_the_upstream_sha256() -> None:
    assert (GIS / f"gnome-initial-setup-{GIS_VERSION}.ebuild").is_file()
    dist = [line.split() for line in (GIS / "Manifest").read_text().splitlines()]
    assert len(dist) == 1, "one pinned distfile, no stray entries"
    entry = dist[0]
    assert entry[:2] == ["DIST", f"gnome-initial-setup-{GIS_VERSION}.tar.xz"]
    fields = dict(zip(entry[3::2], entry[4::2]))
    assert fields["SHA256"] == GIS_SHA256
    assert {"BLAKE2B", "SHA512"} <= fields.keys()


def test_gis_ebuild_disables_the_optional_heavy_features() -> None:
    ebuild = _code(GIS / f"gnome-initial-setup-{GIS_VERSION}.ebuild")
    for flag in ("-Dwebkitgtk=disabled", "-Dparental_controls=disabled", "-Dibus=enabled"):
        assert flag in ebuild
    assert 'KEYWORDS="~amd64"' in ebuild


def test_containerfile_registers_the_overlay_before_the_desktop_emerge() -> None:
    text = _code(ROOT / "Containerfile.gentoo")
    context = text[
        text.index("FROM scratch AS context") : text.index("FROM ${COMMON_IMAGE_REF} AS common")
    ]
    assert "COPY gentoo-overlay /gentoo-overlay" in context
    build = text[
        text.index("FROM builder AS desktop-build") : text.index("FROM desktop-build AS desktop")
    ]
    registered = build.index("/etc/portage/repos.conf/tunaos.conf")
    assert "cp -a /run/context/gentoo-overlay /var/db/repos/tunaos" in build
    assert registered < build.index("install-desktop.sh")


def test_gnome_emerge_list_installs_gis_and_plymouth() -> None:
    gnome = tomllib.loads((ROOT / "tunaos.toml").read_text())["desktops"]["gnome"]
    required = gnome["packages"]["emerge"]["required"]
    assert "gnome-extra/gnome-initial-setup" in required
    assert "sys-boot/plymouth" in required
    assert "gnome-extra/gnome-initial-setup" in gnome["emerge_accept_keywords"]
    # 24.004.60 is package.masked in ::gentoo; the stable 22.02 line is used.
    assert "sys-boot/plymouth" not in gnome["emerge_accept_keywords"]


def test_plymouth_selector_gives_gentoo_the_splash_karg() -> None:
    script = _code(ROOT / "build_scripts" / "plymouth-set-theme.sh")
    karg = script[: script.index("10-tunaos-plymouth-splash.toml")]
    condition = karg[karg.rindex("\nif ") :]
    assert "$alternatives_done" in condition
    assert "command -v emerge" in condition


def test_plymouth_selector_ships_the_label_plugin_where_populate_initrd_does_not() -> None:
    script = _code(ROOT / "build_scripts" / "plymouth-set-theme.sh")
    block = script[script.index('populate="$(') : script.index("46-tunaos-plymouth-label.conf")]
    assert "! grep -q 'label' \"$populate\"" in block
    assert "fc-match -f '%{file}'" in block
    assert "exit 1" in block, (
        "no font means an invisible prompt; say so, do not write a fontless conf"
    )
