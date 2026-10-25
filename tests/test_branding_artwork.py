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
import shutil
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
    assert config.drawn_artwork_problems(config.load()) == []


def theme_files(themes, theme):
    """A theme as plymouth-set-theme.sh expects it: descriptor and script naming the theme's own directory."""
    (themes / theme).mkdir(parents=True, exist_ok=True)
    (themes / theme / f"{theme}.plymouth").write_text(
        f"[Plymouth Theme]\nName={theme}\nModuleName=script\n\n[script]\nImageDir=/usr/share/plymouth/themes/{theme}\n"
        f"ScriptFile=/usr/share/plymouth/themes/{theme}/{theme}.script\n", encoding="utf-8")
    (themes / theme / f"{theme}.script").touch()


def drawn_tree(root, fork):
    """Every wallpaper and splash a fork's tunaos.toml names, valid; returns (walls, themes)."""
    walls = root / "system_files/usr/share/backgrounds/tunaos"
    themes = root / "system_files/usr/share/plymouth/themes"
    walls.mkdir(parents=True)
    for name in [*fork["variants"], "tunaos-default"]:
        (walls / f"{name}.jpg").write_bytes(b"\xff\xd8\xff\xe0 jpeg")
    for theme in {v["branding"]["plymouth"] for v in fork["variants"].values()} | {fork["defaults"]["branding"]["plymouth"]}:
        theme_files(themes, theme)
    return walls, themes


def test_a_fork_without_its_drawings_is_told_which_files_to_add(tmp_path):
    """Wallpapers and splashes are fork-supplied; a missing one names the file."""
    fork = copy.deepcopy(config.load())
    fork["variants"]["marlin"]["branding"]["plymouth"] = "anchor"
    walls, themes = drawn_tree(tmp_path, fork)
    (walls / "marlin.jpg").unlink()
    for suffix in ("plymouth", "script"):
        (themes / "anchor" / f"anchor.{suffix}").unlink()
    assert config.drawn_artwork_problems(fork, tmp_path) == [
        "system_files/usr/share/backgrounds/tunaos/marlin.jpg (variants.marlin): missing",
        "system_files/usr/share/plymouth/themes/anchor/anchor.plymouth (variants.marlin.branding.plymouth): missing",
        "system_files/usr/share/plymouth/themes/anchor/anchor.script (variants.marlin.branding.plymouth): missing",
    ]


def test_a_wallpaper_that_is_not_a_jpeg_is_refused(tmp_path):
    """A renamed PNG or a placeholder passes an exists() check and then fails on the desktop."""
    fork = copy.deepcopy(config.load())
    walls, _ = drawn_tree(tmp_path, fork)
    (walls / "marlin.jpg").write_bytes(b"\x89PNG\r\n\x1a\n")
    assert config.drawn_artwork_problems(fork, tmp_path) == [
        "system_files/usr/share/backgrounds/tunaos/marlin.jpg (variants.marlin): "
        "not a JPEG (a wallpaper must be a JPEG file, not a renamed PNG or a placeholder)"]


def test_a_copied_theme_that_still_names_its_original_is_refused(tmp_path):
    """cp -r tunaos acmeos, rename the two files, and the descriptor still boots the old splash."""
    fork = copy.deepcopy(config.load())
    fork["defaults"]["branding"]["plymouth"] = "acmeos"
    _, themes = drawn_tree(tmp_path, fork)
    descriptor = themes / "acmeos" / "acmeos.plymouth"
    descriptor.write_text(descriptor.read_text().replace("themes/acmeos", "themes/tunaos"), encoding="utf-8")
    problems = config.drawn_artwork_problems(fork, tmp_path)
    assert [p.split(": ")[0] for p in problems] == [
        "system_files/usr/share/plymouth/themes/acmeos/acmeos.plymouth (defaults.branding.plymouth)"] * 2
    assert "ImageDir is '/usr/share/plymouth/themes/tunaos', expected '/usr/share/plymouth/themes/acmeos'" in problems[0]
    assert "ScriptFile is '/usr/share/plymouth/themes/tunaos/acmeos.script'" in problems[1]


def test_the_check_command_prints_every_problem_and_exits_nonzero(tmp_path):
    shutil.copytree(ROOT / "scripts", tmp_path / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(ROOT / "tunaos.toml", tmp_path / "tunaos.toml")
    drawn_tree(tmp_path, config.load())
    (tmp_path / "system_files/usr/share/backgrounds/tunaos/marlin.jpg").write_bytes(b"GIF89a")
    result = subprocess.run([sys.executable, str(tmp_path / "scripts/config.py"), "check-drawn-artwork", "--root", str(tmp_path)],
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert "drawn artwork for tunaos.toml is missing or wrong:" in result.stderr
    assert "marlin.jpg (variants.marlin): not a JPEG" in result.stderr
