"""tunaOS#2450: guppy:gnome built GNOME 49 and failed the GNOME 50 floor.

::gentoo stable stops at GNOME 49 (gnome-shell 49.7), and the official
binhost builds stable only. GNOME 50 (gnome-shell 50.5) is in ::gentoo under
~amd64 only, measured on packages.gentoo.org and with emerge --pretend
against ::gentoo on 2026-10-07. verify-desktop-experience.sh rejects
anything below 50, so guppy:gnome needs two things:

- gnome.yaml's emerge_accept_keywords lists the GNOME 50 core set, as bare
  category/name atoms, and install-desktop.sh writes it before the binhost
  lock runs.
- gentoo-binhost-version-lock.sh does not mask a keyworded package. With
  that mask, gnome-shell is locked to the binhost's 49.7, the lock's own
  --pretend check still resolves (to 49), and the image ships GNOME 49.

Falsification: behavioural for the lock. The test runs the lock's real
Python block against a binhost index with gnome-shell 49.7. Without the
keyword exemption it prints >gnome-base/gnome-shell-49.7, and the test
fails (checked by deleting the `if key in keyworded:` skip). Structural for
the manifest and the installer order: dropping a core atom from gnome.yaml,
pinning a version in an atom, or moving the keyword write below the lock
makes the matching test fail.
"""

import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "manifests" / "desktops" / "gnome.yaml"
INSTALL = ROOT / "build_scripts" / "desktop" / "install-desktop.sh"
LOCK = ROOT / "build_scripts" / "desktop" / "gentoo-binhost-version-lock.sh"

# Each of these has its GNOME 50 ebuild under ~amd64 only.
CORE = {
    "gnome-base/gnome-shell",
    "x11-wm/mutter",
    "gnome-base/gdm",
    "gnome-base/gnome-session",
    "gnome-base/gsettings-desktop-schemas",
    "gnome-base/gnome-control-center",
    "gnome-base/gnome-settings-daemon",
    "sys-apps/xdg-desktop-portal-gnome",
}


def _keywords():
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    return set(manifest.get("emerge_accept_keywords") or [])


def test_gnome_manifest_accepts_the_gnome_50_core_set():
    missing = sorted(CORE - _keywords())
    assert not missing, f"gnome.yaml emerge_accept_keywords lacks {missing}"


def test_keyword_atoms_are_bare_so_a_50_x_bump_needs_no_edit():
    pinned = sorted(
        k for k in _keywords() if k[:1] in "<>=~" or k.count("/") != 1
    )
    assert not pinned, f"use bare category/name atoms, not {pinned}"


def test_installer_writes_the_keywords_before_the_lock_reads_them():
    body = INSTALL.read_text(encoding="utf-8")
    kw = body.index("emerge_accept_keywords")
    lock = body.index('gentoo-binhost-version-lock.sh"')
    assert kw < lock, "install-desktop.sh writes the keywords after the lock runs"


def _run_lock_python(tmp_path, keyword_lines):
    script = LOCK.read_text(encoding="utf-8")
    block = script.split("<<'PYEOF'\n", 1)[1].split("\nPYEOF\n", 1)[0]
    index = tmp_path / "Packages"
    index.write_text(
        "CPV: gnome-base/gnome-shell-49.7\n"
        "CPV: gnome-base/gdm-49.2-r4\n"
        "CPV: gnome-base/gnome-session-49.1\n",
        encoding="utf-8",
    )
    keywords = tmp_path / "package.accept_keywords"
    keywords.mkdir()
    (keywords / "tunaos-gnome").write_text(keyword_lines, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-", "gnome-base", str(index), str(keywords)],
        input=block,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.split()


def test_binhost_lock_does_not_mask_a_keyworded_package(tmp_path):
    masks = _run_lock_python(
        tmp_path,
        "gnome-base/gnome-shell ~amd64\n=gnome-base/gdm-50.0 ~amd64\n",
    )
    assert ">gnome-base/gnome-shell-49.7" not in masks
    assert ">gnome-base/gdm-49.2-r4" not in masks
    # A package nobody keyworded is still locked to the binhost.
    assert ">gnome-base/gnome-session-49.1" in masks
