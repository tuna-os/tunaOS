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


# ── The ceiling is not a diagnosis ───────────────────────────────────────────
#
# Everything above keeps the ceiling high enough for a real build. It says
# nothing about what happens when a build is not slow but STUCK, and the
# difference matters because the two look identical from outside:
#
#   Build Hummingbird #66, run 32907940350, `hummingbird / gnome / linux-amd64`
#     23:12:27  [13/30] pcre2-utf32-0:10.47-1.2.hum1 100% | 247.5 KiB | 00m00s
#     03:00:31  ##[error]The operation was canceled.
#
# 3h48m of total silence inside one dnf transaction, then the ceiling fired.
# The cancellation wrote no digest artifact, so Manifest failed and Sign,
# Gate, Promote, Attest SBOM and the gnome ISO were all skipped -- and the
# log said only "canceled", with nothing naming what had wedged.
#
# Raising the ceiling would have made that worse, not better. The fix is a
# wall-clock bound INSIDE the step, so a wedge fails early enough to leave
# room for telemetry and says so in an annotation.

STEP_BOUND_MINUTES = 210


@pytest.fixture(scope="module")
def build_image_step(build_push):
    for step in build_push["steps"]:
        if step.get("name") == "Build Image":
            return step
    raise AssertionError("Build Image step not found")


def test_the_build_is_bounded_inside_the_step_not_only_by_the_job(build_image_step):
    run = build_image_step["run"]
    assert f"timeout --kill-after=60s {STEP_BOUND_MINUTES}m" in run, (
        "the build invocation is not wrapped in a wall-clock timeout, so a "
        "wedged layer costs the entire job ceiling and reports as a cancellation"
    )


def test_the_timeout_runs_under_sudo_so_it_can_signal_a_root_buildah(build_image_step):
    """A non-root `timeout` cannot kill the root process it is bounding.

    `timeout ... sudo just build` would fire, fail to signal the setuid child,
    and wedge exactly as before while looking like it was handled.
    """
    run = build_image_step["run"]
    sudo = run.index("sudo --preserve-env=")
    timeout = run.index("timeout --kill-after=60s")
    assert sudo < timeout, "timeout must be inside sudo, not outside it"


def test_the_step_bound_leaves_the_job_room_to_report(build_push):
    ceiling = build_push["timeout-minutes"]
    assert STEP_BOUND_MINUTES < ceiling, (
        "a step bound at or above the job ceiling never fires -- the job is "
        "cancelled first and nothing is gained"
    )
    assert ceiling - STEP_BOUND_MINUTES >= 30, (
        "not enough margin for Build telemetry and the log upload to run "
        "after the bound fires"
    )


def test_the_step_bound_still_clears_the_slowest_real_build(build_push):
    """The bound must not become a second, lower ceiling by accident."""
    slowest = max(OBSERVED_MINUTES.values())
    assert STEP_BOUND_MINUTES > slowest, (
        f"a {STEP_BOUND_MINUTES}m bound would kill guppy kde, which was still "
        f"compiling at {slowest}m"
    )


def test_a_wedged_build_is_annotated_rather_than_reported_as_a_cancellation(
    build_image_step,
):
    """124 (timed out) and 137 (SIGKILL after --kill-after) both mean wedged."""
    run = build_image_step["run"]
    assert "::error title=Build wedged::" in run
    assert "124" in run and "137" in run, (
        "both timeout exit codes must be recognised -- --kill-after means a "
        "process that ignores SIGTERM exits 137, not 124"
    )


def test_a_normal_build_failure_still_fails_the_step(build_image_step):
    """Capturing rc must not turn a real build error into a pass."""
    run = build_image_step["run"]
    assert '[ "$rc" -eq 0 ] || exit "$rc"' in run, (
        "rc is captured with `|| rc=$?` but never re-raised, so every build "
        "failure would now be swallowed"
    )
