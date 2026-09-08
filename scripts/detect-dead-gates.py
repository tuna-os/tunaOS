#!/usr/bin/env python3
"""Report assertions that have been red on every run for N consecutive runs.

A check that always says the same thing cannot report a regression. The
always-GREEN case is what epic #2250's CI contract already guards -- a
criterion with no executing implementation. This is the inverse, and on this
repo it cost more: three assertions in e2e-runtime-checks.sh were red on every
cell for months, each for a reason unrelated to what it claimed to test, and
each had been read as a known issue rather than as a dead gate.

The signal is cheap. TAP lines on the serial console are already collected in
the workflow logs; an assertion whose verdict has not changed in N runs is
either broken or measuring nothing, and both are worth a look.

This is deliberately a REPORT, not a gate. Turning "always red" into a hard
failure would block the repo on the very assertions it is trying to surface,
and a report that names them is enough to make them undeniable.

Usage:
    scripts/detect-dead-gates.py --workflow luks-e2e.yml --runs 10
    scripts/detect-dead-gates.py --from-logs out/*.log   # offline
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
import sys
from pathlib import Path

# Real TAP arrives on a guest serial console, so the line is prefixed with a
# kernel timestamp and the emitting unit:
#   [   11.6] e2e-runtime-checks[943]: not ok - graphical.target is active
# Allow any prefix that ends in ": ", plus bare TAP and "# "-quoted TAP.
TAP = re.compile(
    r"^(?:.*?:\s+)?(?:#\s*)?(ok|not ok)(?:\s+\d+)?\s+-\s+(.+?)\s*$", re.M
)


def parse_tap(text: str) -> dict[str, set[str]]:
    """assertion description -> set of verdicts seen ({'ok'}, {'not ok'}, or both)."""
    seen: dict[str, set[str]] = collections.defaultdict(set)
    for verdict, desc in TAP.findall(text):
        # Strip trailing measured values so "(state=x)" variants group together.
        key = re.sub(r"\s*\([^)]*\)\s*$", "", desc).strip()
        if key:
            seen[key].add(verdict)
    return seen


def gh_run_logs(workflow: str, limit: int) -> list[str]:
    ids = subprocess.run(
        ["gh", "run", "list", "--workflow", workflow, "--limit", str(limit),
         "--json", "databaseId", "-q", ".[].databaseId"],
        capture_output=True, text=True, check=False,
    ).stdout.split()
    out = []
    for rid in ids:
        r = subprocess.run(["gh", "run", "view", rid, "--log"],
                           capture_output=True, text=True, check=False)
        if r.stdout:
            out.append(r.stdout)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow")
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--from-logs", nargs="*", default=[])
    ap.add_argument("--min-runs", type=int, default=3,
                    help="don't call anything dead on fewer runs than this")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    texts = [Path(p).read_text(errors="replace") for p in args.from_logs]
    if args.workflow:
        texts += gh_run_logs(args.workflow, args.runs)
    if len(texts) < args.min_runs:
        print(f"only {len(texts)} run(s); need {args.min_runs} to judge — not enough evidence",
              file=sys.stderr)
        return 0

    merged: dict[str, set[str]] = collections.defaultdict(set)
    for t in texts:
        for k, v in parse_tap(t).items():
            merged[k] |= v

    always_red = sorted(k for k, v in merged.items() if v == {"not ok"})
    always_green = sorted(k for k, v in merged.items() if v == {"ok"})

    if args.json:
        print(json.dumps({"runs": len(texts), "always_red": always_red,
                          "always_green_count": len(always_green)}, indent=2))
    else:
        print(f"Examined {len(texts)} run(s), {len(merged)} distinct assertions.\n")
        if always_red:
            print(f"DEAD GATE CANDIDATES — red in every run ({len(always_red)}):")
            for k in always_red:
                print(f"  not ok (always) - {k}")
            print("\nAn assertion that never passes cannot report a regression.")
            print("Each of these is ONE of two things, and they need opposite responses:")
            print("  (a) a DEAD GATE  -- structurally incapable of passing, so it is")
            print("      measuring nothing and hiding whatever it claims to cover;")
            print("  (b) a REAL and persistent failure that nobody has acted on.")
            print("Both are worth a look; neither is a 'known issue'. Verified example")
            print("of each in this repo: 'graphical.target is active' was (a), asserted")
            print("from inside that target's own startup transaction; the pantheon")
            print("'screen is not blank' assertions were (b), a live session that")
            print("genuinely never painted.")
        else:
            print("No assertion was red in every run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
