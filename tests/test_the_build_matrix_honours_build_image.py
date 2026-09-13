"""build-variant.yml must not build flavors the config turns off.

`build_image: false` is how build-config says "do not build this". Every other
consumer honours it -- luks-e2e, bootc-lifecycle, catalog-facts, daily-verify,
live-overlay, live-initramfs and desktop-contract-sweep all
`select(.build_image == true)`. The matrix generator in build-variant.yml did
not, so those flavors were still built, and they fail, because they are turned
off for reasons that make them unbuildable.

Measured 2026-09-13 across the newest run of each variant:

    albacore   gnome-asahi   2 jobs, all failure   (run 34726078460)
    yellowfin  gnome-asahi   2 jobs, all failure   (run 34705563513)
    skipjack   gnome-asahi   2 jobs, all failure   (run 34705564876)
    flounder   gnome         3 jobs, all failure   (run 34657636354)
    flounder   gnome-nvidia  2 jobs, all failure   (run 34657636354)

    albacore's says it plainly: "no image found in image index for
    architecture arm64" -- gnome-asahi is the arm64 leg of a gnome that
    build-config pins to amd64, and says so in a comment right above the
    `build_image: false` that was being ignored.

Eleven guaranteed-red jobs per nightly, and they set the run conclusion:
flounder reported `failure` in that run with all five of its published flavors
promoted.

No cell count moves. scripts/gen-matrix-status.py already scores only
`build_image` flavors, so these were never counted -- 144 config entries
filter to exactly the 138 the matrix claims today.
"""
from __future__ import annotations

import pathlib
import re

import pytest

yaml = pytest.importorskip("yaml")

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".github" / "build-config.yml"
WORKFLOW = ROOT / ".github" / "workflows" / "build-variant.yml"


def _flatten_step() -> str:
    """The jq pipeline that turns build-config into the build matrix."""
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("FULL_MATRIX=$(yq")
    end = text.index("make_image_matrix()", start)
    return text[start:end]


def _config():
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def test_the_flatten_step_is_where_we_think_it_is():
    """Guard the selector: reading the wrong slice would make the assertion
    below vacuously true (tunaOS#1730)."""
    step = _flatten_step()
    assert ".variants[]" in step and ".flavors[]" in step, (
        "the matrix flatten step moved; this test is reading the wrong part "
        "of build-variant.yml")


def test_the_matrix_filters_on_build_image():
    step = _flatten_step()
    assert re.search(r"select\(\s*\.build_image", step), (
        "build-variant.yml's matrix does not filter on build_image, so a "
        "flavor the config turns off is still built. Those flavors are off "
        "because they cannot build -- 11 jobs failed this way in one night "
        "across albacore, yellowfin, skipjack and flounder, and they set the "
        "run conclusion for variants whose published flavors all promoted.")


def test_no_disabled_flavor_is_the_parent_of_an_enabled_one():
    """What makes the filter safe, stated as a property.

    A stage-N flavor is built FROM its prefix (gnome-nvidia layers on gnome),
    so switching the matrix to build_image-only would orphan a child whose
    parent is off. That is true of no flavor today -- flounder turns gnome AND
    gnome-nvidia off together -- and this fails if a future config breaks it,
    which is the moment to revisit the filter rather than discover it in a
    nightly.
    """
    for variant in _config()["variants"]:
        flavors = {f["id"]: bool(f.get("build_image")) for f in variant["flavors"]}
        for fid, enabled in flavors.items():
            if not enabled:
                continue
            parents = [p for p in flavors if p != fid and fid.startswith(p + "-")]
            for parent in parents:
                assert flavors[parent], (
                    f"{variant['id']}:{fid} is built (build_image: true) but "
                    f"layers on {variant['id']}:{parent}, which is turned off. "
                    f"With the matrix filtering on build_image the parent is "
                    f"never built and the child cannot resolve it.")


def test_the_filtered_matrix_is_the_cell_count_we_publish():
    """144 config entries filter to the 138 the docs claim today.

    Not a coincidence worth leaving implicit: if this number drifts from
    docs/MATRIX-STATUS.md and the README, one of the two is wrong about what
    the product is.
    """
    cfg = _config()
    total = sum(len(v["flavors"]) for v in cfg["variants"])
    built = sum(1 for v in cfg["variants"]
                for f in v["flavors"] if f.get("build_image"))
    assert built < total, (
        "no flavor is turned off at all; either the config changed shape or "
        "build_image stopped being used, and the filter is now a no-op")
    assert built == 138, (
        f"the matrix builds {built} flavors; the published cell count is 138. "
        "If the matrix legitimately changed size, update docs/MATRIX-STATUS.md, "
        "the README and this number together.")
