"""A failed SBOM scan must cost the SBOM, not the whole variant.

`Generate SBOM` runs *after* the platform image is built, pushed and
immutable in GHCR. Nothing it does can un-publish that image. Yet twice now a
dead scan has taken a whole variant down with it, because the step sits
upstream of `Create Job Outputs` -- the step that writes the digest artifact
`Manifest` fans in on. Kill the scan and the chain is:

    Generate SBOM      dies
    Create Job Outputs skipped        (no digest artifact written)
    Manifest           fails at `Load Outputs`
    Sign / Gate / Promote             skipped
    every stage-2 flavor              skipped

A 0/N night for the variant, caused by an artifact that is not a promotion
precondition.

The scan has now escaped two separate bounds, each of which caught only one
failure mode:

    timeout-minutes: 20   enforced by the runner AGENT, so it cannot fire when
                          the agent is the casualty. On 2026-08-14 (#1567) the
                          step overran it by 51 minutes and uploaded no logs.
    timeout 18m           wall-clock, added by #1572. On the 2026-08-16
                          nightly the runner died at 7m56s -- well inside it --
                          with "The runner has received a shutdown signal."

Time was never the fault. Memory is: GOMEMLIMIT is advisory, so a large enough
file inventory sails past it and takes the agent down. These tests pin both
halves of the fix -- a cgroup cap so the kernel kills syft instead of the
agent, and a soft failure so a dead scan cannot skip the digest artifact.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/reusable-build-image.yml"


@pytest.fixture(scope="module")
def build_push():
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]["build_push"]


def step(build_push, name):
    return next(s for s in build_push["steps"] if s.get("name") == name)


# ── the scan must not be able to kill the runner ──────────────────────────


def test_the_scan_is_memory_bounded_not_only_time_bounded(build_push):
    """The agent cannot enforce a limit while it is the thing dying.

    Only a kernel-level cap turns "runner disappears, no logs, variant lost"
    into "syft is killed, step fails, logs intact".
    """
    run = step(build_push, "Generate SBOM")["run"]
    assert "systemd-run" in run, "syft is not run under a cgroup, so nothing bounds its memory"
    assert "MemoryMax" in run, "systemd-run is used without a MemoryMax cap"
    assert "MemorySwapMax=0" in run, (
        "swap is not capped, so the cgroup can thrash instead of killing the scan"
    )


def test_the_wall_clock_bound_is_kept_too(build_push):
    """The two bounds cover different faults; the new one does not replace the old.

    A scan that is merely slow, rather than hungry, is still only caught by
    the wall clock.
    """
    assert "timeout --kill-after" in step(build_push, "Generate SBOM")["run"]


def test_a_missing_cgroup_tool_is_announced_not_silently_ignored(build_push):
    """Falling back without saying so would restore the original failure quietly."""
    run = step(build_push, "Generate SBOM")["run"]
    assert "::warning::" in run, "the unbounded fallback path emits no warning"
    assert "NOT memory-bounded" in run


# ── a dead scan must not cost the variant ─────────────────────────────────


def test_a_failed_scan_does_not_fail_the_build_job(build_push):
    """The image is already pushed; the SBOM is not a promotion precondition.

    Same line drawn for SBOM attestation in #1560/#1766, applied one step
    earlier to SBOM generation.
    """
    assert step(build_push, "Generate SBOM").get("continue-on-error") is True, (
        "a failed SBOM scan still fails build_push, which skips Create Job "
        "Outputs and takes Manifest, Sign, Gate, Promote and every stage-2 "
        "flavor down with it"
    )


def test_the_digest_artifact_does_not_depend_on_the_sbom(build_push):
    """`Manifest` fans in on this. It must survive a dead scan.

    This is the step whose skipping caused the cascade, so its condition must
    not acquire an SBOM dependency.
    """
    for name in ("Create Job Outputs", "Upload Output Artifacts"):
        condition = str(step(build_push, name).get("if", ""))
        assert "sbom" not in condition.lower(), (
            f"{name!r} is gated on the SBOM, so a failed scan loses the digest "
            "artifact and the variant with it"
        )


def test_the_soft_failure_is_not_converted_straight_back_into_a_hard_one(build_push):
    """`Upload SBOM` carries `if-no-files-found: error`.

    With `Generate SBOM` continue-on-error, the job stays green and this step
    would otherwise run against a file that was never written -- turning the
    deliberately soft failure back into a hard one for exactly the same runs.
    """
    generate = step(build_push, "Generate SBOM")
    upload = step(build_push, "Upload SBOM")
    assert generate.get("id") == "sbom", "Generate SBOM has no id to key the upload on"
    assert "steps.sbom.outcome == 'success'" in upload["if"], (
        "Upload SBOM does not check whether the scan actually produced anything"
    )


def test_a_missing_sbom_is_still_reported_somewhere(build_push):
    """Soft must not mean silent.

    attest_sbom is the backstop: it is continue-on-error, so it cannot fail
    the run, but it must still say the SBOM is missing.
    """
    workflow = yaml.safe_load(WORKFLOW.read_text())
    attest = workflow["jobs"]["attest_sbom"]
    assert attest.get("continue-on-error") is True
    body = next(s for s in attest["steps"] if s.get("name") == "Attest SPDX SBOMs")["run"]
    assert "::error::missing SPDX SBOM" in body


# ── the cap has to be a cap on whatever runner we land on ─────────────────


def _cap_mib(total_mib: int, build_push) -> int:
    """Run the step's own sizing arithmetic against a runner of `total_mib`.

    Lifted from the workflow rather than restated here, so the test moves
    when the policy does and cannot quietly drift away from it.
    """
    import re
    import subprocess

    run = step(build_push, "Generate SBOM")["run"]
    start = run.index('mem_total_mib=')
    end = run.index('echo "runner memory')
    body = run[start:end]
    # The one line that asks the kernel; everything after it is arithmetic.
    body = re.sub(r'^mem_total_mib=.*$', f'mem_total_mib={total_mib}', body, flags=re.M)

    env = step(build_push, "Generate SBOM")["env"]
    script = "\n".join(
        [
            "set -euo pipefail",
            f'SYFT_MEMORY_RESERVE_MIB={env["SYFT_MEMORY_RESERVE_MIB"]}',
            f'SYFT_MEMORY_FLOOR_MIB={env["SYFT_MEMORY_FLOOR_MIB"]}',
            body,
            'echo "$cap_mib"',
        ]
    )
    out = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=True
    )
    return int(out.stdout.strip().splitlines()[-1])


def test_the_cap_is_derived_from_the_runner_not_hardcoded(build_push):
    """A hardcoded ceiling stops being a ceiling the moment the box shrinks.

    That is precisely the case the guard exists for: if the number exceeds
    physical memory the cgroup never fires, the kernel picks its own victim,
    and we are back to a dead agent with no logs. Sizing from `free` means
    the cap holds on a runner nobody told us about -- including the arm64
    leg, which is a different image from `ubuntu-latest`.
    """
    run = step(build_push, "Generate SBOM")["run"]
    assert "free -m" in run, "the cap is not sized from the runner's actual memory"
    assert _cap_mib(4096, build_push) < 4096, (
        "the cap exceeds physical memory on a small runner, so it caps nothing"
    )
    assert _cap_mib(64000, build_push) > _cap_mib(16000, build_push), (
        "a larger runner does not buy the scan a larger budget"
    )


def test_the_agent_keeps_a_reserve_on_a_normal_runner(build_push):
    """Guppy's Gentoo inventory needs room; the agent needs to survive reporting it.

    5G was too tight -- exit 137 on run 31942667550 after 2m11s -- on a box
    with far more than 5G to give. The reserve is what the agent gets; the
    scan should get the rest of a standard 16 GB runner, not a fraction of it.
    """
    cap = _cap_mib(15990, build_push)
    assert cap > 10 * 1024, f"a 16 GB runner leaves syft only {cap} MiB"
    assert 15990 - cap >= 4096, (
        f"only {15990 - cap} MiB left for the agent, which is what the cap protects"
    )


def test_a_tiny_runner_still_leaves_the_scan_something_to_work_with(build_push):
    """Reserve-minus-total can go negative; a negative or zero cap kills syft instantly."""
    assert _cap_mib(2048, build_push) > 0
    assert _cap_mib(512, build_push) > 0
