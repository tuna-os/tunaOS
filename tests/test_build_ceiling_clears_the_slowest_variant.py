"""The build ceiling has to clear the slowest real build, or it eats whole cells.

`timeout-minutes` on `build_push` is a max, not a budget: RPM variants finish
in 20-40 minutes and never approach it. It exists for the source-based
experimental variants, where guppy (Gentoo) compiles the desktop from source.

When it is set too low the failure is not "the build was slow" -- it is a
cancelled job, which writes no digest artifact, so `Manifest` fails at
`Load Outputs` and `Sign`, `Gate`, `Promote` and `Attest SBOM` are all
skipped. One cell lost, and it reports as a cancellation rather than as a
timeout, which reads like infrastructure rather than a ceiling.

That has now happened twice:

    #644   at 60   guppy base could not finish from stage3
    #1802  at 180  guppy kde cancelled at 2h57m with 245 of 252 emerge jobs
                   complete, still compiling steadily (load avg 2.61)

These tests pin the ceiling against the slowest build actually observed, so
the next person to lower it has to argue with a measurement.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/reusable-build-image.yml"

# Build Image durations from run 31942667550, the first run in five nights
# where guppy got far enough for stage-2 to build at all.
OBSERVED_MINUTES = {
    "guppy base": 36,
    "guppy xfce": 117,
    "guppy gnome": 119,
    # Cancelled at the ceiling rather than completing, so this is a floor on
    # the true duration, not the duration.
    "guppy kde": 177,
}


@pytest.fixture(scope="module")
def build_push():
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]["build_push"]


def test_the_ceiling_clears_the_slowest_build_we_have_measured(build_push):
    """kde was still emerging at 177 minutes; a ceiling at 180 is not headroom."""
    ceiling = build_push["timeout-minutes"]
    slowest = max(OBSERVED_MINUTES.values())
    assert ceiling > slowest, (
        f"ceiling {ceiling}m does not clear the slowest observed build ({slowest}m)"
    )
    assert ceiling - slowest >= 30, (
        f"only {ceiling - slowest}m of headroom above a build that was still "
        "compiling when it was cancelled -- the next package pushes it over again"
    )


def test_the_ceiling_stays_within_the_platform_limit(build_push):
    """GitHub caps a hosted job at 6 hours; a larger number is silently useless.

    Worth pinning because the failure would be indistinguishable from the
    ceiling working -- the job would just die at 360 with a different message.
    """
    assert build_push["timeout-minutes"] <= 360


def test_the_reason_for_the_number_is_recorded_next_to_it():
    """Twice now the ceiling has been raised without the next reader knowing why.

    A bare number invites someone to trim it back for runner-cost reasons
    without the measurement that set it.
    """
    body = WORKFLOW.read_text()
    ceiling_line = body.index("timeout-minutes: 240")
    preamble = body[max(0, ceiling_line - 1200):ceiling_line]
    assert "#644" in preamble, "the 60-minute precedent is not cited"
    assert "#1802" in preamble, "the 180-minute measurement is not cited"
    assert "binhost" in preamble, (
        "the comment does not say that compiling from source is the real cause"
    )
