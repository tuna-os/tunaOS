"""Stingray's dispatch-only build still gets one infra retry (#3337).

Falsification: removing the workflow-name exception makes this assertion fail;
that is the exact regression where a failed Build Stingray run emits a
workflow_run event with event=workflow_dispatch and is silently ignored.
"""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/rerun-infra-failures.yml"


def test_dispatch_only_stingray_is_an_automatic_retry_source() -> None:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    condition = document["jobs"]["classify-and-rerun"]["if"]

    assert "github.event.workflow_run.event == 'workflow_dispatch'" in condition
    assert "github.event.workflow_run.name == 'Build Stingray [experimental]'" in condition
    assert "github.event.workflow_run.conclusion == 'failure'" in condition
    assert "github.event.workflow_run.run_attempt == 1" in condition
