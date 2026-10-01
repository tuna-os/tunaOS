"""tunaOS#1740: AI porting agent auto-commits/pushes on untrusted upstream diffs.

The legacy watch-* workflows (watch-upstream.yml, watch-aurora.yml,
watch-bluefin-lts.yml, watch-zirconium.yml) fetched raw commit messages and
diffs from third-party repositories and fed them directly into Gemini CLI and
Copilot coding agents holding write tokens (contents: write, pull-requests:
write, and COPILOT_PAT). This created a remote code execution and credential
exfiltration vector via prompt injection on upstream diffs.

This regression test verifies that no workflow or helper script executes AI
coding agents with write credentials (ephemeral write permissions or custom
PATs) on untrusted diffs, and that the legacy per-commit watch workflows and
helper scripts remain decommissioned in favor of snapshot-upstreams.yml
(human-reviewed content diffs).

Falsification: behavioural — synthetic workflow and script fixtures reproducing
the historical Gemini CLI write-token job, PAT-backed Copilot batch dispatch,
omitted-permission inheritance, and renamed local helpers are evaluated against
the security detectors, asserting each insecure pattern is rejected; structural
for the repository tree where all active workflows and scripts are validated.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = ROOT / ".github" / "workflows"
SCRIPTS_DIR = ROOT / ".github" / "scripts"
PROMPTS_DIR = ROOT / ".github" / "prompts"

DECOMMISSIONED_WORKFLOWS = [
    "watch-upstream.yml",
    "watch-aurora.yml",
    "watch-bluefin-lts.yml",
    "watch-zirconium.yml",
]

DECOMMISSIONED_SCRIPTS = [
    "write-gemini-task.py",
    "fire-copilot-batch.py",
    "check-el10-packages.py",
]

DECOMMISSIONED_PROMPTS = [
    "aurora-port.md",
    "bluefin-lts-port.md",
    "zirconium-port.md",
]

AI_AGENT_PATTERN = re.compile(
    r"(run-gemini-cli|copilot-swe-agent|gemini-cli|claude-code)",
    re.IGNORECASE,
)

CUSTOM_WRITE_SECRET_PATTERN = re.compile(
    r"\$\{\{\s*secrets\.(COPILOT_PAT|[A-Za-z0-9_]*PAT[A-Za-z0-9_]*|[A-Za-z0-9_]*TOKEN_WRITE[A-Za-z0-9_]*|PERSONAL_ACCESS_TOKEN)\s*\}\}",
    re.IGNORECASE,
)

AI_HELPER_SCRIPT_CALL = re.compile(
    r"(?:python[0-9]*|bash|sh)\s+.*?\.github/scripts/([a-zA-Z0-9_\-]+\.(?:py|sh))"
)


def scan_script_content(content: str, script_name: str = "script") -> list[str]:
    """Inspect a script for AI agent assignments or custom write credentials."""
    violations: list[str] = []
    if "copilot-swe-agent" in content:
        violations.append(f"{script_name}: assigns tasks to copilot-swe-agent")
    if "COPILOT_PAT" in content:
        violations.append(f"{script_name}: references COPILOT_PAT credential")
    if "run-gemini-cli" in content:
        violations.append(f"{script_name}: invokes run-gemini-cli")
    if "agentAssignment" in content or "replaceActorsForAssignable" in content:
        violations.append(f"{script_name}: performs agentAssignment GraphQL mutation")
    return violations


def scan_workflow_content(
    content: str,
    wf_name: str = "workflow.yml",
    scripts_dir: Path | None = None,
) -> list[str]:
    """Inspect workflow YAML for AI coding agents with write permissions or custom PATs."""
    violations: list[str] = []
    effective_scripts_dir = scripts_dir or SCRIPTS_DIR
    doc = yaml.safe_load(content) or {}
    if not isinstance(doc, dict):
        return violations

    wf_perms = doc.get("permissions")
    jobs = doc.get("jobs", {})
    if not isinstance(jobs, dict):
        return violations

    ai_jobs: set[str] = set()
    job_helper_violations: dict[str, list[str]] = {}

    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        job_yaml_str = yaml.dump(job)

        has_direct_ai = bool(AI_AGENT_PATTERN.search(job_yaml_str))
        helper_matches = AI_HELPER_SCRIPT_CALL.findall(job_yaml_str)
        helper_violations: list[str] = []
        for helper_name in helper_matches:
            helper_path = effective_scripts_dir / helper_name
            if helper_path.exists():
                helper_violations.extend(
                    scan_script_content(
                        helper_path.read_text(encoding="utf-8"),
                        script_name=helper_name,
                    )
                )

        if helper_violations:
            job_helper_violations[job_id] = helper_violations
        if has_direct_ai or helper_violations:
            ai_jobs.add(job_id)

    # If no AI agents or AI helpers are present in this workflow, no AI write violations
    if not ai_jobs:
        return violations

    # Inspect all jobs in workflows containing AI agents
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        job_yaml_str = yaml.dump(job)

        if "permissions" in job:
            effective_perms: Any = job["permissions"]
        elif "permissions" in doc:
            effective_perms = wf_perms
        else:
            effective_perms = None

        is_ai_job = job_id in ai_jobs
        custom_secrets = CUSTOM_WRITE_SECRET_PATTERN.findall(job_yaml_str)
        has_git_push = "git push" in job_yaml_str

        if is_ai_job:
            if job_id in job_helper_violations:
                violations.extend(
                    f"{wf_name} job '{job_id}' calls insecure helper: {hv}"
                    for hv in job_helper_violations[job_id]
                )

            if effective_perms is None:
                violations.append(
                    f"{wf_name} job '{job_id}' uses AI agent/helper with omitted permissions (inherits repo defaults)"
                )
            elif effective_perms == "write-all":
                violations.append(
                    f"{wf_name} job '{job_id}' uses AI agent/helper with write-all permissions"
                )
            elif isinstance(effective_perms, dict):
                if effective_perms.get("contents") == "write":
                    violations.append(
                        f"{wf_name} job '{job_id}' uses AI agent/helper with contents: write permission"
                    )
                if effective_perms.get("pull-requests") == "write":
                    violations.append(
                        f"{wf_name} job '{job_id}' uses AI agent/helper with pull-requests: write permission"
                    )

            if custom_secrets:
                violations.append(
                    f"{wf_name} job '{job_id}' passes custom write credentials: {', '.join(custom_secrets)}"
                )

            if has_git_push:
                violations.append(
                    f"{wf_name} job '{job_id}' executes git push in AI agent job"
                )
        else:
            # Downstream or companion job in an AI workflow
            if effective_perms is None:
                violations.append(
                    f"{wf_name} job '{job_id}' runs in AI workflow with omitted permissions (inherits repo defaults)"
                )
            elif effective_perms == "write-all":
                violations.append(
                    f"{wf_name} job '{job_id}' runs in AI workflow with write-all permissions"
                )
            elif isinstance(effective_perms, dict):
                if effective_perms.get("contents") == "write":
                    violations.append(
                        f"{wf_name} job '{job_id}' has contents: write permission in AI workflow (unsafe cross-job write)"
                    )
                if effective_perms.get("pull-requests") == "write":
                    violations.append(
                        f"{wf_name} job '{job_id}' has pull-requests: write permission in AI workflow (unsafe cross-job write)"
                    )

            if custom_secrets:
                violations.append(
                    f"{wf_name} job '{job_id}' passes custom write credentials in AI workflow: {', '.join(custom_secrets)}"
                )

            if has_git_push:
                violations.append(
                    f"{wf_name} job '{job_id}' executes git push downstream/alongside AI agent in automated workflow"
                )

    return violations


def test_legacy_watch_workflows_and_scripts_are_removed() -> None:
    """Ensure legacy watch-* workflows, helper scripts, and prompts do not exist."""
    for wf in DECOMMISSIONED_WORKFLOWS:
        assert not (WORKFLOWS_DIR / wf).exists(), f"Legacy workflow {wf} must not exist"

    for script in DECOMMISSIONED_SCRIPTS:
        assert not (SCRIPTS_DIR / script).exists(), f"Legacy script {script} must not exist"

    for prompt in DECOMMISSIONED_PROMPTS:
        assert not (PROMPTS_DIR / prompt).exists(), f"Legacy prompt {prompt} must not exist"


def test_no_active_workflow_runs_ai_agents_with_write_credentials() -> None:
    """Ensure no workflow in .github/workflows executes AI agents with write tokens or PATs."""
    all_violations: list[str] = []
    for wf_path in WORKFLOWS_DIR.glob("*.y*ml"):
        content = wf_path.read_text(encoding="utf-8")
        violations = scan_workflow_content(content, wf_name=wf_path.name)
        all_violations.extend(violations)

    assert not all_violations, "Found workflows with insecure AI write configurations:\n" + "\n".join(all_violations)


def test_no_active_scripts_contain_ai_agent_assignments_or_pats() -> None:
    """Ensure no script in .github/scripts/ contains AI agent dispatch or PAT references."""
    all_violations: list[str] = []
    if SCRIPTS_DIR.exists():
        for script_path in SCRIPTS_DIR.glob("*"):
            if not script_path.is_file():
                continue
            content = script_path.read_text(encoding="utf-8", errors="ignore")
            violations = scan_script_content(content, script_name=script_path.name)
            all_violations.extend(violations)

    assert not all_violations, "Found scripts with insecure AI agent patterns:\n" + "\n".join(all_violations)


def test_snapshot_upstreams_is_the_canonical_upstream_tracker() -> None:
    """Ensure snapshot-upstreams.yml is used for tracking upstreams safely."""
    snapshot_wf = WORKFLOWS_DIR / "snapshot-upstreams.yml"
    assert snapshot_wf.exists(), "snapshot-upstreams.yml must exist as the safe upstream sync mechanism"
    content = snapshot_wf.read_text(encoding="utf-8")
    assert "sync-upstream-snapshots.sh" in content
    assert "run-gemini-cli" not in content
    assert "copilot-swe-agent" not in content
    assert "COPILOT_PAT" not in content
    assert scan_workflow_content(content, wf_name="snapshot-upstreams.yml") == []


# ── Falsification Fixtures (behavioural verification of detectors) ───────────

def test_detector_falsifies_on_legacy_gemini_write_workflow() -> None:
    """Falsification: assert detector catches Gemini CLI running with contents: write."""
    legacy_gemini_wf = """
name: Watch Aurora
on:
  schedule:
    - cron: '0 8 * * 1'
jobs:
  port:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
    steps:
      - uses: google-github-actions/run-gemini-cli@v0.1.22
        with:
          gemini_api_key: ${{ secrets.GEMINI_API_KEY }}
          prompt: "Port upstream commit"
      - run: git push origin main
"""
    violations = scan_workflow_content(legacy_gemini_wf, "legacy-watch.yml")
    assert any("contents: write" in v for v in violations)
    assert any("pull-requests: write" in v for v in violations)
    assert any("git push" in v for v in violations)


def test_detector_falsifies_on_pat_backed_ai_job() -> None:
    """Falsification: assert detector catches PAT credential passed to AI agent even with contents: read."""
    pat_backed_wf = """
name: Copilot Batch
on:
  schedule:
    - cron: '0 8 * * 1'
jobs:
  port-copilot:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      issues: write
    steps:
      - uses: actions/checkout@v4
      - name: Run agent
        env:
          GH_TOKEN: ${{ secrets.COPILOT_PAT }}
        uses: google-github-actions/run-gemini-cli@v0.1.22
        with:
          prompt: "Port commit"
"""
    violations = scan_workflow_content(pat_backed_wf, "pat-watch.yml")
    assert any("COPILOT_PAT" in v for v in violations)


def test_detector_falsifies_on_omitted_permissions_ai_job() -> None:
    """Falsification: assert detector catches AI agent with omitted permissions."""
    omitted_perms_wf = """
name: AI Port
on:
  workflow_dispatch:
jobs:
  ai-task:
    runs-on: ubuntu-latest
    steps:
      - uses: google-github-actions/run-gemini-cli@v0.1.22
        with:
          prompt: "Fix code"
"""
    violations = scan_workflow_content(omitted_perms_wf, "omitted-perms.yml")
    assert any("omitted permissions" in v for v in violations)


def test_detector_falsifies_on_script_assigning_copilot_agent() -> None:
    """Falsification: assert detector catches helper script assigning copilot-swe-agent."""
    insecure_script = """
import os, subprocess, json
GH_TOKEN = os.environ.get("GH_TOKEN")
def assign():
    mutation = '''
    mutation {
      replaceActorsForAssignable(input: {
        actorLogins: ["copilot-swe-agent"]
      }) { assignable { number } }
    }
    '''
"""
    violations = scan_script_content(insecure_script, "insecure_helper.py")
    assert any("copilot-swe-agent" in v for v in violations)
    assert any("GraphQL mutation" in v or "agentAssignment" in v for v in violations)


def test_detector_falsifies_on_workflow_calling_ai_helper(tmp_path: Path) -> None:
    """Falsification: assert detector catches workflow calling local script that uses copilot-swe-agent."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    helper = scripts_dir / "custom-batch.py"
    helper.write_text("replaceActorsForAssignable(copilot-swe-agent)")

    wf = """
name: Helper Dispatch
on:
  schedule:
    - cron: '0 8 * * 1'
jobs:
  dispatch:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - run: python3 .github/scripts/custom-batch.py
"""
    violations = scan_workflow_content(wf, "helper-dispatch.yml", scripts_dir=scripts_dir)
    assert any("contents: write" in v for v in violations)
    assert any("custom-batch.py" in v for v in violations)


def test_detector_falsifies_on_split_job_ai_write_pipeline() -> None:
    """Falsification: assert detector catches split-job pipeline where read-only AI job feeds a write job."""
    split_wf = """
name: Split AI Port
on:
  schedule:
    - cron: '0 8 * * 1'
jobs:
  ai-generate:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: google-github-actions/run-gemini-cli@v0.1.22
        with:
          prompt: "Port upstream commit"
      - uses: actions/upload-artifact@v4
        with:
          name: ai-patch
          path: patch.diff
  publish:
    needs: [ai-generate]
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/download-artifact@v4
        with:
          name: ai-patch
      - run: git apply patch.diff && git push origin main
"""
    violations = scan_workflow_content(split_wf, "split-ai-port.yml")
    assert any("publish" in v and ("contents: write" in v or "unsafe cross-job write" in v) for v in violations)
    assert any("publish" in v and "git push" in v for v in violations)

