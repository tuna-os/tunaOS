#!/usr/bin/env python3
"""Compare installer e2e evidence with the ISO+fisherman LUKS lane.

Reads our evidence (results.json plus <boot>-stages.json), the medium
size, and an optional LUKS baseline file. Writes comparison.json and
appends a stage table to the job summary. A missing baseline is not a
failure: the comparison records its absence so the gap stays visible.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_stages(evidence):
    """{(boot): [stage dicts]} for every per-boot evidence file."""
    out = {}
    for path in sorted(Path(evidence).glob("*-stages.json")):
        try:
            out[path.stem.removesuffix("-stages")] = json.loads(path.read_text())["stages"]
        except (json.JSONDecodeError, KeyError, OSError):
            continue
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--medium", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--summary", default="")
    parser.add_argument("--baseline", default="")
    args = parser.parse_args(argv)

    medium = Path(args.medium)
    stages = load_stages(args.evidence)
    baseline = None
    if args.baseline and Path(args.baseline).exists():
        try:
            baseline = json.loads(Path(args.baseline).read_text())
        except json.JSONDecodeError:
            baseline = {"error": "baseline is not JSON"}
    comparison = {
        "medium_bytes": medium.stat().st_size if medium.exists() else None,
        "stages": stages,
        "baseline": baseline,
    }
    Path(args.out).write_text(json.dumps(comparison, indent=2) + "\n")

    if args.summary:
        order = (
            "live-boot",
            "installer-pages",
            "install",
            "unlock",
            "first-boot-setup",
            "desktop-status",
            "switch-rollback",
        )
        with open(args.summary, "a", encoding="utf-8") as handle:
            handle.write("## Image installer e2e\n\n")
            handle.write("| Stage | cdrom | usb |\n|---|---|---|\n")
            for stage in order:
                cells = []
                for boot in ("cdrom", "usb"):
                    status = next(
                        (
                            s.get("status", "?")
                            for s in stages.get(boot, [])
                            if s.get("id") == stage
                        ),
                        "—",
                    )
                    cells.append(status)
                handle.write(f"| {stage} | {cells[0]} | {cells[1]} |\n")
            handle.write(f"\nbaseline: {'present' if baseline else 'none found'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
