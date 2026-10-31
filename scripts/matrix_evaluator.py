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
  tested   axis -> evidence key -> {arch: "sha256:..."}  (digest the producer
           tested; absent when the producer did not record one)
  promoted cell -> {arch: "sha256:..."}  (platform digests the Promote job
           published for the cell; absent when unknown)

Verdicts are the strings "pass", "fail" and "untested".

Digest binding (tunaOS#3381 exit item 4). An axis result counts toward green
only for the image the cell currently publishes. Each asserted axis is compared
with the Promote digest of its cell:

  match                        every tested platform digest equals the
                               promoted one; the result stands
  digest-mismatch              the producer tested another image; downgraded
  digest-unknown               the producer recorded no digest; downgraded
                               only from the configured cutover date on
  promoted-digest-unavailable  no Promote digest to compare with; the result
                               stands, as it did before digest binding

A downgraded axis scores untested, like stale evidence. Its provenance record
keeps the producer's verdict and gains "downgrade_reason".
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

# A per-cell provenance record: axis -> {"verdict", "date", "run", "evidence"},
# plus, once digests are known, "tested_digest"/"promoted_digest" ({arch:
# digest}), "digest_status" and, when the axis was downgraded,
# "downgrade_reason".
Provenance = dict[str, dict[str, dict]]

DIGEST_MISMATCH = "digest-mismatch"
DIGEST_UNKNOWN = "digest-unknown"
DIGEST_MATCH = "match"
PROMOTED_UNAVAILABLE = "promoted-digest-unavailable"
DOWNGRADE_REASONS = (DIGEST_MISMATCH, DIGEST_UNKNOWN)
DIGEST_STATUSES = (DIGEST_MATCH, PROMOTED_UNAVAILABLE) + DOWNGRADE_REASONS

# `builds` is the Promote verdict itself: the digest every other axis is
# compared with, so it is never compared with itself.
UNBOUND_AXES = ("builds",)

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
    """True if evidence date_str is older than sla_days relative to today.

    Under an SLA, evidence with no date, or a date that does not parse, is
    stale: its age cannot be shown to be inside the window, and evidence with
    no expiry is never stale, which green-criteria.yml's rule forbids. Only a
    criterion with no SLA at all leaves an undated verdict alone.
    """
    if sla_days is None:
        return False
    if not date_str:
        return True
    try:
        ev_date = datetime.date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return True
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
    # Digest binding inputs (see the module docstring). Empty means no
    # producer recorded a digest, which binds nothing.
    tested: dict = field(default_factory=dict)
    promoted: dict = field(default_factory=dict)


def digest_binding(
    tested: dict[str, str] | None,
    promoted: dict[str, str] | None,
    unknown_downgrades: bool,
) -> tuple[str, str]:
    """(digest_status, downgrade_reason or "") for one asserted axis result.

    Every platform the producer tested must be one the cell promoted, with
    the same digest. A tested platform the cell does not publish is a
    mismatch: the result describes some other image.
    """
    if not promoted:
        return PROMOTED_UNAVAILABLE, ""
    if not tested:
        return DIGEST_UNKNOWN, DIGEST_UNKNOWN if unknown_downgrades else ""
    if all(promoted.get(arch) == digest for arch, digest in tested.items()):
        return DIGEST_MATCH, ""
    return DIGEST_MISMATCH, DIGEST_MISMATCH


def digest_cutover_reached(
    required_from: str | None,
    today: datetime.date | str | None = None,
) -> bool:
    """Whether evidence without a tested digest is downgraded yet.

    required_from is green-criteria.yml's digest_binding.unknown_downgrades_from.
    None means no cutover is configured, so unknown digests never downgrade.
    A malformed date raises: a typo must not silently disable the binding.
    """
    if required_from is None:
        return False
    cutover = datetime.date.fromisoformat(str(required_from))
    if isinstance(today, datetime.date):
        ref = today
    elif isinstance(today, str) and today:
        ref = datetime.date.fromisoformat(today)
    else:
        ref = datetime.date.today()
    return ref >= cutover


@dataclass(frozen=True)
class CellMatrices:
    """The denominators, as variant -> {flavor}, from build-config.yml.

    published  every cell that build_image publishes (the composite count)
    desktops   the published desktop cells (contract/parity/lifecycle axes)
    isos       the cells that ship an ISO (the iso axis)
    """

    published: dict[str, set[str]]
    desktops: dict[str, set[str]]
    isos: dict[str, set[str]]
    # Install evidence covers the full LUKS matrix, including image-only
    # overlays. Keep the desktop-contract matrix separate: the contract and
    # package-parity axes are only asserted for the five desktop flavors.
    install: dict[str, set[str]] | None = None


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
    unknown_downgrades: bool = False,
) -> tuple[dict[str, str], dict[str, dict]]:
    """Score every axis that applies to one cell.

    Returns (axis -> verdict, axis -> provenance record). Every axis source
    carries (conclusion, date, run_id); the provenance keeps that, so it
    records which run asserted which criterion, and when. It is produced by
    the same wiring that scores the composite, so the provenance can never
    disagree with the board it explains.

    Each asserted axis but `builds` is also bound to the cell's promoted
    digest (digest_binding). The record gains the digests and the status
    once either side is known, and "downgrade_reason" when the binding
    withdraws the result from the composite.
    """
    vstage = evidence.stage.get(variant, {})
    jobs = vstage.get("jobs", {})
    entry: dict[str, dict] = {}
    cell = f"{variant}:{flavor}"
    promoted = evidence.promoted.get(cell)

    def bind(axis: str, key: str) -> None:
        record = entry[axis]
        if axis in UNBOUND_AXES or record["verdict"] == "untested":
            return
        tested = evidence.tested.get(axis, {}).get(key)
        if not tested and not promoted:
            # Nothing to compare: the record stays exactly as it was before
            # digest binding existed (retained historical inputs replay).
            return
        status, reason = digest_binding(tested, promoted, unknown_downgrades)
        if tested:
            record["tested_digest"] = dict(sorted(tested.items()))
        if promoted:
            record["promoted_digest"] = dict(sorted(promoted.items()))
        record["digest_status"] = status
        if reason:
            record["downgrade_reason"] = reason

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
        bind(axis, cell)
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
        bind(axis, key)
        return v

    per_cell = {
        "builds": stage_axis("builds", "Promote"),
        # Every cell has a Gate verdict slot — desktops from the desktop
        # Gate, plain base from the base Gate (W3); whether it BINDS is
        # the criterion's scope, applied in cell_verdict() below.
        "boots": stage_axis("boots", "Gate"),
    }
    install_matrix = (
        matrices.install if matrices.install is not None else matrices.desktops
    )
    if flavor in install_matrix.get(variant, set()):
        per_cell["install"] = result_axis(
            "install", evidence.luks, f"LUKS {cell}"
        )
    if flavor in matrices.desktops.get(variant, set()):
        per_cell["desktop"] = result_axis("desktop", evidence.contract, cell)
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
        if is_stale(d, sla, today) or axis_entry.get("downgrade_reason"):
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
        if (
            axis_entry.get("verdict") == "pass"
            and not axis_entry.get("downgrade_reason")
            and not is_stale(axis_entry.get("date", ""), sla, today)
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
    digest_unknown_downgrades_from: str | None = None,
) -> CompositeEvaluation:
    """Score every published and desktop cell against the blocking criteria.

    Per-criterion applicability follows each axis's own denominator: builds
    applies to every published cell, the desktop/boot/install axes to the
    desktops set, iso to the ISO set. A criterion with no per-cell assertion
    wired here scores untested, which the rule turns into "not green": making
    such a criterion blocking turns the whole board ⬜ loudly instead of
    silently passing it.

    digest_unknown_downgrades_from is green-criteria.yml's
    digest_binding.unknown_downgrades_from: from that date on, an asserted
    axis with no tested digest no longer counts toward green once its cell
    has a promoted digest. A digest mismatch never counts, whatever the date.
    """
    blocking_criteria = [c for c in criteria if c["enforcement"] == "blocking"]
    unknown_downgrades = digest_cutover_reached(
        digest_unknown_downgrades_from, today
    )

    verdicts: dict[str, str] = {}
    links: dict[str, str] = {}
    provenance: Provenance = {}

    def evaluate(variant: str, flavor: str) -> str:
        cell = f"{variant}:{flavor}"
        if cell not in verdicts:
            per_cell, entry = score_cell(
                variant, flavor, matrices, evidence, repo, unknown_downgrades
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
