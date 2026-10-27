"""The R2 pruner must never delete if retained inventory cannot be trusted."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/prune-r2.yml"
STEP_NAME = "Prune dated ISOs older than 14 days (live-isos/)"


def executable(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + body)
    path.chmod(0o755)


def prune_step() -> str:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    step = next(
        item
        for item in workflow["jobs"]["prune"]["steps"]
        if item.get("name") == STEP_NAME
    )
    return step["run"].replace("${{ secrets.R2_BUCKET }}", "${R2_BUCKET}")


def run_prune(tmp_path: Path, failure: str) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    trace = tmp_path / "rclone-calls"
    executable(bin_dir / "yq", "printf '{}\\n'\n")
    executable(
        bin_dir / "python3",
        f"""if [[ "${{1:-}}" == scripts/iso-delivery-policy.py && "${{4:-}}" == retention-filters && "{failure}" == policy ]]; then
    echo 'simulated policy inventory failure' >&2
    exit 19
fi
exec {sys.executable} "$@"
""",
    )
    executable(
        bin_dir / "rclone",
        f"""printf '%s\\n' "$*" >>"{trace}"
if [[ "${{1:-}}" == lsf && "{failure}" == listing ]]; then
    echo 'simulated R2 listing failure' >&2
    exit 21
fi
exit 0
""",
    )
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
        "R2_BUCKET": "fixture-bucket",
        "RCLONE_CONFIG_R2_ACCESS_KEY_ID": "fixture",
        "RCLONE_CONFIG_R2_SECRET_ACCESS_KEY": "fixture",
        "RCLONE_CONFIG_R2_ENDPOINT": "https://example.invalid",
        "DRY_RUN": "false",
        "TRACE": str(trace),
    }
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", prune_step()],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    calls = trace.read_text().splitlines() if trace.exists() else []
    return result, calls


def test_policy_inventory_failure_aborts_before_any_r2_delete(tmp_path: Path) -> None:
    result, calls = run_prune(tmp_path, "policy")
    assert result.returncode == 19
    assert calls == []
    assert "simulated policy inventory failure" in result.stderr


def test_remote_inventory_failure_aborts_before_any_r2_delete(tmp_path: Path) -> None:
    result, calls = run_prune(tmp_path, "listing")
    assert result.returncode == 1
    assert calls == ["lsf --s3-no-check-bucket --files-only R2:fixture-bucket/live-isos/"]
    assert "refusing to prune" in (result.stdout + result.stderr)
