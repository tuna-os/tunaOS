"""Only the `build` job (a reusable-workflow call) needs packages/id-token
write. The validate job only checks out and reads config, so the workflow-level
grant must stay read-only."""
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "build-flavor.yml"


def load() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_workflow_level_grants_are_read_only():
    perms = load()["permissions"]
    assert "packages" not in perms or perms["packages"] != "write"
    assert "id-token" not in perms or perms["id-token"] != "write"
    assert not any(v == "write" for v in perms.values()), perms


def test_build_job_keeps_the_write_grants_it_needs():
    perms = load()["jobs"]["build"]["permissions"]
    assert perms["packages"] == "write"
    assert perms["id-token"] == "write"
