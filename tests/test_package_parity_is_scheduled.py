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


def test_upstream_references_declare_only_real_cells() -> None:
    """The map is a reviewed declaration; a typo'd variant or a flavor the
    variant does not build would silently measure nothing forever."""
    criteria = yaml.safe_load(
        (ROOT / ".github" / "green-criteria.yml").read_text()
    )["criteria"]
    c = next(c for c in criteria if c["id"] == "parity")
    refs = c.get("upstream_references")
    assert refs, "W6 box 2: the upstream map is the criterion's full claim"
    cfg = yaml.safe_load(
        (ROOT / ".github" / "build-config.yml").read_text()
    )
    flavors_by_variant = {
        v["id"]: {f["id"] for f in v.get("flavors", [])}
        for v in cfg["variants"]
    }
    for de, mapping in refs.items():
        for variant, ref in mapping.items():
            assert variant in flavors_by_variant, f"unknown variant {variant}"
            assert de in flavors_by_variant[variant], (
                f"{variant} declares no {de} flavor"
            )
            assert ref.startswith("ghcr.io/ublue-os/"), (
                "upstream anchors are Universal Blue reference images"
            )


def test_upstream_audit_reads_the_declared_map() -> None:
    body = SCRIPT.read_text()
    assert "--upstream-audit" in body
    assert "upstream_references" in body, (
        "the audit must read the criteria map, not a second hardcoded roster"
    )


def test_upstream_sweep_is_wired_and_fails_when_it_measures_nothing() -> None:
    body = WORKFLOW.read_text()
    assert "--upstream-audit" in body
    assert "package-parity-upstream" in body
    assert "upstream parity measured zero cells" in body, (
        "a sweep that measured nothing must fail loudly, like the base audit"
    )
