"""Artwork that follows tunaos.toml is regenerated from it, not kept by hand.

Marks come from each variant's `emoji`, lettermarks from the mark, display
name and `branding.accent`, fastfetch letters from the display name. CI runs
scripts/branding/check-artwork.py with the pinned requirements-branding.txt;
these tests cover the parts that need no rendering libraries.
"""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


config = load("artwork_config_under_test", "scripts/lib/tunaos_config.py")
logos = load("artwork_logos_under_test", "scripts/branding/make-logos.py")
checker = load("artwork_checker_under_test", "scripts/branding/check-artwork.py")
LOGOS = ROOT / "system_files/usr/share/tunaos/logos"


def test_every_committed_mark_is_its_variants_emoji():
    for variant, settings in config.load()["variants"].items():
        assert logos.logo(variant, settings["emoji"]) == (LOGOS / f"{variant}.svg").read_text(encoding="utf-8"), variant


def test_a_forks_emoji_becomes_its_mark():
    mark = logos.logo("marlin", "🐋")
    assert "U+1F40B from Noto Emoji" in mark.splitlines()[1]
    assert mark != (LOGOS / "marlin.svg").read_text(encoding="utf-8")


def test_an_emoji_without_its_noto_drawing_names_the_file_to_add():
    with pytest.raises(SystemExit) as error:
        logos.logo("marlin", "🦄")
    assert "scripts/branding/emoji/1f984.svg" in str(error.value)


def test_display_names_match_what_os_release_shows():
    # 90-image-info.sh: PRETTY_NAME="${IMAGE_NAME^}" with the publish name.
    names = config.display_names(config.load())
    assert names["bonito-rawhide"] == "Bonito"
    assert names["flounder-sid"] == "Flounder"
    assert names["hummingbird"] == "Hummingbird"
    fork = copy.deepcopy(config.load())
    fork["variants"]["marlin"]["publish_name"] = "acmeOS"
    assert config.display_names(fork)["marlin"] == "AcmeOS"


def test_the_checker_reports_missing_stale_and_changed_files(tmp_path):
    generated, committed = tmp_path / "generated", ROOT / "system_files/usr/share/tunaos/logos"
    generated.mkdir()
    for path in committed.iterdir():
        (generated / path.name).write_bytes(path.read_bytes())
    assert checker.differences(generated, committed) == []
    (generated / "yellowfin.svg").write_text("changed")
    (generated / "newfish.svg").write_text("from a new variant")
    (generated / "marlin.svg").unlink()
    problems = checker.differences(generated, committed)
    assert any("yellowfin.svg: differs" in p for p in problems)
    assert any("newfish.svg: missing" in p for p in problems)
    assert any("marlin.svg: stale" in p for p in problems)


def test_logo_generator_writes_one_mark_per_variant(tmp_path):
    subprocess.run([sys.executable, str(ROOT / "scripts/branding/make-logos.py"), "--output", str(tmp_path)],
                   check=True, capture_output=True)
    assert {p.stem for p in tmp_path.iterdir()} == set(config.load()["variants"])


def test_every_stock_variant_has_its_drawn_artwork():
    assert config.missing_drawn_artwork(config.load()) == []


def test_a_fork_without_its_drawings_is_told_which_files_to_add(tmp_path):
    """Wallpapers and splashes are fork-supplied; a missing one names the file."""
    fork = copy.deepcopy(config.load())
    fork["variants"]["marlin"]["branding"]["plymouth"] = "anchor"
    walls = tmp_path / "system_files/usr/share/backgrounds/tunaos"
    themes = tmp_path / "system_files/usr/share/plymouth/themes"
    walls.mkdir(parents=True)
    for name in [*fork["variants"], "tunaos-default"]:
        if name != "marlin":
            (walls / f"{name}.jpg").touch()
    for theme in {v["branding"]["plymouth"] for v in fork["variants"].values()} | {"tunaos"}:
        if theme != "anchor":
            (themes / theme).mkdir(parents=True, exist_ok=True)
            for suffix in ("plymouth", "script"):
                (themes / theme / f"{theme}.{suffix}").touch()
    assert config.missing_drawn_artwork(fork, tmp_path) == [
        "system_files/usr/share/backgrounds/tunaos/marlin.jpg (variants.marlin)",
        "system_files/usr/share/plymouth/themes/anchor/anchor.plymouth (variants.marlin.branding.plymouth)",
        "system_files/usr/share/plymouth/themes/anchor/anchor.script (variants.marlin.branding.plymouth)",
    ]
