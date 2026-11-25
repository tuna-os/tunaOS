"""tunaOS#4865: the initramfs must name the variant's hostname.

Live sessions showed `localhost login:` (yellowfin:xfce,
/tmp/t38 strict-plain-live-serial.log:559) and `fedora login:` (bonito:niri).
The published yellowfin:base initramfs (layer sha256:91a6bfd9…, kernel
6.12.0-281.el10) carries usr/lib/initrd-release with NAME="AlmaLinux Kitten"
and no DEFAULT_HOSTNAME. dracut's dracut-systemd module copies /etc/os-release
there, and on EL10, Fedora, Arch, Debian, Gentoo and openSUSE dracut runs
before 90-image-info.sh writes the identity. PID 1 in the initramfs then sets
systemd's compiled fallback hostname. After switch-root a system without
/etc/hostname keeps it (systemd src/shared/hostname-setup.c, hostname_setup).

initrd-hostname.sh now adds DEFAULT_HOSTNAME right before those dracut runs,
and checks/verify-initrd-hostname.sh stops the build after dracut unless
initrd-release names the variant. The real 26-packages-post.sh runs here
against the tunaOS#4104 fixture image, whose dracut stub writes initrd-release
the way dracut-systemd does. The real 90-image-info.sh runs against the
tests/test_anime_finalization.py fixture.

Falsification: behavioural. Replace initrd-hostname.sh with a no-op and
26-packages-post.sh fails with "initrd-release has no DEFAULT_HOSTNAME". The
check also rejects an upstream name, a name that differs from os-release, and
the real published yellowfin initrd-release. If 90-image-info.sh named the
host differently from initrd-hostname.sh, the last test fails.
"""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "issue4104", Path(__file__).with_name("test_issue_4104_rawhide_boots_its_own_splash.py"))
issue4104 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(issue4104)
Build, INITRAMFS, PUBLISH = issue4104.Build, issue4104.INITRAMFS, issue4104.PUBLISH

sys.path.insert(0, str(ROOT / "tests"))
from test_anime_finalization import Image  # noqa: E402

SEED = ROOT / "build_scripts/initrd-hostname.sh"

# usr/lib/initrd-release of the published yellowfin:base initramfs, verbatim.
PUBLISHED_YELLOWFIN = """NAME="AlmaLinux Kitten"
ID="almalinux"
ID_LIKE="rhel centos fedora"
VERSION_ID="10"
ANSI_COLOR="0;34"
LOGO="fedora-logo-icon"
HOME_URL="https://almalinux.org/"
VERSION="10 (Lion Cub) dracut-107-11.el10"
PRETTY_NAME="AlmaLinux Kitten 10 (Lion Cub) dracut-107-11.el10 (Initramfs)"
DRACUT_VERSION="107-11.el10"
"""


def value(text, key):
    lines = [line for line in text.splitlines() if line.startswith(key + "=")]
    return lines[-1].split("=", 1)[1].strip('"') if lines else None


def initrd_release(build):
    # dracut writes it; the fixture's dracut stub mimics dracut-systemd.
    with tarfile.open(build.root / INITRAMFS) as tar:
        return tar.extractfile("usr/lib/initrd-release").read().decode()


def expected(variant):
    name = PUBLISH[variant]
    aliases = dict(line.split("\t")[:2] for line in
                   (ROOT / "build_scripts/lib/variant-aliases.tsv").read_text().splitlines()
                   if line and not line.startswith("#"))
    return aliases.get(name, name)


@pytest.mark.parametrize("variant", sorted(PUBLISH))
def test_post_packages_puts_the_variant_hostname_in_the_initramfs(tmp_path, variant):
    build = Build(tmp_path, variant)
    result = build.post_packages()
    assert result.returncode == 0, result.stdout + result.stderr
    release = initrd_release(build)
    assert value(release, "DEFAULT_HOSTNAME") == expected(variant)
    # The 99tunaos-identity dracut module renames what systemd's
    # "Welcome to <PRETTY_NAME>!" shows; the fixture os-release says Fedora.
    assert value(release, "NAME") == expected(variant).capitalize()
    assert value(release, "PRETTY_NAME") == expected(variant).capitalize() + " (Initramfs)"
    assert f"TUNAOS_INITRD_HOSTNAME_OK hostname={expected(variant)}" in result.stdout


def test_without_the_identity_module_the_upstream_name_stops_the_build(tmp_path):
    build = Build(tmp_path, "yellowfin")
    module = ROOT / "build_scripts/dracut/99tunaos-identity/module-setup.sh"
    # The seed installs the module from the build context; break that copy.
    # Return before the rewrite so neither the delete nor the append runs.
    text = module.read_text()
    guard = '[[ -n "$host" ]] || return 0'
    assert guard in text
    (build.context / "dracut/99tunaos-identity/module-setup.sh").write_text(
        text.replace(guard, 'return 0'))
    result = build.post_packages()
    assert result.returncode != 0
    assert "initrd-release NAME='Fedora Linux', want 'Yellowfin'" in result.stderr


def test_without_the_seed_the_build_stops(tmp_path):
    build = Build(tmp_path, "yellowfin")
    (build.context / "initrd-hostname.sh").write_text("#!/bin/sh\nexit 0\n")
    result = build.post_packages()
    assert result.returncode != 0
    assert "initrd-release has no DEFAULT_HOSTNAME" in result.stderr
    assert "TUNAOS_INITRD_HOSTNAME_FAIL" in result.stderr


def _check(build, release_text, os_release=None):
    """Run the check against an initramfs whose initrd-release is release_text."""
    # One file is enough: the check reads only initrd-release.
    tree = build.tmp / "tree"
    (tree / "usr/lib").mkdir(parents=True)
    (tree / "usr/lib/initrd-release").write_text(release_text)
    img = build.tmp / "initramfs.img"
    with tarfile.open(img, "w") as tar:
        tar.add(tree / "usr", arcname="usr")
    if os_release is not None:
        (build.root / "usr/lib/os-release").write_text(os_release)
    return subprocess.run(
        ["bash", str(build.context / "checks/verify-initrd-hostname.sh"), str(img)],
        env=build.env, capture_output=True, text=True)


def test_the_published_yellowfin_initramfs_fails(tmp_path):
    build = Build(tmp_path, "yellowfin")
    result = _check(build, PUBLISHED_YELLOWFIN, 'NAME="Yellowfin"\nDEFAULT_HOSTNAME="yellowfin"\n')
    assert result.returncode == 1
    assert "no DEFAULT_HOSTNAME" in result.stderr and "AlmaLinux Kitten" in result.stderr


@pytest.mark.parametrize("name", ["fedora", "localhost", "almalinux", "ubuntu", "archlinux"])
def test_an_upstream_hostname_fails_even_when_os_release_agrees(tmp_path, name):
    build = Build(tmp_path, "yellowfin")
    build.env["IMAGE_NAME"] = build.env["IMAGE_NAME_VARIANT"] = name
    result = _check(build, f'DEFAULT_HOSTNAME="{name}"\n', f'DEFAULT_HOSTNAME="{name}"\n')
    assert result.returncode == 1
    assert "is an upstream name" in result.stderr


def test_a_hostname_that_differs_from_os_release_fails(tmp_path):
    build = Build(tmp_path, "yellowfin")
    result = _check(build, 'DEFAULT_HOSTNAME="bonito"\n', 'DEFAULT_HOSTNAME="yellowfin"\n')
    assert result.returncode == 1
    assert "image os-release has 'yellowfin'" in result.stderr


def test_the_seed_refuses_to_guess(tmp_path):
    result = subprocess.run(["bash", str(SEED)], env={"PATH": "/usr/bin:/bin"},
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert "refusing to guess" in result.stderr


@pytest.mark.parametrize("variant", sorted(PUBLISH))
def test_90_image_info_keeps_the_seeded_hostname(tmp_path, variant):
    """The final writer must agree with the name the initramfs got."""
    image = Image(tmp_path, variant)
    image.env["IMAGE_NAME"] = PUBLISH[variant]
    env = {**image.env, "TUNAOS_SYSROOT": str(image.root)}
    subprocess.run(["bash", str(SEED)], env=env, check=True, capture_output=True)
    seeded = value((image.root / "usr/lib/os-release").read_text(), "DEFAULT_HOSTNAME")
    image.info()
    final = value((image.root / "usr/lib/os-release").read_text(), "DEFAULT_HOSTNAME")
    assert seeded == final == expected(variant)
