#!/usr/bin/env python3
"""Prove that every green criterion is asserted by something that runs.

`.github/green-criteria.yml` says what "green" means. Each criterion carries a
`gates` block naming the workflow, the job(s), the verdict step, and the
scripts that assert it, plus a `freshness_sla_days` bound on how old its
evidence may be. That block is only worth anything if something checks it
against the workflows as they actually are — a test existing in the repository
is not the same as a test being run (#2250, Hive practice #1).

This script walks the contract and reports every way it can be broken:

  * a gate names a workflow, job, step or script that does not exist
  * a gate's workflow is not reachable from an active trigger (a reusable
    workflow nobody calls, or a workflow that only ever fires by hand)
  * a blocking gate's job or verdict step carries `continue-on-error`, so a
    failure would leave the run green
  * a blocking gate's job is conditionally skipped on the flavor without the
    criterion declaring a reviewed `scope` for the exemption
  * the schedule that produces the evidence fires less often than the
    criterion's freshness SLA allows

Usage: scripts/check-ci-contract.py [--criteria PATH] [--workflows DIR]
Exit status is the number of violations, capped at 1 for shells.
tests/test_ci_contract.py imports the same functions so the PR gate and the
CLI cannot disagree.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CRITERIA = ROOT / ".github" / "green-criteria.yml"
WORKFLOWS = ROOT / ".github" / "workflows"

# Triggers that fire without a human pressing a button. `workflow_dispatch`
# and `workflow_call` are deliberately absent: a workflow that can only be
# dispatched is a tool, not a gate, and a reusable workflow is only as active
# as whatever calls it.
ACTIVE_TRIGGERS = {"schedule", "push", "pull_request", "merge_group",
                   "workflow_run", "release"}


# ── loading ────────────────────────────────────────────────────────────────

def load_criteria(path: Path = CRITERIA) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["criteria"]


def load_workflows(directory: Path = WORKFLOWS) -> dict[str, dict]:
    """Map `.github/workflows/<name>` → parsed document."""
    docs = {}
    for f in sorted(directory.glob("*.y*ml")):
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        docs[f"{directory.relative_to(ROOT)}/{f.name}"] = doc
    return docs


def triggers(doc: dict) -> dict:
    """The `on:` block; PyYAML parses the bare key `on` as boolean True."""
    on = doc.get("on", doc.get(True, {}))
    if isinstance(on, str):
        return {on: None}
    if isinstance(on, list):
        return {k: None for k in on}
    return on or {}


# ── reachability ───────────────────────────────────────────────────────────

def callers(workflows: dict[str, dict]) -> dict[str, set[str]]:
    """Reusable workflow → the workflows whose jobs `uses:` it."""
    out: dict[str, set[str]] = {}
    for name, doc in workflows.items():
        for job in (doc.get("jobs") or {}).values():
            uses = (job or {}).get("uses", "")
            if isinstance(uses, str) and uses.startswith("./"):
                out.setdefault(uses[2:], set()).add(name)
    return out


def is_reachable(name: str, workflows: dict[str, dict], _seen=None) -> bool:
    """True when some active trigger leads to this workflow, directly or via
    a chain of `uses:` calls."""
    _seen = _seen or set()
    if name in _seen:
        return False
    _seen.add(name)
    doc = workflows.get(name)
    if doc is None:
        return False
    if ACTIVE_TRIGGERS & set(triggers(doc)):
        return True
    return any(is_reachable(c, workflows, _seen)
               for c in callers(workflows).get(name, ()))


# ── schedule cadence ───────────────────────────────────────────────────────

def _expand(field: str, lo: int, hi: int) -> set[int]:
    """Expand one cron field (lists, ranges, steps, names not supported)."""
    vals: set[int] = set()
    for part in field.split(","):
        step = 1
        if "/" in part:
            part, step_s = part.split("/", 1)
            step = int(step_s)
        if part == "*":
            a, b = lo, hi
        elif "-" in part:
            a_s, b_s = part.split("-", 1)
            a, b = int(a_s), int(b_s)
        else:
            a = b = int(part)
        vals.update(range(a, b + 1, step))
    return vals


_DOW_NAMES = {"SUN": "0", "MON": "1", "TUE": "2", "WED": "3", "THU": "4",
              "FRI": "5", "SAT": "6"}


def cron_max_gap_days(expr: str) -> float:
    """Longest wait between two firings of a cron, in days (upper bound).

    Deliberately coarse: the contract asks "does this fire at least every N
    days", and the answer only needs to be right at the granularity of the
    SLAs in use (2, 8, 35). A daily cron is 1; weekly on one weekday is 7;
    monthly on one day-of-month is 31; every-N-months multiplies by N.
    """
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(f"not a 5-field cron: {expr!r}")
    _minute, _hour, dom, mon, dow = fields
    for name, num in _DOW_NAMES.items():
        dow = dow.upper().replace(name, num)
    dow = dow.replace("7", "0")

    def circular_gap(values: set[int], period: int) -> int:
        if not values:
            return period
        ordered = sorted(values)
        gaps = [b - a for a, b in zip(ordered, ordered[1:])]
        gaps.append(period - ordered[-1] + ordered[0])
        return max(gaps)

    month_factor = 1
    if mon != "*":
        months = _expand(mon, 1, 12)
        month_factor = circular_gap(months, 12)

    if dom == "*" and dow == "*":
        return 1.0 * month_factor
    candidates = []
    if dow != "*":
        candidates.append(circular_gap(_expand(dow, 0, 6), 7))
    if dom != "*":
        candidates.append(circular_gap(_expand(dom, 1, 31), 31))
    # cron ORs day-of-month and day-of-week when both are restricted, so the
    # firing set is the union and the gap is the smaller of the two.
    return float(min(candidates)) * month_factor


def cadence_days(name: str, workflows: dict[str, dict], _seen=None) -> float | None:
    """How often evidence from this workflow is refreshed, in days.

    0 means "on every change" (push / pull_request), a schedule gives its
    max gap, a reusable workflow inherits the best cadence of its callers,
    and None means nothing automatic ever runs it.
    """
    _seen = _seen or set()
    if name in _seen:
        return None
    _seen.add(name)
    doc = workflows.get(name)
    if doc is None:
        return None
    on = triggers(doc)
    best: float | None = None
    if {"push", "pull_request", "merge_group"} & set(on):
        best = 0.0
    for entry in on.get("schedule") or []:
        gap = cron_max_gap_days(entry["cron"])
        best = gap if best is None else min(best, gap)
    for caller in callers(workflows).get(name, ()):
        c = cadence_days(caller, workflows, _seen)
        if c is not None:
            best = c if best is None else min(best, c)
    return best


# ── the checks ─────────────────────────────────────────────────────────────

def _steps_by_name(job: dict) -> dict[str, dict]:
    return {s.get("name"): s for s in (job.get("steps") or []) if s.get("name")}


def violations_for(criterion: dict, workflows: dict[str, dict],
                   root: Path = ROOT) -> list[str]:
    cid = criterion["id"]
    problems: list[str] = []
    gates = criterion.get("gates")
    if not gates:
        if criterion.get("asserted_by"):
            problems.append(f"{cid}: asserted_by names something but there is "
                            "no machine-readable `gates` block")
        return problems
    if "freshness_sla_days" not in criterion:
        problems.append(f"{cid}: no freshness_sla_days — evidence with no "
                        "expiry is never stale, which the rule forbids")
    blocking = criterion.get("enforcement") == "blocking"
    prose = criterion.get("asserted_by") or ""

    for gate in gates:
        wf = gate["workflow"]
        doc = workflows.get(wf)
        if doc is None:
            problems.append(f"{cid}: gate workflow {wf} does not exist")
            continue
        if wf.split("/")[-1] not in prose:
            problems.append(f"{cid}: gate workflow {wf} is not mentioned in "
                            "asserted_by — the prose and the contract drifted")
        if not is_reachable(wf, workflows):
            problems.append(f"{cid}: {wf} is not reachable from any active "
                            "trigger (schedule/push/pull_request or a caller "
                            "that has one)")
        sla = criterion.get("freshness_sla_days")
        cad = cadence_days(wf, workflows)
        if sla is not None and cad is not None and cad > sla:
            problems.append(f"{cid}: {wf} refreshes evidence every {cad:g} "
                            f"days but the freshness SLA is {sla} days")

        jobs = doc.get("jobs") or {}
        for job_id, verdict_step in (gate.get("jobs") or {}).items():
            job = jobs.get(job_id)
            if job is None:
                problems.append(f"{cid}: {wf} has no job {job_id!r} "
                                f"(has {sorted(jobs)})")
                continue
            cond = str(job.get("if") or "")
            if cond.strip() in {"false", "${{ false }}"}:
                problems.append(f"{cid}: {wf}:{job_id} is hard-disabled "
                                "(`if: false`)")
            if blocking:
                if job.get("continue-on-error"):
                    problems.append(f"{cid}: blocking gate {wf}:{job_id} has "
                                    "continue-on-error — a failure would not "
                                    "fail the run")
                if ("inputs.flavor" in cond or "matrix.flavor" in cond) \
                        and not criterion.get("scope"):
                    problems.append(f"{cid}: blocking gate {wf}:{job_id} skips "
                                    "on the flavor but the criterion declares "
                                    "no `scope` exemption")
            if verdict_step:
                steps = _steps_by_name(job)
                step = steps.get(verdict_step)
                if step is None:
                    problems.append(f"{cid}: {wf}:{job_id} has no step named "
                                    f"{verdict_step!r} (has {sorted(steps)})")
                elif blocking and step.get("continue-on-error"):
                    problems.append(f"{cid}: verdict step {verdict_step!r} in "
                                    f"{wf}:{job_id} has continue-on-error")
        for script in gate.get("scripts") or []:
            if not (root / script).is_file():
                problems.append(f"{cid}: gate script {script} does not exist")
    return problems


def _ancestors(job_id: str, jobs: dict[str, dict]) -> set[str]:
    anc: set[str] = set()
    job = jobs.get(job_id)
    if not job:
        return anc
    direct_needs = job.get("needs") or []
    if isinstance(direct_needs, str):
        direct_needs = [direct_needs]
    for n in direct_needs:
        anc.add(n)
        anc.update(_ancestors(n, jobs))
    return anc


def check_promote_covers_blocking_gates(
    criteria: list[dict], workflows: dict[str, dict]
) -> list[str]:
    """Every blocking gate in a workflow that contains a Promote job must be
    required by Promote's `needs` and guarded by its `if` condition (#2263).

    Without this, adding a blocking gate to a workflow does not stop Promote
    from shipping a broken image when that gate fails.
    """
    problems: list[str] = []
    blocking_gates_by_wf: dict[str, set[str]] = {}
    for c in criteria:
        if c.get("enforcement") != "blocking":
            continue
        for gate in c.get("gates") or []:
            wf = gate["workflow"]
            for job_id in (gate.get("jobs") or {}).keys():
                blocking_gates_by_wf.setdefault(wf, set()).add(job_id)

    for wf_name, doc in workflows.items():
        jobs = doc.get("jobs") or {}
        for job_id, job in jobs.items():
            is_promote = (
                job_id in {"tag-image", "tag_image", "promote"}
                or job.get("name") == "Promote"
            )
            if not is_promote:
                continue

            needs = job.get("needs") or []
            if isinstance(needs, str):
                needs = [needs]
            needs_set = set(needs)

            all_ancestors: set[str] = set()
            for n in needs_set:
                all_ancestors.update(_ancestors(n, jobs))

            cond = str(job.get("if") or "")

            expected_gates = blocking_gates_by_wf.get(wf_name, set())
            for gate_job_id in sorted(expected_gates):
                if gate_job_id == job_id or gate_job_id in all_ancestors:
                    continue
                if gate_job_id not in needs_set:
                    problems.append(
                        f"{wf_name}:{job_id} (Promote) does not include blocking "
                        f"gate {gate_job_id!r} in its `needs`"
                    )
                result_check = f"needs.{gate_job_id}.result"
                if result_check not in cond:
                    problems.append(
                        f"{wf_name}:{job_id} (Promote) `if:` does not check "
                        f"{result_check!r}"
                    )
    return problems


def check(criteria_path: Path = CRITERIA, workflows_dir: Path = WORKFLOWS) -> list[str]:
    workflows = load_workflows(workflows_dir)
    criteria = load_criteria(criteria_path)
    problems: list[str] = []
    for c in criteria:
        problems.extend(violations_for(c, workflows, criteria_path.parents[1]))
    problems.extend(check_promote_covers_blocking_gates(criteria, workflows))
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--criteria", type=Path, default=CRITERIA)
    ap.add_argument("--workflows", type=Path, default=WORKFLOWS)
    args = ap.parse_args(argv)
    problems = check(args.criteria, args.workflows)
    if problems:
        print(f"CI contract: {len(problems)} violation(s)")
        for p in problems:
            print(f"  ✗ {p}")
        return 1
    criteria = load_criteria(args.criteria)
    print(f"CI contract: {len(criteria)} criteria, every gate exists, is "
          "reachable, and meets its freshness SLA")
    return 0


if __name__ == "__main__":
    sys.exit(main())
