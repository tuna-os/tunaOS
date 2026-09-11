"""The boots scope and the runner routing must name the same compositors.

`boots` is scored by verify_boot, and verify_boot only reaches a cell if a
runner attaches. reusable-build-image.yml sends cosmic/niri/xfwl4 to the GPU
group for a real DRM render node; the account's vCPU limit for that instance
bucket is 0, so the fleet request fails and the job dies before its first step
(#2123, confirmed on runs 33848074014 and 33948918141). Those cells are
therefore out of scope for `boots` -- not red, because nothing was measured.

The failure mode this pins is drift between two lists that must agree. If
someone adds a fourth GPU-gated compositor to the routing and not to the
scope, its cells silently start being scored red for a gate that cannot run
-- which is exactly the state this exclusion was added to end. If someone
removes one from the routing (because capacity arrived) and not from the
scope, the cell stops being judged on booting at all, which is worse: a
regression could not fail it.
"""
from __future__ import annotations

import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
CRITERIA = ROOT / ".github" / "green-criteria.yml"
WORKFLOW = ROOT / ".github" / "workflows" / "reusable-build-image.yml"


def _boots() -> dict:
    doc = yaml.safe_load(CRITERIA.read_text())
    return next(c for c in doc["criteria"] if c["id"] == "boots")


def _routed_prefixes() -> set[str]:
    """The flavors verify_boot sends to the GPU runner group.

    Read out of the runs-on expression rather than hardcoded, so this test
    fails when the workflow changes rather than when someone edits a copy.
    """
    text = WORKFLOW.read_text()
    start = text.index("  verify_boot:")
    end = text.index("\n    steps:", start)
    job = text[start:end]
    # The runs-on expression ONLY. The job's `if:` also calls startsWith --
    # `!startsWith(inputs.flavor, 'base')` -- and reading the whole job swept
    # 'base' in as though it were a GPU-routed compositor. Narrow to the
    # selector that actually chooses the runner.
    sel_start = job.index("    runs-on:")
    sel_end = job.index("\n    timeout-minutes:", sel_start)
    selector = job[sel_start:sel_end]
    assert "runner=gpu" in selector, (
        "verify_boot no longer routes to the GPU runner group; if the gate now "
        "runs on hosted runners, the boots scope exclusion should be removed"
    )
    return set(re.findall(r"startsWith\(inputs\.flavor,\s*'([^']+)'\)", selector))


def test_the_scope_excludes_exactly_the_gpu_routed_compositors():
    scoped = set(_boots()["scope"].get("excludes_flavor_prefixes") or [])
    routed = _routed_prefixes()
    assert routed, "no startsWith(...) prefixes found — the routing expression moved"
    assert scoped == routed, (
        "green-criteria.yml's boots scope and reusable-build-image.yml's GPU "
        f"routing disagree.\n  routed to a GPU runner: {sorted(routed)}\n"
        f"  excluded from boots:    {sorted(scoped)}\n"
        "Cells routed to a runner CI cannot launch must be out of scope; cells "
        "that can reach a runner must be judged on booting."
    )


def _skipped_prefixes() -> set[str]:
    """The flavors verify_boot's `if:` refuses to schedule.

    Read out of the `if:` expression only. That expression also negates 'base',
    which is excluded for an unrelated and permanent reason (base is a parent
    layer, not a user-facing artifact), so 'base' is dropped here rather than
    counted as a GPU-gated compositor.
    """
    text = WORKFLOW.read_text()
    start = text.index("  verify_boot:")
    end = text.index("\n    runs-on:", start)
    job = text[start:end]
    cond_start = job.index("    if: >-")
    condition = job[cond_start:]
    return {
        p for p in re.findall(
            r"!startsWith\(inputs\.flavor,\s*'([^']+)'\)", condition)
        if p != "base"
    }


def test_the_gate_does_not_schedule_what_it_cannot_launch():
    """The `if:` guard and the runs-on routing must name the same compositors.

    Two lists in the same job, and the whole point of the guard is that it
    covers exactly the flavors the routing sends to a group with no capacity
    (maintainer decision 2026-09-11). Drift either way is a silent bug:

      routed but not skipped  → the job is scheduled onto a runner that never
                                attaches, Promote is skipped, and the cell
                                loses its image for a gate that measured
                                nothing — the state this guard exists to end.
      skipped but not routed  → a flavor that CAN reach a hosted runner stops
                                being boot-gated at all, and a real boot
                                regression could no longer fail it.

    So when g4dn capacity returns, deleting the three negations here is part of
    the same change that removes the GPU routing — not a later cleanup.
    """
    routed = _routed_prefixes()
    skipped = _skipped_prefixes()
    assert skipped == routed, (
        "verify_boot's `if:` guard and its GPU routing disagree.\n"
        f"  routed to a GPU runner: {sorted(routed)}\n"
        f"  never scheduled:        {sorted(skipped)}\n"
        "A flavor routed to a runner CI cannot launch must not be scheduled; a "
        "flavor that can reach a runner must still be gated."
    )


def test_the_exclusion_is_scoped_to_boots_and_nothing_else():
    """The gate cannot run — that says nothing about the desktop contract,
    which is measured from the published image with no runner involved."""
    doc = yaml.safe_load(CRITERIA.read_text())
    for crit in doc["criteria"]:
        if crit["id"] == "boots":
            continue
        prefixes = (crit.get("scope") or {}).get("excludes_flavor_prefixes") or []
        assert not set(prefixes) & {"cosmic", "niri", "xfwl4"}, (
            f"criterion {crit['id']!r} also excludes the GPU-gated compositors; "
            "the g4dn quota only blocks the boot gate, so widening it to another "
            "axis stops measuring something CI can actually measure"
        )
