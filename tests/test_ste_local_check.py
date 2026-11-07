"""Keep the local STE gate aligned with the shared CI action."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run-ste-lint.sh"
UTILITIES = ROOT / "just" / "utilities.just"
STE_WORKFLOW = ROOT / ".github" / "workflows" / "ste.yml"


def _recipe(name: str) -> str:
    text = UTILITIES.read_text(encoding="utf-8")
    body = text[text.index(f"\n{name}:") :]
    match = re.search(r"\n[a-z][a-z0-9-]*:", body[1:])
    return body[: match.start() + 1] if match else body


def _ste_ref() -> str:
    match = re.search(
        r"uses: tuna-os/\.github/\.github/workflows/ste-lint\.yml@([0-9a-f]{40})",
        STE_WORKFLOW.read_text(encoding="utf-8"),
    )
    assert match
    return match.group(1)


def test_check_runs_ste_but_fix_does_not() -> None:
    check = _recipe("check")
    fix = _recipe("fix")
    ste = _recipe("ste")
    assert re.search(r"^check: .*\bste\b", check, re.M)
    assert "run-ste-lint.sh" in ste
    assert "run-ste-lint.sh" not in fix
    # File discovery for the config linters moved from inline find commands
    # into the shared runner; it must still keep .git out of every walk.
    assert "./scripts/run-config-lint.sh" in check
    runner = (ROOT / "scripts" / "run-config-lint.sh").read_text(encoding="utf-8")
    assert "-path './.git'" in runner
    assert "-prune" in runner


def test_local_runner_reads_the_ci_pin_and_budget() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert SCRIPT.stat().st_mode & 0o111
    assert "ste_workflow=" in text
    assert "ste_ref=" in text
    assert "ste-lint.mjs" in text
    assert "--summary" in text
    assert "--max" in text
    assert ".ste-budget" in text


def _budget() -> str:
    """The budget the runner will actually pass, read from the same file it reads.

    This used to be the literal "3050" inside the stub below. That made the
    fixture a second, silent copy of .ste-budget: the first ratchet after it
    was written (3050 -> 1650) turned this test red, and the failure said
    `assert 1 == 0` with an empty linter stdout — which looks like a broken
    runner, not like a stale number in a test. Read the file instead, so
    lowering the budget stays a one-file change.
    """
    return (ROOT / ".ste-budget").read_text(encoding="utf-8").strip()


def test_local_runner_uses_a_cached_pinned_linter(tmp_path: Path) -> None:
    cache = tmp_path / "cache" / _ste_ref() / ".github" / "actions" / "ste-lint"
    cache.mkdir(parents=True)
    (cache / "ste-lint.mjs").write_text(
        """
        const args = process.argv.slice(2);
        const valid = args.includes('--summary') ||
          (args.includes('--max') && args[args.indexOf('--max') + 1] === '%s');
        process.exit(valid ? 0 : 1);
        """ % _budget(),
        encoding="utf-8",
    )
    env = os.environ | {"TUNAOS_STE_CACHE_DIR": str(tmp_path / "cache")}
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def _ste_workflow() -> dict:
    import yaml

    return yaml.safe_load(STE_WORKFLOW.read_text(encoding="utf-8"))


def test_the_pull_request_gate_holds_a_branch_to_what_it_adds() -> None:
    """A branch answers for its own findings, not for the whole-repo count.

    The whole-repo budget failed every Markdown pull request whenever main sat
    over it (84 of 238 runs in the week of 2026-10-31), for findings the
    branch never touched.
    """
    document = _ste_workflow()
    triggers = document.get("on") or document.get(True)
    assert "push" not in triggers, "a push run only re-reports debt the PR gate already holds"
    job = document["jobs"]["new-findings"]
    assert job["if"] == "github.event_name == 'pull_request'"
    run = next(s["run"] for s in job["steps"] if s.get("name") == "No new findings")
    assert "--changed-only" in run and "--max 0" in run
    assert job["name"] == "ste / Simplified Technical English", (
        "the check context the reusable workflow reported must not change"
    )


def test_the_whole_repo_budget_runs_only_on_request() -> None:
    document = _ste_workflow()
    assert document["jobs"]["ste"]["if"] == "github.event_name == 'workflow_dispatch'"


def test_both_jobs_pin_the_same_linter_revision() -> None:
    document = _ste_workflow()
    reusable = re.search(r"@([0-9a-f]{40})", document["jobs"]["ste"]["uses"])
    assert reusable
    checkout = next(
        s
        for s in document["jobs"]["new-findings"]["steps"]
        if (s.get("with") or {}).get("repository") == "tuna-os/.github"
    )
    assert checkout["with"]["ref"] == reusable[1] == _ste_ref()
