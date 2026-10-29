"""tunaOS#3932: a beta-cell lifecycle verdict must come from a validation run.

The 2026-10-25 nightly refresh (f854697f, #3931) scored all eight
bonito-rawhide and flounder-sid lifecycle cells `fail` from run 38713238238
(2026-10-15). The committed-snapshot test from c4646856 required those cells
to read untested, so main went red. The generator was correct. In that run
the jobs were unprefixed (`bonito-rawhide:gnome (amd64)` and similar) and
failed in the stable-lane step `Validate bootc image update, rebase, rollback
& aliases`. From da167151 (2026-08-10) until #3720 merged (7f590be8,
2026-10-23), the beta predicate in bootc-lifecycle.yml was inverted
(`"rawhide" | test($v)`), so rawhide and sid cells ran the real validation.
79c0ed38, also merged in #3720, made lifecycle_results() score those
historical unprefixed validations and keep skipping `BETA ` existence probes.
The old snapshot test still encoded the earlier rule and stayed green only
because no live regeneration was committed until that nightly.

The invariant that matters: a beta cell's lifecycle verdict is untested, or
it is dated no later than the routing fix. After that date the workflow names
every beta job `BETA ...`, so a later verdict can only be a leaked probe or
a routing regression.

Falsification: behavioural -- test_a_probe_dated_after_the_routing_fix_is_rejected
gives the checker a beta verdict dated after the fix and expects a violation.
The test test_committed_snapshot_scores_beta_lifecycle_only_from_validation_runs
fails on any committed snapshot of that shape. Structural -- restore the
inverted `"rawhide" | test($v)` predicate in bootc-lifecycle.yml and
test_lifecycle_workflow_routes_beta_cells_to_probe_jobs fails.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("gen_matrix_status_3932", ROOT / "scripts/gen-matrix-status.py")
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load scripts/gen-matrix-status.py")
gms = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gms)

# Merge 7f590be8 (#3720) put the corrected beta routing on main on this date.
BETA_ROUTING_FIXED = "2026-10-23"
UNTESTED = {"date": "", "evidence": "", "run": "", "verdict": "untested"}


def beta_lifecycle_violations(provenance: dict) -> list[str]:
    violations = []
    for cell, axes in sorted(provenance["cells"].items()):
        result = axes.get("lifecycle")
        if result is None or not gms._is_beta_lifecycle_cell(cell) or result == UNTESTED:
            continue
        if result["verdict"] not in ("pass", "fail") or not result["run"]:
            violations.append(f"{cell}: tested verdict without a run: {result}")
        elif not result["date"] or result["date"] > BETA_ROUTING_FIXED:
            violations.append(f"{cell}: dated {result['date']!r}, after beta jobs became probes")
    return violations


def committed_provenance() -> dict:
    return json.loads((ROOT / "docs/matrix-provenance.json").read_text())


def test_committed_snapshot_scores_beta_lifecycle_only_from_validation_runs():
    provenance = committed_provenance()
    beta_lifecycle = [
        axes["lifecycle"]
        for cell, axes in provenance["cells"].items()
        if cell.startswith(("bonito-rawhide:", "flounder-sid:")) and "lifecycle" in axes
    ]
    # Beta cells stay in the lifecycle denominator, tested or not.
    assert len(beta_lifecycle) == 8
    assert beta_lifecycle_violations(provenance) == []
    verdicts = [axes["lifecycle"]["verdict"] for axes in provenance["cells"].values() if "lifecycle" in axes]
    assert provenance["summary"]["lifecycle"] == {
        "passed": verdicts.count("pass"),
        "tested": sum(verdict != "untested" for verdict in verdicts),
        "total": len(verdicts),
    }


def test_a_probe_dated_after_the_routing_fix_is_rejected():
    provenance = copy.deepcopy(committed_provenance())
    provenance["cells"]["bonito-rawhide:gnome"]["lifecycle"] = {
        "date": "2026-10-24",
        "evidence": "https://github.com/tuna-os/tunaOS/actions/runs/1#artifacts",
        "run": "https://github.com/tuna-os/tunaOS/actions/runs/1",
        "verdict": "pass",
    }
    assert beta_lifecycle_violations(provenance) == [
        "bonito-rawhide:gnome: dated '2026-10-24', after beta jobs became probes"
    ]


def test_generator_scores_historical_validation_and_never_a_probe():
    raw = {
        "BETA bonito-rawhide:gnome (amd64)": ("success", "2026-10-24", "3"),
        "bonito-rawhide:gnome (amd64)": ("failure", "2026-10-15", "2"),
        "BETA flounder-sid:kde (amd64)": ("success", "2026-10-24", "3"),
    }
    got = gms.lifecycle_results(raw)
    assert got["bonito-rawhide:gnome"] == ("failure", "2026-10-15", "2")
    assert "flounder-sid:kde" not in got


def test_lifecycle_workflow_routes_beta_cells_to_probe_jobs():
    workflow = (ROOT / ".github/workflows/bootc-lifecycle.yml").read_text()
    assert 'name: "BETA ${{ matrix.variant }}:${{ matrix.flavor }} (${{ matrix.arch }})"' in workflow
    predicates = re.findall(r"\| \((.*)\) as \$is_beta", workflow)
    assert len(predicates) == 2, predicates
    for predicate in predicates:
        assert '($v | contains("rawhide"))' in predicate and '($v | contains("sid"))' in predicate
        assert "test($v)" not in predicate
