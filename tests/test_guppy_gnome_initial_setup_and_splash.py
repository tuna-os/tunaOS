"""guppy:gnome ships GNOME Initial Setup and a branded Plymouth (tunaOS#4426).

::gentoo has no gnome-initial-setup ebuild, so the in-repo gentoo-overlay/
carries one, and sys-boot/plymouth was never emerged. Strict ISO
qualification needs both: first-boot account creation through GNOME Initial
Setup, and the variant's splash drawing the LUKS passphrase prompt.
"""

from __future__ import annotations

import re
import subprocess
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
    manifest = (GIS / "Manifest").read_text().splitlines()
    dist = [line.split() for line in manifest if line.startswith("DIST ")]
    assert len(dist) == 1, "one pinned distfile"
    entry = dist[0]
    assert entry[1] == f"gnome-initial-setup-{GIS_VERSION}.tar.xz"
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


SCRIPT = ROOT / "build_scripts" / "plymouth-set-theme.sh"


def _shell_block(start: str, end: str) -> str:
    """Lines of plymouth-set-theme.sh from the one starting `start` through
    the first later line equal to `end`."""
    lines = SCRIPT.read_text().splitlines()
    first = next(i for i, line in enumerate(lines) if line.startswith(start))
    last = next(i for i in range(first, len(lines)) if lines[i] == end)
    return "\n".join(lines[first : last + 1])


def _splash_karg(tmp_path: Path, os_release: str, with_emerge: bool) -> str:
    (tmp_path / "os-release").write_text(os_release)
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    emerge = bindir / "emerge"
    if with_emerge:
        emerge.write_text("#!/bin/sh\n")
        emerge.chmod(0o755)
    elif emerge.exists():
        emerge.unlink()
    block = _shell_block("splash_karg=", "fi").replace(
        "/usr/lib/os-release", str(tmp_path / "os-release")
    )
    done = subprocess.run(
        ["/bin/bash", "-c", f'alternatives_done=false; {block}; echo "$splash_karg"'],
        capture_output=True,
        text=True,
        check=True,
        env={"PATH": f"{bindir}:/usr/bin:/bin"},
    )
    return done.stdout.strip()


def test_plymouth_selector_gives_gentoo_the_splash_karg(tmp_path: Path) -> None:
    assert _splash_karg(tmp_path, 'ID="gentoo"\n', with_emerge=True) == "true"
    assert _splash_karg(tmp_path, "ID=fedora\n", with_emerge=False) == "false"
    suse = 'ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n'
    assert _splash_karg(tmp_path, suse, with_emerge=False) == "true"


# plymouth-populate-initrd shapes. 24.004.60 and 23.360.11 install the label
# plugin from scripts/plymouth-populate-initrd.in (upstream tags); 22.02.122
# has no label line at all.
POPULATE_24 = """\
inst ${PLYMOUTH_PLUGIN_PATH}/details.so $INITRDDIR
DEFAULT_FONT=$(fc-match -f %{file} 2> /dev/null)
if [ -f "${PLYMOUTH_PLUGIN_PATH}/label-freetype.so" ]; then
     inst ${PLYMOUTH_PLUGIN_PATH}/label-freetype.so $INITRDDIR
     # The label-freetype plugin expects it at this location
fi
"""
POPULATE_22 = """\
inst ${PLYMOUTH_PLUGIN_PATH}/text.so $INITRDDIR
inst ${PLYMOUTH_PLUGIN_PATH}/details.so $INITRDDIR
inst ${PLYMOUTH_PLUGIN_PATH}/${PLYMOUTH_MODULE_NAME}.so $INITRDDIR
inst ${PLYMOUTH_PLUGIN_PATH}/renderers/frame-buffer.so $INITRDDIR
"""
# 22.02 plus the word "label" where it installs nothing: a comment, a
# commented-out inst, an unrelated identifier and a test on the plugin path.
POPULATE_22_INCIDENTAL = POPULATE_22 + """\
# the label plugin is not installed here
# inst ${PLYMOUTH_PLUGIN_PATH}/label.so $INITRDDIR
PLYMOUTH_LABEL_FONT=sans
[ -f "${PLYMOUTH_PLUGIN_PATH}/label.so" ] && echo found
"""


def _populate_installs_label(tmp_path: Path, text: str) -> bool:
    populate = tmp_path / "plymouth-populate-initrd"
    populate.write_text(text)
    function = _shell_block("populate_installs_label() {", "}")
    done = subprocess.run(
        ["/bin/bash", "-c", f'{function}; populate_installs_label "$1"', "_", str(populate)],
        check=False,
    )
    return done.returncode == 0


def test_label_gate_reads_only_an_inst_of_the_label_plugin(tmp_path: Path) -> None:
    assert _populate_installs_label(tmp_path, POPULATE_24)
    assert not _populate_installs_label(tmp_path, POPULATE_22)
    assert not _populate_installs_label(tmp_path, POPULATE_22_INCIDENTAL)


def test_plymouth_selector_ships_the_label_plugin_where_populate_initrd_does_not() -> None:
    script = _code(SCRIPT)
    block = script[script.index('populate="$(') : script.index("46-tunaos-plymouth-label.conf")]
    assert '! populate_installs_label "$populate"' in block
    assert "fc-match -f '%{file}'" in block
    assert "exit 1" in block, (
        "no font means an invisible prompt; say so, do not write a fontless conf"
    )
