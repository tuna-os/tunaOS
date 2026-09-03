"""The build ceiling has to clear the slowest real build, or it eats whole cells.

`timeout-minutes` on `build_push` is a max, not a budget: RPM variants finish
in 20-40 minutes and never approach it. It exists for the source-based
experimental variants, where guppy (Gentoo) compiles the desktop from source.

When it is set too low the failure is not "the build was slow" -- it is a
cancelled job, which writes no digest artifact, so `Manifest` fails at
`Load Outputs` and `Sign`, `Gate`, `Promote` and `Attest SBOM` are all
skipped. One cell lost, and it reports as a cancellation rather than as a
timeout, which reads like infrastructure rather than a ceiling.

That has now happened three times:

    #644   at 60   guppy base could not finish from stage3
    #1802  at 180  guppy kde cancelled at 2h57m with 245 of 252 emerge jobs
                   complete, still compiling steadily (load avg 2.61)
    run 33624381727, 2026-09-02, at the flat 210m step bound from #2081:
                   guppy kde killed with 250 of 254 emerge jobs complete and
                   three packages actively compiling (plasma-desktop,
                   powerdevil, plasma-browser-integration), because Gentoo
                   had bumped plasma to 6.6.5 and the binhost had not caught
                   up, so the whole set built from source. Three days earlier
                   the same cell took 55 minutes off a warm binhost.

The duration is bimodal, and the slow mode is the one the ceiling exists for.
So the ceiling is per variant: guppy gets the platform maximum, every binary
variant keeps the old number, so raising guppy's headroom does not raise the
price of a wedge on the twelve variants that never need it.

These tests pin both numbers against the slowest build actually observed, so
the next person to lower either has to argue with a measurement.
"""

from __future__ import annotations

import re
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

# The slow mode. Run 33624381727 (2026-09-02) was killed at exactly 210
# minutes with four emerge jobs still to go, so this too is a floor: the
# true from-source duration is higher by however long plasma-desktop and the
# other three take to compile.
OBSERVED_FROM_SOURCE_FLOOR = {"guppy kde (plasma 6.6.5 from source)": 210}

# The fast mode, for the record: run 33310245957 (2026-08-30), warm binhost.
OBSERVED_FROM_BINHOST = {"guppy kde": 55}

# The variant that compiles from source, and one that never does.
SOURCE_VARIANT = "guppy"
BINARY_VARIANT = "yellowfin"

PER_VARIANT = re.compile(
    r"^\$\{\{\s*inputs\.image-variant == '(?P<variant>[\w-]+)'\s*&&\s*(?P<yes>\d+)"
    r"\s*\|\|\s*(?P<no>\d+)\s*\}\}$"
)


def minutes_for(setting, variant: str) -> int:
    """Resolve a plain integer or a `variant == X && A || B` expression."""
    if isinstance(setting, int):
        return setting
    match = PER_VARIANT.match(str(setting).strip())
    assert match, f"unrecognised ceiling expression: {setting!r}"
    if variant == match.group("variant"):
        return int(match.group("yes"))
    return int(match.group("no"))


@pytest.fixture(scope="module")
def build_push():
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]["build_push"]


@pytest.fixture(scope="module")
def build_image_step(build_push):
    for step in build_push["steps"]:
        if step.get("name") == "Build Image":
            return step
    raise AssertionError("Build Image step not found")


def ceiling_for(build_push, variant: str) -> int:
    return minutes_for(build_push["timeout-minutes"], variant)


def step_bound_for(build_image_step, variant: str) -> int:
    return minutes_for(build_image_step["env"]["BUILD_BOUND_MINUTES"], variant)


def test_the_expression_parser_reads_both_shapes():
    assert minutes_for(240, "guppy") == 240
    expr = "${{ inputs.image-variant == 'guppy' && 360 || 240 }}"
    assert minutes_for(expr, "guppy") == 360
    assert minutes_for(expr, "yellowfin") == 240


def test_the_ceiling_clears_the_slowest_build_we_have_measured(build_push):
    """kde was still emerging at 177 minutes; a ceiling at 180 is not headroom."""
    ceiling = ceiling_for(build_push, SOURCE_VARIANT)
    slowest = max(OBSERVED_MINUTES.values())
    assert ceiling > slowest, (
        f"ceiling {ceiling}m does not clear the slowest observed build ({slowest}m)"
    )
    assert ceiling - slowest >= 30, (
        f"only {ceiling - slowest}m of headroom above a build that was still "
        "compiling when it was cancelled -- the next package pushes it over again"
    )


def test_the_ceiling_clears_a_from_source_plasma_build(build_push):
    """210 was a kill with four packages to go, so it is a floor, not a duration.

    Sixty minutes over that floor is the least that plausibly covers
    plasma-desktop plus the rechunk and push that follow the emerge.
    """
    ceiling = ceiling_for(build_push, SOURCE_VARIANT)
    floor = max(OBSERVED_FROM_SOURCE_FLOOR.values())
    assert ceiling - floor >= 60, (
        f"{ceiling}m is only {ceiling - floor}m above a build that was killed "
        "mid-emerge at {floor}m -- the same binhost miss kills it again"
    )


def test_binary_variants_do_not_pay_for_guppys_headroom(build_push):
    """A wedge on an RPM variant should still fail in four hours, not six.

    The ceiling is a max, so the extra headroom is free on a healthy build;
    it is not free on a wedged one, and there are twelve binary variants to
    guppy's one.
    """
    assert ceiling_for(build_push, BINARY_VARIANT) <= 240


def test_the_ceiling_stays_within_the_platform_limit(build_push):
    """GitHub caps a hosted job at 6 hours; a larger number is silently useless.

    Worth pinning because the failure would be indistinguishable from the
    ceiling working -- the job would just die at 360 with a different message.
    """
    for variant in (SOURCE_VARIANT, BINARY_VARIANT):
        assert ceiling_for(build_push, variant) <= 360


def test_the_reason_for_the_number_is_recorded_next_to_it():
    """Twice now the ceiling has been raised without the next reader knowing why.

    A bare number invites someone to trim it back for runner-cost reasons
    without the measurement that set it.
    """
    body = WORKFLOW.read_text()
    ceiling_line = body.index("timeout-minutes: ${{ inputs.image-variant")
    preamble = body[max(0, ceiling_line - 1800) : ceiling_line]
    assert "#644" in preamble, "the 60-minute precedent is not cited"
    assert "#1802" in preamble, "the 180-minute measurement is not cited"
    assert "binhost" in preamble, (
        "the comment does not say that compiling from source is the real cause"
    )
    assert "33624381727" in preamble, (
        "the 210-minute kill that showed the duration is bimodal is not cited"
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
# room for telemetry and says so in an annotation. But it is a clock: it
# fires on a slow build exactly as it fires on a wedged one, and run
# 33624381727 showed what happens when the message pretends otherwise.


def test_the_build_is_bounded_inside_the_step_not_only_by_the_job(build_image_step):
    run = build_image_step["run"]
    assert 'timeout --kill-after=60s "${BUILD_BOUND_MINUTES}m"' in run, (
        "the build invocation is not wrapped in the per-variant wall-clock "
        "timeout, so a wedged layer costs the entire job ceiling and reports "
        "as a cancellation"
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


@pytest.mark.parametrize("variant", [SOURCE_VARIANT, BINARY_VARIANT])
def test_the_step_bound_leaves_the_job_room_to_report(build_push, build_image_step, variant):
    ceiling = ceiling_for(build_push, variant)
    bound = step_bound_for(build_image_step, variant)
    assert bound < ceiling, (
        f"{variant}: a step bound at or above the job ceiling never fires -- "
        "the job is cancelled first and nothing is gained"
    )
    assert ceiling - bound >= 30, (
        f"{variant}: not enough margin for Build telemetry and the log upload "
        "to run after the bound fires"
    )


def test_the_step_bound_still_clears_the_slowest_real_build(build_image_step):
    """The bound must not become a second, lower ceiling by accident.

    It did, once: the flat 210m bound from #2081 was above the 177m
    measurement it was set against and below the from-source build that
    followed three weeks later.
    """
    bound = step_bound_for(build_image_step, SOURCE_VARIANT)
    slowest = max(max(OBSERVED_MINUTES.values()), max(OBSERVED_FROM_SOURCE_FLOOR.values()))
    assert bound - slowest >= 60, (
        f"a {bound}m bound is only {bound - slowest}m above a guppy kde build "
        f"that was killed mid-emerge at {slowest}m"
    )


def test_a_binary_variant_keeps_the_tighter_bound(build_image_step):
    """Guppy's headroom is guppy's; an RPM wedge still fails at 210."""
    assert step_bound_for(build_image_step, BINARY_VARIANT) <= 210


def test_a_killed_build_is_annotated_rather_than_reported_as_a_cancellation(
    build_image_step,
):
    """124 (timed out) and 137 (SIGKILL after --kill-after) both mean killed."""
    run = build_image_step["run"]
    assert "::error title=" in run
    assert "124" in run and "137" in run, (
        "both timeout exit codes must be recognised -- --kill-after means a "
        "process that ignores SIGTERM exits 137, not 124"
    )


def test_the_annotation_does_not_claim_to_know_why(build_image_step):
    """A wall clock cannot tell a wedge from a slow compile; the message must not.

    Run 33624381727's annotation read "made no progress for 210 minutes" over
    a log whose last lines were three packages actively emerging. The next
    reader should be sent to the log, not handed a diagnosis the tool cannot
    make.
    """
    run = build_image_step["run"]
    annotation = next(line for line in run.splitlines() if "::error title=" in line)
    assert "no progress" not in annotation
    assert "${BUILD_BOUND_MINUTES}" in annotation, (
        "the annotation should say which bound fired, in the variant's own minutes"
    )
    assert "last line of build output" in annotation


def test_a_normal_build_failure_still_fails_the_step(build_image_step):
    """Capturing rc must not turn a real build error into a pass."""
    run = build_image_step["run"]
    assert '[ "$rc" -eq 0 ] || exit "$rc"' in run, (
        "rc is captured with `|| rc=$?` but never re-raised, so every build "
        "failure would now be swallowed"
    )
