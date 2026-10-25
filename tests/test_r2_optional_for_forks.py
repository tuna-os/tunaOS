"""R2 is optional: a fork with no R2 secrets must skip every R2 step cleanly.

Epic #3668 says a fork works by editing tunaos.toml and assets alone. R2 is
TunaOS's own bucket (epic #3470), so no workflow may fail, hit an anonymous
endpoint, or fail when the four R2_* secrets are empty
(#1129: empty secrets make rclone resolve s3.auto.amazonaws.com and retry for
minutes before failing).

This parses every workflow and classifies each step that uses an R2 secret or
runs rclone. A step is "guarded" when one of these is true with empty secrets:

  env        step/job `if:` has `env.R2_CONFIGURED == 'true'` as a conjunct and
             the job's R2_CONFIGURED expression requires all four secrets
             (`secrets` is not readable in `if:`, hence the env hop);
  preflight  step `if:` keys off the output of an earlier step that tests the
             four secrets for emptiness and writes skip=true (iso-e2e);
  probe      the step only tests the four secrets for emptiness (no rclone);
  script     the step body exits 0 on an empty credential BEFORE its first
             rclone command (the job still runs; the step reports success).

R2-only scheduled jobs must additionally be `env`-guarded on every step, so on
a fork every step is skipped and the job reports success. The job itself still
gets a runner: step-level `if:` runs after allocation and `secrets` is not
readable in a job-level `if:`, so this test does not claim runner avoidance.

Print the reproducible table:  python tests/test_r2_optional_for_forks.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

R2_SECRETS = ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_ENDPOINT", "R2_BUCKET")
R2_SECRET_REF = re.compile(r"secrets\.R2_[A-Z_]+")
RCLONE_CMD = re.compile(r"(?m)^\s*(?:[A-Za-z_]+=\S+\s+)*rclone\s+(?:\S+\s+)*?(?:copy|copyto|delete|lsf|size|sync|ls|lsd|cat)\b")
ENV_GUARD = "env.R2_CONFIGURED == 'true'"
EMPTY_CHECK = re.compile(r'\[\[\s+-z\s+"\$\{?(RCLONE_CONFIG_R2_ACCESS_KEY_ID|R2_BUCKET)(?::-)?\}?"\s+\]\]')

# Scheduled jobs whose only purpose is R2: every step must be env-guarded.
R2_ONLY_JOBS = {
    ("prune-r2.yml", "prune"),
    ("audit-nvidia-release-assets.yml", "audit"),
}


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _conjuncts(cond: str) -> list[str]:
    return [c.strip() for c in re.sub(r"^\$\{\{|\}\}$", "", cond.strip()).split("&&")]


def _env_flag_requires_all_secrets(job: dict) -> bool:
    expr = str((job.get("env") or {}).get("R2_CONFIGURED", ""))
    return all(f"secrets.{n} != ''" in expr for n in R2_SECRETS)


def _uses_r2(step: dict) -> bool:
    blob = yaml.dump(step.get("env") or {}) + yaml.dump(step.get("with") or {}) + str(step.get("run", ""))
    return bool(R2_SECRET_REF.search(blob) or RCLONE_CMD.search(str(step.get("run", ""))))


def _guard(step_idx: int, steps: list[dict], job: dict) -> str | None:
    """Name of the guard that is false with empty secrets, or None."""
    step = steps[step_idx]
    conds = _conjuncts(str(step.get("if", ""))) + _conjuncts(str(job.get("if", "")))
    if ENV_GUARD in conds and _env_flag_requires_all_secrets(job):
        return "env"
    blob = yaml.dump(step.get("env") or {})
    if (not RCLONE_CMD.search(str(step.get("run", ""))) and "skip=true" in str(step.get("run", ""))
            and all(f"secrets.{n}" in blob for n in R2_SECRETS)):
        return "probe"  # only tests the secrets for emptiness (iso-e2e preflight)
    for prior in steps[:step_idx]:
        sid = prior.get("id")
        if not sid or f"steps.{sid}.outputs.skip != 'true'" not in conds:
            continue
        blob = yaml.dump(prior.get("env") or {})
        if all(f"secrets.{n}" in blob for n in R2_SECRETS) and "skip=true" in str(prior.get("run", "")):
            return "preflight"
    run = str(step.get("run", ""))
    first_rclone = RCLONE_CMD.search(run)
    check = EMPTY_CHECK.search(run)
    if first_rclone and check and check.start() < first_rclone.start():
        var = check.group(1)
        env = step.get("env") or {}
        bound = "secrets.R2_" in str(env.get(var, ""))
        if bound and "exit 0" in run[check.end():first_rclone.start()]:
            return "script"
    return None


def audit() -> list[dict]:
    rows = []
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        doc = _load(path)
        for job_id, job in (doc.get("jobs") or {}).items():
            job = job or {}
            if "uses" in job:
                continue  # secret passthrough to a reusable workflow: nothing runs here
            steps = job.get("steps") or []
            only = (path.name, job_id) in R2_ONLY_JOBS
            for i, step in enumerate(steps):
                if not (_uses_r2(step) or only):
                    continue
                g = _guard(i, steps, job)
                rows.append({
                    "workflow": path.name, "job": job_id,
                    "step": step.get("name") or step.get("uses") or f"#{i}",
                    "if": str(step.get("if", job.get("if", "-"))).replace("\n", " "),
                    "guard": g, "r2_only_job": only,
                })
    return rows


def _outcome(row: dict) -> str:
    if row["guard"] is None:
        return "UNVERIFIED: no recognized guard (runtime outcome not inspected)"
    if row["r2_only_job"] and row["guard"] != "env":
        return "runner spent, step skips late"
    return {"env": "skipped", "probe": "emptiness probe, no R2 call", "preflight": "skipped (preflight)", "script": "no-op exit 0"}[row["guard"]]


ROWS = audit()


def test_the_scan_finds_the_known_r2_steps():
    """Guard the guard: an empty scan would pass every test below."""
    seen = {(r["workflow"], r["job"]) for r in ROWS}
    for wf, job in [
        ("prune-r2.yml", "prune"),
        ("audit-nvidia-release-assets.yml", "audit"),
        ("publish-iso-groups.yml", "build-and-publish"),
        ("reusable-build-artifacts.yml", "iso"),
        ("installer-smoke.yml", "publish-screenshots"),
        ("iso-e2e.yml", "e2e"),
        ("weekly-desktop-screenshots.yml", "screenshot"),
        ("weekly-qcow2-screenshots.yml", "screenshot"),
    ]:
        assert (wf, job) in seen, (wf, job)


@pytest.mark.parametrize("row", ROWS, ids=lambda r: f"{r['workflow']}::{r['job']}::{r['step']}")
def test_every_r2_step_is_guarded_when_the_secrets_are_empty(row):
    assert row["guard"], (
        f"{row['workflow']} job {row['job']!r} step {row['step']!r} uses R2 with no guard "
        f"(if: {row['if']}). No recognized guard, so it may run with empty secrets in a fork "
        f"(rclone then resolves an AWS endpoint). Add "
        f"`if: env.R2_CONFIGURED == 'true'` with the job env R2_CONFIGURED from the four secrets."
    )


@pytest.mark.parametrize("wf,job", sorted(R2_ONLY_JOBS))
def test_scheduled_r2_only_jobs_skip_every_step_on_forks(wf, job):
    bad = [r["step"] for r in ROWS if (r["workflow"], r["job"]) == (wf, job) and r["guard"] != "env"]
    assert not bad, f"{wf}::{job} has steps that are not env-guarded, so they run on forks: {bad}"
    assert any((r["workflow"], r["job"]) == (wf, job) for r in ROWS)


def test_env_flag_requires_all_four_secrets_and_is_true_only_when_all_set():
    job = {"env": {"R2_CONFIGURED": "${{ secrets.R2_ACCESS_KEY_ID != '' && secrets.R2_SECRET_ACCESS_KEY != '' && secrets.R2_ENDPOINT != '' && secrets.R2_BUCKET != '' }}"}}
    assert _env_flag_requires_all_secrets(job)
    assert not _env_flag_requires_all_secrets({"env": {"R2_CONFIGURED": "${{ secrets.R2_BUCKET != '' }}"}})
    assert not _env_flag_requires_all_secrets({})


def test_the_detector_flags_an_unguarded_rclone_step():
    step = {"name": "x", "env": {"RCLONE_CONFIG_R2_ACCESS_KEY_ID": "${{ secrets.R2_ACCESS_KEY_ID }}"},
            "run": "rclone copy a R2:b/"}
    assert _uses_r2(step)
    assert _guard(0, [step], {}) is None
    guarded = dict(step, **{"if": "inputs.go && env.R2_CONFIGURED == 'true'"})
    job = {"env": {"R2_CONFIGURED": "${{ " + " && ".join(f"secrets.{n} != ''" for n in R2_SECRETS) + " }}"}}
    assert _guard(0, [guarded], job) == "env"
    assert not _uses_r2({"name": "i", "run": "sudo apt-get install -y rclone"})


def test_no_workflow_step_calls_the_public_download_host():
    """download.tunaos.org is TunaOS's bucket; only comments may name it."""
    bad = []
    for path in WORKFLOWS.glob("*.y*ml"):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "download.tunaos.org" in line and not line.lstrip().startswith("#"):
                bad.append(f"{path.name}:{n}")
    assert not bad, bad


def test_live_iso_bootc_does_not_install_unused_rclone():
    text = (WORKFLOWS / "live-iso-bootc.yml").read_text(encoding="utf-8")
    assert not re.search(r"(?m)^[^#\n]*\brclone\b", text)


if __name__ == "__main__":
    print("| workflow | job | step | if | guard | fork outcome |")
    print("|---|---|---|---|---|---|")
    for r in ROWS:
        print(f"| {r['workflow']} | {r['job']} | {r['step']} | `{r['if'][:60]}` | {r['guard'] or 'NONE'} | {_outcome(r)} |")
    sys.exit(0)
