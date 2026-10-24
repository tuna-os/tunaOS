import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "lint.yml"
UTILITIES = ROOT / "just" / "utilities.just"
LINTERS = ("shellcheck", "shfmt", "yaml", "json", "actionlint", "just")


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



def _check_recipe() -> str:
    text = UTILITIES.read_text(encoding="utf-8")
    body = text[text.index("\ncheck:") + 1 :]
    end = re.search(r"\n\S", body)
    return body[: end.start()] if end else body


def test_local_check_runs_every_shared_linter() -> None:
    """`just check` must run the same gates CI runs, through the same runner.

    Replaces the shfmt-in-check assertions removed with the inline find
    commands: if a refactor drops a linter from the local gate, CI would keep
    passing while contributors stop seeing the failure before they push.
    """
    check = _check_recipe()
    assert re.match(r"check: .*\b_ensure_check_deps\b", check)
    for linter in LINTERS:
        assert f"./scripts/run-config-lint.sh {linter}\n" in check, linter


def test_ci_runs_every_shared_linter() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for linter in LINTERS:
        assert f"./scripts/run-config-lint.sh {linter}" in text, linter
