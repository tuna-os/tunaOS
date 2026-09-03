"""Failure injection: Rekor / cosign 5xx outage after signing.

Incident: tunaOS#1560 (136 cells down during Rekor outage on 2026-08-15).
Where to assert: `.github/scripts/cosign-retry.sh` + `.github/workflows/reusable-build-image.yml` promote decision.

Asserts all five invariant properties:
  (1) Fails: cosign_retry helper fails when the deadline passes.
  (2) Says why: emits SIGSTORE_OUTAGE and Rekor 502/503 status in stderr.
  (3) Does not call the cell green: sign job failure leaves cell un-green in composite matrix.
  (4) Does not promote: tag-image condition requires sign == success, preventing promotion.
  (5) Keeps enough evidence to diagnose: SIGSTORE_OUTAGE marker is captured for rerun-infra-failures.yml.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

from tests.injection.helpers import (
    ROOT,
    evaluate_composite_status,
    evaluate_promote_condition,
    load_reusable_workflow,
)

HELPER = ROOT / ".github" / "scripts" / "cosign-retry.sh"


def _run_cosign_retry_probe(tmp_path: Path, error_body: str):
    """Run cosign_retry with a command that simulates a Sigstore 5xx outage."""
    probe_script = tmp_path / "probe.sh"
    probe_script.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -u
            sleep() {{ :; }}
            source "{HELPER}"
            outage() {{
              echo '{error_body}' >&2
              return 1
            }}
            cosign_retry outage
            """
        ),
        encoding="utf-8",
    )

    env = dict(os.environ)
    env["SIGN_DEADLINE_MINUTES"] = "0"  # Expire immediately
    env["SIGN_BACKOFF_CAP_SECONDS"] = "1"

    return subprocess.run(
        ["bash", str(probe_script)],
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.mark.parametrize(
    "error_body",
    [
        'Error: Post "https://rekor.sigstore.dev/api/v1/log/entries": status 502 Bad Gateway',
        'Error: Post "https://rekor.sigstore.dev/api/v1/log/entries": status 503 Service Unavailable',
        'Error: Get "https://fulcio.sigstore.dev/api/v2/signingCert": status 500 Internal Server Error',
    ],
)
def test_property_1_and_2_sigstore_outage_fails_and_says_why(tmp_path, error_body):
    """(1) Fails and (2) says why: cosign_retry exits non-zero and emits SIGSTORE_OUTAGE."""
    proc = _run_cosign_retry_probe(tmp_path, error_body)

    # (1) Fails
    assert proc.returncode != 0, "cosign_retry must exit non-zero when deadline expires"

    # (2) Says why
    assert "SIGSTORE_OUTAGE" in proc.stderr
    assert ("502" in proc.stderr or "503" in proc.stderr or "500" in proc.stderr)


def test_property_3_signing_failure_does_not_call_cell_green():
    """(3) Does not call the cell green: cell with failing sign job is not composite green."""
    # When image signing fails, Promote is skipped and builds criterion is not satisfied
    stage = {
        "albacore": {
            "jobs": {
                ("gnome", "build_push"): "success",
                ("gnome", "sign"): "failure",
                ("gnome", "Promote"): "skipped",
            },
            "date": "2026-09-02",
        }
    }
    green, total, lines, prov = evaluate_composite_status(stage)
    assert green == 0, "Cell with failing sign job must not be composite green"
    verdict = prov.get("albacore:gnome", {}).get("builds", {}).get("verdict")
    assert verdict in ("fail", "untested")


def test_property_4_signing_failure_does_not_promote_image():
    """(4) Does not promote: tag-image explicitly requires sign job success."""
    wf = load_reusable_workflow()
    tag_job = wf["jobs"]["tag-image"]
    assert "needs.sign.result == 'success'" in tag_job["if"]

    # When sign fails:
    needs_results = {
        "manifest": "success",
        "sign": "failure",
        "verify_boot": "success",
    }
    assert evaluate_promote_condition(needs_results) is False, "Promote must NOT run when image signing fails"


def test_property_4_sbom_attestation_outage_does_not_block_promote():
    """Promote requires image signature, but does NOT wait on non-blocking SBOM attestation."""
    wf = load_reusable_workflow()
    tag_job = wf["jobs"]["tag-image"]

    # attest_sbom is omitted from needs and if condition of Promote
    assert "attest_sbom" not in tag_job.get("needs", [])
    assert "attest_sbom" not in tag_job.get("if", "")

    # When image sign succeeded but attest_sbom failed (with continue-on-error):
    needs_results = {
        "manifest": "success",
        "sign": "success",
        "verify_boot": "success",
    }
    assert evaluate_promote_condition(needs_results) is True


def test_property_5_sigstore_outage_keeps_diagnostic_evidence(tmp_path):
    """(5) Keeps enough evidence to diagnose: SIGSTORE_OUTAGE marker matches rerun workflow regex."""
    err = 'Error: Post "https://rekor.sigstore.dev/api/v1/log/entries": status 502 Bad Gateway'
    proc = _run_cosign_retry_probe(tmp_path, err)

    assert "SIGSTORE_OUTAGE" in proc.stderr
    assert "rekor.sigstore.dev" in proc.stderr

    # rerun-infra-failures.yml classifies on this exact marker
    rerun_wf = (ROOT / ".github" / "workflows" / "rerun-infra-failures.yml").read_text()
    assert "SIGSTORE_OUTAGE" in rerun_wf, "rerun-infra-failures workflow must look for SIGSTORE_OUTAGE"
