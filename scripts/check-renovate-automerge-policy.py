#!/usr/bin/env python3
"""Enforce the tuna-os Renovate automerge boundary on a repository config.

Routine updates may automerge after CI. Major updates require human review.
This checks local overrides; the shared preset enforces the same boundary at
its source in tuna-os/.github.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RISKY_TYPES = {"major"}
SCOPING_KEYS = {
    "matchPackageNames",
    "matchPackagePatterns",
    "matchPackagePrefixes",
    "matchDepNames",
    "matchDepPatterns",
    "matchDepTypes",
    "matchDatasources",
    "matchManagers",
    "matchFileNames",
    "matchSourceUrls",
    "matchCurrentVersion",
    "matchCurrentValue",
    "matchBaseBranches",
    "matchLanguages",
    "matchCategories",
}


def violations(config: dict) -> list[str]:
    """Return descriptions of rules that can automerge a major update."""
    findings: list[str] = []
    state = {kind: bool(config.get("automerge", False)) for kind in RISKY_TYPES}
    source = {kind: "top-level automerge" for kind in RISKY_TYPES}

    for index, rule in enumerate(config.get("packageRules", [])):
        if "automerge" not in rule:
            continue

        match_types = rule.get("matchUpdateTypes")
        applies_to = RISKY_TYPES if match_types is None else RISKY_TYPES & set(match_types)
        if not applies_to:
            continue

        label = f"packageRules[{index}]"
        if rule.get("description"):
            label += f" ({rule['description']!r})"

        if SCOPING_KEYS & rule.keys():
            if rule["automerge"]:
                findings.append(f"{label} automerges major updates for a scoped dependency set")
            continue

        for kind in applies_to:
            state[kind] = bool(rule["automerge"])
            source[kind] = label

    for kind in sorted(RISKY_TYPES):
        if state[kind]:
            findings.append(f"{source[kind]} automerges {kind} updates")

    return findings


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "renovate.json")
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"ERROR: could not read/parse {path}: {error}", file=sys.stderr)
        return 1

    findings = violations(config)
    if findings:
        print(f"FAIL: {path} violates the org Renovate automerge policy:", file=sys.stderr)
        for finding in findings:
            print(f"  - {finding}", file=sys.stderr)
        print("Major updates require human review (tuna-os/.github#12).", file=sys.stderr)
        return 1

    print(f"OK: {path} does not automerge major updates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
