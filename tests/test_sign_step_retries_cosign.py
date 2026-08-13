"""The Sign+attest step must not die on cosign's very first flake.

cosign has its own internal retry -- two attempts, sub-second apart -- which
is built to ride out a dropped packet, not a Sigstore outage. Measured
directly from run 31663727643 (flounder, base):

    Error: signing ghcr.io/tuna-os/flounder@sha256:...: creating bundle:
    signing bundle: error signing bundle: Post
    "https://rekor.sigstore.dev/api/v1/log/entries": giving up after
    2 attempt(s): status 502 Bad Gateway

The same signature recurred, in the same ~90-minute run window, across
albacore, skipjack, sailfin, bonito and bonito-rawhide -- builds that had
genuinely succeeded, failing only at this one unwrapped `cosign sign`. One
outside outage took down Sign+attest fleet-wide because nothing in this repo
retried past cosign's own two attempts.

The fix wraps every cosign invocation in a `cosign_retry` helper, following
the same linear-backoff idiom the "Push to GHCR" step already uses for GHCR
blob-push flakiness. These tests pin that the wrapper exists, that every
sign/verify/attest call goes through it, and that its own failure still
kills the job -- an unenforced retry that swallows a real, permanent
signing failure would be worse than no retry at all.
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

COSIGN_SUBCOMMANDS = ("sign", "verify", "verify-attestation", "attest")


@pytest.fixture(scope="module")
def sign_step():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    step = next(
        s
        for s in workflow["jobs"]["sign"]["steps"]
        if s.get("name") == "Sign images and attest SBOMs"
    )
    return step


def test_a_retry_helper_is_defined(sign_step):
    assert "cosign_retry()" in sign_step["run"], (
        "no cosign_retry helper defined in the Sign+attest step"
    )


def test_every_cosign_invocation_goes_through_the_retry_helper(sign_step):
    run = sign_step["run"]
    # Strip the function definition itself so its body (which legitimately
    # calls "$@", not "cosign") doesn't produce false matches or hide a bare
    # `cosign ...` call sitting right next to it.
    body = re.sub(r"cosign_retry\(\) \{.*?\n\}\n", "", run, flags=re.S)
    assert "cosign_retry() {" not in body, "failed to strip the helper definition before scanning"

    for sub in COSIGN_SUBCOMMANDS:
        # Every line invoking `cosign <sub>` must carry the retry helper's
        # name on that same line -- a bare cosign call anywhere here is
        # exactly the gap that let one Sigstore blip fail Sign+attest
        # fleet-wide.
        for line in body.splitlines():
            if re.search(rf"\bcosign {sub}\b", line) and "cosign_retry" not in line:
                pytest.fail(f"cosign {sub} is invoked without cosign_retry: {line.strip()!r}")


def test_the_helper_retries_more_than_once():
    # cosign's own retry is 2 attempts; if MAX_RETRIES resolves to 1 or 2,
    # this wrapper adds nothing over what cosign already does internally.
    workflow = yaml.safe_load(WORKFLOW.read_text())
    sign_job = workflow["jobs"]["sign"]
    step = next(
        s
        for s in sign_job["steps"]
        if s.get("name") == "Sign images and attest SBOMs"
    )
    max_retries = step.get("env", {}).get("MAX_RETRIES")
    assert max_retries is not None, "MAX_RETRIES is not set for the Sign+attest step"
    assert int(max_retries) >= 3, (
        f"MAX_RETRIES={max_retries!r} does not meaningfully exceed cosign's "
        "own 2-attempt internal retry"
    )


def _extract_helper_source(sign_step_run: str) -> str:
    match = re.search(r"cosign_retry\(\) \{.*?\n\}\n", sign_step_run, re.S)
    assert match, "could not extract the cosign_retry function body"
    return match.group(0)


def test_the_helper_itself_fails_the_job_when_retries_are_exhausted(sign_step, tmp_path):
    """A retry helper that swallows a permanent failure is worse than none.

    Drives the REAL helper extracted from the workflow file -- not a
    reimplementation -- against a command that always fails, and checks
    that under `set -e` (exactly how the step invokes it: a bare statement,
    not inside if/&&/||) the calling script dies rather than continuing.
    """
    helper_src = _extract_helper_source(sign_step["run"])
    script = tmp_path / "probe.sh"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            MAX_RETRIES=3
            {helper_src}
            cosign_retry false
            echo "UNREACHABLE"
            """
        )
    )
    proc = subprocess.run(["bash", str(script)], capture_output=True, text=True)
    assert proc.returncode != 0, "the script did not fail when retries were exhausted"
    assert "UNREACHABLE" not in proc.stdout, (
        f"execution continued past exhausted retries: {proc.stdout!r}"
    )


def test_the_helper_succeeds_as_soon_as_the_command_does(sign_step, tmp_path):
    """A flake that clears on attempt 2 must not be treated as a failure."""
    helper_src = _extract_helper_source(sign_step["run"])
    marker = tmp_path / "attempts"
    script = tmp_path / "probe.sh"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            MAX_RETRIES=3
            {helper_src}
            flaky() {{
              local n=0
              [[ -f "{marker}" ]] && n=$(cat "{marker}")
              n=$((n + 1))
              echo "$n" > "{marker}"
              [[ "$n" -ge 2 ]]
            }}
            cosign_retry flaky
            echo "REACHED after $(cat "{marker}") attempt(s)"
            """
        )
    )
    proc = subprocess.run(["bash", str(script)], capture_output=True, text=True)
    assert proc.returncode == 0, f"helper did not recover from a transient flake: {proc.stderr!r}"
    assert "REACHED after 2 attempt(s)" in proc.stdout
