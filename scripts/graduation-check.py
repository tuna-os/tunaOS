#!/usr/bin/env python3
"""Which advisory green criteria have earned the right to block?

`.github/green-criteria.yml` marks a criterion `advisory` when it is measured
but not yet trusted to fail a cell. The file's own history shows what
happens next: `lifecycle` said "advisory until a second consecutive weekly
sweep holds the shape, then graduate" on 2026-08-17, and the graduation
depended on somebody remembering to look. Advisory checks that nobody
re-evaluates become permanent dashboard wallpaper (epic #2250, item 8).

This script makes the re-evaluation mechanical. The `graduation` block in
green-criteria.yml states the bar — how many consecutive scheduled runs of
the gate workflow must succeed, and how high the failure rate over a
lookback window may be — and this script measures each advisory criterion
against it from the workflow's real run history on the default branch.
It only RECOMMENDS: a human flips `enforcement`, because graduating a
criterion changes what "green" means for every cell.

Usage:
  scripts/graduation-check.py            # query GitHub via `gh`, print a report
  scripts/graduation-check.py --json     # machine-readable
  scripts/graduation-check.py --runs FILE  # offline: {"<workflow file>": [runs]}
                                           # (the shape `gh run list --json` emits)

Exit status is always 0 when the check ran; a criterion being ready is a
finding, not an error. Used by .github/workflows/graduation-check.yml, which
opens (or refreshes) an issue when at least one criterion is ready.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CRITERIA = ROOT / ".github" / "green-criteria.yml"

DEFAULT_POLICY = {
    "required_consecutive_passes": 3,
    "maximum_failure_rate": 0.10,
    "lookback_runs": 20,
}


def load(path: Path = CRITERIA) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def policy_for(spec: dict, criterion: dict) -> dict:
    """Repo-wide `graduation` block, overridden per criterion."""
    merged = dict(DEFAULT_POLICY)
    merged.update(spec.get("graduation") or {})
    merged.update(criterion.get("graduation") or {})
    return merged


def gh_runs(workflow_file: str, limit: int) -> list[dict] | None:
    """Completed scheduled runs on the default branch, newest first."""
    cmd = ["gh", "run", "list", "--workflow", workflow_file, "--event", "schedule",
           "--branch", "main", "--status", "completed", "--limit", str(limit),
           "--json", "conclusion,createdAt,databaseId,url"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return json.loads(out) if out.strip() else []


def measure(runs: list[dict]) -> dict:
    """Streak of leading successes and the failure rate over the window.

    `cancelled`, `skipped` and similar are not passes and not failures:
    they are runs that produced no verdict, and they break a streak the
    same way a red run does — a gate that did not run has not proven
    anything (the rule `skipped_is_not_green`).
    """
    streak = 0
    for r in runs:
        if r.get("conclusion") == "success":
            streak += 1
        else:
            break
    concluded = [r for r in runs if r.get("conclusion") in {"success", "failure"}]
    failures = sum(1 for r in concluded if r["conclusion"] == "failure")
    rate = failures / len(concluded) if concluded else None
    return {"streak": streak, "runs": len(runs), "failures": failures,
            "failure_rate": rate}


def evaluate(spec: dict, runs_for: callable) -> list[dict]:
    """One row per advisory criterion, with the verdict against its bar."""
    rows = []
    for c in spec["criteria"]:
        if c.get("enforcement") != "advisory":
            continue
        pol = policy_for(spec, c)
        workflows = sorted({g["workflow"] for g in c.get("gates") or []})
        row = {"id": c["id"], "policy": pol, "workflows": workflows,
               "measured": {}, "ready": False, "reason": ""}
        if not workflows:
            row["reason"] = "no gates declared"
            rows.append(row)
            continue
        verdicts = []
        for wf in workflows:
            runs = runs_for(Path(wf).name, pol["lookback_runs"])
            if runs is None:
                row["measured"][wf] = None
                verdicts.append((False, f"{Path(wf).name}: run history unavailable"))
                continue
            m = measure(runs)
            row["measured"][wf] = m
            need = pol["required_consecutive_passes"]
            if m["runs"] == 0:
                verdicts.append((False, f"{Path(wf).name}: no scheduled runs on main"))
            elif m["streak"] < need:
                verdicts.append((False, f"{Path(wf).name}: streak {m['streak']} < {need}"))
            elif m["failure_rate"] is not None and m["failure_rate"] > pol["maximum_failure_rate"]:
                verdicts.append((False, f"{Path(wf).name}: failure rate "
                                        f"{m['failure_rate']:.0%} > {pol['maximum_failure_rate']:.0%}"))
            else:
                verdicts.append((True, f"{Path(wf).name}: {m['streak']} consecutive passes, "
                                       f"{m['failures']}/{m['runs']} failed in window"))
        row["ready"] = all(ok for ok, _ in verdicts)
        row["reason"] = "; ".join(msg for _, msg in verdicts)
        rows.append(row)
    return rows


def render(rows: list[dict]) -> str:
    lines = ["| Criterion | Ready | Bar | Measured |", "|---|---|---|---|"]
    for r in rows:
        p = r["policy"]
        bar = (f"{p['required_consecutive_passes']} consecutive, "
               f"≤{p['maximum_failure_rate']:.0%} failed of last {p['lookback_runs']}")
        lines.append(f"| `{r['id']}` | {'✅ yes' if r['ready'] else '⬜ not yet'} | {bar} | {r['reason']} |")
    ready = [r["id"] for r in rows if r["ready"]]
    lines.append("")
    if ready:
        lines.append(f"**Ready to graduate advisory → blocking:** {', '.join(f'`{i}`' for i in ready)}. "
                     "A human flips `enforcement` in `.github/green-criteria.yml`; the composite "
                     "green count will change when they do — say by how much in the PR.")
    else:
        lines.append("No advisory criterion has met its graduation bar yet.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--criteria", type=Path, default=CRITERIA)
    ap.add_argument("--runs", type=Path, help="offline run history JSON keyed by workflow file name")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args(argv)

    spec = load(args.criteria)
    if args.runs:
        fixture = json.loads(args.runs.read_text(encoding="utf-8"))

        def runs_for(name: str, limit: int):
            runs = fixture.get(name)
            return None if runs is None else runs[:limit]
    else:
        runs_for = gh_runs

    rows = evaluate(spec, runs_for)
    if args.as_json:
        print(json.dumps({"ready": [r["id"] for r in rows if r["ready"]], "rows": rows}, indent=2))
    else:
        print(render(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
