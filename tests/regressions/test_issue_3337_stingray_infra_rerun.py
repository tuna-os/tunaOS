"""Stingray's dispatch-only build still gets one infra retry (#3337).

Falsification: removing the workflow-name exception makes this assertion fail;
that is the exact regression where a failed Build Stingray run emits a
workflow_run event with event=workflow_dispatch and is silently ignored.
"""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/rerun-infra-failures.yml"
LIFECYCLE_WORKFLOW = ROOT / ".github/workflows/bootc-lifecycle.yml"
DAILY_WORKFLOW = ROOT / ".github/workflows/daily-verify.yml"


def test_dispatch_only_stingray_is_an_automatic_retry_source() -> None:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    condition = document["jobs"]["classify-and-rerun"]["if"]

    assert "github.event.workflow_run.event == 'workflow_dispatch'" in condition
    assert "github.event.workflow_run.name == 'Build Stingray [experimental]'" in condition
    assert "github.event.workflow_run.conclusion == 'failure'" in condition
    assert "github.event.workflow_run.run_attempt == 1" in condition


def test_experimental_variants_use_beta_lifecycle_lane() -> None:
    document = yaml.safe_load(LIFECYCLE_WORKFLOW.read_text(encoding="utf-8"))
    generate = next(
        step["run"]
        for step in document["jobs"]["generate-matrix"]["steps"]
        if step.get("id") == "gen"
    )

    assert generate.count("($variant.experimental == true)") == 2


def test_experimental_only_lifecycle_dispatch_skips_empty_stable_lane() -> None:
    document = yaml.safe_load(LIFECYCLE_WORKFLOW.read_text(encoding="utf-8"))
    condition = document["jobs"]["lifecycle"]["if"]
    assert "needs.generate-matrix.outputs.matrix" in condition
    assert "include[0]" in condition


def test_daily_rotation_excludes_dispatch_only_experimental_variants() -> None:
    document = yaml.safe_load(DAILY_WORKFLOW.read_text(encoding="utf-8"))
    generate = next(
        step["run"]
        for step in document["jobs"]["generate_matrix"]["steps"]
        if step.get("id") == "set-matrix"
    )
    assert "$variant.experimental != true" in generate
