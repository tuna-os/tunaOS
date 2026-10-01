"""tunaOS#1740: AI porting agent auto-commits/pushes on untrusted upstream diffs.

The legacy watch-* workflows (watch-upstream.yml, watch-aurora.yml,
watch-bluefin-lts.yml, watch-zirconium.yml) fetched raw commit messages and
diffs from third-party repositories and fed them directly into Gemini CLI and
Copilot coding agents holding write tokens (contents: write, pull-requests:
write, and COPILOT_PAT). This created a remote code execution and credential
exfiltration vector via prompt injection on upstream diffs.

This regression test verifies that no workflow in .github/workflows/ feeds
untrusted upstream commit diffs to an AI agent with write credentials, and that
the legacy per-commit watch workflows and helper scripts remain decommissioned
in favor of snapshot-upstreams.yml (human-reviewed content diffs).

Falsification: structural — restoring watch-upstream.yml, write-gemini-task.py,
or any workflow running an AI coding agent with write tokens on untrusted
upstream diffs causes this test to fail.
"""

from __future__ import annotations

import re
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = ROOT / ".github" / "workflows"
SCRIPTS_DIR = ROOT / ".github" / "scripts"

DECOMMISSIONED_WORKFLOWS = [
    "watch-upstream.yml",
    "watch-aurora.yml",
    "watch-bluefin-lts.yml",
    "watch-zirconium.yml",
]

DECOMMISSIONED_SCRIPTS = [
    "write-gemini-task.py",
    "fire-copilot-batch.py",
]


def test_legacy_watch_workflows_and_scripts_are_removed() -> None:
    """Ensure legacy watch-* workflows and helper scripts do not exist."""
    for wf in DECOMMISSIONED_WORKFLOWS:
        assert not (WORKFLOWS_DIR / wf).exists(), f"Legacy workflow {wf} must not exist"

    for script in DECOMMISSIONED_SCRIPTS:
        assert not (SCRIPTS_DIR / script).exists(), f"Legacy script {script} must not exist"


def test_no_workflow_runs_ai_agents_with_write_tokens_on_untrusted_diffs() -> None:
    """Ensure no workflow executes AI agents under write credentials on upstream diffs."""
    ai_actions = re.compile(r"(run-gemini-cli|copilot-swe-agent)", re.IGNORECASE)

    for wf_path in WORKFLOWS_DIR.glob("*.y*ml"):
        content = wf_path.read_text(encoding="utf-8")
        if not ai_actions.search(content):
            continue

        doc = yaml.safe_load(content) or {}
        wf_perms = doc.get("permissions")
        jobs = doc.get("jobs", {})

        if wf_perms == "write-all":
            assert False, (
                f"{wf_path.name} uses an AI coding agent with workflow-level write-all permissions"
            )

        for job_id, job in (jobs.items() if isinstance(jobs, dict) else []):
            if not isinstance(job, dict):
                continue
            if not ai_actions.search(yaml.dump(job)):
                continue

            # Resolve job permissions over workflow defaults
            if "permissions" in job:
                effective_perms = job["permissions"]
            elif "permissions" in doc:
                effective_perms = wf_perms
            else:
                effective_perms = None

            assert effective_perms is not None, (
                f"{wf_path.name} job '{job_id}' uses an AI coding agent with omitted permissions "
                f"(inherits repository defaults)"
            )

            if isinstance(effective_perms, str):
                assert effective_perms != "write-all", (
                    f"{wf_path.name} job '{job_id}' uses an AI coding agent with write-all permissions"
                )
            elif isinstance(effective_perms, dict):
                assert effective_perms.get("contents") != "write", (
                    f"{wf_path.name} job '{job_id}' uses an AI coding agent with contents: write permission"
                )
                assert effective_perms.get("pull-requests") != "write", (
                    f"{wf_path.name} job '{job_id}' uses an AI coding agent with pull-requests: write permission"
                )


def test_snapshot_upstreams_is_the_canonical_upstream_tracker() -> None:
    """Ensure snapshot-upstreams.yml is used for tracking upstreams safely."""
    snapshot_wf = WORKFLOWS_DIR / "snapshot-upstreams.yml"
    assert snapshot_wf.exists(), "snapshot-upstreams.yml must exist as the safe upstream sync mechanism"
    content = snapshot_wf.read_text(encoding="utf-8")
    assert "sync-upstream-snapshots.sh" in content
    assert "run-gemini-cli" not in content
    assert "fire-copilot-batch.py" not in content
