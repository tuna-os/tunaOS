#!/usr/bin/env python3
"""Generate the two-speed workflow inventory in docs/CI_SPEC.md.

The inventory is derived from workflow triggers and green-criteria gates. It is
not a hand-maintained status table: adding a workflow or moving a gate between
lanes changes generated output and the PR contract test.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
CRITERIA = ROOT / ".github/green-criteria.yml"
DOC = ROOT / "docs/CI_SPEC.md"
BEGIN = "<!-- BEGIN GENERATED CI LANES — scripts/gen-ci-lanes.py -->"
END = "<!-- END GENERATED CI LANES -->"

PR_TRIGGERS = {"pull_request", "pull_request_target", "merge_group"}
POST_MERGE_TRIGGERS = {
    "push",
    "workflow_run",
    "release",
    "repository_dispatch",
    "workflow_dispatch",
}


def triggers(document: dict) -> dict:
    """Return `on:` despite PyYAML's YAML-1.1 boolean parsing of that key."""
    value = document.get("on", document.get(True, {}))
    if isinstance(value, str):
        return {value: None}
    if isinstance(value, list):
        return {item: None for item in value}
    return value or {}


def load_workflows(directory: Path = WORKFLOWS) -> dict[str, dict]:
    return {
        f".github/workflows/{path.name}": yaml.safe_load(path.read_text()) or {}
        for path in sorted(directory.glob("*.y*ml"))
    }


def callers(workflows: dict[str, dict]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for caller, document in workflows.items():
        for job in (document.get("jobs") or {}).values():
            uses = (job or {}).get("uses", "")
            if isinstance(uses, str) and uses.startswith("./.github/workflows/"):
                result[uses[2:]].add(caller)
    return result


def workflow_lanes(name: str, workflows: dict[str, dict], seen=None) -> set[str]:
    """Classify direct triggers; reusable workflows inherit caller lanes."""
    seen = set(seen or ())
    if name in seen:
        return set()
    seen.add(name)
    on = set(triggers(workflows[name]))
    lanes = set()
    if on & PR_TRIGGERS:
        lanes.add("PR-deterministic")
    if "schedule" in on:
        lanes.add("scheduled")
    if on & POST_MERGE_TRIGGERS:
        lanes.add("post-merge")
    # Issue/discussion/status events are trusted-repository automation too.
    # Keep newly introduced event types visible without maintaining a second
    # exhaustive copy of GitHub's webhook catalogue here.
    if on - PR_TRIGGERS - {"schedule", "workflow_call"}:
        lanes.add("post-merge")
    for caller in callers(workflows).get(name, ()):
        lanes.update(workflow_lanes(caller, workflows, seen))
    # A workflow_call-only helper with no current caller is still inventory,
    # but it cannot claim to be a gate. Keep it visible in the post-merge lane.
    return lanes or {"post-merge"}


def trigger_cadence(document: dict) -> str:
    on = triggers(document)
    values = []
    if "pull_request" in on or "pull_request_target" in on:
        values.append("each PR")
    if "merge_group" in on:
        values.append("merge queue")
    if "push" in on:
        values.append("push")
    values.extend(f"`{entry['cron']}`" for entry in (on.get("schedule") or []))
    if "workflow_run" in on:
        values.append("workflow completion")
    if "release" in on:
        values.append("release")
    if "repository_dispatch" in on:
        values.append("repository dispatch")
    if "workflow_dispatch" in on:
        values.append("manual")
    if "workflow_call" in on:
        values.append("caller cadence")
    handled = PR_TRIGGERS | POST_MERGE_TRIGGERS | {"schedule", "workflow_call"}
    values.extend(sorted(set(on) - handled))
    return ", ".join(values) or "no active trigger"


def criterion_index(criteria_path: Path = CRITERIA):
    criteria = yaml.safe_load(criteria_path.read_text())["criteria"]
    asserted: dict[str, list[dict]] = defaultdict(list)
    for criterion in criteria:
        for gate in criterion.get("gates") or []:
            asserted[gate["workflow"]].append(criterion)
    return asserted


def escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def render(workflows=None, asserted=None) -> str:
    workflows = workflows or load_workflows()
    asserted = asserted or criterion_index()
    rows = [
        BEGIN,
        "",
        "## Executing workflow lanes",
        "",
        (
            "This inventory is generated from workflow triggers and "
            "`.github/green-criteria.yml`; run `scripts/gen-ci-lanes.py` after "
            "changing either. **PR-deterministic** is fast contributor feedback. "
            "**Post-merge** publishes or reacts to trusted repository events. "
            "**Scheduled** independently revalidates state and freshness."
        ),
        "",
        "| Workflow | Lane | Assertion | Cadence | Freshness SLA |",
        "|---|---|---|---|---|",
    ]
    order = {"PR-deterministic": 0, "post-merge": 1, "scheduled": 2}
    for name, document in workflows.items():
        criteria = asserted.get(name, [])
        lanes = sorted(workflow_lanes(name, workflows), key=order.get)
        assertion = ", ".join(f"`{item['id']}`" for item in criteria)
        if not assertion:
            assertion = escape(str(document.get("name") or "workflow automation"))
        slas = (
            ", ".join(f"`{item['id']}`: {item['freshness_sla_days']}d" for item in criteria) or "—"
        )
        rows.append(
            f"| `{Path(name).name}` | {' + '.join(lanes)} | {assertion} | "
            f"{escape(trigger_cadence(document))} | {slas} |"
        )
    rows.extend(["", END])
    return "\n".join(rows)


def update(check: bool = False, doc_path: Path = DOC) -> int:
    text = doc_path.read_text()
    if BEGIN not in text or END not in text:
        raise SystemExit(f"{doc_path} is missing the generated CI lane markers")
    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    updated = head + render() + tail
    if updated == text:
        print("CI lane inventory is current")
        return 0
    if check:
        print("CI lane inventory is out of date; run scripts/gen-ci-lanes.py", file=sys.stderr)
        return 1
    doc_path.write_text(updated)
    print(f"updated {doc_path}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    return update(args.check)


if __name__ == "__main__":
    raise SystemExit(main())
