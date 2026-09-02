"""A hand-written matrix size goes stale the first time a flavor is added.

#2006 spotted that docs/DEVELOPER-GUIDE.md still said 142 and corrected it to
143. The configured number was already 145: the correction was itself two
cells behind by the time it was written, because nothing checks it.

This is that check. It is deliberately narrow -- the count in the guide's
own section heading and its diagram -- because those are the two places a
reader takes as authoritative. Every other count in the README is written by
.github/scripts/update-build-status.sh at refresh time and cannot drift.
"""
from __future__ import annotations

import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".github" / "build-config.yml"
GUIDE = ROOT / "docs" / "DEVELOPER-GUIDE.md"


def configured_cells() -> int:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    return sum(1 for variant in config["variants"]
               for flavor in variant.get("flavors", [])
               if flavor.get("build_image"))


def test_the_guides_heading_names_the_configured_cell_count():
    n = configured_cells()
    heading = re.search(r"^## \d+\. The build matrix: (\d+) cells$",
                        GUIDE.read_text(encoding="utf-8"), re.M)
    assert heading, "docs/DEVELOPER-GUIDE.md lost its build-matrix heading"
    assert int(heading.group(1)) == n, (
        f"the guide says {heading.group(1)} cells; .github/build-config.yml "
        f"declares {n} with build_image: true"
    )


def test_the_diagram_does_not_carry_a_second_stale_number():
    n = configured_cells()
    for stale in re.findall(r"Built X/(\d+) · composite green Y/(\d+)",
                            GUIDE.read_text(encoding="utf-8")):
        assert {int(x) for x in stale} == {n}, (
            f"the README box in the guide's diagram still says {stale}, "
            f"not {n}"
        )
