"""W6 of docs/GREEN-MASTER-PLAN.md: parity measured daily, fed to the board.

package-parity.sh existed and ran never — criterion 7 read "not scheduled".
The workflow now audits every desktop against its own base daily (the #858
no-desktop-at-all shape) and the verdicts flow to the composite.
"""
from __future__ import annotations

import importlib.util
import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "package-parity.yml"
SCRIPT = ROOT / "scripts" / "package-parity.sh"
spec = importlib.util.spec_from_file_location(
    "gms", ROOT / "scripts" / "gen-matrix-status.py"
)
gms = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gms)


def test_workflow_is_scheduled_and_advisory_shaped() -> None:
    doc = yaml.safe_load(WORKFLOW.read_text())
    assert "schedule" in doc[True] if True in doc else "schedule" in doc["on"]
    body = WORKFLOW.read_text()
    assert "package-parity-baseline" in body, "the scoreboard reads this artifact"
    assert "measured zero cells" in body, (
        "an audit that measured nothing must fail loudly — 52 quiet ⬜ cells "
        "is the failure mode this program exists to stop"
    )


def test_audit_roster_derives_from_build_config() -> None:
    body = SCRIPT.read_text()
    assert ".github/build-config.yml" in body, (
        "a hardcoded variant list silently omits declared variants "
        "(bonito-rawhide, flounder-sid and gurnard were missing)"
    )
    assert "PARITY_JSON" in body


def test_parity_results_maps_verdicts() -> None:
    gms._PARITY_CACHE = (
        [
            {"cell": "a:gnome", "verdict": "ok", "delta": 400},
            {"cell": "b:kde", "verdict": "BROKEN: no more packages than base",
             "delta": -2},
            {"cell": "c:xfce", "verdict": "suspect: only 3 added", "delta": 3},
            {"cell": "d:niri", "verdict": "unmeasured: no base manifest",
             "delta": 0},
        ],
        "2026-08-17", "1",
    )
    try:
        got = gms.parity_results()
    finally:
        gms._PARITY_CACHE = None
    assert got == {
        "a:gnome": ("success", "2026-08-17", "1"),
        "b:kde": ("failure", "2026-08-17", "1"),
        "c:xfce": ("failure", "2026-08-17", "1"),
    }, "ok passes; BROKEN and suspect fail; unmeasured renders ⬜"


def test_criterion_is_advisory_with_the_cadence_named() -> None:
    criteria = yaml.safe_load(
        (ROOT / ".github" / "green-criteria.yml").read_text()
    )["criteria"]
    c = next(c for c in criteria if c["id"] == "parity")
    assert c["enforcement"] == "advisory"
    assert "package-parity.yml" in c["asserted_by"]


def test_committed_doc_carries_the_parity_section() -> None:
    doc = (ROOT / "docs" / "MATRIX-STATUS.md").read_text()
    assert "## Package parity" in doc
