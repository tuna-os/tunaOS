import os
import re
import shutil
import subprocess
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


def test_shfmt_gate_handles_empty_inputs_and_reports_real_drift(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    scripts = root / "scripts"
    tools = tmp_path / "bin"
    scripts.mkdir(parents=True)
    tools.mkdir()
    runner = scripts / "lint-runner"
    shutil.copy2(ROOT / "scripts" / "run-config-lint.sh", runner)
    log = tmp_path / "shfmt.log"
    shfmt = tools / "shfmt"
    shfmt.write_text(
        "#!/usr/bin/env bash\n"
        "printf 'called\\n' >> \"$SHFMT_LOG\"\n"
        "[[ \"${SHFMT_DRIFT:-}\" != true ]] || printf '%s\\n' \"${@: -1}\"\n",
        encoding="utf-8",
    )
    shfmt.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tools}:{os.environ['PATH']}",
        "SHFMT_LOG": str(log),
    }

    empty = subprocess.run(
        ["bash", str(runner), "shfmt"], env=env, text=True, capture_output=True
    )
    assert empty.returncode == 0, empty.stdout + empty.stderr
    assert not log.exists()

    shell_file = root / "example.sh"
    shell_file.write_text("#!/usr/bin/env bash\ntrue\n", encoding="utf-8")
    drift = subprocess.run(
        ["bash", str(runner), "shfmt"],
        env={**env, "SHFMT_DRIFT": "true"},
        text=True,
        capture_output=True,
    )
    assert drift.returncode != 0
    assert str(shell_file.relative_to(root)) in drift.stdout
    assert log.read_text(encoding="utf-8").splitlines() == ["called"]
