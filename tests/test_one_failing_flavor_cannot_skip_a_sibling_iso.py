"""One failing desktop must not skip the ISOs of the flavors that built.

`build_artifacts_s{2,3,4}` in build-variant.yml take
`needs: [generate_matrix, build_stage{2,3,4}]`, and `build_stageN` is a
MATRIX over every flavor in that stage. A matrix job fails if any leg fails,
so one failing desktop skipped every ISO and QCOW2 in its stage -- including
flavors that built perfectly. Same shape as #1729 (stage 2 hard-gated on a
fully-green multi-arch base) one edge further down, and as the stage-4
artifact jail the comment above those jobs already records.

Measured on Build Hummingbird run 32786338463: `gnome / linux-amd64`,
`gnome / Manifest` and `gnome / Sign` all succeeded; `kde` and `niri` failed;
all three `iso:` cells were SKIPPED with their names unexpanded, meaning the
job never reached matrix expansion because the `if` was false.

The obvious relaxation is wrong on its own, and that is the interesting part.
The ISO job builds from a MOVING TAG (`<published_tag>-<safeplatform>`), not
from the digest its image job produced. For a flavor whose image build
FAILED, that tag still resolves to the PREVIOUS image -- so a bare
`!cancelled()` would succeed and emit media that looks fresh and is not.
Silently stale media is worse than no media and worse than a skipped cell.

So the two halves are ONE invariant and are tested as one: an artifact job
may be relaxed off whole-stage success only while it passes its cell's
`image-digest-artifact`, which reusable-build-image.yml uploads only after
`podman push` returns a digest, named with `github.run_id` so it proves THIS
run rather than an earlier one.
"""
from __future__ import annotations

import pathlib
import subprocess

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
VARIANT = ROOT / ".github" / "workflows" / "build-variant.yml"
ARTIFACTS = ROOT / ".github" / "workflows" / "reusable-build-artifacts.yml"
IMAGE = ROOT / ".github" / "workflows" / "reusable-build-image.yml"

ARTIFACT_JOBS = ("build_artifacts_s2", "build_artifacts_s3", "build_artifacts_s4")


def jobs(path: pathlib.Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"]


def test_no_artifact_job_is_gated_on_a_fully_green_stage_matrix() -> None:
    for name in ARTIFACT_JOBS:
        job = jobs(VARIANT)[name]
        stage = name.replace("build_artifacts_s", "build_stage")
        condition = " ".join(str(job.get("if", "")).split())

        assert f"needs.{stage}.result == 'success'" not in condition, (
            f"{name} requires the WHOLE {stage} matrix to be green, so one "
            f"failing desktop skips every ISO in the stage (#2059)"
        )
        # A job whose `if` contains no status function gets success() implied
        # on every need -- which is exactly how s2 acquired this coupling
        # without ever saying so.
        assert "!cancelled()" in condition, (
            f"{name} has no status function in its `if`, so success() is "
            f"implicit on {stage} and the coupling is back, silently"
        )


def test_relaxing_the_gate_is_paired_with_the_provenance_artifact() -> None:
    """The half that stops the relaxation from emitting stale media."""
    for name in ARTIFACT_JOBS:
        supplied = jobs(VARIANT)[name]["with"].get("image-digest-artifact", "")
        assert "github.run_id" in supplied, (
            f"{name} builds ISOs from a moving tag with no proof this run "
            f"published the image; a failed flavor would emit a stale ISO. "
            f"got: {supplied!r}"
        )


def test_the_consumer_asks_for_the_name_the_producer_uploads() -> None:
    """Two templates that must agree, in files that are edited apart.

    A mismatch here fails EVERY ISO cell rather than none, so it is loud --
    but it is loud at the end of a two-hour image build, which is exactly the
    kind of thing worth catching in a second.
    """
    upload = next(
        step for step in jobs(IMAGE)["build_push"]["steps"]
        if step.get("name") == "Upload Output Artifacts"
    )
    produced = upload["with"]["name"]
    # The producer reads its values from env/inputs, the consumer from its
    # own matrix; normalise both to the field ORDER they interpolate.
    produced_fields = ["IMAGE_NAME", "DEFAULT_TAG", "safeplatform", "run_id"]
    for field in produced_fields:
        assert field in produced, f"producer name no longer carries {field}: {produced}"

    consumed = jobs(VARIANT)["build_artifacts_s2"]["with"]["image-digest-artifact"]
    for field in ["matrix.image_name", "matrix.published_tag",
                  "matrix.safeplatform", "github.run_id"]:
        assert field in consumed, f"consumer name no longer carries {field}: {consumed}"

    assert consumed.index("matrix.image_name") < consumed.index("matrix.published_tag") \
        < consumed.index("matrix.safeplatform") < consumed.index("github.run_id"), (
        "consumer interpolates the fields in a different ORDER than the "
        f"producer ({produced}); the names cannot match: {consumed}"
    )


def test_the_producer_only_uploads_after_a_real_push() -> None:
    """Pin the PREMISE that makes the artifact's existence mean anything.

    If the upload ever became unconditional, or moved ahead of the push, the
    gate would still be present and would prove nothing -- the exact shape of
    check this repository keeps re-learning to distrust.
    """
    steps = jobs(IMAGE)["build_push"]["steps"]
    names = [s.get("name") for s in steps]
    push_at = names.index("Create Job Outputs")
    upload_at = names.index("Upload Output Artifacts")
    assert push_at < upload_at

    create = steps[push_at]
    assert "remote_image_digest" in str(create.get("env", {})), (
        "the digest file no longer comes from the push step's digestfile, so "
        "the artifact no longer evidences a successful push"
    )
    assert steps[upload_at]["with"]["if-no-files-found"] == "error", (
        "an empty upload would create the artifact anyway and the gate would "
        "pass for a cell that pushed nothing"
    )


def _run_gate(fetched: str, digest: str | None,
              tmp_path: pathlib.Path) -> tuple[int, str]:
    """Run the gate's OWN shell out of the workflow, against a fixture.

    Asserting on the step's text would pass just as happily with the gate
    unreachable. This executes it.
    """
    step = next(
        s for s in jobs(ARTIFACTS)["iso"]["steps"]
        if str(s.get("name", "")).startswith("Provenance gate")
    )
    script = step["run"]
    cell = tmp_path / "cell-digest"
    cell.mkdir()
    if digest is not None:
        (cell / "img.txt").write_text(digest)
    # The step reads /tmp/cell-digest; point it at the fixture instead.
    script = script.replace("/tmp/cell-digest", str(cell))
    proc = subprocess.run(
        ["bash", "-c", script],
        env={"PATH": "/usr/bin:/bin", "ARTIFACT": "img-gnome-linux-amd64-42",
             "FETCHED": fetched, "VARIANT": "hummingbird", "FLAVOR": "gnome",
             "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md")},
        capture_output=True, text=True,
    )
    return proc.returncode, proc.stdout + proc.stderr


def test_the_gate_refuses_a_cell_that_published_nothing(tmp_path) -> None:
    """A VALID digest file is planted deliberately, and the gate must still
    refuse.

    The obvious fixture -- fetch failed, no file -- proves nothing: `cat` of
    an unmatched glob under `set -e` exits non-zero on its own, so the test
    passes identically with the outcome check deleted. Verified: it did.
    Planting a good digest leaves the fetch OUTCOME as the only thing that
    can fail the step.
    """
    code, output = _run_gate("failure", "sha256:" + "b" * 64 + "\n", tmp_path)
    assert code != 0, (
        "a flavor whose image build failed would build an ISO from the tag "
        "its PREVIOUS run published -- stale media that looks fresh"
    )
    assert "published no image in this run" in output, (
        "the gate stopped the build but not with the sentence that explains "
        f"why; a maintainer reads this one: {output!r}"
    )


def test_the_gate_refuses_when_the_artifact_carries_no_digest_file(tmp_path) -> None:
    code, output = _run_gate("success", None, tmp_path)
    assert code != 0, "the artifact existed but held no digest file at all"
    assert "published no image in this run" in output, (
        "download-artifact can warn-and-succeed on a missing name instead of "
        "failing; that path must reach the same explanation, not `cat: no "
        f"such file`: {output!r}"
    )


def test_the_gate_refuses_an_empty_digest(tmp_path) -> None:
    code, _ = _run_gate("success", "\n", tmp_path)
    assert code != 0, (
        "the artifact existed but recorded no digest, so nothing was pushed"
    )


def test_the_gate_passes_a_cell_this_run_published(tmp_path) -> None:
    code, _ = _run_gate("success", "sha256:" + "a" * 64 + "\n", tmp_path)
    assert code == 0, (
        "the gate rejects a legitimate cell, which would fail every ISO"
    )
