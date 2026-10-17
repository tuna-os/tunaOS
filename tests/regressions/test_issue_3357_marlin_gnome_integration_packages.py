"""tunaOS#3357: marlin:gnome omitted GNOME integration packages.

A booted marlin:gnome host with BUILD_ID=4ace379 reported that
`pacman -Q gvfs-goa` could not find the package, and its
`/usr/share/thumbnailers/` directory had no video or document thumbnailer.
The Arch GNOME manifest must name the Arch packages that provide those desktop
integration paths: `gvfs-goa` for GNOME Online Accounts mounts and
`gst-thumbnailers` for Nautilus media/document thumbnailing.

Falsification: structural -- remove either package from
`packages.pacman` in manifests/desktops/gnome-arch.yaml and this test fails.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "manifests/desktops/gnome-arch.yaml"
REQUIRED_PACKAGES = {"gvfs-goa", "gst-thumbnailers"}


def test_marlin_gnome_manifest_names_integration_packages():
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    packages = set(manifest["packages"]["pacman"])
    missing = REQUIRED_PACKAGES - packages

    assert not missing, (
        "manifests/desktops/gnome-arch.yaml is missing GNOME integration "
        f"packages: {sorted(missing)}"
    )
