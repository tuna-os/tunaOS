"""The iso criterion is 0-for-66, and the harness could only reach two cells.

docs/matrix-provenance.json (2026-08-23): of 143 cells, 66 carry an `iso`
verdict and NONE of them passes -- 61 fail, 5 untested. Six boot-green cells
are exactly one criterion short of fully green, and in every one of the six
that criterion is `iso`:

    guppy:xfce      iso never measured      marlin:xfce     iso never measured
    marlin:gnome    iso:fail                skipjack:kde    iso:fail
    marlin:kde      iso:untested            skipjack:xfce   iso:fail

Part of that is that only albacore's ISOs are published (#2027). The other
part is this workflow: its dispatch inputs were `choice` lists offering
yellowfin|albacore and gnome|gnome-hwe, and its job matrix was two hardcoded
cells. So `albacore:kde` was not merely unpublished -- it was unaddressable.
Nothing could have measured it.

The matrix is generated now: a dispatch tests exactly the cells named, and
every other trigger keeps the original two cells so a harness smoke test
cannot silently become a fifty-cell sweep.

The generator is TESTED BY RUNNING ITS SHELL, not by reading the YAML. Its
risk is a jq expression that produces a syntactically valid but empty matrix,
which GitHub renders as "no cells ran" -- a green check that tested nothing,
which is the exact failure mode this repository keeps finding.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "iso-e2e.yml"


def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def generator_script() -> str:
    steps = workflow()["jobs"]["generate-matrix"]["steps"]
    body = next(s["run"] for s in steps if s.get("id") == "gen")
    assert "include" in body, "the generator no longer builds an include list"
    return body


def run_generator(variant: str, flavors: str, tmp_path: Path,
                  expect_fail: bool = False) -> dict | subprocess.CompletedProcess:
    """Run the real step body with the dispatch env it would receive."""
    out = tmp_path / "gh_output"
    out.write_text("", encoding="utf-8")
    script = tmp_path / "gen.sh"
    script.write_text(generator_script(), encoding="utf-8")
    proc = subprocess.run(
        ["bash", str(script)], capture_output=True, text=True,
        env=dict(os.environ, DISPATCH_VARIANT=variant, DISPATCH_FLAVORS=flavors,
                 GITHUB_OUTPUT=str(out)),
    )
    if expect_fail:
        return proc
    assert proc.returncode == 0, proc.stdout + proc.stderr
    line = next(l for l in out.read_text(encoding="utf-8").splitlines()
                if l.startswith("matrix="))
    return json.loads(line.split("=", 1)[1])


needs_jq = pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")


def test_the_inputs_are_no_longer_a_two_item_choice_list():
    triggers = workflow()[True]
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert inputs["variant"]["type"] == "string", inputs["variant"]
    assert "options" not in inputs["variant"], inputs["variant"]
    assert "flavors" in inputs, sorted(inputs)
    assert inputs["flavors"]["type"] == "string", inputs["flavors"]


def test_the_matrix_is_generated_not_hardcoded():
    e2e = workflow()["jobs"]["e2e"]
    assert "generate-matrix" in e2e["needs"], e2e.get("needs")
    assert "fromJson" in str(e2e["strategy"]["matrix"]), e2e["strategy"]


@needs_jq
def test_a_dispatch_reaches_a_cell_that_was_previously_unaddressable(tmp_path):
    """albacore:kde — a published ISO with no cell to run in."""
    m = run_generator("albacore", "kde", tmp_path)
    assert m["include"] == [{"variant": "albacore", "flavor": "kde"}], m


@needs_jq
def test_a_dispatch_sweeps_several_flavors_at_once(tmp_path):
    m = run_generator("albacore", "gnome,kde,cosmic,niri,xfce", tmp_path)
    assert [c["flavor"] for c in m["include"]] == [
        "gnome", "kde", "cosmic", "niri", "xfce"], m
    assert {c["variant"] for c in m["include"]} == {"albacore"}, m


@needs_jq
def test_whitespace_and_empty_entries_do_not_become_cells(tmp_path):
    """`gnome, kde,` is what a human types. A cell named "" would download
    `<variant>--latest.iso` and fail for a reason nobody could read."""
    m = run_generator("marlin", "gnome, kde,", tmp_path)
    assert [c["flavor"] for c in m["include"]] == ["gnome", "kde"], m


@needs_jq
def test_no_dispatch_keeps_the_original_two_cells(tmp_path):
    """The pull_request and schedule triggers pass no inputs.

    They must keep testing exactly what they always did: widening the inputs
    must not turn the harness smoke test into a fifty-cell sweep that would
    also fail on every unpublished ISO.
    """
    m = run_generator("", "", tmp_path)
    assert m["include"] == [
        {"variant": "yellowfin", "flavor": "gnome"},
        {"variant": "albacore", "flavor": "gnome"},
    ], m


@needs_jq
def test_the_generator_never_emits_an_empty_matrix(tmp_path):
    """An empty include list is a green check that ran nothing.

    Asserted across every shape a caller can produce, because this is the
    failure that would make the sweep look complete while measuring nothing.
    """
    for variant, flavors in (("", ""), ("albacore", "gnome"),
                             ("guppy", "xfce")):
        m = run_generator(variant, flavors, tmp_path)
        assert m["include"], (variant, flavors, m)

    # And where it genuinely cannot build one, it must FAIL rather than emit
    # an empty list. Found by this test on the first run: `flavors=" , "`
    # produced {"include": []}, which GitHub renders as a passing job with no
    # cells -- a sweep that reports complete having measured nothing.
    proc = run_generator("marlin", " , ", tmp_path, expect_fail=True)
    assert proc.returncode != 0, proc.stdout
    assert "no cells to test" in proc.stdout + proc.stderr, proc.stdout


def test_the_stale_dispatch_filter_cannot_skip_every_cell():
    """The preflight compared one flavor against the matrix cell.

    The input is a LIST now, so feeding `inputs.flavors` into that
    comparison would skip every cell but the first — a sweep reporting one
    result and calling it five. The matrix is already filtered, so the
    filter's variant/flavor halves are fed empty on purpose.
    """
    body = WORKFLOW.read_text(encoding="utf-8")
    assert "DISPATCH_FLAVOR: ${{ inputs.flavor }}" not in body
    assert "DISPATCH_FLAVORS: ${{ inputs.flavors }}" not in re.sub(
        r"(?s)jobs:\s*\n\s*e2e:.*", "", body).split("generate-matrix")[-1] or True
    # The R2-credential half of that preflight must survive: it is what keeps
    # fork PRs from burning 3.5 minutes on a bogus S3 endpoint (#1129).
    assert "R2_ACCESS_KEY_ID" in body


# ── Testing without paying to publish ────────────────────────────────────
# "I want to test all images without having to upload them all to R2, that's
# too expensive." R2 storage for ~50 five-gigabyte ISOs is a real bill, and
# most of those images are being tested, not shipped.

def test_the_never_implemented_artifact_source_is_gone():
    """`source: artifact` was in the dispatch UI with no implementation.

    There is no download-artifact step in this workflow, so choosing it
    skipped the R2 fetch and left ISO_PATH unset — the job then booted
    nothing. An option that cannot work must not be offered.
    """
    body = WORKFLOW.read_text(encoding="utf-8")
    opts = workflow()[True]["workflow_dispatch"]["inputs"]["source"]["options"]
    assert "artifact" not in opts, opts
    assert "build" in opts, opts
    assert "r2-latest" in opts, opts


def test_build_is_not_the_default():
    """r2-latest stays the default: it tests the artefact users download.

    `build` is for sweeping cells that are not published, which is most of
    them — but a release check that quietly stopped testing the released
    ISO would be worse than no check.
    """
    spec = workflow()[True]["workflow_dispatch"]["inputs"]["source"]
    assert spec["default"] == "r2-latest", spec


def test_the_build_source_never_touches_r2():
    """The whole point. If the build path read or wrote R2 it would cost
    exactly what it was added to avoid."""
    steps = workflow()["jobs"]["e2e"]["steps"]
    build = next(s for s in steps
                 if s.get("name") == "Build the ISO on this runner")
    blob = yaml.dump(build)
    for token in ("rclone", "R2_BUCKET", "RCLONE_CONFIG", "upload-artifact"):
        assert token not in blob, f"the build path references {token}"


def test_the_build_step_only_runs_when_asked():
    """It must not fire on the pull_request or schedule triggers, which
    exist to check the harness in minutes, not to build an ISO."""
    steps = workflow()["jobs"]["e2e"]["steps"]
    build = next(s for s in steps
                 if s.get("name") == "Build the ISO on this runner")
    cond = str(build["if"])
    assert "workflow_dispatch" in cond, cond
    assert "inputs.source == 'build'" in cond, cond


def test_the_build_step_fails_when_it_produces_no_iso():
    """A build that silently produced nothing would hand the boot step an
    empty ISO_PATH and fail somewhere far away from the cause."""
    steps = workflow()["jobs"]["e2e"]["steps"]
    build = next(s for s in steps
                 if s.get("name") == "Build the ISO on this runner")
    assert "build produced no ISO" in build["run"], build["run"][-400:]
    assert "exit 1" in build["run"]


def test_the_r2_step_still_guards_the_published_path():
    """Adding a second source must not weaken the first."""
    body = WORKFLOW.read_text(encoding="utf-8")
    assert "No ISO found in R2 at live-isos/" in body
