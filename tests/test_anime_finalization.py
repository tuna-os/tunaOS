"""PR #3465: execute wallpaper writers in the Containerfiles' order.

Full 90-image-info.sh runs with only filesystem paths redirected and its unrelated
OS detection/countme boundary stubbed. This is source execution, not an OS build.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
WALLS = ROOT / "system_files/usr/share/backgrounds/tunaos"
IDS = [line.split("\t")[0] for line in
       (ROOT / "build_scripts/lib/variant-identity.tsv").read_text().splitlines()
       if line and not line.startswith("#")]


class Image:
    def __init__(self, tmp_path, variant="yellowfin", flavor="gnome", target=None):
        self.root = tmp_path / "root"
        self.context = tmp_path / "context"
        self.walls = self.root / "usr/share/backgrounds/tunaos"
        for directory in ("etc/xdg", "usr/lib", "usr/share/tunaos", "usr/share/backgrounds/tunaos"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        for directory in ("build_scripts/lib", "build_scripts/desktop", "manifests"):
            (self.context / directory).mkdir(parents=True, exist_ok=True)
        for path in ("etc/os-release", "usr/lib/os-release"):
            (self.root / path).write_text('NAME="Fixture"\n')
        self.env = {**os.environ, "IMAGE_NAME": variant, "IMAGE_NAME_VARIANT": variant,
                    "IMAGE_VENDOR": "tuna-os", "BASE_IMAGE": "fixture", "MAJOR_VERSION_NUMBER": "1",
                    "DESKTOP_FLAVOR": target or flavor, "TUNAOS_IMAGE_FLAVOR": flavor,
                    "PKG_MGR": "dnf"}
        (self.context / "build_scripts/lib.sh").write_text("# OS detection boundary\n")
        countme = self.context / "build_scripts/install-countme.sh"
        countme.write_text("#!/bin/sh\nexit 0\n")
        countme.chmod(0o755)
        shutil.copyfile(ROOT / "build_scripts/lib/variant-identity.tsv",
                        self.context / "build_scripts/lib/variant-identity.tsv")
        shutil.copyfile(ROOT / "build_scripts/lib/fork-branding.sh",
                        self.context / "build_scripts/lib/fork-branding.sh")
        for path in ("build_scripts/90-image-info.sh", "build_scripts/desktop/select-wallpaper.sh"):
            source = (ROOT / path).read_text()
            # Keep the whole script and ordering; redirect literal filesystem roots.
            source = source.replace("/usr/", f"{self.root}/usr/").replace("/etc/", f"{self.root}/etc/")
            source = source.replace("/run/context", str(self.context))
            source = source.replace(f"#!{self.root}/usr/bin/env bash", "#!/usr/bin/env bash")
            # The fork adapter already exposes a root argument for isolated tests.
            source = source.replace(f"tunaos_apply_fork_branding {self.context}",
                                    f'tunaos_apply_fork_branding {self.context} "{self.root}"')
            target_path = self.context / path
            target_path.write_text(source)
            target_path.chmod(0o755)
        shutil.copyfile(WALLS / f"{variant}.jpg", self.walls / f"{variant}.jpg")
        anime = WALLS / f"{variant}-anime.jpg"
        if anime.exists():
            shutil.copyfile(anime, self.walls / anime.name)
        self.reset_copy()

    def reset_copy(self):
        shutil.copyfile(WALLS / "tunaos-default.jpg", self.walls / "tunaos-default.jpg")

    def run(self, path, *args):
        result = subprocess.run(["bash", str(self.context / path), *args],
                                env=self.env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

    def info(self):
        self.run("build_scripts/90-image-info.sh")

    def desktop(self):
        self.run("build_scripts/desktop/select-wallpaper.sh", self.env["TUNAOS_IMAGE_FLAVOR"])
        if (self.context / "manifests/fork-config.json").exists():
            result = subprocess.run(["bash", "-c", 'source "$1"; tunaos_apply_fork_branding "$2" "$3"',
                                     "test", str(self.context / "build_scripts/lib/fork-branding.sh"),
                                     str(self.context), str(self.root)],
                                    env=self.env, capture_output=True, text=True)
            assert result.returncode == 0, result.stderr

    def output(self):
        return (self.walls / "tunaos-default.jpg").read_bytes()


@pytest.mark.parametrize("variant", IDS)
@pytest.mark.parametrize("flavor", ["gnome", "kde", "cosmic", "niri", "xfce", "pantheon"])
def test_real_art_survives_final_identity_writer(tmp_path, variant, flavor):
    image = Image(tmp_path, variant, flavor)
    image.info()
    image.desktop()
    image.info()
    expected = WALLS / f"{variant}-anime.jpg"
    if not expected.exists():
        expected = WALLS / f"{variant}.jpg"
    assert image.output() == expected.read_bytes()
    assert (image.walls / f"{variant}.jpg").read_bytes() == (WALLS / f"{variant}.jpg").read_bytes()


@pytest.mark.parametrize("family", ["rpm", "apt", "gentoo", "overlay"])
@pytest.mark.parametrize("art", ["override", "anime", "vector", "missing"])
def test_family_last_writer_and_fallbacks(tmp_path, family, art):
    image = Image(tmp_path, flavor="gnome-nvidia" if family == "overlay" else "gnome",
                  target="desktop" if family == "overlay" else None)
    expected = (WALLS / "yellowfin-anime.jpg").read_bytes()
    if art == "override":
        (image.walls / "yellowfin-gnome.jpg").write_bytes(b"explicit desktop art")
        expected = b"explicit desktop art"
    if art in ("vector", "missing"):
        (image.walls / "yellowfin-anime.jpg").unlink()
        expected = (WALLS / "yellowfin.jpg").read_bytes()
    if art == "missing":
        (image.walls / "yellowfin.jpg").unlink()
        expected = (WALLS / "tunaos-default.jpg").read_bytes()
    image.info()
    image.desktop()
    if family == "overlay":
        image.reset_copy()
    if family != "apt":
        image.info()
    assert image.output() == expected


def test_unknown_identity_keeps_existing_default(tmp_path):
    image = Image(tmp_path)
    (image.root / "usr/share/tunaos/identity.env").write_text("TUNAOS_VARIANT='unknown'\n")
    image.desktop()
    assert image.output() == (WALLS / "tunaos-default.jpg").read_bytes()


@pytest.mark.parametrize("family", ["rpm", "apt", "gentoo", "overlay"])
def test_custom_fork_wallpaper_and_urls_win_after_finalization(tmp_path, family):
    image = Image(tmp_path, flavor="gnome-nvidia" if family == "overlay" else "gnome",
                  target="desktop" if family == "overlay" else None)
    image.env.update(IMAGE_VENDOR="fork-preview", IMAGE_REGISTRY="localhost")
    asset = (WALLS / "tunaos-default.jpg").read_bytes()
    digest = hashlib.sha256(asset).hexdigest()
    asset_path = f"fork-assets/{digest}.jpg"
    (image.context / "manifests/fork-assets").mkdir()
    (image.context / "manifests" / asset_path).write_bytes(asset)
    manifest = {
        "schema_version": 1, "variant": "yellowfin", "flavor": image.env["TUNAOS_IMAGE_FLAVOR"],
        "platform": "linux/arm64" if os.uname().machine == "aarch64" else "linux/amd64",
        "image": {"registry": "localhost", "namespace": "fork-preview"},
        "package_manager": "dnf", "sources": {"sha256": "a" * 64},
        "intent": {"branding": {"homepage": "https://example.test/", "documentation": "https://example.test/docs",
                                "support": "https://example.test/help", "wallpaper": "art/final.jpeg"},
                   "packages": {"add": [], "remove": [], "optional": [], "repositories": []}},
        "assets": {"wallpaper": {"path": asset_path, "sha256": digest}},
    }
    (image.context / "manifests/fork-config.json").write_text(json.dumps(manifest))
    if family == "overlay":
        result = subprocess.run(["bash", str(image.context / "build_scripts/90-image-info.sh")],
                                env=image.env, capture_output=True, text=True)
        assert result.returncode != 0
        assert "invalid or unsupported manifest" in result.stderr
        return
    image.info()
    image.desktop()
    if family != "apt":
        image.info()
    assert image.output() == asset
    assert 'HOME_URL="https://example.test/"' in (image.root / "usr/lib/os-release").read_text()
    assert 'DOCUMENTATION_URL="https://example.test/docs"' in (image.root / "usr/lib/os-release").read_text()


def test_containerfile_order_and_final_writer_contract():
    for name in ("el10", "gentoo"):
        source = (ROOT / f"Containerfile.{name}").read_text()
        assert source.rindex("90-image-info.sh") > source.index("/build_scripts/desktop/install-desktop.sh")
    for name in ("debian", "ubuntu"):
        source = (ROOT / f"Containerfile.{name}").read_text()
        assert source.index("/build_scripts/90-image-info.sh") < source.index("/build_scripts/desktop/install-desktop.sh")
    overlay = (ROOT / "Containerfile.overlay").read_text()
    assert overlay.index("/build_scripts/00-copy-files.sh") < overlay.index("/build_scripts/90-image-info.sh")
    source = (ROOT / "build_scripts/90-image-info.sh").read_text()
    assert source.index("/build_scripts/desktop/select-wallpaper.sh") < source.index("tunaos_apply_fork_branding")
    assert 'VARIANT_WALLPAPER=' not in source
