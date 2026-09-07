"""bootc is pinned by a CEILING, and the two places that say so must agree.

Build Marlin was red on every run for days: Renovate bumped bootc to v1.16.11
on 2026-09-03, and v1.16.11 made `selinux` a hard, non-optional dependency of
bootc-lib (crates/lib/Cargo.toml: `selinux = { workspace = true }`, no feature
flag). selinux-sys' build script needs selinux/selinux.h, and Arch does not
ship it -- `libselinux` is not in the official repos at all, so there is
nothing to add to Containerfile.arch's bootc-builder stage. Every marlin build
died with:

    selinux-sys: Failed to find 'selinux/selinux.h'

Verified by building that stage on a clean archlinux:latest at both versions:
v1.16.11 fails as above, v1.16.10 completes.

A pin alone does not hold -- Renovate would simply bump it again next run,
which is how this arrived. The renovate.json ceiling is the half that makes it
stick, so these tests pin BOTH and require them to agree.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]

# The last bootc release that builds on Arch. Raise only with evidence: build
# Containerfile.arch's bootc-builder stage at the new version first.
CEILING = "1.16.10"


def pinned_version() -> str:
    d = yaml.safe_load((ROOT / "image-versions.yaml").read_text())
    return d["downloads"]["bootc"].lstrip("v")


def ceiling_rule() -> dict:
    rules = json.loads((ROOT / "renovate.json").read_text())["packageRules"]
    matching = [
        r for r in rules if "bootc-dev/bootc" in r.get("matchPackageNames", [])
    ]
    assert len(matching) == 1, "expected exactly one bootc packageRule"
    return matching[0]


def test_the_pin_is_at_or_below_the_ceiling() -> None:
    assert pinned_version() == CEILING, (
        f"image-versions.yaml pins bootc {pinned_version()}, but {CEILING} is "
        "the last release that builds on Arch"
    )


def test_renovate_cannot_bump_past_the_ceiling() -> None:
    """The half that makes the pin stick.

    Without this, Renovate re-bumps and Build Marlin goes red again -- which
    is exactly how it arrived.
    """
    assert ceiling_rule().get("allowedVersions") == f"<={CEILING}"


def test_the_rule_says_why_and_when_to_lift_it() -> None:
    """A ceiling with no stated exit condition becomes permanent by accident."""
    description = ceiling_rule().get("description", "").lower()
    assert "selinux" in description
    assert "arch" in description
    # It must name what would make lifting it correct, not just forbid the bump.
    assert "optional" in description or "libselinux" in description


def test_the_pin_documents_the_direction() -> None:
    """FLOOR and CEILING pins live in this same file and mean opposite things.

    tacklebox directly below is a floor -- moving it UP is always fine. Reading
    one as the other is how a well-intentioned bump reintroduces this.
    """
    text = (ROOT / "image-versions.yaml").read_text()
    block = text[text.index("depName=bootc-dev/bootc"):]
    block = block[: block.index('bootc: "')]
    assert "CEILING" in block
    assert "selinux" in block
