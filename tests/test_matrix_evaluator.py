"""The composite scoring rules are a pure module (tunaOS#2532).

scripts/gen-matrix-status.py collected evidence over `gh` and HTTP, scored it,
and rendered Markdown in one namespace, so a test of a scoring rule had to
patch transport. Phase 1 of the split moves the scoring into
scripts/matrix_evaluator.py. These tests pin that boundary: the evaluator
takes plain dicts and does no I/O, and the generator's composite_section()
renders exactly what the evaluator decides.
"""
from __future__ import annotations

import ast
import datetime
import importlib.util
import pathlib
import sys
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
EVALUATOR = ROOT / "scripts" / "matrix_evaluator.py"

sys.path.insert(0, str(EVALUATOR.parent))
import matrix_evaluator as me  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "gms_evaluator_boundary", ROOT / "scripts" / "gen-matrix-status.py"
)
gms = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gms)

REPO = "tuna-os/tunaOS"
TODAY = datetime.date(2026, 10, 3)

CRITERIA = [
    {"id": "builds", "enforcement": "blocking"},
    {"id": "boots", "enforcement": "blocking",
     "scope": {"excludes_flavor_suffixes": ["-nvidia"]}},
    {"id": "desktop", "enforcement": "blocking", "freshness_sla_days": 7},
    {"id": "iso", "enforcement": "advisory"},
    {"id": "parity", "enforcement": "unimplemented"},
]

MATRICES = me.CellMatrices(
    published={"albacore": {"gnome", "kde", "base-nvidia"}},
    desktops={"albacore": {"gnome", "kde"}},
    isos={"albacore": {"gnome"}},
)


def _stage(**cells: tuple[str, str]) -> dict:
    jobs = {}
    for flavor, (promote, gate) in cells.items():
        flavor = flavor.replace("_", "-")
        jobs[(flavor, "Promote")] = promote
        jobs[(flavor, "Gate")] = gate
    return {"albacore": {"jobs": jobs, "date": "2026-10-01",
                         "run_id": "100", "cell_run": {}}}


EVIDENCE = me.AxisEvidence(
    stage=_stage(gnome=("success", "success"), kde=("success", "success"),
                 base_nvidia=("success", "skipped")),
    contract={
        "albacore:gnome": ("success", "2026-10-02", "200"),
        # Older than the 7-day SLA: the pass no longer counts.
        "albacore:kde": ("success", "2026-09-01", "201"),
    },
    smoke={"albacore:gnome": ("failure", "2026-10-02", "300")},
)


def test_the_evaluator_does_no_io() -> None:
    """The evaluator imports no transport and touches no file."""
    tree = ast.parse(EVALUATOR.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"__future__", "datetime", "dataclasses"}, imported
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "open" not in calls


def test_plain_dicts_score_every_cell() -> None:
    result = me.evaluate_composite(CRITERIA, MATRICES, EVIDENCE, REPO, TODAY)
    assert result.verdicts == {
        "albacore:gnome": "pass",
        # The desktop pass is stale, so the axis scores untested.
        "albacore:kde": "untested",
        # boots is out of scope for -nvidia, so the skipped Gate does not
        # count against it, and desktop does not apply to a non-desktop cell.
        "albacore:base-nvidia": "pass",
    }
    assert (result.green, result.total) == (2, 3)
    assert result.blocking == ["builds", "boots", "desktop"]
    assert result.advisory == ["iso"]
    assert result.unimplemented == ["parity"]


def test_an_advisory_failure_is_recorded_but_does_not_block() -> None:
    result = me.evaluate_composite(CRITERIA, MATRICES, EVIDENCE, REPO, TODAY)
    assert result.provenance["albacore:gnome"]["iso"]["verdict"] == "fail"
    assert result.verdicts["albacore:gnome"] == "pass"


def test_provenance_keeps_its_schema() -> None:
    result = me.evaluate_composite(CRITERIA, MATRICES, EVIDENCE, REPO, TODAY)
    gnome = result.provenance["albacore:gnome"]
    assert set(gnome) == {"builds", "boots", "desktop", "install",
                          "lifecycle", "no_silent_omissions", "parity", "iso"}
    assert set(result.provenance["albacore:base-nvidia"]) == {"builds", "boots"}
    assert gnome["desktop"] == {
        "verdict": "pass",
        "date": "2026-10-02",
        "run": "https://github.com/tuna-os/tunaOS/actions/runs/200",
        "evidence": "https://github.com/tuna-os/tunaOS/actions/runs/200#artifacts",
    }
    # Nothing asserted install: untested, with no date and no link.
    assert gnome["install"] == {"verdict": "untested", "date": "",
                                "run": "", "evidence": ""}


def test_a_green_cell_links_runtime_evidence_first() -> None:
    result = me.evaluate_composite(CRITERIA, MATRICES, EVIDENCE, REPO, TODAY)
    # boots (Gate) outranks desktop and builds; both are run 100 here.
    assert result.evidence["albacore:gnome"] == (
        "https://github.com/tuna-os/tunaOS/actions/runs/100#artifacts"
    )
    assert "albacore:kde" not in result.evidence


def test_composite_section_renders_what_the_evaluator_decides() -> None:
    expected = me.evaluate_composite(CRITERIA, MATRICES, EVIDENCE, REPO, TODAY)

    def matrix(key: str, desktops_only: bool) -> dict[str, set[str]]:
        return MATRICES.desktops if desktops_only else MATRICES.published

    with mock.patch.object(gms, "_matrix", side_effect=matrix), \
            mock.patch.object(gms, "iso_matrix", return_value=MATRICES.isos):
        lines, green, total, provenance = gms.composite_section(
            CRITERIA, EVIDENCE.stage, EVIDENCE.contract, EVIDENCE.luks,
            EVIDENCE.smoke, EVIDENCE.lifecycle, EVIDENCE.omissions,
            EVIDENCE.parity, today=TODAY,
        )
    assert (green, total) == (expected.green, expected.total)
    assert provenance == expected.provenance
    row = next(line for line in lines if line.startswith("| **albacore**"))
    link = expected.evidence["albacore:gnome"]
    assert row == f"| **albacore** | [{gms.PASS}]({link}) | {gms.UNTESTED} | — | — | — |"


def test_the_generator_reexports_the_evaluator_rules() -> None:
    """Callers that import these from the generator keep working."""
    assert gms.composite_verdict is me.composite_verdict
    assert gms.criterion_scope_allows is me.criterion_scope_allows
    assert gms.is_stale is me.is_stale
    assert gms.green_axes_without_evidence is me.green_axes_without_evidence
    assert gms._stage_verdict is me.stage_verdict
