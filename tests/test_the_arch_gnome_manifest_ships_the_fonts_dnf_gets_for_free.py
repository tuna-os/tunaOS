"""marlin:gnome must ship the fonts every dnf GNOME variant gets for free.

dnf GNOME variants get their font stack from two places neither of which
Containerfile.arch runs: the "Fonts" dnf group in manifests/desktops/gnome.yaml
(DejaVu, Liberation, Noto incl. color emoji) and the Nerd Font that
build_scripts/26-packages-post.sh curls and installs to
/usr/share/fonts/JetBrainsMonoNerdFont. Containerfile.arch explicitly skips
26-packages-post.sh -- the same skip already required hand-written
compensation for remora (install-remora.sh) and depmod (a dedicated RUN,
both with comments explaining why) -- but nobody added compensation for
fonts, so marlin never got any.

Measured on a booted marlin:gnome (BUILD_ID=4ace379, VERSION_ID=20260814.0):

    $ ls /usr/share/fonts
    Adwaita  encodings  gnu-free
    $ fc-match monospace
    FreeMono.otf: "FreeMono" "Regular"
    $ fc-list | grep -i emoji
    (nothing)
    $ pacman -Q ttf-dejavu ttf-liberation noto-fonts noto-fonts-emoji \
        ttf-jetbrains-mono-nerd
    error: package 'ttf-dejavu' was not found
    error: package 'ttf-liberation' was not found
    error: package 'noto-fonts' was not found
    error: package 'noto-fonts-emoji' was not found
    error: package 'ttf-jetbrains-mono-nerd' was not found

No generic sans/serif/monospace fallback, no color emoji, no CJK coverage,
and the Nerd Font every other GNOME variant ships was entirely absent (a
user-installed copy in ~/.local/share/fonts, owned by no package, was the
only reason any Nerd Font glyphs rendered at all on the box this was
measured on).

This test asserts manifests/desktops/gnome-arch.yaml lists the real Arch
`extra`-repo packages that close the gap. It does not assert monospace-font-name
defaults to the Nerd Font: Ptyxis's default (Adwaita Mono 11, via the
upstream Bluefin zz0-bluefin-modifications.gschema.override) is inherited
verbatim from real Bluefin -- that default is by design, not this bug.
"""
from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "manifests" / "desktops" / "gnome-arch.yaml"

# Real `extra`-repo package names (verified with `pacman -Ss` against a
# synced db -- these are not AUR names).
REQUIRED_FONT_PACKAGES = {
    "ttf-dejavu",
    "ttf-liberation",
    "noto-fonts",
    "noto-fonts-emoji",
    "ttf-jetbrains-mono-nerd",
}


@pytest.fixture(scope="module")
def manifest() -> dict:
    assert MANIFEST.is_file(), (
        f"{MANIFEST} is missing -- this test guards the Arch GNOME desktop "
        "manifest; if it moved, point this test at its new home rather than "
        "deleting the guard."
    )
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def test_the_manifest_has_a_pacman_package_list(manifest: dict):
    pacman_packages = manifest.get("packages", {}).get("pacman")
    assert isinstance(pacman_packages, list) and pacman_packages, (
        "manifests/desktops/gnome-arch.yaml has no packages.pacman list -- "
        "the manifest shape changed out from under this test."
    )


def test_the_arch_gnome_manifest_ships_the_missing_font_packages(manifest: dict):
    pacman_packages = set(manifest["packages"]["pacman"])
    missing = REQUIRED_FONT_PACKAGES - pacman_packages
    assert not missing, (
        "manifests/desktops/gnome-arch.yaml is missing font packages that "
        f"every dnf GNOME variant gets for free: {sorted(missing)}.\n"
        "Containerfile.arch never runs build_scripts/26-packages-post.sh "
        "(the dnf path's font/Nerd-Font install step), and nothing "
        "compensates for that the way install-remora.sh compensates for the "
        "same skip. Add the missing package(s) to packages.pacman in "
        "manifests/desktops/gnome-arch.yaml."
    )
