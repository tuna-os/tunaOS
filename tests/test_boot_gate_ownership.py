"""The Gate job's evidence must be readable before anything reads it.

scripts/iso-e2e.sh runs under sudo, so verify-out and everything in it comes
back root-owned. Every later step in the Gate job runs as the runner user.

That ownership gap is not a cosmetic problem. GitHub evaluates a step's `if:`
expression as the runner user, and hashFiles() on a file it cannot read does
not return an empty string -- it raises, and a raise inside a template
expression fails the whole job:

    The template is not valid. System.InvalidOperationException:
    hashFiles('verify-out/serial.log') failed. Fail to hash files under
    directory '/home/runner/work/tunaOS/tunaOS'

Gate is a `needs:` of Promote, so that error stopped images whose serial log
said "Desktop experience contract passed" from ever getting their bare tags --
it took marlin and flounder to 0 green cells while their builds were fine.

These tests pin the two properties that keep it fixed: the chown happens
before anything reads verify-out, and no `if:` in the Gate job hashes a path
that sudo wrote.
"""

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/reusable-build-image.yml"
GATE_JOB = "verify_boot"
EVIDENCE_DIR = "verify-out"


@pytest.fixture(scope="module")
def gate_steps():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    return workflow["jobs"][GATE_JOB]["steps"]


def _index_of(steps, predicate):
    return next((i for i, step in enumerate(steps) if predicate(step)), None)


def _chowns_evidence(step):
    run = step.get("run", "")
    return "chown" in run and EVIDENCE_DIR in run


def test_the_gate_job_still_exists(gate_steps):
    assert gate_steps, f"{GATE_JOB} has no steps; the rest of this file is vacuous"


def test_something_chowns_the_evidence_directory(gate_steps):
    assert _index_of(gate_steps, _chowns_evidence) is not None, (
        f"no step in {GATE_JOB} hands {EVIDENCE_DIR} back to the runner user; "
        "iso-e2e.sh runs under sudo, so it is root-owned"
    )


def test_the_chown_precedes_every_step_that_reads_the_evidence(gate_steps):
    first_chown = _index_of(gate_steps, _chowns_evidence)
    assert first_chown is not None

    for i, step in enumerate(gate_steps[:first_chown]):
        # The step that produces the evidence runs under sudo itself, so it is
        # allowed to touch verify-out before the chown. Nothing else is.
        run = step.get("run", "")
        produces = "iso-e2e.sh" in run
        if produces:
            continue
        assert EVIDENCE_DIR not in run, (
            f"step {i} ({step.get('name')!r}) reads {EVIDENCE_DIR} in its run: "
            f"block before the chown at step {first_chown}; it will hit "
            "permission errors on root-owned files"
        )
        assert EVIDENCE_DIR not in str(step.get("if", "")), (
            f"step {i} ({step.get('name')!r}) references {EVIDENCE_DIR} in its "
            f"if: expression before the chown at step {first_chown}"
        )


def test_no_gate_condition_hashes_a_sudo_written_path(gate_steps):
    for step in gate_steps:
        condition = str(step.get("if", ""))
        if "hashFiles(" not in condition:
            continue
        assert EVIDENCE_DIR not in condition, (
            f"step {step.get('name')!r} gates on hashFiles() over "
            f"{EVIDENCE_DIR}. hashFiles raises rather than returning '' when a "
            "file is unreadable, and a raise in an if: expression fails the "
            "whole Gate job -- which blocks Promote for an image that booted "
            "fine. Gate on a step output instead."
        )


def test_the_tier_one_check_gates_on_a_step_output(gate_steps):
    tier1 = _index_of(gate_steps, lambda s: "tier-1" in str(s.get("name", "")).lower())
    assert tier1 is not None, "the tier-1 functional checks step disappeared"

    condition = str(gate_steps[tier1].get("if", ""))
    assert "steps." in condition and ".outputs." in condition, (
        "the tier-1 step must gate on a step output, not on the filesystem: "
        f"if: {condition!r}"
    )

    # The output it reads has to be published by an earlier step, or the
    # condition is permanently false and the check silently never runs.
    referenced = {
        part.split(".")[1]
        for part in condition.replace("(", " ").replace(")", " ").split()
        if part.startswith("steps.") and len(part.split(".")) > 1
    }
    earlier_ids = {s.get("id") for s in gate_steps[:tier1] if s.get("id")}
    missing = referenced - earlier_ids
    assert not missing, (
        f"tier-1 gates on output of {sorted(missing)}, which no earlier step "
        f"in {GATE_JOB} defines (earlier ids: {sorted(earlier_ids)})"
    )


def test_the_publisher_of_that_output_is_the_step_that_chowns(gate_steps):
    tier1 = _index_of(gate_steps, lambda s: "tier-1" in str(s.get("name", "")).lower())
    condition = str(gate_steps[tier1].get("if", ""))
    referenced = {
        part.split(".")[1]
        for part in condition.replace("(", " ").replace(")", " ").split()
        if part.startswith("steps.") and len(part.split(".")) > 1
    }
    publishers = [s for s in gate_steps[:tier1] if s.get("id") in referenced]
    assert publishers, "no earlier step publishes the gating output"

    # Reading the file and fixing its ownership have to be the same step: if
    # the readability probe runs before the chown it reports false, and the
    # tier-1 check is skipped on a perfectly good serial log.
    assert any(_chowns_evidence(s) for s in publishers), (
        "the step publishing the tier-1 gating output must also be the step "
        "that chowns the evidence, so the probe sees post-chown ownership"
    )


def test_the_gate_still_blocks_promotion(gate_steps):
    # If this ever stops being true the bug above is harmless -- and so is the
    # gate. Keep the coupling visible.
    workflow = yaml.safe_load(WORKFLOW.read_text())
    promote = workflow["jobs"]["tag-image"]
    assert GATE_JOB in promote["needs"]
    assert f"needs.{GATE_JOB}.result == 'success'" in promote["if"]
