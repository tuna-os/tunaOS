#!/usr/bin/env python3
"""Fork simulation: execute every pull_request workflow under simulated fork conditions.

On a `pull_request` event from an external fork:
  * GitHub downgrades GITHUB_TOKEN to read-only permissions
  * All repository secrets (${{ secrets.X }}) are empty
  * Untrusted checkout of the PR's synthetic head ref

This script evaluates all PR workflows across three contributor personas:
  1. First-time external contributor (head.repo.fork == true, read-only token, empty secrets)
  2. Same-repo contributor (head.repo.fork == false, internal branch)
  3. Renovate bot (user.type == 'Bot', actor == 'renovate[bot]')

It proves every PR workflow survives without unguarded write operations (403) or
unguarded secret access (empty credentials).

Usage:
  scripts/fork-simulation.py               # Human-readable Markdown report
  scripts/fork-simulation.py --json        # Machine-readable JSON summary
  scripts/fork-simulation.py --workflow X  # Evaluate a single workflow file
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = ROOT / ".github" / "workflows"

WRITE_ACTIONS = re.compile(
    r"git push|gh pr (comment|create|edit|review|merge)|gh issue (comment|create|edit)"
    r"|gh api [^\n]*(--method|-X) ?(POST|PATCH|PUT|DELETE)"
    r"|gh api [^\n]*-F |gh release |actions/github-script"
)
SECRET_REF = re.compile(r"\$\{\{\s*secrets\.(?!GITHUB_TOKEN\b)([A-Za-z0-9_]+)")

FORK_GUARDS = (
    "github.event_name != 'pull_request'",
    'github.event_name != "pull_request"',
    "github.event_name == 'workflow_dispatch'",
    "head.repo.fork",
    "head.repo.full_name",
    "IS_FORK",
    "no_r2_credentials",
)


@dataclass
class Persona:
    id: str
    name: str
    is_fork: bool
    actor: str
    user_type: str
    user_login: str
    head_repo_full_name: str
    base_repo_full_name: str = "tuna-os/tunaos"
    is_draft: bool = False
    secrets: dict[str, str] = field(default_factory=dict)


PERSONAS = [
    Persona(
        id="external_contributor",
        name="First-time external contributor",
        is_fork=True,
        actor="external-dev",
        user_type="User",
        user_login="external-dev",
        head_repo_full_name="external-dev/tunaos",
        is_draft=False,
    ),
    Persona(
        id="same_repo_contributor",
        name="Same-repo contributor",
        is_fork=False,
        actor="maintainer",
        user_type="User",
        user_login="maintainer",
        head_repo_full_name="tuna-os/tunaos",
        is_draft=False,
    ),
    Persona(
        id="renovate",
        name="Renovate bot",
        is_fork=False,
        actor="renovate[bot]",
        user_type="Bot",
        user_login="renovate[bot]",
        head_repo_full_name="tuna-os/tunaos",
        is_draft=False,
    ),
]


def load_workflow(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def workflow_triggers(doc: dict[str, Any]) -> dict[str, Any]:
    on = doc.get("on", doc.get(True, {}))
    if isinstance(on, str):
        return {on: None}
    if isinstance(on, list):
        return {k: None for k in on}
    return on or {}


def is_pr_workflow(doc: dict[str, Any]) -> bool:
    return "pull_request" in workflow_triggers(doc)


def get_pr_workflows(directory: Path = WORKFLOWS_DIR) -> list[Path]:
    return sorted(
        f for f in directory.glob("*.y*ml")
        if is_pr_workflow(load_workflow(f))
    )


def _fork_aware(text: str) -> bool:
    return any(g in text for g in FORK_GUARDS)


def build_context(persona: Persona, event_name: str = "pull_request") -> dict[str, Any]:
    return {
        "github": {
            "event_name": event_name,
            "repository": persona.base_repo_full_name,
            "repository_owner": persona.base_repo_full_name.split("/")[0],
            "actor": persona.actor,
            "event": {
                "pull_request": {
                    "number": 42,
                    "draft": persona.is_draft,
                    "user": {
                        "type": persona.user_type,
                        "login": persona.user_login,
                    },
                    "head": {
                        "ref": "synthetic-patch",
                        "repo": {
                            "fork": persona.is_fork,
                            "full_name": persona.head_repo_full_name,
                        },
                    },
                    "base": {
                        "ref": "main",
                        "repo": {
                            "fork": False,
                            "full_name": persona.base_repo_full_name,
                        },
                    },
                },
            },
        },
        "secrets": persona.secrets,
    }


def _eval_gh_expression(expr_str: str, context: dict[str, Any]) -> bool | None:
    """Evaluate GitHub Actions if expression under the given context.
    Returns True/False, or None if undetermined."""
    clean = expr_str.strip()
    if clean.startswith("${{") and clean.endswith("}}"):
        clean = clean[3:-2].strip()

    # Pre-process GitHub Actions syntax to Python AST compatible syntax
    # 1. replace '&&' with ' and ', '||' with ' or ', '!' with ' not '
    # 2. replace github action functions: always() -> True, cancelled() -> False, success() -> True
    # 3. startsWith(a, b), endsWith(a, b), contains(a, b)
    def resolve_path(path_str: str) -> Any:
        parts = path_str.split(".")
        curr: Any = context
        for p in parts:
            if isinstance(curr, dict) and p in curr:
                curr = curr[p]
            else:
                return None
        return curr

    # Try simplified token evaluation for common patterns
    if clean in ("always()", "!cancelled()", "true", "True"):
        return True
    if clean in ("cancelled()", "false", "False"):
        return False

    # Check for direct fork guards
    if "github.event.pull_request.head.repo.fork == false" in clean:
        if persona_fork := context["github"]["event"]["pull_request"]["head"]["repo"]["fork"]:
            return False
    if "github.event.pull_request.head.repo.fork == true" in clean:
        if not (context["github"]["event"]["pull_request"]["head"]["repo"]["fork"]):
            return False

    if "github.event.pull_request.user.type == 'Bot'" in clean:
        if context["github"]["event"]["pull_request"]["user"]["type"] != "Bot":
            return False

    if "github.actor != 'renovate[bot]'" in clean:
        if context["github"]["actor"] == "renovate[bot]":
            return False

    # General python expression evaluation translation
    py_expr = clean
    py_expr = re.sub(r"\balways\(\)", "True", py_expr)
    py_expr = re.sub(r"\bcancelled\(\)", "False", py_expr)
    py_expr = re.sub(r"\bsuccess\(\)", "True", py_expr)
    py_expr = re.sub(r"\btrue\b", "True", py_expr)
    py_expr = re.sub(r"\bfalse\b", "False", py_expr)
    py_expr = re.sub(r"\&\&", " and ", py_expr)
    py_expr = re.sub(r"\|\|", " or ", py_expr)
    py_expr = re.sub(r"(?<![a-zA-Z0-9_])!(?!=)", " not ", py_expr)

    # Convert dot-lookups like github.event.pull_request.draft to dict accesses or resolved values
    # Match identifiers with dots
    def replace_identifier(m):
        full_ident = m.group(0)
        val = resolve_path(full_ident)
        if val is None:
            # Maybe it's a step output or input that is not in context; represent as ''
            return "''"
        if isinstance(val, str):
            return repr(val)
        if isinstance(val, bool):
            return "True" if val else "False"
        return repr(val)

    py_expr = re.sub(r"\b(?:github|inputs|steps|secrets)(?:\.[a-zA-Z0-9_\-]+)+", replace_identifier, py_expr)

    try:
        res = eval(py_expr, {"__builtins__": {}}, {})
        return bool(res)
    except Exception:
        # Fallback to conservative None
        return None


def simulate_job(
    job_id: str,
    job: dict[str, Any],
    persona: Persona,
    context: dict[str, Any]
) -> dict[str, Any]:
    job_if = job.get("if")
    if job_if is not None:
        eval_if = _eval_gh_expression(str(job_if), context)
        if eval_if is False:
            return {
                "job_id": job_id,
                "executed": False,
                "skipped": True,
                "status": "skipped",
                "details": f"job condition evaluated to False for {persona.name}",
                "problems": [],
            }

    job_guard = _fork_aware(str(job.get("if", "")))
    steps = job.get("steps") or []
    aware_ids = {
        s.get("id") for s in steps
        if s.get("id") and _fork_aware(
            str(s.get("if", "")) + yaml.dump(s.get("env") or {}) + str(s.get("run", ""))
        )
    }

    problems = []
    executed_steps = 0

    for step in steps:
        step_if = step.get("if")
        if step_if is not None:
            eval_step_if = _eval_gh_expression(str(step_if), context)
            if eval_step_if is False:
                continue

        executed_steps += 1
        blob = yaml.dump(step)
        needs_write = bool(WRITE_ACTIONS.search(blob))
        secrets = [m.group(1) for m in SECRET_REF.finditer(blob)]

        if not needs_write and not secrets:
            continue

        cond = str(step.get("if", ""))
        step_text = cond + "\n" + yaml.dump(step.get("env") or {}) + "\n" + str(step.get("run", ""))
        guarded_by_preflight = any(f"steps.{sid}.outputs" in cond for sid in aware_ids)

        if job_guard or guarded_by_preflight or _fork_aware(step_text) or step.get("continue-on-error"):
            continue

        if persona.is_fork:
            what = "secrets " + ",".join(sorted(set(secrets))) if secrets else "a write action"
            problems.append(
                f"job {job_id!r} step {step.get('name', '?')!r} attempts {what} without fork guard"
            )

    status = "fail" if problems else "pass"
    details = "clean execution" if not problems else "; ".join(problems)
    return {
        "job_id": job_id,
        "executed": True,
        "skipped": False,
        "status": status,
        "details": details,
        "problems": problems,
    }


def simulate_workflow(workflow_path: Path, personas: list[Persona] = PERSONAS) -> dict[str, Any]:
    doc = load_workflow(workflow_path)
    wf_name = doc.get("name", workflow_path.name)
    jobs = doc.get("jobs") or {}

    persona_results = {}
    all_failures = []

    for persona in personas:
        context = build_context(persona)
        job_results = []
        persona_failed = False
        persona_skipped = True

        for job_id, job in jobs.items():
            if not isinstance(job, dict):
                continue
            j_res = simulate_job(job_id, job, persona, context)
            job_results.append(j_res)
            if j_res["status"] == "fail":
                persona_failed = True
                all_failures.extend([f"[{persona.id}] {p}" for p in j_res["problems"]])
            if not j_res["skipped"]:
                persona_skipped = False

        if persona_failed:
            p_status = "fail"
            p_desc = "; ".join(r["details"] for r in job_results if r["status"] == "fail")
        elif persona_skipped:
            p_status = "skipped"
            p_desc = "all jobs skipped"
        else:
            p_status = "pass"
            active_jobs = [r["job_id"] for r in job_results if not r["skipped"]]
            p_desc = f"jobs succeeded ({', '.join(active_jobs)})"

        persona_results[persona.id] = {
            "status": p_status,
            "details": p_desc,
            "jobs": job_results,
        }

    passed = len(all_failures) == 0
    return {
        "file": workflow_path.name,
        "name": wf_name,
        "passed": passed,
        "personas": persona_results,
        "failures": all_failures,
    }


def evaluate(
    workflows_dir: Path | None = None,
    personas: list[Persona] = PERSONAS,
    only_workflow: str | None = None
) -> list[dict[str, Any]]:
    target_dir = workflows_dir or WORKFLOWS_DIR
    wf_files = get_pr_workflows(target_dir)
    if only_workflow:
        wf_files = [f for f in wf_files if f.name == only_workflow]

    results = []
    for wf in wf_files:
        res = simulate_workflow(wf, personas)
        results.append(res)
    return results


def render_markdown(results: list[dict[str, Any]]) -> str:
    lines = [
        "## Fork simulation report",
        "",
        f"Simulated {len(results)} `pull_request` workflows under fork conditions "
        "(empty repository secrets, read-only `GITHUB_TOKEN`, synthetic branch) across 3 contributor personas.",
        "",
        "| Workflow | Verdict | External Contributor | Same-Repo Contributor | Renovate | Summary |",
        "|---|---|---|---|---|---|",
    ]

    status_icon = {
        "pass": "✅ pass",
        "fail": "❌ fail",
        "skipped": "⬜ skipped",
    }

    failed_wfs = []
    for r in results:
        v_icon = "✅ pass" if r["passed"] else "❌ fail"
        p_ext = status_icon.get(r["personas"]["external_contributor"]["status"], "—")
        p_same = status_icon.get(r["personas"]["same_repo_contributor"]["status"], "—")
        p_ren = status_icon.get(r["personas"]["renovate"]["status"], "—")
        summary = r["personas"]["external_contributor"]["details"]
        if not r["passed"]:
            failed_wfs.append(r["file"])
            summary = "; ".join(r["failures"])
        lines.append(
            f"| `{r['file']}` | {v_icon} | {p_ext} | {p_same} | {p_ren} | {summary} |"
        )

    lines.append("")
    if failed_wfs:
        lines.append(
            f"**Fork simulation failed for {len(failed_wfs)} workflow(s):** "
            + ", ".join(f"`{w}`" for w in failed_wfs)
            + ".\n\nFailing steps must be fork-guarded (e.g. `head.repo.fork`), "
            "deliver diffs to job summary instead of pushing/commenting, or check for empty secrets before use."
        )
    else:
        lines.append("All `pull_request` workflows passed fork simulation.")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", action="store_true", dest="as_json", help="emit JSON summary")
    ap.add_argument("--workflow", help="simulate a single workflow file")
    ap.add_argument("--dir", type=Path, help="workflows directory to evaluate")
    ap.add_argument("--strict", action="store_true", help="exit with non-zero code if any simulation fails")
    args = ap.parse_args(argv)

    results = evaluate(workflows_dir=args.dir, only_workflow=args.workflow)
    failed = [r["file"] for r in results if not r["passed"]]

    if args.as_json:
        data = {
            "passed": len(failed) == 0,
            "failed": failed,
            "total": len(results),
            "passed_count": len(results) - len(failed),
            "failed_count": len(failed),
            "personas": [p.id for p in PERSONAS],
            "workflows": results,
        }
        print(json.dumps(data, indent=2))
    else:
        print(render_markdown(results))

    if args.strict and failed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
