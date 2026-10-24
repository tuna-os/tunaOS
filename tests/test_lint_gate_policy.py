from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "lint.yml"


def test_every_declared_lint_and_policy_check_is_gating() -> None:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = {step["name"]: step for step in document["jobs"]["lint"]["steps"]}
    required_gates = {
        "Run shellcheck",
        "Check shell formatting",
        "Run yamllint",
        "Validate JSON files",
        "Run actionlint",
        "Check action pins",
        "Check Justfile formatting",
        "Package source policy",
    }

    assert required_gates <= steps.keys()
    for name in required_gates:
        assert steps[name].get("continue-on-error") is not True, f"{name} is advisory"

