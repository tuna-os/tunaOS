#!/usr/bin/env python3
"""Read-only CI inventory for #3011; writes JSON, never changes repository settings.

Requires gh authenticated with GH_TOKEN and PyYAML. Missing API access is recorded
as unknown, never interpreted as an absent gate. No workflow code is executed.
"""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from urllib.parse import quote

import yaml


def api(endpoint: str, *, paginate: bool = False):
    command = ["gh", "api", "--method", "GET", endpoint]
    if paginate:
        command += ["--paginate", "--slurp"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=90)
    if result.returncode:
        # stdout contains the API's JSON error, not token-bearing request headers.
        raise RuntimeError(result.stdout.strip() or "gh API request failed")
    data = json.loads(result.stdout)
    return [item for page in data for item in page] if paginate else data


def observation(endpoint: str, *, paginate: bool = False) -> dict:
    try:
        return {"state": "observed", "value": api(endpoint, paginate=paginate)}
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        return {"state": "unknown", "error": str(error)}


def workflow_summary(path: str, text: str) -> dict:
    doc = yaml.safe_load(text) or {}
    if not isinstance(doc, dict):
        raise ValueError("workflow must be a mapping")
    triggers = doc.get("on", doc.get(True, {})) or {}
    if isinstance(triggers, str):
        triggers = [triggers]
    definitions = doc.get("jobs") or {}
    if not isinstance(definitions, dict):
        raise ValueError("jobs must be a mapping")
    jobs = []
    for job_id, job in definitions.items():
        if not isinstance(job, dict):
            raise ValueError(f"job {job_id} must be a mapping")
        uses = job.get("uses")
        jobs.append({
            "id": job_id,
            "name": job.get("name", job_id),
            "uses": uses,
            "timeout_minutes": job.get("timeout-minutes"),
            "timeout_source": "callee" if uses else (
                "explicit" if "timeout-minutes" in job else "platform-default"),
            "continue_on_error": job.get("continue-on-error", False),
            "if": job.get("if"),
            "step_continue_on_error": [
                step.get("name", step.get("id", str(index)))
                for index, step in enumerate(job.get("steps") or [])
                if step.get("continue-on-error")
            ],
        })
    return {"path": path, "triggers": sorted(triggers), "jobs": jobs}


def audit_repo(repo: dict) -> dict:
    name, branch = repo["full_name"], repo["default_branch"]
    result = {"repository": name, "default_branch": branch,
              "archived": repo["archived"], "fork": repo["fork"], "workflows": []}
    root = f"repos/{name}"
    encoded_branch = quote(branch, safe="")
    # Effective rules include inherited rulesets; classic protection is separate.
    result["branch_protection"] = observation(
        f"{root}/branches/{encoded_branch}/protection")
    result["effective_rules"] = observation(
        f"{root}/rules/branches/{encoded_branch}", paginate=True)
    try:
        commit = api(f"{root}/commits/{encoded_branch}")
        result["sha"] = commit["sha"]
        tree = api(f"{root}/git/trees/{commit['commit']['tree']['sha']}?recursive=1")
        if tree.get("truncated"):
            raise RuntimeError("Git tree truncated; inventory is incomplete")
        for entry in tree["tree"]:
            path = entry["path"]
            if (entry["type"] != "blob" or not path.startswith(".github/workflows/")
                    or path.count("/") != 2 or not path.endswith((".yml", ".yaml"))):
                continue
            try:
                blob = api(f"{root}/git/blobs/{entry['sha']}")
                summary = workflow_summary(path, base64.b64decode(blob["content"]).decode())
                result["workflows"].append(summary)
            except (RuntimeError, ValueError, TypeError, AttributeError, yaml.YAMLError, subprocess.TimeoutExpired) as error:
                result["workflows"].append({"path": path, "error": str(error)})
        result["inventory_state"] = (
            "incomplete" if any("error" in w for w in result["workflows"]) else "observed")
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        result.update(inventory_state="unknown", error=str(error))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", default="tuna-os")
    parser.add_argument("--repo", action="append", help="Repository name; repeat to restrict scope")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repos = api(f"orgs/{quote(args.org, safe='')}/repos?per_page=100", paginate=True)
    if args.repo:
        requested = set(args.repo)
        found = {r["name"] for r in repos}
        if requested - found:
            parser.error(f"repositories not found: {sorted(requested - found)}")
        repos = [r for r in repos if r["name"] in requested]
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(audit_repo, sorted(repos, key=lambda r: r["full_name"])))
    report = {"schema": 1, "observed_at": datetime.now(timezone.utc).isoformat(),
              "organization": args.org, "repositories": rows}
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    incomplete = sum(r["inventory_state"] != "observed" for r in rows)
    unknown_settings = sum(
        r[key]["state"] == "unknown" for r in rows
        for key in ("branch_protection", "effective_rules"))
    print(f"{len(rows)} repositories; {incomplete} incomplete workflow inventories; "
          f"{unknown_settings} unknown protection/rules observations; {args.output}")
    return 1 if incomplete else 0


if __name__ == "__main__":
    raise SystemExit(main())
