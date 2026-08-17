"""W1 of docs/GREEN-MASTER-PLAN.md: the scoreboard scores against the bar.

The README matrix counted *promoted* cells and MATRIX-STATUS tracked the other
axes separately; nothing composed them, so "green" kept meaning the weakest
claim the pipeline makes. These tests pin the composition machinery in
scripts/gen-matrix-status.py and the graduation guard in
.github/scripts/update-build-status.sh.
"""
from __future__ import annotations

import importlib.util
import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "gms", ROOT / "scripts" / "gen-matrix-status.py"
)
gms = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gms)

CRITERIA = yaml.safe_load(
    (ROOT / ".github" / "green-criteria.yml").read_text()
)["criteria"]

# Criteria composite_section() can score per-cell today. A criterion outside
# this set that graduates to blocking turns every cell ⬜ (loud), never green
# (silent) — test_blocking_criteria_are_scoreable below is the tripwire that
# makes the graduation a conscious wiring decision instead of a surprise.
SCOREABLE = {"builds", "boots", "desktop", "install", "iso", "lifecycle",
             "no_silent_omissions"}


def test_composite_verdict_orders_fail_over_untested_over_pass() -> None:
    assert gms.composite_verdict(["pass", "pass"]) == "pass"
    assert gms.composite_verdict(["pass", "untested"]) == "untested"
    assert gms.composite_verdict(["untested", "fail"]) == "fail"
    assert gms.composite_verdict(["fail", "pass"]) == "fail"


def test_stage_verdict_treats_skipped_as_untested_not_failure() -> None:
    """tunaOS#1730: absence of evidence is not failure — and
    green-criteria.yml's skipped_is_not_green keeps it from being green."""
    assert gms._stage_verdict("success") == "pass"
    assert gms._stage_verdict("failure") == "fail"
    assert gms._stage_verdict("skipped") == "untested"
    assert gms._stage_verdict(None) == "untested"


def test_blocking_criteria_are_scoreable() -> None:
    blocking = {c["id"] for c in CRITERIA if c["enforcement"] == "blocking"}
    unwired = blocking - SCOREABLE
    assert not unwired, (
        f"{sorted(unwired)} graduated to blocking but composite_section() has "
        "no per-cell assertion for them; every cell will read ⬜. Wire the "
        "axis in scorers() (and update SCOREABLE here), or the raise is a "
        "board-wide blank, not a raised bar."
    )


def test_offline_composite_covers_the_full_matrix() -> None:
    """With no CI data at all: nothing green, every published cell counted,
    and the total agrees with the README denominator (build_image cells)."""
    lines, green, total, _ = gms.composite_section(CRITERIA, {}, {}, {}, {}, {}, {}, {})
    assert green == 0
    cfg = gms._matrix("build_image", desktops_only=False)
    assert total == sum(len(f) for f in cfg.values())
    assert any("Composite green" in l for l in lines)


def test_composite_scores_a_promoted_gated_cell_green_iff_blocking_pass() -> None:
    stage = {"albacore": {"jobs": {("gnome", "Promote"): "success",
                                   ("gnome", "Gate"): "failure"}, "date": "x"}}
    lines, green, total, _ = gms.composite_section(CRITERIA, stage, {}, {}, {}, {}, {}, {})
    blocking = {c["id"] for c in CRITERIA if c["enforcement"] == "blocking"}
    if blocking == {"builds"}:
        # A failing Gate is advisory today: the cell is still composite-green.
        assert green == 1
    else:
        # Once boots (or anything else) blocks, the same cell must not be.
        assert green == 0


def test_readme_updater_guards_the_composite_number() -> None:
    body = (ROOT / ".github" / "scripts" / "update-build-status.sh").read_text()
    assert 'select(.enforcement == "blocking")' in body
    assert "composite green" in body.casefold()
    assert '::error::' in body, (
        "the guard must fail the refresh loudly when a criterion this script "
        "cannot score graduates to blocking"
    )


def test_committed_doc_carries_the_composite_section() -> None:
    doc = (ROOT / "docs" / "MATRIX-STATUS.md").read_text()
    assert "## Composite green — the bar" in doc
    assert doc.index("## Composite green") < doc.index("## LUKS E2E"), (
        "the composite is the headline; the axis sections are its inputs"
    )


def test_provenance_records_which_run_asserted_which_criterion() -> None:
    """W1's last box: the axis tuples already carried (conclusion, date,
    run_id); the glyphs threw them away. The provenance payload comes out of
    the SAME wiring that scores the board, so the two cannot disagree."""
    stage = {
        "sailfin": {
            "jobs": {("gnome", "Promote"): "success",
                     ("gnome", "Gate"): "failure"},
            "date": "2026-08-17",
            "run_id": "32068513822",
        }
    }
    lifecycle = {"sailfin:gnome": ("success", "2026-08-17", "32040213366")}
    _, _, _, prov = gms.composite_section(
        CRITERIA, stage, {}, {}, {}, lifecycle, {}, {}
    )
    cell = prov["sailfin:gnome"]
    assert cell["builds"]["verdict"] == "pass"
    assert cell["builds"]["run"].endswith("/actions/runs/32068513822")
    assert cell["boots"]["verdict"] == "fail"
    assert cell["lifecycle"]["verdict"] == "pass"
    assert cell["lifecycle"]["run"].endswith("/actions/runs/32040213366")
    assert cell["lifecycle"]["date"] == "2026-08-17"
    # An unasserted axis is recorded as untested with NO run — absence stays
    # visible instead of becoming a hole in the payload.
    assert cell["desktop"]["verdict"] == "untested"
    assert cell["desktop"]["run"] == ""


def test_provenance_ships_with_the_doc() -> None:
    body = (ROOT / "scripts" / "gen-matrix-status.py").read_text()
    assert 'Path("docs/matrix-provenance.json")' in body
    doc = (ROOT / "docs" / "MATRIX-STATUS.md").read_text()
    assert "matrix-provenance.json" in doc
    wf = (ROOT / ".github" / "workflows" / "matrix-status.yml").read_text()
    assert wf.count("docs/matrix-provenance.json") >= 2, (
        "the refresh workflow must both diff-check AND git-add the JSON, or "
        "it regenerates and then silently fails to ship"
    )
