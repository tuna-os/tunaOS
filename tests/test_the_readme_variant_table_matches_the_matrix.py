"""The README's hand-written variant table must list the desktops we build.

That table is the first thing a reader sees, and it is the only part of the
README that is NOT generated: `update-build-status.yml` rewrites the build
status block further down, and never touches this one. So it drifts silently,
and it has -- measured 2026-09-13, ten of fourteen rows disagreed with
`.github/build-config.yml`, in both directions:

    guppy         advertised GNOME, which tunaOS#2451 removed for the GNOME 50
                  floor; omitted XFCE, which it does build
    grouper       advertised Niri, which it has never built
    flounder      advertised COSMIC and Niri, neither built
    flounder-sid  advertised COSMIC and Niri, neither built
    wahoo         omitted COSMIC and KDE
    sailfin       omitted COSMIC
    bonito        omitted XFCE
    skipjack      omitted XFCE
    yellowfin     omitted XFCE
    albacore      omitted XFCE

Advertising a desktop nobody builds is the worse direction: a reader pulls
`ghcr.io/tuna-os/flounder:cosmic` and gets a 404, and nothing in the repo
disagreed with the claim.

The generated block below it is not a substitute. It reports how many cells
are green, per variant -- not which desktops exist -- so a variant can read
`5/5` while the row above it names a flavor that was never built.

`base` is excluded because every variant has one and only the base-centric
rows mention it, and the hardware/storage suffixes (-hwe, -nvidia, -cachyos,
-asahi, -t2, -zfs) are excluded because the column lists desktops, not the
matrix. Change either convention and this test needs to change with it, which
is the point: the rule becomes explicit instead of remembered.
"""
from __future__ import annotations

import pathlib
import re

import pytest

yaml = pytest.importorskip("yaml")

ROOT = pathlib.Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
CONFIG = ROOT / ".github" / "build-config.yml"

# Longest first: -nvidia-hwe must strip before -hwe.
HARDWARE_SUFFIXES = ("-nvidia-hwe", "-nvidia", "-hwe", "-cachyos",
                     "-asahi", "-t2", "-zfs")


def _desktop_of(flavor_id: str) -> str:
    for suffix in HARDWARE_SUFFIXES:
        if flavor_id.endswith(suffix):
            return _desktop_of(flavor_id[: -len(suffix)])
    return flavor_id


def _config_desktops() -> dict[str, set[str]]:
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    out = {}
    for v in cfg["variants"]:
        names = {_desktop_of(f["id"]) for f in v["flavors"] if f.get("build_image")}
        names.discard("base")
        out[v["id"]] = names
    return out


def _readme_rows() -> dict[str, set[str]]:
    """The desktop column of each hand-written variant row.

    Parenthetical notes are dropped before splitting on commas -- "GNOME
    (x86_64 only, see note)" is one entry, not two.
    """
    rows = {}
    for line in README.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*\S+\s+\*\*([A-Za-z ]+?)\*\*\s*\|", line)
        if not m or line.count("|") < 5:
            continue
        variant = m.group(1).strip().lower().replace(" ", "-")
        column = re.sub(r"\([^)]*\)", "", line.split("|")[4])
        names = {t.strip().lower() for t in column.split(",")}
        names -= {"", "base"}
        rows[variant] = names
    return rows


def test_the_table_and_the_config_are_both_readable():
    """Guard both selectors: either coming back empty, or keyed differently,
    would make the assertion below vacuously true (tunaOS#1730)."""
    rows, conf = _readme_rows(), _config_desktops()
    assert rows, "no variant rows parsed out of README.md"
    assert conf, "no variants parsed out of build-config.yml"
    shared = set(rows) & set(conf)
    assert len(shared) >= 10, (
        f"only {sorted(shared)} matched by name; the table's row format or the "
        "config's variant ids moved, so most rows are being skipped silently")


@pytest.mark.parametrize("variant", sorted(set(_readme_rows()) & set(_config_desktops())))
def test_a_variant_row_lists_the_desktops_it_builds(variant: str):
    listed = _readme_rows()[variant]
    built = _config_desktops()[variant]
    assert listed == built, (
        f"README's {variant} row lists {sorted(listed) or '[]'} but "
        f"build-config.yml builds {sorted(built) or '[]'}.\n"
        f"  advertised but not built: {sorted(listed - built) or '[]'}  "
        f"(a reader pulling that tag gets a 404)\n"
        f"  built but not advertised: {sorted(built - listed) or '[]'}\n"
        "Update the row, or the flavor list, so the two say the same thing."
    )
