"""The master plan must cover the whole matrix and stay anchored to the criteria.

A plan document that silently omits a variant is how cells fall off the radar:
nobody schedules work for a variant no plan names. And a plan that drifts from
.github/green-criteria.yml stops being a plan for *green* and becomes a plan
for whatever it remembered green meaning.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs/GREEN-MASTER-PLAN.md"
CONFIG = ROOT / ".github/build-config.yml"
CRITERIA = ROOT / ".github/green-criteria.yml"


@pytest.fixture(scope="module")
def plan():
    return PLAN.read_text(encoding="utf-8")


def test_every_variant_has_a_section(plan):
    """13 variants, 13 sections. An unnamed variant is an unplanned variant."""
    variants = [v["id"] for v in yaml.safe_load(CONFIG.read_text())["variants"]]
    missing = [v for v in variants if f"### {v} " not in plan and f"### {v}(" not in plan]
    assert not missing, f"variants with no plan section: {missing}"


def test_the_plan_defers_to_the_criteria_file(plan):
    """One source of truth for what green means; the plan sequences it."""
    assert "green-criteria.yml" in plan
    assert "GREEN-CRITERIA.md" in plan


def test_every_criterion_maps_to_a_workstream(plan):
    """Ten criteria; each must be someone's work, not ambient hope.

    Checked loosely by id-ish keywords rather than prose, so rewording the
    plan does not break this — dropping a whole criterion does.
    """
    spec = yaml.safe_load(CRITERIA.read_text())
    keywords = {
        "builds": "build",
        "desktop": "desktop",
        "boots": "gate",
        "iso": "ISO",
        "install": "LUKS",
        "lifecycle": "Lifecycle",
        "parity": "parity",
        "no_silent_omissions": "omissions",
        "rebuildable": "pin",
        "arch_honesty": "honesty",
    }
    ids = {c["id"] for c in spec["criteria"]}
    assert set(keywords) == ids, "keyword map out of sync with criteria ids"
    lowered = plan.lower()
    missing = [cid for cid, kw in keywords.items() if kw.lower() not in lowered]
    assert not missing, f"criteria with no presence in the plan: {missing}"


def test_undiagnosed_items_are_marked_not_hidden(plan):
    """The plan's honesty contract: unknowns say so.

    If every 'undiagnosed' marker disappears, either the work happened (great,
    and this list shrinks with it) or someone edited the uncertainty away
    without doing the diagnosis. This test forces that edit to be visible.
    """
    assert plan.count("undiagnosed") >= 1 or "Phase 0" not in plan
