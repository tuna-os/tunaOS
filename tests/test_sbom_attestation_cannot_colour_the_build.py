"""A Sigstore outage must not decide what colour a nightly is.

`attest_sbom` was already `continue-on-error: true` and already absent from
Promote's `needs:` -- that was #1560's fix and it works. On the 2026-09-02
yellowfin nightly (run 33591594151) every platform of every flavor built,
pushed, signed, manifested and promoted; `base / Promote` succeeded; the one
failing job in thirty was `base / Attest SBOM` against a Rekor that answered
502.

The run still concluded `failure`. `continue-on-error` stops a job from
failing the run it is DEFINED in; across a reusable-workflow boundary the
caller's `uses:` job reports the called workflow's aggregate result, and that
is the conclusion the world reads. Three things read it:

  * `.github/scripts/update-build-status.sh` renders the variant's "Latest
    run" column from it, so the README matrix reported 47/143 built for a
    fleet that had built;
  * `rerun-infra-failures.yml` fires only on a failed run, so every one of
    these nights entered the recovery path;
  * anyone glancing at the Actions tab.

So the attestation now has its own workflow, its own run and its own
conclusion (tuna-os/tunaOS#2282). These tests pin the separation and the two
things that separation is easy to break: the trigger list going stale as
variants are added, and the artifacts it reads across runs expiring before
the re-run that recovers an outage can read them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
BUILD = WORKFLOWS / "reusable-build-image.yml"
ATTEST = WORKFLOWS / "attest-sbom.yml"
RERUN = WORKFLOWS / "rerun-infra-failures.yml"
VARIANT = "build-variant.yml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def _triggers(doc: dict) -> dict:
    """The `on:` block. PyYAML reads the bare key `on` as the boolean True."""
    on = doc.get("on", doc.get(True, {}))
    if isinstance(on, str):
        return {on: None}
    if isinstance(on, list):
        return {k: None for k in on}
    return on or {}


@pytest.fixture(scope="module")
def attest() -> dict:
    return _load(ATTEST)


@pytest.fixture(scope="module")
def build() -> dict:
    return _load(BUILD)


# ── the separation itself ─────────────────────────────────────────────────


def test_the_attestation_is_not_a_job_in_the_build_run(build):
    """Any placement inside the build workflow colours the build's run."""
    assert "attest_sbom" not in build["jobs"], (
        "SBOM attestation is back in the build workflow; continue-on-error "
        "does not stop it deciding the run's conclusion (run 33591594151)"
    )
    for job_name, job in build["jobs"].items():
        for step in job.get("steps") or []:
            assert "cosign attest" not in (step.get("run") or ""), (
                f"{job_name}/{step.get('name')} attests inside the build run"
            )


def test_the_attestation_runs_off_the_build_run(attest):
    """`workflow_run` is what buys it a conclusion of its own."""
    assert "workflow_run" in _triggers(attest), (
        "attest-sbom.yml is not triggered by workflow_run, so it is either "
        "dead or back on the build's clock"
    )


def test_every_variant_nightly_is_attested(attest):
    """The trigger list is hand-written; a new variant must not fall out.

    Nothing fails when a workflow is missing from it -- the variant simply
    stops being attested, quietly, for as long as nobody checks. Derive the
    list from the callers instead of restating it.
    """
    listed = set(_triggers(attest)["workflow_run"]["workflows"])
    missing = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        doc = _load(path) or {}
        jobs = doc.get("jobs") or {}
        if not any((j or {}).get("uses", "").endswith(VARIANT) for j in jobs.values()):
            continue
        name = doc.get("name")
        if name not in listed:
            missing.append(f"{path.name} ({name!r})")
    assert not missing, (
        "these workflows build images with SBOMs but are not in "
        f"attest-sbom.yml's workflow_run list, so nothing attests them: {missing}"
    )


def test_a_pull_request_build_is_not_attested(attest):
    """PR builds never publish, so there is no immutable ref to attest."""
    assert "github.event.workflow_run.event != 'pull_request'" in attest["jobs"]["attest"]["if"]


# ── what it reads, and for how long it can read it ────────────────────────


def _build_push_step(build, name):
    return next(
        s for s in build["jobs"]["build_push"]["steps"] if s.get("name") == name
    )


def test_the_image_reference_is_recorded_not_guessed(build):
    """`<image-name>-<tag>-<platform>.txt` cannot be parsed back into a ref.

    Both of the first two fields contain hyphens, so the filename the
    attesting workflow sees splits a dozen ways and only one of them is right.
    It is handed the answer instead.
    """
    step = _build_push_step(build, "Record Attestation Target")
    assert ".ref" in step["run"]
    assert "IMAGE_REGISTRY" in step["run"] and "DIGEST" in step["run"]

    upload = _build_push_step(build, "Upload Output Artifacts")
    assert "*.ref" in upload["with"]["path"], (
        "the ref sidecar is written but never uploaded, so attest-sbom.yml "
        "finds nothing to attest"
    )


def test_recording_the_ref_cannot_cost_the_digest_artifact(build):
    """The reason it is a separate step.

    `Create Job Outputs` writes the digest artifact `Manifest` fans in on.
    Gating that on the SBOM is what cost a whole variant in #1796, so the
    SBOM condition belongs on the new step and nowhere near the old one.
    """
    assert "sbom" not in str(_build_push_step(build, "Create Job Outputs").get("if", "")).lower()
    assert "inputs.sbom" in str(_build_push_step(build, "Record Attestation Target")["if"])


def test_the_digest_artifact_outlives_the_outage_it_has_to_survive(build):
    """One day was fine when only `Manifest`, in the same run, read it.

    attest-sbom.yml reads it from a different run, and the recovery path for a
    transparency-log outage is rerun-infra-failures.yml waiting 45 minutes and
    re-running -- possibly the following morning. An expired artifact turns a
    recoverable outage into a permanently unattested image.
    """
    upload = _build_push_step(build, "Upload Output Artifacts")
    assert int(upload["with"]["retention-days"]) >= 2, (
        "the digest artifacts expire before an overnight re-run could read them"
    )


# ── the recovery path still reaches it ────────────────────────────────────


def test_the_rerun_classifier_can_still_recover_an_outage():
    """Moving the job out of the nightly moved it out of the classifier too.

    `rerun-infra-failures.yml` was the documented recovery for a missed
    attestation. It watches a list of workflows and only acts on runs whose
    own event is unattended -- and an attest run's event is `workflow_run`,
    never `schedule`.
    """
    doc = _load(RERUN)
    assert _load(ATTEST)["name"] in _triggers(doc)["workflow_run"]["workflows"], (
        "attest-sbom.yml is not watched by the infra re-run classifier, so a "
        "Sigstore outage now leaves the SBOM unattested with no recovery"
    )
    condition = doc["jobs"]["classify-and-rerun"]["if"]
    assert "github.event.workflow_run.event == 'workflow_run'" in condition, (
        "the classifier still only accepts `schedule` runs, so it watches "
        "attest-sbom.yml and can never act on it"
    )


def test_the_outage_marker_the_classifier_greps_for_still_reaches_the_log(attest):
    """cosign_retry prints SIGSTORE_OUTAGE; the loop captures cosign's output.

    Capturing it into a variable to decide whether to keep going is exactly
    how the marker gets lost, and losing it reclassifies an outage as a
    product failure that is deliberately never re-run.
    """
    step = next(
        s for s in attest["jobs"]["attest"]["steps"]
        if s.get("name") == "Attest SPDX SBOMs"
    )
    assert "cosign-retry.sh" in step["run"]
    assert "SIGSTORE_OUTAGE" in step["run"]
    assert "printf '%s\\n' \"$out\" >&2" in step["run"], (
        "cosign's captured output is never re-emitted, so SIGSTORE_OUTAGE "
        "never reaches the job log the classifier reads"
    )


def test_one_outage_does_not_cost_a_full_deadline_per_image(attest):
    """The old job handled one flavor; this one handles a whole variant.

    24 refs x 2 cosign calls x a 10m deadline is four hours of red for a log
    that has already said it is down. Once it has, the loop stops asking.
    """
    step = next(
        s for s in attest["jobs"]["attest"]["steps"]
        if s.get("name") == "Attest SPDX SBOMs"
    )
    assert 'outage="yes"' in step["run"]
    assert "ATTEST_BUDGET_MINUTES" in step["env"]
