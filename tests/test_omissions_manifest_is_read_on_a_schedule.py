"""W5 of docs/GREEN-MASTER-PLAN.md: the omissions manifest is finally read.

Every image writes /usr/share/tunaos/missing-on-*.txt; until now nothing read
it on a schedule, so a package silently skipped in an already-published image
stayed invisible (the tunaOS#858 class — published, no desktop). The sweep now
runs the SAME gate the build runs (verify-package-wishlist.sh) against every
image it pulls: one multi-GB pull, two axes.
"""
from __future__ import annotations

import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SWEEP = ROOT / ".github" / "workflows" / "desktop-contract-sweep.yml"
spec = importlib.util.spec_from_file_location(
    "gms", ROOT / "scripts" / "gen-matrix-status.py"
)
gms = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gms)


def test_sweep_runs_the_same_gate_the_build_runs() -> None:
    body = SWEEP.read_text(encoding="utf-8")
    assert "verify-package-wishlist.sh" in body, (
        "the omissions read must be the build gate itself, not a "
        "reimplementation that can drift from it"
    )
    assert "TUNAOS_WISHLIST_ALLOWLIST" in body
    assert "package-miss-allowlist.txt" in body


def test_sweep_mirrors_the_hummingbird_skip() -> None:
    """The gate skips hummingbird at build time (bootstrap gap is measured by
    its own tooling); the published-image read must skip for the same
    recorded reason, not fail those cells for a decision already made."""
    assert "IS_HUMMINGBIRD" in SWEEP.read_text(encoding="utf-8")


def test_result_json_carries_the_omissions_verdict() -> None:
    body = SWEEP.read_text(encoding="utf-8")
    assert "omissions_status" in body
    assert "omissions_reason" in body
    # A lost job's synthesized row must score untested, not clean.
    assert body.count('omissions_status: "untested"') >= 1


def test_omissions_results_translates_only_real_verdicts() -> None:
    """pass→success, fail→failure; artifacts predating the field, and cells
    whose image was never read, yield nothing — cell() then renders ⬜."""
    gms._BASELINE_CACHE = (
        [
            {"cell": "a:gnome", "status": "pass", "omissions_status": "pass"},
            {"cell": "b:kde", "status": "fail", "omissions_status": "fail"},
            {"cell": "c:xfce", "status": "missing",
             "omissions_status": "untested"},
            {"cell": "d:niri", "status": "pass"},  # pre-field artifact
        ],
        "2026-08-17", "1",
    )
    try:
        got = gms.omissions_results()
    finally:
        gms._BASELINE_CACHE = None
    assert got == {
        "a:gnome": ("success", "2026-08-17", "1"),
        "b:kde": ("failure", "2026-08-17", "1"),
    }


def test_composite_scores_the_omissions_axis() -> None:
    """An unallowlisted omission on an otherwise-perfect cell must show in
    the composite the moment no_silent_omissions graduates to blocking —
    and today (advisory) must not block."""
    criteria = [
        {"id": "builds", "enforcement": "blocking"},
        {"id": "no_silent_omissions", "enforcement": "blocking"},
    ]
    stage = {"albacore": {"jobs": {("gnome", "Promote"): "success"},
                          "date": "x"}}
    omissions = {"albacore:gnome": ("failure", "x", "1")}
    _, green, _, _ = gms.composite_section(
        criteria, stage, {}, {}, {}, {}, omissions, {}
    )
    assert green == 0, "a cell shipping silent omissions must not be green"


def test_criterion_is_now_advisory_with_a_named_assertion() -> None:
    import yaml
    criteria = yaml.safe_load(
        (ROOT / ".github" / "green-criteria.yml").read_text()
    )["criteria"]
    c = next(c for c in criteria if c["id"] == "no_silent_omissions")
    assert c["enforcement"] == "advisory"
    assert "desktop-contract-sweep" in c["asserted_by"]
