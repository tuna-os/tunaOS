"""tunaOS#4866: every shipping initramfs must carry the variant's own splash.

verify-plymouth-initramfs.sh ran only from 26-packages-post.sh (EL10 and
Fedora) and Containerfile.opensuse. The Arch, Debian, Gentoo and Ubuntu
initramfs builds, and the cachyos and nvidia overlay rebuilds, never checked
which splash dracut packed. On EL10 an image with no plymouth was only a
::warning::. The checker also could not pass a Debian or Ubuntu image: there
default.plymouth is the dpkg alternative. Measured on gurnard:pantheon:
"FAIL: image default.plymouth -> '/etc/alternatives/default.plymouth'", and the
initramfs carries that link dangling, with plymouthd.conf Theme=robot.

This test runs the real checker against fixture images built by the real
26-packages-post.sh (the tunaOS#4104 fixture), and reads every Containerfile
and overlay script that runs dracut.

Falsification: behavioural for the checker. On the unfixed checker the
alternatives image fails, and a blocked hummingbird or guppy:base exits 2. The
call-site test is structural: delete any verify-plymouth-initramfs.sh line that
this change added after a dracut run, and that site is named as unchecked.
"""
import importlib.util
from pathlib import Path
import re
import shutil
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "issue4104", Path(__file__).with_name("test_issue_4104_rawhide_boots_its_own_splash.py"))
issue4104 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(issue4104)
Build, built, INITRAMFS = issue4104.Build, issue4104.built, issue4104.INITRAMFS

THEMES_REL = "usr/share/plymouth/themes"
ALTERNATIVE = "etc/alternatives/default.plymouth"


def _as_dpkg_alternative(root, theme, with_target=True):
    """Lay default.plymouth out the way update-alternatives does."""
    link = root / THEMES_REL / "default.plymouth"
    link.unlink()
    link.symlink_to(f"/{ALTERNATIVE}")
    if with_target:
        (root / ALTERNATIVE).parent.mkdir(parents=True, exist_ok=True)
        (root / ALTERNATIVE).symlink_to(f"/{THEMES_REL}/{theme}/{theme}.plymouth")


def _repack(build, edit):
    tree = build.tmp / "repack"
    shutil.rmtree(tree, ignore_errors=True)
    img = build.root / INITRAMFS
    with tarfile.open(img) as tar:
        tar.extractall(tree, filter="tar")
    edit(tree)
    with tarfile.open(img, "w") as tar:
        for child in sorted(tree.iterdir()):
            tar.add(child, arcname=child.name)


def test_debian_alternative_passes_in_the_image_and_the_initramfs(tmp_path):
    """grouper's coral through the alternative; dracut packs the link dangling."""
    build = built(tmp_path, "grouper")
    _as_dpkg_alternative(build.root, "coral")
    _repack(build, lambda tree: _as_dpkg_alternative(tree, "coral", with_target=False))
    result = build.check("grouper")
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"image default.plymouth -> /{THEMES_REL}/coral/coral.plymouth" in result.stdout
    assert "initramfs default.plymouth names the dpkg alternative" in result.stdout


def test_an_alternative_that_names_another_theme_fails(tmp_path):
    build = built(tmp_path, "grouper")
    _as_dpkg_alternative(build.root, "coral")
    (build.root / ALTERNATIVE).unlink()
    (build.root / ALTERNATIVE).symlink_to(f"/{THEMES_REL}/tunaos/tunaos.plymouth")
    result = build.check("grouper")
    assert result.returncode == 1
    assert f"resolves to '/{THEMES_REL}/tunaos/tunaos.plymouth', want coral/coral.plymouth" in result.stderr


def _without_plymouth(tmp_path, variant, flavor):
    if shutil.which("plymouthd", path="/usr/bin:/bin"):
        pytest.skip("host plymouthd on /usr/bin:/bin; cannot hide it")
    build = built(tmp_path, variant)
    (build.stubs / "plymouthd").unlink()
    build.env["TUNAOS_IMAGE_FLAVOR"] = flavor
    return build.check(variant)


@pytest.mark.parametrize("variant, flavor", [
    ("hummingbird", "tuna"), ("hummingbird", "base"), ("guppy", "base"),
])
def test_images_without_plymouth_on_purpose_are_named_and_pass(tmp_path, variant, flavor):
    result = _without_plymouth(tmp_path, variant, flavor)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"TUNAOS_PLYMOUTH_EXEMPT variant={variant} flavor={flavor}" in result.stdout


@pytest.mark.parametrize("variant, flavor", [
    ("guppy", "gnome"), ("marlin", "base"), ("grouper", "base"), ("yellowfin", "gnome"),
])
def test_every_other_image_without_plymouth_fails(tmp_path, variant, flavor):
    result = _without_plymouth(tmp_path, variant, flavor)
    assert result.returncode == 2, result.stdout
    assert "TUNAOS_PLYMOUTH_BLOCKED" in result.stderr
    assert "is not an image that ships no plymouth on purpose" in result.stderr


# ------------------------------------------------------------- call sites --

# Each file that builds an initramfs an image ships, by family.
SITES = {
    "Containerfile.arch": 1,
    "Containerfile.debian": 1,
    "Containerfile.gentoo": 2,
    "Containerfile.opensuse": 1,
    "build_scripts/26-packages-post.sh": 1,
    "build_scripts/bootc/finalize.sh": 1,
    "build_scripts/overlay/cachyos.sh": 1,
    "build_scripts/overlay/overrides/nvidia/20-nvidia.sh": 1,
    "build_scripts/overlay/overrides/nvidia-arch/20-nvidia.sh": 1,
    "build_scripts/overlay/overrides/nvidia-debian/20-nvidia.sh": 1,
}
DRACUT_RUN = re.compile(r"^\s*(/usr/bin/)?dracut\s+(-|--)")
CHECK = "checks/verify-plymouth-initramfs.sh"


@pytest.mark.parametrize("rel, runs", sorted(SITES.items()))
def test_every_dracut_run_is_followed_by_the_splash_check(rel, runs):
    lines = [line for line in (ROOT / rel).read_text().splitlines()
             if not line.lstrip().startswith("#")]
    starts = [i for i, line in enumerate(lines) if DRACUT_RUN.search(line)]
    assert len(starts) == runs, f"{rel}: expected {runs} dracut run(s), found {len(starts)}"
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        assert any(CHECK in line for line in lines[start:end]), (
            f"{rel}: the dracut run on non-comment line {start + 1} ships an "
            "initramfs nobody checks for the variant's splash")


def test_post_packages_no_longer_downgrades_a_missing_splash_to_a_warning():
    text = (ROOT / "build_scripts/26-packages-post.sh").read_text()
    assert "::warning::no TunaOS boot splash" not in text
