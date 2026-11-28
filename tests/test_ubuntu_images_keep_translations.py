"""Ubuntu desktop images keep their translations (tunaOS#5044 follow-up).

The Ubuntu container base excludes every .mo file through
/etc/dpkg/dpkg.cfg.d/excludes. GNOME's language lists take only locales with
translations, so gnome-setup on gurnard:pantheon listed no language even with
locales-all (run 45931354235). Measured in ubuntu:24.04: with the exclude,
GnomeDesktop.get_all_locales() returns 0 locales; without it, 240.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTAINERFILE = ROOT / "Containerfile.ubuntu"
UBUNTU_EXCLUDES = """# Drop all man pages
path-exclude=/usr/share/man/*

# Drop all translations
path-exclude=/usr/share/locale/*/LC_MESSAGES/*.mo

# Drop all documentation ...
path-exclude=/usr/share/doc/*
"""


def base_stage() -> str:
    text = CONTAINERFILE.read_text()
    start = text.index("AS base-no-de")
    return text[start : text.index("\nFROM ", start)]


def keep_translations_step() -> str:
    stage = base_stage()
    at = stage.index("f=/etc/dpkg/dpkg.cfg.d/excludes")
    run = stage.rindex("RUN set -eux;", 0, at)
    end = stage.index("\n\n", at)
    return stage[run + len("RUN ") : end].replace("\\\n", "\n")


def test_the_base_stage_removes_the_translation_exclude_before_any_package() -> None:
    stage = base_stage()
    assert "f=/etc/dpkg/dpkg.cfg.d/excludes" in stage
    first_install = min(
        i for i in (stage.find("apt-get install"), stage.find("10-base-packages.sh")) if i >= 0
    )
    assert stage.index("f=/etc/dpkg/dpkg.cfg.d/excludes") < first_install


def test_the_step_drops_only_the_translation_exclude(tmp_path: Path) -> None:
    excludes = tmp_path / "excludes"
    excludes.write_text(UBUNTU_EXCLUDES)
    step = keep_translations_step().replace("/etc/dpkg/dpkg.cfg.d/excludes", str(excludes))
    subprocess.run(["sh", "-c", step], check=True)
    text = excludes.read_text()
    assert "LC_MESSAGES" not in text
    assert "path-exclude=/usr/share/man/*" in text
    assert "path-exclude=/usr/share/doc/*" in text


def test_a_base_with_no_exclude_file_builds(tmp_path: Path) -> None:
    step = keep_translations_step().replace(
        "/etc/dpkg/dpkg.cfg.d/excludes", str(tmp_path / "absent")
    )
    subprocess.run(["sh", "-c", step], check=True)
