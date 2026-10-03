"""tunaOS#2767: every workflow must declare its token permissions.

The 2026-10-03 repository audit measured 27 workflows without a top-level
``permissions`` block, leaving their default GITHUB_TOKEN scope dependent on
repository settings. This test holds every workflow to an explicit default and
rejects the unrestricted ``write-all`` shorthand.

Falsification: structural — remove a workflow's top-level permissions key, or
set it to write-all, and this test fails with that workflow's path.
"""

from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.y*ml"))


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda path: path.name)
def test_workflow_declares_least_privilege_permissions(path: Path) -> None:
    workflow = yaml.safe_load(path.read_text())

    assert "permissions" in workflow, (
        f"{path.relative_to(ROOT)} has no top-level permissions block; "
        "declare the workflow's least-privilege GITHUB_TOKEN default"
    )
    assert workflow["permissions"] != "write-all", (
        f"{path.relative_to(ROOT)} grants write-all; list only required scopes"
    )
