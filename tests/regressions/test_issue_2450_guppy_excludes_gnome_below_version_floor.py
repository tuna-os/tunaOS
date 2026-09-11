"""#2450: guppy:gnome fails the GNOME 50 version floor (Gentoo ::gentoo tops out at 49.9).

Gentoo's ::gentoo main tree carries GNOME 49.9 (measured 49.7-49.9), while the
desktop contract (manifests/desktops/gnome.yaml minimum_version: 50,
verify-desktop-experience.sh GNOME_MINIMUM_MAJOR=50) requires at least GNOME 50.
Every scheduled Build Guppy run failed deterministically on guppy:gnome since
the floor was introduced on 2026-09-03 (run 34471218388).

Until Gentoo packages GNOME 50+ or an overlay provides it, guppy must not declare
the gnome flavor in the build matrix (.github/build-config.yml), avoiding repeated
CI failure cycles.

Falsification: structural — fails if `gnome` is declared in guppy's flavors in
.github/build-config.yml or if guppy flavor count in build-variant.yml rots.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / ".github" / "build-config.yml"
BUILD_VARIANT = ROOT / ".github" / "workflows" / "build-variant.yml"


def test_guppy_does_not_declare_gnome_flavor() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    guppy = next(v for v in config["variants"] if v["id"] == "guppy")
    flavors = {f["id"] for f in guppy.get("flavors", [])}
    assert "gnome" not in flavors, (
        "guppy declares the gnome flavor, but Gentoo ::gentoo tops out at "
        "GNOME 49.9 and fails the GNOME 50 floor (#2450)"
    )


def test_guppy_exclusion_reason_is_documented() -> None:
    raw = CONFIG.read_text(encoding="utf-8")
    assert "2450" in raw, (
        ".github/build-config.yml should document the guppy:gnome floor "
        "exclusion referencing #2450"
    )


def test_guppy_flavor_count_matches_nightly_schedule_registry() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    guppy = next(v for v in config["variants"] if v["id"] == "guppy")
    declared_count = len(guppy.get("flavors", []))
    assert declared_count == 3, f"expected 3 guppy flavors, got {declared_count}"
