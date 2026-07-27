#!/usr/bin/env python3
"""Regenerate the data tables in docs/MATRIX-STATUS.md.

Only the block between the GENERATED markers is rewritten. Everything else —
the scope section, the systemic gaps, the failure modes — is hand-written
narrative that no generator should be touching.

The whole point of the document is that "never tested" is distinguishable from
"passing", so this script is deliberately conservative: a cell is only marked
pass or fail if a named run actually asserted it. Anything else is UNTESTED,
and an API failure raises rather than silently degrading a cell to unknown —
a status page that quietly downgrades itself is worse than no status page.

Usage:
    scripts/gen-matrix-status.py [--check]

    --check  exit 1 if the file would change (for CI drift detection)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

REPO = "tuna-os/tunaOS"
DOC = Path("docs/MATRIX-STATUS.md")
CONFIG = Path(".github/build-config.yml")

BEGIN = "<!-- BEGIN GENERATED — scripts/gen-matrix-status.py -->"
END = "<!-- END GENERATED -->"

# How many recent runs to walk per workflow. Newest wins per cell, so this only
# needs to be deep enough to reach the last full sweep.
RUN_DEPTH = 20

DESKTOPS = ["gnome", "kde", "cosmic", "niri", "xfce"]

PASS, FAIL, UNTESTED, NA = "✅", "❌", "⬜", "—"


def gh_json(*args: str):
    """Run gh and parse JSON. Raises on failure — see module docstring."""
    out = subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=True
    ).stdout
    return json.loads(out) if out.strip() else None


def iso_matrix() -> dict[str, set[str]]:
    """variant -> {flavors with build_iso: true}, from build-config.yml."""
    try:
        import yaml
    except ImportError:
        sys.exit("PyYAML required: pip install pyyaml")
    cfg = yaml.safe_load(CONFIG.read_text())
    out: dict[str, set[str]] = {}
    for variant in cfg.get("variants", []):
        flavors = {
            f["id"] for f in variant.get("flavors", []) if f.get("build_iso")
        }
        if flavors:
            out[variant["id"]] = flavors
    return out


def latest_results(workflow: str, name_re: str) -> dict[str, tuple[str, str, str]]:
    """Newest result per job name across recent runs.

    Returns {job_name: (conclusion, iso_date, run_id)}. Walking newest-first
    and keeping the first hit means a cell re-run in isolation correctly
    supersedes its result from the last full sweep.
    """
    runs = gh_json(
        "run", "list", "--repo", REPO, "--workflow", workflow,
        "--limit", str(RUN_DEPTH),
        "--json", "databaseId,createdAt,status",
    ) or []
    pattern = re.compile(name_re)
    found: dict[str, tuple[str, str, str]] = {}
    for run in runs:
        if run.get("status") != "completed":
            continue
        run_id, date = str(run["databaseId"]), run["createdAt"][:10]
        detail = gh_json(
            "run", "view", run_id, "--repo", REPO, "--json", "jobs"
        ) or {}
        for job in detail.get("jobs", []):
            name, conclusion = job.get("name", ""), job.get("conclusion")
            if not pattern.search(name) or conclusion not in ("success", "failure"):
                continue
            found.setdefault(name, (conclusion, date, run_id))
    return found


def overlay_tags() -> set[str]:
    """Published live-overlay tags, digest tags excluded."""
    token_url = (
        "https://ghcr.io/token?scope=repository:tuna-os/live-overlay:pull"
    )
    with urllib.request.urlopen(token_url, timeout=30) as resp:
        token = json.load(resp)["token"]
    req = urllib.request.Request(
        "https://ghcr.io/v2/tuna-os/live-overlay/tags/list",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        tags = json.load(resp).get("tags") or []
    return {t for t in tags if not t.startswith("sha256-")}


def cell(results: dict, key: str, in_matrix: bool) -> str:
    """A real result always wins over "not built".

    sailfin has build_iso: false everywhere yet is covered by LUKS E2E. Keying
    the table purely off build_iso silently dropped four tested cells — the
    exact class of omission this document exists to prevent.
    """
    hit = results.get(key)
    if hit:
        return PASS if hit[0] == "success" else FAIL
    return UNTESTED if in_matrix else NA


def variants_in_scope(matrix, results) -> list[str]:
    """ISO-building variants, plus any variant a run actually exercised."""
    seen = set(matrix)
    for key in results:
        seen.add(key.replace("LUKS ", "").split(":")[0])
    return sorted(seen)


def desktop_table(matrix, results, key_fmt) -> list[str]:
    rows = ["| Variant | " + " | ".join(DESKTOPS) + " |",
            "|---|" + ":--:|" * len(DESKTOPS)]
    for variant in variants_in_scope(matrix, results):
        cells = [
            cell(results, key_fmt(variant, d), d in matrix.get(variant, set()))
            for d in DESKTOPS
        ]
        rows.append(f"| **{variant}** | " + " | ".join(cells) + " |")
    return rows


def tally(matrix, results, key_fmt):
    total = tested = passed = 0
    for variant in variants_in_scope(matrix, results):
        flavors = matrix.get(variant, set())
        for d in DESKTOPS:
            hit = results.get(key_fmt(variant, d))
            if d not in flavors and not hit:
                continue
            total += 1
            if hit:
                tested += 1
                if hit[0] == "success":
                    passed += 1
    return total, tested, passed


def nvidia_tally(matrix, results, key_fmt):
    """Count NVIDIA cells that still carry a stale result.

    luks-e2e.yml deliberately excludes -nvidia (commit 5c730e9, 2026-07-24):
    "-nvidia takes the identical LUKS path in headless QEMU (no GPU)". That is
    a sound scoping decision, so these cells are OUT OF SCOPE, not failing.

    Reporting them as "0 of 24 green" implied a 24-cell gap that nobody was
    ever going to close, which is its own kind of dishonest status page — the
    mirror image of the problem this document exists to fix. What is worth
    surfacing is only how many stale pre-exclusion results are still lying
    around, so the number shrinks to zero as they age out.
    """
    stale = 0
    for variant, flavors in matrix.items():
        for f in flavors:
            if "nvidia" in f and results.get(key_fmt(variant, f)):
                stale += 1
    return stale


def build() -> str:
    matrix = iso_matrix()
    luks = latest_results("luks-e2e.yml", r"^LUKS ")
    smoke = latest_results("installer-smoke.yml", r":")
    tags = overlay_tags()

    luks_key = lambda v, d: f"LUKS {v}:{d}"          # noqa: E731
    smoke_key = lambda v, d: f"{v}:{d}"              # noqa: E731

    # Deliberately NO wall-clock timestamp. A generated "as of <now>" line
    # changes on every run, which would (a) make --check always fail and (b)
    # produce a daily commit even when no cell moved. The commit date already
    # records when it ran; what matters here is how fresh the DATA is, which
    # is stated per-axis below and in Provenance.
    out: list[str] = [
        BEGIN,
        "",
        "*Generated by `scripts/gen-matrix-status.py` — do not edit this block "
        "by hand. It changes only when a cell actually moves, so this file's "
        "git history is a record of when each combination flipped.*",
        "",
    ]

    # ── LUKS ────────────────────────────────────────────────────────────────
    total, tested, passed = tally(matrix, luks, luks_key)
    nv_stale = nvidia_tally(matrix, luks, luks_key)
    out += [
        "## LUKS E2E",
        "",
        f"**{passed} of {total}** non-NVIDIA ISO cells green "
        f"({tested} tested, {total - tested} never tested).",
        "",
    ]
    out += desktop_table(matrix, luks, luks_key)
    if nv_stale:
        out += [
            "",
            f"NVIDIA cells are **out of scope** for this workflow — "
            f"`luks-e2e.yml` excludes them deliberately, because `-nvidia` "
            f"takes the identical LUKS path in headless QEMU. "
            f"{nv_stale} stale pre-exclusion result(s) remain from before "
            "that change; they are not a gap and will age out.",
            "",
        ]

    dates = sorted({v[1] for v in luks.values()})
    if dates:
        out += [
            f"Newest result {dates[-1]}, oldest still-authoritative result "
            f"{dates[0]}. Results older than the most recent round of fixes "
            "are the best available data, not current data.",
            "",
        ]

    # ── Installer smoke ─────────────────────────────────────────────────────
    total, tested, passed = tally(matrix, smoke, smoke_key)
    pct = round(100 * tested / total) if total else 0
    out += [
        "## Installer smoke",
        "",
        f"**{tested} of {total}** non-NVIDIA ISO cells have *ever* been "
        f"tested — {pct}% coverage. {passed} of those pass.",
        "",
        "This is the only axis that checks a human could actually install. "
        f"For {total - tested} combinations, nobody has confirmed the "
        "installer appears on screen.",
        "",
    ]
    out += desktop_table(matrix, smoke, smoke_key)
    out += [
        "",
        "cosmic, niri, xfwl4 and kde all need a DRM render node; a ❌ for those on "
        "hosted CI may be a harness limitation rather than a product failure. "
        "See *Known systemic gaps*.",
        "",
    ]

    # ── Overlays ────────────────────────────────────────────────────────────
    missing = sorted(
        f"{v}-{d}"
        for v, flavors in matrix.items()
        for d in flavors
        if "nvidia" not in d and "hwe" not in d and f"{v}-{d}" not in tags
    )
    out += [
        "## Live overlay",
        "",
        f"**{len(tags)}** tags published.",
        "",
    ]
    if missing:
        out += [
            f"Missing for {len(missing)} ISO cell(s): "
            + ", ".join(f"`{m}`" for m in missing),
            "",
        ]
    else:
        out += ["Every non-NVIDIA ISO cell has an overlay.", ""]

    # ── Provenance ──────────────────────────────────────────────────────────
    runs = defaultdict(list)
    for name, (_, date, run_id) in {**luks, **smoke}.items():
        runs[(date, run_id)].append(name)
    out += [
        "## Provenance",
        "",
        "| Date | Run | Cells |",
        "|---|---|---|",
    ]
    for (date, run_id), names in sorted(runs.items(), reverse=True)[:12]:
        url = f"https://github.com/{REPO}/actions/runs/{run_id}"
        out.append(f"| {date} | [{run_id}]({url}) | {len(names)} |")
    out += ["", END]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the document would change")
    args = ap.parse_args()

    if not DOC.exists():
        sys.exit(f"{DOC} not found — run from the repo root")
    text = DOC.read_text()
    if BEGIN not in text or END not in text:
        sys.exit(f"{DOC} is missing the GENERATED markers")

    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    updated = head + build() + tail

    if updated == text:
        print("MATRIX-STATUS.md already current")
        return 0
    if args.check:
        print("MATRIX-STATUS.md is out of date", file=sys.stderr)
        return 1
    DOC.write_text(updated)
    print(f"MATRIX-STATUS.md regenerated ({os.path.getsize(DOC)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
