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
    scripts/gen-matrix-status.py [--check | --check-structure]

    --check            exit 1 if the file would change (for CI drift detection)
    --check-structure  exit 1 only if the block differs in ways a pull request
                       controls — hand-edits and build-config drift — ignoring
                       content that is a function of live CI state
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

REPO = "tuna-os/tunaOS"
DOC = Path("docs/MATRIX-STATUS.md")
PROV = Path("docs/matrix-provenance.json")
CONFIG = Path(".github/build-config.yml")
GREEN_CRITERIA = Path(".github/green-criteria.yml")

BEGIN = "<!-- BEGIN GENERATED — scripts/gen-matrix-status.py -->"
END = "<!-- END GENERATED -->"

# How many recent COMPLETED runs to walk per workflow.
#
# This was 20, with the reasoning "newest wins per cell, so this only needs to
# be deep enough to reach the last full sweep". That holds while cells are
# tested in sweeps. It breaks the moment they are dispatched one at a time:
# ~15 single-cell luks-e2e runs in one morning pushed every earlier result out
# of the window, and the generator reported
#
#   -**3 of 54** cells green (41 tested, 13 never tested).
#   +**7 of 53** cells green (10 tested, 43 never tested).
#
# flipping whole rows — every marlin cell, most of yellowfin and albacore —
# from a real ❌ or ✅ to ⬜ "never tested". Those results had not been
# superseded; they had scrolled off. This file's own header argues that a
# status page which quietly downgrades itself is worse than no status page,
# and that is exactly what happened.
#
# Depth is cheap in correctness and linear in API calls (one `run view` each),
# so it is set to cover a heavy debugging day rather than a sweep. Counting only
# completed runs (see FETCH_DEPTH below) matters as much, for the same reason.
#
# 80 was measured against live data and lands ON the cliff edge rather than past
# it: walking it, cells were still being discovered at positions 74, 75, 76, 78,
# 79 and 80 — the window ends part-way through the last sweep, not after it. Two
# walks minutes apart disagreed about `yellowfin:xfce`, ❌ in one and ⬜ "never
# tested" in the other, because a run completing at the head pushed its result
# past the boundary. A depth that reports a different table depending on the
# minute it runs is the same silent downgrade, just intermittent, and it also
# drifts the generated prose (the stale-NVIDIA count) with it.
#
# Measured tallies for the same repo, minutes apart, varying only this number:
#
#    20 →  8 of 53 green (11 tested, 42 never tested)
#    80 → 24 of 53 green (41 tested, 12 never tested)
#   150 → 24 of 53 green (41 tested, 12 never tested)
#   200 → 29 of 54 green (50 tested,  4 never tested)
#
# The plateau between 80 and 150 is why 80 looked sufficient: the next sweep
# worth reaching sits past 150, so a spot check at any depth in between agrees
# with itself and still misses two thirds of the untested cells. 200 reaches it
# — the oldest still-authoritative result moves from 2026-08-05 back to
# 2026-08-01 — and whole rows (bonito-rawhide, flounder-sid) come back with it.
#
# Do not read 200 as the saturation point; read it as the depth at which the
# walk stopped telling us it was truncating. latest_results warns on stderr
# when the oldest run it examined was still producing first-time results, which
# is the condition that made 20 and then 80 wrong, and it is silent at 200 (see issue #931).
# Raise this when that warning appears rather than when a row looks wrong.
RUN_DEPTH = 200

# Queued and in-progress runs carry no results, so they must not consume window
# slots: during a dispatch sweep half the newest runs are in flight, and letting
# them eat the window silently demoted cells a completed run had already
# asserted back to "never tested" — the exact absence-of-evidence failure this
# document exists to prevent. So fetch wider and count only completed runs.
FETCH_DEPTH = RUN_DEPTH * 4

DESKTOPS = ["gnome", "kde", "cosmic", "niri", "xfce"]

PASS, FAIL, UNTESTED, NA = "✅", "❌", "⬜", "—"


def gh_json(*args: str):
    """Run gh and parse JSON. Returns None on missing/failed query after retries."""
    for attempt in range(3):
        try:
            out = subprocess.run(
                ["gh", *args], capture_output=True, text=True, check=True
            ).stdout
            return json.loads(out) if out.strip() else None
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            if attempt == 2:
                return None
            time.sleep(2)
    return None


def load_build_config(config_path: Path = CONFIG) -> dict:
    """Load .github/build-config.yml using PyYAML or internal fallback parser."""
    try:
        import yaml
        return yaml.safe_load(config_path.read_text())
    except ImportError:
        pass
    content = config_path.read_text()
    iso_groups = []
    if "iso_groups:" in content:
        ig_section = content.split("iso_groups:\n", 1)[1].split("\n\n", 1)[0]
        current_g = None
        for line in ig_section.splitlines():
            line = line.strip()
            if line.startswith("- suffix:"):
                if current_g:
                    iso_groups.append(current_g)
                suf = line.split(":", 1)[1].strip().strip("\"'")
                current_g = {"suffix": suf, "publish": True, "flavors": [], "offline_flavors": []}
            elif line.startswith("publish:") and current_g:
                current_g["publish"] = line.split(":", 1)[1].strip() == "true"
            elif line.startswith("flavors:") and current_g:
                flavs = line.split("[", 1)[1].split("]", 1)[0].split(",")
                current_g["flavors"] = [fl.strip() for fl in flavs if fl.strip()]
            elif line.startswith("offline_flavors:") and current_g:
                flavs = line.split("[", 1)[1].split("]", 1)[0].split(",")
                current_g["offline_flavors"] = [fl.strip() for fl in flavs if fl.strip()]
        if current_g:
            iso_groups.append(current_g)

    variants = []
    v_section = content.split("variants:\n", 1)[1]
    raw_vars = re.split(r"\n  - id: ", "\n" + v_section)
    for rv in raw_vars:
        if not rv.strip():
            continue
        lines = rv.strip().splitlines()
        vid = lines[0].split("#")[0].strip().strip("\"'")
        v_platforms = ["linux/amd64", "linux/arm64"]
        header_part = rv.split("flavors:\n", 1)[0]
        vp_match = re.search(r"platforms:\s*\[(.*?)\]", header_part)
        if vp_match:
            v_platforms = [p.strip().strip("\"'") for p in vp_match.group(1).split(",")]
        flavors = []
        if "flavors:" in rv:
            fl_text = rv.split("flavors:\n", 1)[1]
            raw_fls = re.split(r"\n      - id: ", "\n" + fl_text)
            for rf in raw_fls:
                if not rf.strip():
                    continue
                fl_lines = rf.strip().splitlines()
                fid = fl_lines[0].split("#")[0].strip().strip("\"'")
                b_img = "build_image: true" in rf
                b_iso = "build_iso: true" in rf
                b_qcow2 = "build_qcow2: true" in rf
                fp_match = re.search(r"platforms:\s*\[(.*?)\]", rf)
                if fp_match:
                    f_platforms = [p.strip().strip("\"'") for p in fp_match.group(1).split(",")]
                else:
                    f_platforms = list(v_platforms)
                flavors.append({
                    "id": fid,
                    "build_image": b_img,
                    "build_iso": b_iso,
                    "build_qcow2": b_qcow2,
                    "platforms": f_platforms,
                })
        variants.append({
            "id": vid,
            "platforms": v_platforms,
            "flavors": flavors,
        })
    return {"iso_groups": iso_groups, "variants": variants}


def _matrix(key: str, desktops_only: bool) -> dict[str, set[str]]:
    """variant -> {flavors where <key> is true}, from build-config.yml."""
    cfg = load_build_config(CONFIG)
    out: dict[str, set[str]] = {}
    for variant in cfg.get("variants", []):
        flavors = {
            f["id"]
            for f in variant.get("flavors", [])
            if f.get(key) and (not desktops_only or f["id"] in DESKTOPS)
        }
        if flavors:
            out[variant["id"]] = flavors
    return out


def iso_matrix() -> dict[str, set[str]]:
    """Cells that ship an ISO. The denominator for installer smoke."""
    return _matrix("build_iso", desktops_only=False)


def luks_matrix() -> dict[str, set[str]]:
    """Cells LUKS E2E actually covers — the denominator for that axis.

    luks-e2e.yml builds its matrix from build_image, NOT build_iso, and says
    why: the browser ISO builder makes an ISO from any published image, so
    image-only variants (sailfin, guppy, flounder-sid) need boot+install
    coverage too. Measuring that axis against build_iso understated the work
    being done and forced a "promote any result over not-built" special case
    in cell() to stop sailfin's four tested cells from vanishing.

    Using the workflow's own definition removes the special case: a cell is in
    the LUKS denominator exactly when luks-e2e.yml would schedule it.
    """
    return _matrix("build_image", desktops_only=True)


def latest_results(workflow: str, name_re: str) -> dict[str, tuple[str, str, str]]:
    """Newest result per job name across recent runs.

    Returns {job_name: (conclusion, iso_date, run_id)}. Walking newest-first
    and keeping the first hit means a cell re-run in isolation correctly
    supersedes its result from the last full sweep.
    """
    runs = gh_json(
        "run", "list", "--repo", REPO, "--workflow", workflow,
        "--limit", str(FETCH_DEPTH),
        "--json", "databaseId,createdAt,status",
    ) or []
    pattern = re.compile(name_re)
    found: dict[str, tuple[str, str, str]] = {}
    walked = 0
    deepest_was_new = False
    for run in runs:
        if run.get("status") != "completed":
            continue
        if walked >= RUN_DEPTH:
            break
        walked += 1
        run_id, date = str(run["databaseId"]), run["createdAt"][:10]
        detail = gh_json(
            "run", "view", run_id, "--repo", REPO, "--json", "jobs"
        ) or {}
        deepest_was_new = False
        for job in detail.get("jobs", []):
            name, conclusion = job.get("name", ""), job.get("conclusion")
            if not pattern.search(name) or conclusion not in ("success", "failure"):
                continue
            if name not in found:
                deepest_was_new = True
            found.setdefault(name, (conclusion, date, run_id))

    # Say so when the window is the thing deciding the answer. RUN_DEPTH has now
    # been outgrown twice, and both times the only symptom was cells quietly
    # reading ⬜ "never tested" — the walk stopped mid-discovery and the page
    # reported the shortfall as fact. If the oldest run we looked at was still
    # handing us cells we had not seen, there is no reason to believe the next
    # one would not have too, so the depth is a lower bound, not a sweep.
    #
    # The test is `walked`, not len(runs): the fetch is deliberately wider than
    # the window (FETCH_DEPTH) so that in-flight runs cannot eat slots, so
    # len(runs) says nothing about whether the walk was cut short. Only hitting
    # the RUN_DEPTH cap does.
    if deepest_was_new and walked >= RUN_DEPTH:
        print(
            f"warning: {workflow}: the oldest of {walked} completed runs examined "
            "still contained results not seen in any newer run, so RUN_DEPTH is "
            "cutting the walk short and cells may read as never tested when "
            "they have in fact been tested. Raise RUN_DEPTH.",
            file=sys.stderr,
        )
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


_BASELINE_CACHE: tuple[list[dict], str, str] | None = None


def _baseline_cells() -> tuple[list[dict], str, str]:
    """The newest trustworthy desktop-contract-baseline artifact, once.

    contract_results() and omissions_results() read the same all.json — the
    sweep records both axes from one image pull — so download it once per
    invocation rather than once per axis.
    """
    global _BASELINE_CACHE
    if _BASELINE_CACHE is not None:
        return _BASELINE_CACHE
    runs = gh_json(
        "run", "list", "--repo", REPO, "--workflow", "desktop-contract-sweep.yml",
        "--limit", "10", "--json", "databaseId,createdAt,status,conclusion",
    ) or []
    for run in runs:
        if run.get("status") != "completed" or run.get("conclusion") != "success":
            continue
        run_id, date = str(run["databaseId"]), run["createdAt"][:10]
        with tempfile.TemporaryDirectory() as tmp:
            try:
                subprocess.run(
                    ["gh", "run", "download", run_id, "--repo", REPO,
                     "--name", "desktop-contract-baseline", "--dir", tmp],
                    capture_output=True, text=True, check=True,
                )
            except subprocess.CalledProcessError:
                continue
            all_json = Path(tmp) / "all.json"
            if not all_json.exists():
                continue
            _BASELINE_CACHE = (json.loads(all_json.read_text()), date, run_id)
            return _BASELINE_CACHE
    _BASELINE_CACHE = ([], "", "")
    return _BASELINE_CACHE


def omissions_results() -> dict[str, tuple[str, str, str]]:
    """Per-cell no_silent_omissions verdict from the sweep's baseline.

    Same artifact as contract_results(), different field: the sweep runs
    checks/verify-package-wishlist.sh against every published image it pulls
    (green criterion 8). Cells from artifacts that predate the field, and
    cells whose image was never read (missing/error/lost), score untested —
    absence of evidence, per the same #1730 rule as everywhere else.
    """
    cells, date, run_id = _baseline_cells()
    out: dict[str, tuple[str, str, str]] = {}
    for c in cells:
        verdict = c.get("omissions_status")
        if verdict in ("pass", "fail"):
            out[c["cell"]] = (
                "success" if verdict == "pass" else "failure", date, run_id
            )
    return out


_PARITY_CACHE: tuple[list[dict], str, str] | None = None


def parity_results() -> dict[str, tuple[str, str, str]]:
    """Per-cell parity verdict from package-parity.yml's baseline artifact.

    ok → success; BROKEN/suspect → failure (a desktop adding fewer than the
    floor of packages over its base is below the bar even when it isn't the
    zero-added #858 case); unmeasured cells yield nothing — cell() renders ⬜.
    """
    global _PARITY_CACHE
    if _PARITY_CACHE is None:
        runs = gh_json(
            "run", "list", "--repo", REPO, "--workflow", "package-parity.yml",
            "--limit", "10", "--json", "databaseId,createdAt,status,conclusion",
        ) or []
        _PARITY_CACHE = ([], "", "")
        for run in runs:
            if run.get("status") != "completed" or run.get("conclusion") != "success":
                continue
            run_id, date = str(run["databaseId"]), run["createdAt"][:10]
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    subprocess.run(
                        ["gh", "run", "download", run_id, "--repo", REPO,
                         "--name", "package-parity-baseline", "--dir", tmp],
                        capture_output=True, text=True, check=True,
                    )
                except subprocess.CalledProcessError:
                    continue
                parity_json = Path(tmp) / "parity.json"
                if not parity_json.exists():
                    continue
                _PARITY_CACHE = (
                    json.loads(parity_json.read_text()), date, run_id
                )
                break
    cells, date, run_id = _PARITY_CACHE
    out: dict[str, tuple[str, str, str]] = {}
    for c in cells:
        verdict = c.get("verdict", "")
        if verdict == "ok":
            out[c["cell"]] = ("success", date, run_id)
        elif verdict.startswith(("BROKEN", "suspect")):
            out[c["cell"]] = ("failure", date, run_id)
    return out


def contract_results() -> dict[str, tuple[str, str, str]]:
    """Newest per-cell verdict from desktop-contract-sweep.yml (tunaOS#858).

    Deliberately NOT built on latest_results(): that helper reads a job's
    GitHub *conclusion* as the pass/fail signal, which is exactly wrong here.
    desktop-contract-sweep.yml's per-cell step runs under `set +e` on purpose
    ("a contract failure is data, not an error" — see its own comment, and
    sweep 30627663051, where the opposite bug silently dropped seven real
    failures from the baseline) specifically so a failing contract does not
    read as infrastructure trouble. That means every dispatched job's
    `conclusion` is "success" whether its cell passed, failed, or found no
    image at all — reading it the way LUKS/installer-smoke are read would
    make marlin:kde-style failures render as a green ✅ in this very document,
    which is worse than the missing section this function replaces: a status
    page that actively lies is worse than one with a known gap.

    The real per-cell verdict lives where the workflow's own `collate` job
    puts it — the `desktop-contract-baseline` artifact's `all.json`, already
    built for exactly this purpose. Read that instead.

    Returns {cell: (status, iso_date, run_id)} with status one of this
    workflow's five real outcomes (pass/fail/missing/error/lost) — not
    translated to success/failure here, so callers can tell "no image
    published" apart from "published and broken" if they need to.
    """
    cells, date, run_id = _baseline_cells()
    return {c["cell"]: (c["status"], date, run_id) for c in cells}


def load_green_criteria(path: Path = GREEN_CRITERIA) -> list[dict]:
    """The criteria roster. PyYAML only — this file has anchors-free simple
    structure, but hand-parsing it would mean two parsers to keep honest;
    matrix-status.yml pip-installs pyyaml before running this script."""
    try:
        import yaml
    except ImportError:
        sys.exit("green-criteria.yml needs PyYAML: pip install pyyaml")
    return yaml.safe_load(path.read_text())["criteria"]


def build_stage_results() -> dict[str, dict]:
    """Per-variant Promote and Gate outcomes from the newest CONCLUSIVE build.

    Same selection rule as .github/scripts/update-build-status.sh: walk recent
    runs, take the first whose conclusion is success or failure — a cancelled
    run is not a verdict on anything (tunaOS#1730). One run view per variant,
    not a RUN_DEPTH walk: a build run asserts its whole matrix at once, so the
    newest conclusive run IS the current state of every cell it scheduled.
    """
    out: dict[str, dict] = {}
    for variant in sorted(_matrix("build_image", desktops_only=False)):
        runs = gh_json(
            "run", "list", "--repo", REPO,
            "--workflow", f"build-{variant}.yml",
            "--branch", "main", "--limit", "10",
            "--json", "databaseId,conclusion,createdAt",
        ) or []
        run = next(
            (r for r in runs if r.get("conclusion") in ("success", "failure")),
            None,
        )
        if run is None:
            out[variant] = {"jobs": {}, "date": ""}
            continue
        detail = gh_json(
            "run", "view", str(run["databaseId"]), "--repo", REPO,
            "--json", "jobs",
        ) or {}
        jobs: dict[tuple[str, str], str] = {}
        for job in detail.get("jobs", []):
            m = re.search(
                r" / (?P<flavor>[^/]+) / (?P<stage>Promote|Gate)$",
                job.get("name", ""),
            )
            if not m:
                continue
            key = (m["flavor"], m["stage"])
            conclusion = job.get("conclusion") or ""
            # Two jobs can share a display name for one cell: the desktop
            # Gate (skipped on base) and the base Gate (skipped on desktops)
            # both render as "base / Gate". A real verdict must never be
            # overwritten by its skipped twin, and job order must not decide.
            if key in jobs and conclusion not in ("success", "failure"):
                continue
            jobs[key] = conclusion
        out[variant] = {
            "jobs": jobs,
            "date": run["createdAt"][:10],
            # Kept for provenance: builds/boots verdicts all come from this
            # one conclusive run, so the cell→run attribution is per-variant.
            "run_id": str(run["databaseId"]),
        }
    return out


def _stage_verdict(conclusion: str | None) -> str:
    """success → pass, failure → fail, anything else → untested.

    Skipped and missing are deliberately NOT failures: "no job asserted this
    cell" is absence of evidence (tunaOS#1730), and green-criteria.yml's rule
    already refuses to count it as green (skipped_is_not_green) — ⬜ says both.
    """
    if conclusion == "success":
        return "pass"
    if conclusion == "failure":
        return "fail"
    return "untested"


def _axis_from_results(results: dict, key: str) -> str:
    hit = results.get(key)
    return _stage_verdict(hit[0] if hit else None)


# bootc-lifecycle job names carry an arch suffix, and the smoke-tier jobs a
# BETA prefix: "yellowfin:gnome (amd64)", "BETA guppy:gnome (amd64)". The
# composite and the Lifecycle section key cells as plain "variant:flavor".
_LIFECYCLE_NAME = re.compile(
    r"^(?:BETA\s+)?(?P<cell>[a-z0-9-]+:[a-z0-9-]+)\s+\([a-z0-9]+\)$"
)


def lifecycle_results() -> dict[str, tuple[str, str, str]]:
    """Cell-keyed lifecycle verdicts, worst-of-arches.

    The wiring below was written before Bootc Lifecycle had ever run, and
    the first real sweep (run 32040213366, 168 jobs) proved the raw job
    names never matched a cell lookup: every cell rendered ⬜ while 133
    passes sat in the run. Normalise the names here, and merge a cell's
    arch legs pessimistically — one green leg must not mask a red one, for
    the same reason never-tested is not green.
    """
    merged: dict[str, tuple[str, str, str]] = {}
    for name, hit in latest_results("bootc-lifecycle.yml", r":").items():
        m = _LIFECYCLE_NAME.match(name)
        if not m:
            continue
        cell = m.group("cell")
        prev = merged.get(cell)
        if prev is None or (prev[0] == "success" and hit[0] == "failure"):
            merged[cell] = hit
    return merged


def composite_verdict(verdicts: list[str]) -> str:
    """Compose per-criterion verdicts under green-criteria.yml's rule.

    fail outranks untested for the glyph — a demonstrated failure is more
    information than an absence — but neither is green: the count below only
    ever admits cells where every applicable blocking criterion says pass.
    """
    if any(v == "fail" for v in verdicts):
        return "fail"
    if any(v == "untested" for v in verdicts):
        return "untested"
    return "pass"


def criterion_scope_allows(criterion: dict, flavor: str) -> bool:
    """Whether a criterion is scored on this flavor at all.

    A scope entry in green-criteria.yml is a REVIEWED declaration that CI
    cannot assert the criterion for that cell (asahi has no aarch64 KVM;
    base-hwe/base-nvidia are unbooted derivations). Out-of-scope cells are
    not judged on the criterion — which is different from ⬜: untested counts
    against green, out-of-scope simply isn't part of that cell's bar.
    """
    scope = criterion.get("scope") or {}
    if flavor in (scope.get("excludes_flavors") or []):
        return False
    return not any(
        flavor.endswith(suffix)
        for suffix in (scope.get("excludes_flavor_suffixes") or [])
    )


def composite_section(criteria, stage, contract, luks, smoke, lifecycle,
                      omissions, parity):
    """The bar itself: one table scored against the blocking criteria.

    Per-criterion applicability follows each axis's own denominator, exactly
    like the sections below — builds applies to every published cell, the
    desktop/boot/install axes to the desktops set, iso to the ISO set. A
    criterion with no per-cell assertion wired here scores untested, which the
    rule turns into "not green": making such a criterion blocking turns the
    whole board ⬜ loudly instead of silently passing it.
    """
    desktops = _matrix("build_image", desktops_only=True)
    everything = _matrix("build_image", desktops_only=False)
    isos = iso_matrix()

    # W1's last box: which run asserted which criterion, when. Every axis
    # source already carries (conclusion, date, run_id) — the glyphs threw
    # that away. Recorded here, as a side product of the same wiring that
    # scores the composite, so the provenance can never disagree with the
    # board it explains.
    provenance: dict[str, dict[str, dict[str, str]]] = {}

    def _run_url(run_id: str) -> str:
        return f"https://github.com/{REPO}/actions/runs/{run_id}" if run_id else ""

    def scorers(variant: str, flavor: str) -> dict[str, str]:
        vstage = stage.get(variant, {})
        jobs = vstage.get("jobs", {})
        entry = provenance.setdefault(f"{variant}:{flavor}", {})

        def stage_axis(axis: str, stage_name: str) -> str:
            v = _stage_verdict(jobs.get((flavor, stage_name)))
            entry[axis] = {
                "verdict": v,
                "date": vstage.get("date", "") if (flavor, stage_name) in jobs else "",
                "run": _run_url(vstage.get("run_id", "")) if (flavor, stage_name) in jobs else "",
            }
            return v

        def result_axis(axis: str, results: dict, key: str) -> str:
            hit = results.get(key)
            v = _stage_verdict(hit[0] if hit else None)
            entry[axis] = {
                "verdict": v,
                "date": hit[1] if hit else "",
                "run": _run_url(hit[2]) if hit else "",
            }
            return v

        per_cell = {
            "builds": stage_axis("builds", "Promote"),
            # Every cell has a Gate verdict slot — desktops from the desktop
            # Gate, plain base from the base Gate (W3); whether it BINDS is
            # the criterion's scope, applied in verdict() below.
            "boots": stage_axis("boots", "Gate"),
        }
        if flavor in desktops.get(variant, set()):
            per_cell["desktop"] = result_axis(
                "desktop", contract, f"{variant}:{flavor}"
            )
            per_cell["install"] = result_axis(
                "install", luks, f"LUKS {variant}:{flavor}"
            )
            per_cell["lifecycle"] = result_axis(
                "lifecycle", lifecycle, f"{variant}:{flavor}"
            )
            per_cell["no_silent_omissions"] = result_axis(
                "no_silent_omissions", omissions, f"{variant}:{flavor}"
            )
            per_cell["parity"] = result_axis(
                "parity", parity, f"{variant}:{flavor}"
            )
        if flavor in isos.get(variant, set()):
            per_cell["iso"] = result_axis(
                "iso", smoke, f"{variant}:{flavor}"
            )
        return per_cell

    blocking_criteria = [c for c in criteria if c["enforcement"] == "blocking"]
    blocking = [c["id"] for c in blocking_criteria]
    advisory = [c["id"] for c in criteria if c["enforcement"] == "advisory"]
    unimplemented = [
        c["id"] for c in criteria if c["enforcement"] == "unimplemented"
    ]

    def verdict(variant: str, flavor: str) -> str:
        per_cell = scorers(variant, flavor)
        applicable = []
        for criterion in blocking_criteria:
            if not criterion_scope_allows(criterion, flavor):
                continue
            cid = criterion["id"]
            if cid in ("builds", "boots"):
                # Universal criteria: absence of a verdict is ⬜, it never
                # silently drops out of the bar (skipped_is_not_green).
                applicable.append(per_cell.get(cid, "untested"))
            elif cid in per_cell:
                # Axis-scoped criteria (desktop/install/iso/...): judged only
                # where their own denominator schedules the cell.
                applicable.append(per_cell[cid])
        return composite_verdict(applicable or ["untested"])

    green = total = 0
    for variant, flavors in everything.items():
        for flavor in flavors:
            total += 1
            if verdict(variant, flavor) == "pass":
                green += 1

    glyph = {"pass": PASS, "fail": FAIL, "untested": UNTESTED}
    rows = ["| Variant | " + " | ".join(DESKTOPS) + " |",
            "|---|" + ":--:|" * len(DESKTOPS)]
    for variant in sorted(desktops):
        cells = [
            glyph[verdict(variant, d)] if d in desktops[variant] else NA
            for d in DESKTOPS
        ]
        rows.append(f"| **{variant}** | " + " | ".join(cells) + " |")

    lines = [
        "## Composite green — the bar",
        "",
        (
            "Scored against `.github/green-criteria.yml`: a cell is green only "
            "when every **blocking** criterion applicable to it has a current "
            "affirmative result; a criterion that was skipped, never tested, "
            "or unasserted renders \u2b1c and does not count as satisfied. "
            "Blocking today: "
            + ", ".join(f"`{c}`" for c in blocking)
            + ". Advisory (measured in the sections below, not yet biting): "
            + ", ".join(f"`{c}`" for c in advisory)
            + ". Unimplemented: "
            + ", ".join(f"`{c}`" for c in unimplemented)
            + ". Graduating a criterion is an edit to `enforcement:` in that "
            "file — this table and the README count tighten with no code "
            "change."
        ),
        "",
        f"**{green} of {total}** published cells are composite-green.",
        "",
    ] + rows + [
        "",
        (
            "Cells outside the desktop columns (base, hwe, nvidia and friends) "
            "are in the count above but not the table; only `builds` applies "
            "to them today."
        ),
        "",
        (
            "Per-cell provenance \u2014 which run asserted which criterion, when \u2014 "
            "is machine-readable in "
            "[matrix-provenance.json](matrix-provenance.json), regenerated "
            "with this document."
        ),
        "",
    ]
    # The escaped square renders literally otherwise.
    lines = [l.replace("\u2b1c", UNTESTED) for l in lines]
    return lines, green, total, provenance


def omissions_section(lmatrix, omissions) -> list[str]:
    """Green criterion 8 as its own axis section (see omissions_results)."""
    om_key = lambda v, d: f"{v}:{d}"                   # noqa: E731
    total, tested, passed = tally(lmatrix, omissions, om_key)
    return [
        "## Silent omissions",
        "",
        f"**{passed} of {total}** cells clean "
        f"({tested} read, {total - tested} never read).",
        "",
        (
            "Green criterion 8 (`no_silent_omissions`): the sweep runs "
            "`checks/verify-package-wishlist.sh` against every published image "
            "it pulls — the same gate new builds pass at build time — so an "
            "image shipping a silently-skipped package outside "
            "`package-miss-allowlist.txt` reads ❌ here even if it was "
            "published before the gate existed. A cell whose image was not "
            "read (no image, pull error, job lost) is ⬜, not clean."
        ),
        "",
    ] + desktop_table(lmatrix, omissions, om_key) + [""]


def parity_section(lmatrix, parity) -> list[str]:
    """Green criterion 7's first cadence (see parity_results)."""
    pkey = lambda v, d: f"{v}:{d}"                     # noqa: E731
    total, tested, passed = tally(lmatrix, parity, pkey)
    return [
        "## Package parity",
        "",
        f"**{passed} of {total}** cells at parity "
        f"({tested} measured, {total - tested} never measured).",
        "",
        (
            "Green criterion 7 (`parity`), first cadence: every desktop's "
            "package set audited daily against its own base "
            "(`package-parity.yml` → `scripts/package-parity.sh --audit`) — "
            "the shape that exposes a build applying no desktop at all "
            "(#858). ❌ covers both BROKEN (no more packages than base) and "
            "suspect (fewer than 25 added). Diffing against each variant's "
            "upstream reference is the next step and is not yet asserted."
        ),
        "",
    ] + desktop_table(lmatrix, parity, pkey) + [""]


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
    """Count only cells build-config actually schedules.

    A stale result for a cell the matrix no longer declares used to be counted,
    because `hit` alone was enough to enter the denominator. That put
    flounder:cosmic and flounder-sid:cosmic in the LUKS totals as permanent
    failures: both flavours were removed on purpose in 491544d1 ("drop the
    COSMIC flavours Debian cannot build"), so no run will ever turn them green,
    and the board read 39 of 54 when the live set was 52.

    Two cells is small; the dishonesty is not. It is the same one nvidia_tally
    below was written to fix — a gap nobody is ever going to close, reported as
    if someone should. Undeclared cells now get the same treatment: out of the
    tally, and disclosed by count so the number visibly shrinks as they age out
    rather than vanishing silently.

    This does NOT hide a failing cell. A cell build-config still declares is
    counted whether it passes, fails or has never run.
    """
    total = tested = passed = 0
    for variant in variants_in_scope(matrix, results):
        flavors = matrix.get(variant, set())
        for d in DESKTOPS:
            if d not in flavors:
                continue
            hit = results.get(key_fmt(variant, d))
            total += 1
            if hit:
                tested += 1
                if hit[0] == "success":
                    passed += 1
    return total, tested, passed


def undeclared_tally(matrix, results, key_fmt):
    """Stale results for cells build-config no longer schedules.

    Deliberately reported rather than dropped: a flavour that disappears from
    build-config while red should not simply stop being mentioned. Returns the
    "variant:flavor" names so the disclosure can say which, and so the count
    reaching zero is checkable.
    """
    stale = []
    for variant in variants_in_scope(matrix, results):
        flavors = matrix.get(variant, set())
        for d in DESKTOPS:
            if d not in flavors and results.get(key_fmt(variant, d)):
                stale.append(f"{variant}:{d}")
    return sorted(stale)


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
    # Two different denominators on purpose — each axis is measured against the
    # set of cells that axis actually schedules. Sharing one matrix made the
    # LUKS numbers wrong in both directions: image-only variants were missing
    # from the total, while cells that ship no ISO were counted once a run
    # happened to touch them.
    matrix = iso_matrix()
    lmatrix = luks_matrix()
    luks = latest_results("luks-e2e.yml", r"^LUKS ")
    # NOT r":" — installer-smoke.yml has TWO jobs per cell and both carry a
    # colon:
    #
    #     build-iso:  name: build ${{ matrix.variant }}:${{ matrix.flavor }}
    #     smoke:      name: ${{ matrix.variant }}:${{ matrix.flavor }}
    #
    # A bare colon matched both, so every ISO BUILD result was filed as a
    # smoke result under a phantom variant literally named "build yellowfin".
    # The 2026-08-24 refresh published it: a "build yellowfin" row reading
    # ✅✅✅✅✅ sat directly above the real yellowfin row reading ❌❌❌❌❌,
    # while the summary line above them said "0 of those pass".
    #
    # That is the worst kind of wrong for this document: the build jobs DO
    # pass, so the phantom row looked like the good news anyone would want to
    # see, on the one axis where there is none. Anchor the exclusion instead.
    smoke = latest_results("installer-smoke.yml", r"^(?!build )[^:]+:")
    tags = overlay_tags()

    # desktop-contract-sweep.yml schedules from the identical build_image /
    # desktops-only set luks-e2e.yml does (both select build_image==true
    # flavors restricted to gnome/kde/cosmic/niri/xfce from build-config.yml)
    # — no separate matrix function needed, lmatrix already is that set.
    contract_raw = contract_results()
    # Translated to the same success/failure vocabulary latest_results()
    # produces, so cell()/desktop_table()/tally() below don't need a second
    # code path — but only for the two outcomes that vocabulary can actually
    # represent. "missing" (no published image), "error" (infra trouble) and
    # "lost" (job died) are none of them a pass OR a demonstrated failure, so
    # they are dropped here rather than forced into one; cell() then reports
    # them as UNTESTED, same as a cell no run has ever touched — which is
    # honest for all three. contract_other below keeps the dropped count
    # visible instead of silently shrinking the denominator.
    contract = {
        k: ("success" if v[0] == "pass" else "failure", v[1], v[2])
        for k, v in contract_raw.items()
        if v[0] in ("pass", "fail")
    }
    contract_other = sum(
        1 for v in contract_raw.values() if v[0] not in ("pass", "fail")
    )

    luks_key = lambda v, d: f"LUKS {v}:{d}"          # noqa: E731
    smoke_key = lambda v, d: f"{v}:{d}"              # noqa: E731
    contract_key = lambda v, d: f"{v}:{d}"           # noqa: E731

    # Deliberately NO wall-clock timestamp. A generated "as of <now>" line
    # changes on every run, which would (a) make --check always fail and (b)
    # produce a daily commit even when no cell moved. The commit date already
    # records when it ran; what matters here is how fresh the DATA is, which
    # is stated per-axis below and in Provenance.
    #
    # Provenance carries that same "as of <now>" property in disguise, since it
    # names the run behind each verdict and so advances on any re-run. That is
    # why the pull_request gate compares through structural() with provenance
    # masked, rather than byte-for-byte.
    out: list[str] = [
        BEGIN,
        "",
        "*Generated by `scripts/gen-matrix-status.py` — do not edit this block "
        "by hand. It changes only when a cell actually moves, so this file's "
        "git history is a record of when each combination flipped.*",
        "",
    ]

    # ── Composite ───────────────────────────────────────────────────────────
    # First, because everything below is an input to it: this is the section
    # that composes the axes into the one claim the word "green" now makes.
    lifecycle = lifecycle_results()
    omissions = omissions_results()
    parity = parity_results()
    composite_lines, _, _, provenance = composite_section(
        load_green_criteria(), build_stage_results(), contract, luks, smoke,
        lifecycle, omissions, parity,
    )
    out += composite_lines

    out += omissions_section(lmatrix, omissions)
    out += parity_section(lmatrix, parity)


    # ── LUKS ────────────────────────────────────────────────────────────────
    total, tested, passed = tally(lmatrix, luks, luks_key)
    # NOT lmatrix: it is desktops_only, so no flavor in it can ever contain
    # "nvidia" and the stale count would be a permanent 0 — silently deleting
    # the out-of-scope disclosure below, while section 3 still points at it.
    # That is exactly the absence-of-evidence failure this document exists to
    # prevent, so count over every published flavor instead.
    nv_stale = nvidia_tally(
        _matrix("build_image", desktops_only=False), luks, luks_key
    )
    # lmatrix here, unlike the NVIDIA count above: this asks which of the
    # DESKTOPS columns the table renders are no longer scheduled, and that is
    # exactly the desktops_only matrix the table itself is built from.
    undeclared = undeclared_tally(lmatrix, luks, luks_key)
    out += [
        "## LUKS E2E",
        "",
        f"**{passed} of {total}** cells green "
        f"({tested} tested, {total - tested} never tested).",
        "",
        (
            "Measured against the set `luks-e2e.yml` schedules: every published "
            "desktop image (`build_image`), not only the ones that ship an ISO. "
            "That is wider than the ISO matrix below on purpose — the browser ISO "
            "builder can make an ISO from any image, so image-only variants "
            "(`sailfin`, `guppy`, `flounder-sid`) need boot and install coverage "
            "too."
        ),
        "",
    ]
    out += desktop_table(lmatrix, luks, luks_key)
    # Unconditional: the blank line used to live inside the NVIDIA block, so
    # when no stale NVIDIA results remained the next paragraph butted straight
    # up against the table.
    out += [""]
    if nv_stale:
        out += [
            f"NVIDIA cells are **out of scope** for this workflow — "
            f"`luks-e2e.yml` excludes them deliberately, because `-nvidia` "
            f"takes the identical LUKS path in headless QEMU. "
            f"{nv_stale} stale pre-exclusion result(s) remain from before "
            "that change; they are not a gap and will age out.",
            "",
        ]

    # Named, not just counted, and left visible in the table above: a flavour
    # that leaves build-config while red must not simply stop being mentioned.
    # It is out of the tally because no run can ever move it, which is a
    # different statement from "it passed".
    if undeclared:
        out += [
            "The table above still shows a result for "
            + ", ".join(f"`{c}`" for c in undeclared)
            + ". `.github/build-config.yml` no longer declares "
            + ("that flavour" if len(undeclared) == 1 else "those flavours")
            + ", so `luks-e2e.yml` cannot schedule "
            + ("it" if len(undeclared) == 1 else "them")
            + " and no run will ever turn "
            + ("it" if len(undeclared) == 1 else "them")
            + " green. "
            + ("It is" if len(undeclared) == 1 else "They are")
            + " excluded from the count above — a last-measured verdict kept "
            "visible, not a gap. Same reasoning as the NVIDIA note.",
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

    # ── Desktop Contract Sweep ──────────────────────────────────────────────
    # tunaOS#858: marlin:kde published with no /usr/share/wayland-sessions/
    # at all — the live payload's desktop detection silently fell back to
    # gnome — and desktop-contract-sweep.yml had been running daily, and
    # catching exactly this class of bug, for two weeks before anyone
    # noticed, because nothing here ever showed its results. Runs directly
    # against the published image (no boot, no DRM render node needed), so
    # it is not subject to the "CI cannot test four of five desktops" gap
    # documented in *Known systemic gaps* below — it is the one axis that
    # gap does not apply to.
    total, tested, passed = tally(lmatrix, contract, contract_key)
    out += [
        "## Desktop Contract Sweep",
        "",
        f"**{passed} of {total}** cells satisfy "
        "`build_scripts/checks/verify-desktop-experience.sh` "
        f"({tested} tested, {total - tested} never tested).",
        "",
        (
            "Pulls the **published** image and runs the contract script "
            "against it directly (`podman run`, no boot required) — the "
            "same denominator as LUKS E2E above (`build_image`, restricted "
            "to the five desktop flavors). This is what catches a desktop "
            "whose packages silently never landed, independent of whether "
            "anything can actually boot it on hosted CI."
        ),
        "",
    ]
    out += desktop_table(lmatrix, contract, contract_key)
    out += [""]
    if contract_other:
        out += [
            f"{contract_other} cell(s) in the most recent sweep are "
            "missing (no published image), errored (registry/runner "
            "trouble), or lost (job produced no result) rather than a "
            "clean pass or fail — not counted above; see that sweep's own "
            "`desktop-contract-baseline` artifact for which.",
            "",
        ]
    dates = sorted({v[1] for v in contract.values()})
    if dates:
        out += [f"Newest result {dates[-1]}.", ""]

    # ── Bootc Lifecycle ──────────────────────────────────────────────────────
    # `lifecycle` itself was fetched up top, where the composite scores it.
    lifecycle_key = lambda v, d: f"{v}:{d}"            # noqa: E731
    total, tested, passed = tally(lmatrix, lifecycle, lifecycle_key)
    out += [
        "## Bootc Lifecycle",
        "",
        f"**{passed} of {total}** cells green "
        f"({tested} tested, {total - tested} never tested).",
        "",
        (
            "Validates bootc image update, rebase, rollback, alias resolution, "
            "and post-switch system contracts across published stream deployments."
        ),
        "",
    ]
    out += desktop_table(lmatrix, lifecycle, lifecycle_key)
    out += [""]
    dates = sorted({v[1] for v in lifecycle.values()})
    if dates:
        out += [f"Newest result {dates[-1]}.", ""]

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
        # NOT "they need a DRM render node". Run 32681262659 read /dev/dri from
        # inside the guest and found renderD128 present with `[drm] features:
        # -virgl` -- a node without 3D. gnome starts on that same hardware
        # through Mesa's software path. Why the other four do not is open, so
        # this line states the symptom and points at the section that carries
        # the evidence, rather than restating a cause the measurement did not
        # support.
        "cosmic, niri, xfwl4 and kde do not bring a session up on hosted CI. The "
        "cause is undiagnosed rather than established -- gnome starts on the "
        "same guest, which has a render node but no 3D. See *Known systemic "
        "gaps*.",
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
    # Re-running a cell to the same verdict rewrites this table and nothing
    # else, which is not something a pull request can be answerable for, so
    # VOLATILE_LINE masks these rows out of the structural comparison.
    # Iterated as separate dicts, not merged with `**` — smoke and contract
    # use the identical "variant:desktop" key format (LUKS is alone in
    # prefixing "LUKS "), so a merge would let one silently overwrite the
    # other on every cell they share and undercount both in the table below.
    runs = defaultdict(list)
    for results in (luks, smoke, contract, lifecycle):
        for name, (_, date, run_id) in results.items():
            runs[(date, run_id)].append(name)
    out += [
        "## Provenance",
        "",
        "The run that last asserted each verdict above. Re-running a cell moves "
        "a row here without moving the cell, so this table is refreshed only "
        "when a verdict actually changes — treat the dates as \"no older than\".",
        "",
        "| Date | Run | Cells |",
        "|---|---|---|",
    ]
    for (date, run_id), names in sorted(runs.items(), reverse=True)[:12]:
        url = f"https://github.com/{REPO}/actions/runs/{run_id}"
        out.append(f"| {date} | [{run_id}]({url}) | {len(names)} |")
    out += ["", END]
    return "\n".join(out), provenance


# Lines whose whole content is a readout of live CI or registry state.
VOLATILE_LINE = re.compile(
    r"^(?:"
    r"\| \d{4}-\d\d-\d\d \| \["          # provenance row
    r"|Newest result "                    # freshness of the LUKS data
    r"|NVIDIA cells are "                 # present only while stale results remain
    r"|The table above still shows a result for "  # same: only while they remain
    r"|Missing for "                      # depends on published overlay tags
    r"|Every non-NVIDIA ISO cell has an overlay"
    r")"
)

# A result glyph is live state; NA is structure, because it means build-config
# does not schedule that cell at all.
LIVE_GLYPH = re.compile(f"[{PASS}{FAIL}{UNTESTED}]")

ROW = re.compile(r"^\| \*\*(?P<variant>[^*]+)\*\* \|")


def table_rows(block: str) -> set[tuple[str, str]]:
    """(section, variant) for every table row in the block.

    Row *existence* is partly live state: variants_in_scope() adds a row for any
    variant a run touched, even one the matrix does not schedule, so gurnard
    appears and vanishes with nothing but the run window moving.
    """
    section, rows = "", set()
    for line in block.splitlines():
        if line.startswith("## "):
            section = line
        match = ROW.match(line)
        if match:
            rows.add((section, match["variant"]))
    return rows


def structural(block: str, keep_rows: set[tuple[str, str]] | None = None) -> str:
    """The part of the generated block a pull request is answerable for.

    The pull_request drift check exists to catch two things, per matrix-status.yml:
    a hand-edit inside the generated block, and a generator that breaks on a
    build-config change. It was instead failing on repo-wide CI churn — a LUKS
    run completing mid-review moves cells, tallies and the provenance table, so
    the gate went red for reasons the PR neither caused nor can fix, and the only
    "fix" available was committing another snapshot that went stale in minutes.

    So compare with live-derived content masked: cell results, every count, the
    data-freshness dates, the provenance rows, the overlay inventory. What
    survives is the shape of the document — its prose, its sections, and which
    cells build-config schedules at all (NA versus scheduled) — which is exactly
    the surface a PR can break. Byte-exact drift is still enforced on the
    scheduled run, which is what actually keeps the file fresh.

    keep_rows limits table rows to those both sides agree exist; pass the
    intersection of table_rows() from each side.
    """
    section, lines = "", []
    for line in block.splitlines():
        if line.startswith("## "):
            section = line
        if VOLATILE_LINE.match(line):
            continue
        match = ROW.match(line)
        if (
            match
            and keep_rows is not None
            and (section, match["variant"]) not in keep_rows
        ):
            continue
        line = LIVE_GLYPH.sub("?", line)
        line = re.sub(r"\d+", "N", line)
        if not line.strip() and lines and not lines[-1].strip():
            continue  # dropped lines leave double blanks behind
        lines.append(line)
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true",
                      help="exit 1 if the document would change")
    mode.add_argument("--check-structure", action="store_true",
                      help="exit 1 only on differences a pull request controls "
                           "— hand-edits and build-config drift — ignoring "
                           "content derived from live CI state")
    args = ap.parse_args()

    if not DOC.exists():
        sys.exit(f"{DOC} not found — run from the repo root")
    text = DOC.read_text()
    if BEGIN not in text or END not in text:
        sys.exit(f"{DOC} is missing the GENERATED markers")

    head, rest = text.split(BEGIN, 1)
    committed, tail = rest.split(END, 1)
    generated, provenance = build()
    updated = head + generated + tail

    if args.check_structure:
        committed = BEGIN + committed + END
        shared = table_rows(committed) & table_rows(generated)
        want = structural(committed, shared)
        got = structural(generated, shared)
        if want == got:
            print("MATRIX-STATUS.md structure is current "
                  "(live CI values deliberately ignored)")
            return 0
        print(
            "docs/MATRIX-STATUS.md differs from the generator in content a pull "
            "request controls: either the generated block was hand-edited, or a "
            "build-config change moved rows the committed doc has not caught up "
            "with. Run scripts/gen-matrix-status.py and commit the result.",
            file=sys.stderr,
        )
        diff = difflib.unified_diff(
            want.splitlines(), got.splitlines(),
            fromfile="committed (live values masked)",
            tofile="generated (live values masked)",
            lineterm="",
        )
        print("\n".join(diff), file=sys.stderr)
        return 1

    if not args.check:
        # The JSON is regenerated whenever the doc is, and also when the
        # doc happens to be byte-identical: same inputs, same payload, so
        # this is idempotent rather than churn.
        PROV.write_text(json.dumps(
            {"about": "Which run asserted which criterion, when — "
                      "per published cell, per axis. Generated by "
                      "scripts/gen-matrix-status.py alongside "
                      "MATRIX-STATUS.md; empty run+date means the axis "
                      "has no current assertion for that cell.",
             "cells": provenance},
            indent=1, sort_keys=True) + "\n")
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
