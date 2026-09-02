"""Signing must ride out a Sigstore outage -- and must not hold Promote hostage.

Two separate failures, both measured, drive what this file pins.

**Retrying is not enough.** cosign's own retry is two attempts, sub-second
apart, built to ride out a dropped packet rather than an outage. Wrapping it
in a fixed six-attempt ladder was the first fix, and it was still not enough:
on run 31858324517 (albacore, 2026-08-15) `cosign attest` burned the entire
15m45s budget against a Rekor 502 and failed at 16m19s. The budget also slept
*after* the final attempt, so every failing job ran eight minutes longer than
it had any reason to. The helper is now a wall-clock deadline that fails fast
on errors that are not Sigstore unavailability.

**What blocks promotion matters more than the retry.** In that same run every
albacore flavor built, pushed and passed its gates, and all twelve Promote
jobs were skipped -- because SBOM attestation shared a job with image signing
and Promote required the whole thing. projectbluefin/dakota splits these:
publish-image signs, publish-sbom attaches and signs the SBOM with
continue-on-error, and promote needs only publish-image. tunaOS now does the
same, so these tests pin the split as much as the retry: an image signature is
a promotion precondition, an SBOM attestation delayed by a transparency-log
outage is not.
"""

from __future__ import annotations

import re
import subprocess
import textwrap
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/reusable-build-image.yml"
HELPER = ROOT / ".github/scripts/cosign-retry.sh"

COSIGN_SUBCOMMANDS = ("sign", "verify", "verify-attestation", "attest")


@pytest.fixture(scope="module")
def workflow():
    return yaml.safe_load(WORKFLOW.read_text())


def _cosign_run_blocks(workflow):
    """Every `run:` body in the workflow that invokes cosign directly."""
    blocks = []
    for job_name, job in workflow["jobs"].items():
        for step in job.get("steps") or []:
            run = step.get("run")
            if run and re.search(r"\bcosign (?:%s)\b" % "|".join(COSIGN_SUBCOMMANDS), run):
                blocks.append((job_name, step.get("name"), run))
    return blocks


def test_the_retry_helper_is_a_shared_script():
    assert HELPER.is_file(), f"{HELPER} is missing"
    assert "cosign_retry()" in HELPER.read_text(), "no cosign_retry helper defined"


def test_every_cosign_invocation_goes_through_the_retry_helper(workflow):
    blocks = _cosign_run_blocks(workflow)
    assert blocks, "no cosign invocations found -- has the workflow moved?"

    for job_name, step_name, run in blocks:
        assert "cosign-retry.sh" in run, (
            f"{job_name}/{step_name} calls cosign without sourcing the retry helper"
        )
        for line in run.splitlines():
            stripped = line.strip()
            # `cosign login` is a local credential write with no Sigstore
            # round trip, so it is deliberately outside the retry contract.
            if stripped.startswith("source ") or "cosign login" in stripped:
                continue
            for sub in COSIGN_SUBCOMMANDS:
                if re.search(rf"\bcosign {sub}\b", stripped) and "cosign_retry" not in stripped:
                    pytest.fail(
                        f"{job_name}/{step_name}: cosign {sub} invoked without "
                        f"cosign_retry: {stripped!r}"
                    )


def _deadline(workflow, job_name, step_name) -> int:
    job = workflow["jobs"][job_name]
    step = next(s for s in job["steps"] if s.get("name") == step_name)
    env = step.get("env") or {}
    assert "SIGN_DEADLINE_MINUTES" in env, (
        f"{job_name}/{step_name} does not set SIGN_DEADLINE_MINUTES"
    )
    assert "MAX_RETRIES" not in env, (
        f"{job_name}/{step_name} still carries the old MAX_RETRIES budget"
    )
    return int(env["SIGN_DEADLINE_MINUTES"])


def test_the_retry_budget_is_a_deadline_not_an_attempt_count(workflow):
    """An attempt count silently changes duration whenever a call gets slower.

    Run 31858324517 is the counter-example: six attempts read like a long
    budget and delivered 16 minutes against a longer outage.
    """
    for job_name, step_name, _ in _cosign_run_blocks(workflow):
        _deadline(workflow, job_name, step_name)


def test_a_blocking_cosign_step_waits_out_a_real_outage(workflow):
    """Signing gates promotion, so giving up early throws away a whole build."""
    assert _deadline(workflow, "sign", "Sign images") >= 30, (
        "the image-signing deadline is shorter than outages already observed "
        "in production, and Promote requires it"
    )


def test_a_non_blocking_cosign_step_gives_up_much_sooner(workflow):
    """Off the critical path still costs wall-clock, and that has to be cheap.

    attest_sbom is continue-on-error and absent from Promote's needs, but
    build-variant.yml's stage 2 waits for the entire reusable-workflow call --
    this job included. On gurnard run 31891742138 `pantheon` sat idle while a
    non-blocking attestation burned its budget against a Rekor outage. With a
    40m deadline a four-stage chain spends ~2h40m per variant waiting for an
    artifact it is explicitly allowed to do without.
    """
    attest = _deadline(workflow, "attest_sbom", "Attest SPDX SBOMs")
    sign = _deadline(workflow, "sign", "Sign images")
    assert attest < sign, (
        f"attest_sbom waits {attest}m, as long as blocking signing -- a "
        "transparency-log outage stalls every downstream stage for it"
    )
    assert attest <= 15, (
        f"attest_sbom's {attest}m deadline is charged to every later stage's "
        "wall clock during an outage"
    )
    # Long enough that an ordinary flake is still absorbed: image signing
    # completed in 19s on the run above.
    assert attest >= 5, f"{attest}m is too short to ride out an ordinary flake"


def test_the_non_blocking_step_has_a_ceiling_the_env_deadline_cannot_give_it(workflow):
    """SIGN_DEADLINE_MINUTES bounds one cosign call, not the step.

    The attest loop runs `cosign attest` + `cosign verify-attestation` per
    platform digest and each call starts its own deadline, so the step's worst
    case is deadline x 2 x platforms.

    That worst case is a code property, not a measured one, and the
    distinction matters. On run 31891742138 the step took 39m19s -- 21 Rekor
    502s against a single 40-minute deadline, then SIGSTORE_OUTAGE -- because
    `set -e` aborts the loop on the first *failing* call. Multiplication needs
    calls that succeed slowly, one after another, which nothing aborts. Only a
    step-level timeout bounds the thing stage 2 is actually waiting on.
    """
    attest = workflow["jobs"]["attest_sbom"]
    step = next(s for s in attest["steps"] if s.get("name") == "Attest SPDX SBOMs")
    ceiling = step.get("timeout-minutes")
    assert ceiling, (
        "the attest step has no timeout-minutes, so its duration is "
        "deadline x 2 x platforms with nothing bounding the total"
    )
    per_call = int(step["env"]["SIGN_DEADLINE_MINUTES"])
    assert per_call <= int(ceiling), (
        f"a {per_call}m per-call deadline cannot fit inside a {ceiling}m step "
        "ceiling, so even one slow call trips the timeout"
    )


# ── The promotion contract ────────────────────────────────────────────────


def test_promote_requires_image_signatures(workflow):
    """The supply-chain invariant: nothing unsigned reaches a bare tag."""
    condition = workflow["jobs"]["tag-image"]["if"]
    assert "needs.sign.result == 'success'" in condition, (
        "Promote no longer requires the sign job -- unsigned images could be promoted"
    )


def test_promote_does_not_wait_on_sbom_attestation(workflow):
    """...and the part that is not an invariant must not block promotion.

    This is the whole point of splitting the job. If attest_sbom ever appears
    in Promote's needs or condition, one Rekor outage skips every Promote in
    the matrix again, exactly as it did on 2026-08-15.
    """
    promote = workflow["jobs"]["tag-image"]
    assert "attest_sbom" not in promote["needs"], (
        "Promote depends on attest_sbom -- a Sigstore outage would block promotion again"
    )
    assert "attest_sbom" not in promote["if"], (
        "Promote's condition references attest_sbom -- see above"
    )


def test_sbom_attestation_does_not_fail_the_run(workflow):
    attest = workflow["jobs"]["attest_sbom"]
    assert attest.get("continue-on-error") is True, (
        "attest_sbom is not continue-on-error, so a transparency-log outage "
        "still turns the whole variant red"
    )


def test_sbom_attestation_still_runs_and_still_reports(workflow):
    """Off the critical path is not the same as optional.

    A missing SBOM must still be an error inside the job, or "non-blocking"
    quietly becomes "never happens".
    """
    attest = workflow["jobs"]["attest_sbom"]
    step = next(s for s in attest["steps"] if s.get("name") == "Attest SPDX SBOMs")
    assert "::error::missing SPDX SBOM" in step["run"]
    assert "cosign attest" in step["run"]


# ── The helper's own behaviour, driven directly ───────────────────────────


def _probe(tmp_path: Path, body: str, env: dict[str, str] | None = None):
    script = tmp_path / "probe.sh"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            source {HELPER}
            {body}
            """
        )
    )
    full_env = {"PATH": "/usr/bin:/bin", "SIGN_DEADLINE_MINUTES": "1", "SIGN_BACKOFF_CAP_SECONDS": "1"}
    full_env.update(env or {})
    return subprocess.run(
        ["bash", str(script)], capture_output=True, text=True, env=full_env, timeout=180
    )


def test_the_helper_fails_the_job_when_the_deadline_passes(tmp_path):
    """A retry helper that swallows a permanent failure is worse than none."""
    proc = _probe(
        tmp_path,
        textwrap.dedent(
            """\
            outage() {
              echo 'Error: Post "https://rekor.sigstore.dev/api/v1/log/entries": status 502 Bad Gateway'
              return 1
            }
            cosign_retry outage
            echo "UNREACHABLE"
            """
        ),
    )
    assert proc.returncode != 0, "the script did not fail when the deadline passed"
    assert "UNREACHABLE" not in proc.stdout


def test_exhaustion_emits_the_marker_the_rerun_workflow_greps_for(tmp_path):
    """rerun-infra-failures.yml classifies on this string.

    If the wording drifts, the re-run silently stops recognising Sigstore
    outages and the recovery path this pairs with quietly does nothing.
    """
    proc = _probe(
        tmp_path,
        textwrap.dedent(
            """\
            outage() {
              echo 'Error: Post "https://rekor.sigstore.dev/api/v1/log/entries": status 503 Service Unavailable'
              return 1
            }
            cosign_retry outage || true
            """
        ),
    )
    assert "SIGSTORE_OUTAGE" in proc.stderr, (
        f"no SIGSTORE_OUTAGE marker emitted on exhaustion: {proc.stderr!r}"
    )

    rerun = (ROOT / ".github/workflows/rerun-infra-failures.yml").read_text()
    assert "SIGSTORE_OUTAGE" in rerun, (
        "the re-run workflow no longer looks for the marker the helper emits"
    )


def test_a_non_transient_error_is_not_retried(tmp_path):
    """A bad identity or a registry 403 will not fix itself.

    The old ladder spent its whole budget discovering that. Failing fast is
    the difference between a 16-minute job and an immediate, readable error.
    """
    proc = _probe(
        tmp_path,
        textwrap.dedent(
            """\
            denied() {
              echo 'Error: GET https://ghcr.io/token: status 403 Forbidden'
              return 1
            }
            cosign_retry denied || echo "FAILED-FAST"
            """
        ),
        env={"SIGN_DEADLINE_MINUTES": "30", "SIGN_BACKOFF_CAP_SECONDS": "120"},
    )
    assert "FAILED-FAST" in proc.stdout
    assert "not retrying" in proc.stderr
    # With a 30-minute deadline, any retrying at all would blow the timeout.
    assert "retrying in" not in proc.stderr


def test_an_unrelated_5xx_is_not_treated_as_a_sigstore_outage(tmp_path):
    """Only failures that name a Sigstore endpoint count as transient.

    A 502 from the registry is a different problem with a different fix, and
    burning the signing budget on it hides that.
    """
    proc = _probe(
        tmp_path,
        textwrap.dedent(
            """\
            registry_down() {
              echo 'Error: PUT https://ghcr.io/v2/tuna-os/albacore/manifests/x: status 502 Bad Gateway'
              return 1
            }
            cosign_retry registry_down || echo "FAILED-FAST"
            """
        ),
        env={"SIGN_DEADLINE_MINUTES": "30", "SIGN_BACKOFF_CAP_SECONDS": "120"},
    )
    assert "FAILED-FAST" in proc.stdout
    assert "retrying in" not in proc.stderr


def test_the_helper_succeeds_as_soon_as_the_command_does(tmp_path):
    """A flake that clears on attempt 2 must not be treated as a failure."""
    marker = tmp_path / "attempts"
    proc = _probe(
        tmp_path,
        textwrap.dedent(
            f"""\
            flaky() {{
              local n=0
              [[ -f "{marker}" ]] && n=$(cat "{marker}")
              n=$((n + 1))
              echo "$n" > "{marker}"
              if [[ "$n" -lt 2 ]]; then
                echo 'Post "https://rekor.sigstore.dev/api/v1/log/entries": status 502 Bad Gateway'
                return 1
              fi
            }}
            cosign_retry flaky
            echo "REACHED after $(cat "{marker}") attempt(s)"
            """
        ),
    )
    assert proc.returncode == 0, f"helper did not recover from a transient flake: {proc.stderr!r}"
    assert "REACHED after 2 attempt(s)" in proc.stdout


def test_the_helper_does_not_sleep_after_its_last_attempt(tmp_path):
    """The old ladder slept 480s past the final attempt for nothing.

    A 1-minute deadline with a 1-second cap should return at or before the
    deadline, not a backoff period after it.
    """
    proc = _probe(
        tmp_path,
        textwrap.dedent(
            """\
            start=$(date +%s)
            outage() {
              echo 'Post "https://rekor.sigstore.dev/api/v1/log/entries": status 502 Bad Gateway'
              return 1
            }
            cosign_retry outage || true
            echo "ELAPSED=$(( $(date +%s) - start ))"
            """
        ),
    )
    elapsed = int(re.search(r"ELAPSED=(\d+)", proc.stdout).group(1))
    assert elapsed <= 62, f"helper overran its 60s deadline by {elapsed - 60}s of dead sleep"
