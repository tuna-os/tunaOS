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
    assert "./.git/*" in check
    assert "-path './.git' -prune" in check


def test_local_runner_reads_the_ci_pin_and_budget() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert SCRIPT.stat().st_mode & 0o111
    assert "ste_workflow=" in text
    assert "ste_ref=" in text
    assert "ste-lint.mjs" in text
    assert "--summary" in text
    assert "--max" in text
    assert ".ste-budget" in text


def test_local_runner_uses_a_cached_pinned_linter(tmp_path: Path) -> None:
    cache = tmp_path / "cache" / _ste_ref() / ".github" / "actions" / "ste-lint"
    cache.mkdir(parents=True)
    (cache / "ste-lint.mjs").write_text(
        """
        const args = process.argv.slice(2);
        const valid = args.includes('--summary') ||
          (args.includes('--max') && args[args.indexOf('--max') + 1] === '3050');
        process.exit(valid ? 0 : 1);
        """,
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
