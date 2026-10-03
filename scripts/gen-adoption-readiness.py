#!/usr/bin/env python3
"""Regenerate the live assessment in docs/ADOPTION-READINESS.md.

The assessment is a stricter, adoption-facing view of matrix-provenance.json.
It never treats a build as proof that an image can be installed or maintained.
"""

from __future__ import annotations

import argparse
import datetime
import difflib
import json
from pathlib import Path

import yaml

DOC = Path("docs/ADOPTION-READINESS.md")
PROVENANCE = Path("docs/matrix-provenance.json")
BUILD_CONFIG = Path(".github/build-config.yml")
GREEN_CRITERIA = Path(".github/green-criteria.yml")

BEGIN = "<!-- BEGIN GENERATED — scripts/gen-adoption-readiness.py -->"
END = "<!-- END GENERATED -->"
DESKTOPS = ["gnome", "kde", "cosmic", "niri", "xfce"]
REQUIRED_AXES = [
    "builds",
    "desktop",
    "boots",
    "iso",
    "install",
    "lifecycle",
    "parity",
    "no_silent_omissions",
]
GLYPHS = {"ready": "✅", "failed": "❌", "unverified": "⬜"}


def load_inputs() -> tuple[dict, dict, dict[str, int]]:
    config = yaml.safe_load(BUILD_CONFIG.read_text())
    provenance = json.loads(PROVENANCE.read_text())["cells"]
    criteria = yaml.safe_load(GREEN_CRITERIA.read_text())["criteria"]
    slas = {c["id"]: c["freshness_sla_days"] for c in criteria}
    return config, provenance, slas


def iso_desktop_matrix(config: dict) -> dict[str, set[str]]:
    """Return user-facing desktop cells that publish installation media."""
    return {
        variant["id"]: {
            flavor["id"]
            for flavor in variant.get("flavors", [])
            if flavor.get("build_iso") and flavor["id"] in DESKTOPS
        }
        for variant in config.get("variants", [])
        if any(
            flavor.get("build_iso") and flavor["id"] in DESKTOPS
            for flavor in variant.get("flavors", [])
        )
    }


def evidence_is_current(date: str, sla_days: int, today: datetime.date) -> bool:
    try:
        measured = datetime.date.fromisoformat(date)
    except (TypeError, ValueError):
        return False
    return (today - measured).days <= sla_days


def cell_status(
    axes: dict[str, dict[str, str]], slas: dict[str, int], today: datetime.date
) -> str:
    """Classify one cell without converting missing or stale evidence to green."""
    current = []
    incomplete = False
    for axis in REQUIRED_AXES:
        result = axes.get(axis, {})
        if not evidence_is_current(result.get("date", ""), slas[axis], today):
            incomplete = True
            continue
        current.append(result.get("verdict", "untested"))
    if "fail" in current:
        return "failed"
    if incomplete or any(verdict != "pass" for verdict in current):
        return "unverified"
    return "ready"


def build(today: datetime.date | None = None) -> str:
    config, provenance, slas = load_inputs()
    matrix = iso_desktop_matrix(config)
    today = today or datetime.date.today()
    statuses = {
        f"{variant}:{desktop}": cell_status(
            provenance.get(f"{variant}:{desktop}", {}), slas, today
        )
        for variant, desktops in matrix.items()
        for desktop in desktops
    }

    counts = {status: list(statuses.values()).count(status) for status in GLYPHS}
    out = [
        BEGIN,
        "",
        "*Generated from `.github/build-config.yml`, `.github/green-criteria.yml`, "
        "and `matrix-provenance.json`; do not edit this block by hand.*",
        "",
        "## Current automated candidates",
        "",
        (
            f"Among {len(statuses)} ISO cells for desktops, **{counts['ready']}** meet "
            "every automated adoption gate. "
            f"{counts['failed']} have a current failure. "
            f"{counts['unverified']} lack current evidence for at least one gate."
        ),
        "",
        "A ✅ is only an **automated candidate**, not an adoption-ready declaration. "
        "Before promotion, add evidence for physical hardware, a plain install, "
        "the support owner, and the limits of that cell.",
        "",
        "| Variant | " + " | ".join(DESKTOPS) + " |",
        "|---|" + ":--:|" * len(DESKTOPS),
    ]
    for variant in sorted(matrix):
        cells = [
            GLYPHS[statuses[f"{variant}:{desktop}"]]
            if desktop in matrix[variant]
            else "—"
            for desktop in DESKTOPS
        ]
        out.append(f"| **{variant}** | " + " | ".join(cells) + " |")

    out += [
        "",
        "### Desktop-family roll-up",
        "",
        "| Desktop | Ready candidates | Current failures | Unverified | ISO cells |",
        "|---|---:|---:|---:|---:|",
    ]
    for desktop in DESKTOPS:
        values = [
            statuses[f"{variant}:{desktop}"]
            for variant in matrix
            if desktop in matrix[variant]
        ]
        out.append(
            f"| {desktop.upper() if desktop == 'xfce' else desktop.title()} "
            f"| {values.count('ready')} | {values.count('failed')} "
            f"| {values.count('unverified')} | {len(values)} |"
        )

    tracks: dict[str, list[str]] = {
        "release/stream": [], "rolling": [], "experimental": []
    }
    for variant in config.get("variants", []):
        if variant["id"] in matrix:
            tracks.setdefault(variant.get("upstream_track", "release/stream"), []).append(
                variant["id"]
            )
    out += [
        "",
        "### Availability track",
        "",
        "This is the support promise declared by `.github/build-config.yml`, not a "
        "quality score. Failure remains fail-closed on every track.",
        "",
        "| Track | Variants with published desktop ISOs | Promise |",
        "|---|---|---|",
    ]
    promises = {
        "release/stream": "Continuous promotion target; red scheduled builds are regressions.",
        "rolling": "Best effort; upstream movement can interrupt promotion.",
        "experimental": "Evaluation only; no uptime or continued-publication promise.",
    }
    for track in ("release/stream", "rolling", "experimental"):
        names = ", ".join(f"`{name}`" for name in sorted(tracks.get(track, []))) or "—"
        out.append(f"| {track} | {names} | {promises[track]} |")

    out += [
        "",
        "The per-axis verdict, evidence run, and measurement date for every cell "
        "remain in [MATRIX-STATUS.md](MATRIX-STATUS.md) and "
        "[matrix-provenance.json](matrix-provenance.json).",
        "",
        END,
    ]
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    current = DOC.read_text()
    if BEGIN not in current or END not in current:
        raise SystemExit(f"{DOC} is missing generated markers")
    generated = build()
    updated = current.split(BEGIN, 1)[0] + generated + current.split(END, 1)[1]
    if args.check:
        if updated == current:
            return 0
        print("".join(difflib.unified_diff(current.splitlines(True), updated.splitlines(True))))
        return 1
    if updated != current:
        DOC.write_text(updated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
