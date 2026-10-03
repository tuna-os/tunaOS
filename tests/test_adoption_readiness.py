"""Tests for the adoption-facing composition of matrix evidence."""

import datetime
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "adoption_readiness", ROOT / "scripts" / "gen-adoption-readiness.py"
)
adoption = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adoption)

TODAY = datetime.date(2026, 10, 3)
SLAS = {axis: 2 for axis in adoption.REQUIRED_AXES}


def evidence(verdict="pass", date="2026-10-03"):
    return {
        axis: {"verdict": verdict, "date": date}
        for axis in adoption.REQUIRED_AXES
    }


def test_every_current_axis_must_pass():
    assert adoption.cell_status(evidence(), SLAS, TODAY) == "ready"


def test_a_current_failure_is_not_an_adoption_candidate():
    axes = evidence()
    axes["iso"]["verdict"] = "fail"
    assert adoption.cell_status(axes, SLAS, TODAY) == "failed"


def test_current_failure_remains_visible_when_another_axis_is_stale():
    axes = evidence()
    axes["builds"]["date"] = "2026-09-30"
    axes["iso"]["verdict"] = "fail"
    assert adoption.cell_status(axes, SLAS, TODAY) == "failed"


def test_missing_evidence_is_not_a_pass():
    axes = evidence()
    del axes["install"]
    assert adoption.cell_status(axes, SLAS, TODAY) == "unverified"


def test_stale_pass_is_not_a_pass():
    axes = evidence()
    axes["lifecycle"]["date"] = "2026-09-30"
    assert adoption.cell_status(axes, SLAS, TODAY) == "unverified"


def test_only_desktop_cells_that_publish_isos_are_assessed():
    config = {
        "variants": [
            {
                "id": "yellowfin",
                "flavors": [
                    {"id": "gnome", "build_iso": True},
                    {"id": "kde", "build_iso": False},
                    {"id": "base", "build_iso": True},
                ],
            }
        ]
    }
    assert adoption.iso_desktop_matrix(config) == {"yellowfin": {"gnome"}}
