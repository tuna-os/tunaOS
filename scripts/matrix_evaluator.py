"""Pure composite-green scoring for scripts/gen-matrix-status.py.

This module is the evaluator boundary of tunaOS#2532. It takes the green
criteria, the cell matrices and evidence that is already normalized, and it
returns typed verdicts and provenance. It does no I/O: no `gh`, no HTTP, no
file reads, no writes. The generator collects the evidence, calls
evaluate_composite(), and renders the result. So a test can exercise the
scoring rules with plain dicts and no patched transport, and another status
consumer can reuse the same rules without importing the network code.

Evidence shapes (the shapes the generator's collectors return):

  stage    variant -> {"jobs": {(flavor, stage_name): conclusion},
                       "date": str, "run_id": str,
                       "cell_run": {flavor: (date, run_id)}}
  results  cell key -> (conclusion, date, run_id)

Verdicts are the strings "pass", "fail" and "untested".
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

# A per-cell provenance record: axis -> {"verdict", "date", "run", "evidence"}.
Provenance = dict[str, dict[str, dict[str, str]]]

# Axes whose evidence can link a green cell, in order of preference: runtime
# evidence first, build metadata last.
EVIDENCE_AXES = ("boots", "desktop", "no_silent_omissions", "builds")


def stage_verdict(conclusion: str | None) -> str:
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
    if any(
        flavor.startswith(prefix)
        for prefix in (scope.get("excludes_flavor_prefixes") or [])
    ):
        # Prefix rather than exact, because the workflow that routes a cell to
        # a runner does the same: reusable-build-image.yml selects the GPU
        # group with startsWith(inputs.flavor, ...). Matching on the same shape
        # keeps the scope and the routing from disagreeing about which cells a
        # gate can even reach -- and a test pins the two lists equal.
        return False
    return not any(
        flavor.endswith(suffix)
        for suffix in (scope.get("excludes_flavor_suffixes") or [])
    )


def is_stale(
    date_str: str,
    sla_days: int | float | None,
    today: datetime.date | str | None = None,
) -> bool:
    """True if evidence date_str is older than sla_days relative to today."""
    if not date_str or sla_days is None:
        return False
    try:
        ev_date = datetime.date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return False
    if today is None:
        ref = datetime.date.today()
    elif isinstance(today, str):
        try:
            ref = datetime.date.fromisoformat(today)
        except (ValueError, TypeError):
            ref = datetime.date.today()
    elif isinstance(today, datetime.date):
        ref = today
    else:
        ref = datetime.date.today()
    return (ref - ev_date).days > sla_days


def green_axes_without_evidence(provenance: dict) -> list[str]:
    """Name green per-cell axes that cannot lead a reviewer to evidence."""
    return sorted(
        f"{cell}:{axis}"
        for cell, axes in provenance.items()
        for axis, result in axes.items()
        if result.get("verdict") == "pass" and not result.get("evidence")
    )


@dataclass(frozen=True)
class AxisEvidence:
    """Normalized evidence for every axis the composite can score.

    Each field holds the evidence shape named in the module docstring. An
    empty dict means "no run asserted anything", which scores ⬜, not ✅.
    """

    stage: dict = field(default_factory=dict)
    contract: dict = field(default_factory=dict)
    luks: dict = field(default_factory=dict)
    smoke: dict = field(default_factory=dict)
    lifecycle: dict = field(default_factory=dict)
    omissions: dict = field(default_factory=dict)
    parity: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CellMatrices:
    """The denominators, as variant -> {flavor}, from build-config.yml.

    published  every cell that build_image publishes (the composite count)
    desktops   the published desktop cells (the desktop/install/... axes)
    isos       the cells that ship an ISO (the iso axis)
    """

    published: dict[str, set[str]]
    desktops: dict[str, set[str]]
    isos: dict[str, set[str]]


@dataclass(frozen=True)
class CompositeEvaluation:
    """The typed result of evaluate_composite().

    verdicts   "variant:flavor" -> composite verdict, for every scored cell
    evidence   "variant:flavor" -> evidence URL for a green cell that has a
               current affirmative axis with a link; absent otherwise
    provenance "variant:flavor" -> axis -> record (matrix-provenance.json)
    """

    blocking: list[str]
    advisory: list[str]
    unimplemented: list[str]
    verdicts: dict[str, str]
    evidence: dict[str, str]
    provenance: Provenance
    green: int
    total: int


def run_url(repo: str, run_id: str) -> str:
    return f"https://github.com/{repo}/actions/runs/{run_id}" if run_id else ""


def score_cell(
    variant: str,
    flavor: str,
    matrices: CellMatrices,
    evidence: AxisEvidence,
    repo: str,
) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Score every axis that applies to one cell.

    Returns (axis -> verdict, axis -> provenance record). Every axis source
    carries (conclusion, date, run_id); the provenance keeps that, so it
    records which run asserted which criterion, and when. It is produced by
    the same wiring that scores the composite, so the provenance can never
    disagree with the board it explains.
    """
    vstage = evidence.stage.get(variant, {})
    jobs = vstage.get("jobs", {})
    entry: dict[str, dict[str, str]] = {}

    def stage_axis(axis: str, stage_name: str) -> str:
        v = stage_verdict(jobs.get((flavor, stage_name)))
        asserted = (flavor, stage_name) in jobs
        # Provenance is per cell now, not per variant: cells of one
        # variant can legitimately come from different runs.
        date, rid = vstage.get("cell_run", {}).get(
            flavor, (vstage.get("date", ""), vstage.get("run_id", ""))
        )
        run = run_url(repo, rid) if asserted else ""
        entry[axis] = {
            "verdict": v,
            "date": date if asserted else "",
            "run": run,
            "evidence": f"{run}#artifacts" if run else "",
        }
        return v

    def result_axis(axis: str, results: dict, key: str) -> str:
        hit = results.get(key)
        v = stage_verdict(hit[0] if hit else None)
        run = run_url(repo, hit[2]) if hit else ""
        entry[axis] = {
            "verdict": v,
            "date": hit[1] if hit else "",
            "run": run,
            "evidence": f"{run}#artifacts" if run else "",
        }
        return v

    cell = f"{variant}:{flavor}"
    per_cell = {
        "builds": stage_axis("builds", "Promote"),
        # Every cell has a Gate verdict slot — desktops from the desktop
        # Gate, plain base from the base Gate (W3); whether it BINDS is
        # the criterion's scope, applied in cell_verdict() below.
        "boots": stage_axis("boots", "Gate"),
    }
    if flavor in matrices.desktops.get(variant, set()):
        per_cell["desktop"] = result_axis("desktop", evidence.contract, cell)
        per_cell["install"] = result_axis(
            "install", evidence.luks, f"LUKS {cell}"
        )
        per_cell["lifecycle"] = result_axis(
            "lifecycle", evidence.lifecycle, cell
        )
        per_cell["no_silent_omissions"] = result_axis(
            "no_silent_omissions", evidence.omissions, cell
        )
        per_cell["parity"] = result_axis("parity", evidence.parity, cell)
    if flavor in matrices.isos.get(variant, set()):
        per_cell["iso"] = result_axis("iso", evidence.smoke, cell)
    return per_cell, entry


def cell_verdict(
    flavor: str,
    per_cell: dict[str, str],
    entry: dict[str, dict[str, str]],
    blocking_criteria: list[dict],
    today: datetime.date | str | None = None,
) -> str:
    """Compose one cell's blocking criteria into its composite verdict."""
    applicable = []
    for criterion in blocking_criteria:
        if not criterion_scope_allows(criterion, flavor):
            continue
        cid = criterion["id"]
        sla = criterion.get("freshness_sla_days")
        axis_entry = entry.get(cid, {})
        v = axis_entry.get("verdict", "untested")
        d = axis_entry.get("date", "")
        if is_stale(d, sla, today):
            v = "untested"
        if cid in ("builds", "boots"):
            # Universal criteria: absence of a verdict is ⬜, it never
            # silently drops out of the bar (skipped_is_not_green).
            applicable.append(v)
        elif cid in per_cell:
            # Axis-scoped criteria (desktop/install/iso/...): judged only
            # where their own denominator schedules the cell.
            applicable.append(v)
    return composite_verdict(applicable or ["untested"])


def evidence_link(
    entry: dict[str, dict[str, str]],
    criteria: list[dict],
    today: datetime.date | str | None = None,
) -> str:
    """The evidence URL for a green cell, or "" when no current axis has one.

    Prefer runtime evidence over build metadata when both assert green.
    """
    for axis in EVIDENCE_AXES:
        axis_entry = entry.get(axis, {})
        sla = next(
            (c.get("freshness_sla_days") for c in criteria if c.get("id") == axis),
            None,
        )
        if axis_entry.get("verdict") == "pass" and not is_stale(
            axis_entry.get("date", ""), sla, today
        ):
            url = axis_entry.get("evidence", "")
            if url:
                return url
    return ""


def evaluate_composite(
    criteria: list[dict],
    matrices: CellMatrices,
    evidence: AxisEvidence,
    repo: str,
    today: datetime.date | str | None = None,
) -> CompositeEvaluation:
    """Score every published and desktop cell against the blocking criteria.

    Per-criterion applicability follows each axis's own denominator: builds
    applies to every published cell, the desktop/boot/install axes to the
    desktops set, iso to the ISO set. A criterion with no per-cell assertion
    wired here scores untested, which the rule turns into "not green": making
    such a criterion blocking turns the whole board ⬜ loudly instead of
    silently passing it.
    """
    blocking_criteria = [c for c in criteria if c["enforcement"] == "blocking"]

    verdicts: dict[str, str] = {}
    links: dict[str, str] = {}
    provenance: Provenance = {}

    def evaluate(variant: str, flavor: str) -> str:
        cell = f"{variant}:{flavor}"
        if cell not in verdicts:
            per_cell, entry = score_cell(
                variant, flavor, matrices, evidence, repo
            )
            provenance[cell] = entry
            verdicts[cell] = cell_verdict(
                flavor, per_cell, entry, blocking_criteria, today
            )
            if verdicts[cell] == "pass":
                url = evidence_link(entry, criteria, today)
                if url:
                    links[cell] = url
        return verdicts[cell]

    green = total = 0
    for variant, flavors in matrices.published.items():
        for flavor in flavors:
            total += 1
            if evaluate(variant, flavor) == "pass":
                green += 1
    # The desktop table renders these cells; score any the count above did
    # not reach, so the table and the provenance never miss a rendered cell.
    for variant, flavors in matrices.desktops.items():
        for flavor in flavors:
            evaluate(variant, flavor)

    return CompositeEvaluation(
        blocking=[c["id"] for c in blocking_criteria],
        advisory=[c["id"] for c in criteria if c["enforcement"] == "advisory"],
        unimplemented=[
            c["id"] for c in criteria if c["enforcement"] == "unimplemented"
        ],
        verdicts=verdicts,
        evidence=links,
        provenance=provenance,
        green=green,
        total=total,
    )
