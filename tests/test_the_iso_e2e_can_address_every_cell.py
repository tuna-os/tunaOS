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
def test_no_dispatch_runs_one_small_fixed_cell_list(tmp_path):
    """The pull_request and schedule triggers pass no inputs.

    Two properties, and the second is why this test changed. Widening the
    dispatch inputs must not turn the harness smoke test into a fifty-cell
    sweep -- so the list stays small and fixed. And with no inputs there is
    no `source`, so the ISO must come from R2, which means every cell here
    must be one R2 actually holds.

    It used to be yellowfin:gnome + albacore:gnome. Measured against the
    live bucket on 2026-08-25, albacore-gnome-latest.iso is 200 and
    yellowfin-gnome-latest.iso is 404 (#2027), so that cell could only ever
    fail -- on every PR that touched this workflow, for a publishing gap
    rather than a harness regression.
    """
    m = run_generator("", "", tmp_path)
    assert m["include"] == [{"variant": "albacore", "flavor": "gnome"}], m
    assert len(m["include"]) <= 2, "the no-input default must stay a smoke test"


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


def test_nothing_compares_dispatch_inputs_to_a_matrix_cell_any_more():
    """Belt and braces: the comparison itself must be gone from the job,
    not merely neutralised, since neutralising it is what broke the sweep."""
    steps = workflow()["jobs"]["e2e"]["steps"]
    blob = yaml.dump(steps)
    assert "DISPATCH_FLAVOR:" not in blob, blob[:400]
    assert "matrix.variant }}\" ]]" not in blob


def test_the_build_source_never_touches_r2():
    """The whole point. If the build path read or wrote R2 it would cost
    exactly what it was added to avoid."""
    steps = workflow()["jobs"]["e2e"]["steps"]
    build = next(s for s in steps
                 if s.get("name") == "Build the ISO on this runner")
    blob = yaml.dump(build)
    for token in ("rclone", "R2_BUCKET", "RCLONE_CONFIG", "upload-artifact"):
        assert token not in blob, f"the build path references {token}"


def test_the_build_step_is_not_gated_on_a_source_input():
    """No ISO is published, so the build is the only source on every trigger:
    pull_request and schedule build the fixed cell, a dispatch builds what it
    names. A `source` input or an `if:` on the build step would bring back a
    path that finds nothing to boot."""
    assert "source" not in workflow()[True]["workflow_dispatch"]["inputs"]
    steps = workflow()["jobs"]["e2e"]["steps"]
    build = next(s for s in steps
                 if s.get("name") == "Build the ISO on this runner")
    assert "if" not in build, build["if"]

def test_the_build_step_fails_when_it_produces_no_iso():
    """A build that silently produced nothing would hand the boot step an
    empty ISO_PATH and fail somewhere far away from the cause."""
    steps = workflow()["jobs"]["e2e"]["steps"]
    build = next(s for s in steps
                 if s.get("name") == "Build the ISO on this runner")
    assert "build produced no ISO" in build["run"], build["run"][-400:]
    assert "exit 1" in build["run"]


def test_grouped_iso_identity_reaches_the_e2e_harness_through_sudo(tmp_path):
    """Snapshot filenames omit the desktop, so the harness needs matrix identity."""
    steps = workflow()["jobs"]["e2e"]["steps"]
    body = next(step["run"] for step in steps if step.get("name") == "Run readiness e2e")

    fake_bin = tmp_path / "bin"
    scripts = tmp_path / "scripts"
    fake_bin.mkdir()
    scripts.mkdir()
    capture = tmp_path / "identity"
    sudo = fake_bin / "sudo"
    sudo.write_text(
        "#!/usr/bin/env bash\n"
        "variant=${VARIANT-}; flavor=${FLAVOR-}; kvm=${KVM_FLAG-}\n"
        "preserve=\n"
        "if [[ ${1-} == --preserve-env=* ]]; then preserve=${1#*=}; shift; fi\n"
        "[[ ${1-} == chown ]] && exit 0\n"
        "unset VARIANT FLAVOR KVM_FLAG\n"
        "[[ ,$preserve, == *,VARIANT,* ]] && export VARIANT=$variant\n"
        "[[ ,$preserve, == *,FLAVOR,* ]] && export FLAVOR=$flavor\n"
        "[[ ,$preserve, == *,KVM_FLAG,* ]] && export KVM_FLAG=$kvm\n"
        'exec "$@"\n',
        encoding="utf-8",
    )
    sudo.chmod(0o755)
    harness = scripts / "iso-e2e.sh"
    harness.write_text(
        f"#!/usr/bin/env bash\nprintf '%s:%s:%s\\n' "
        f'"${{VARIANT-unset}}" "${{FLAVOR-unset}}" "${{KVM_FLAG-unset}}" >"{capture}"\n',
        encoding="utf-8",
    )
    harness.chmod(0o755)
    github_output = tmp_path / "github-output"
    proc = subprocess.run(
        ["/bin/bash", "-eu", "-o", "pipefail", "-c", body],
        cwd=tmp_path,
        env=os.environ | {
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "ISO_PATH": str(tmp_path / "yellowfin-snapshot-run-1.iso"),
            "VARIANT": "yellowfin",
            "FLAVOR": "gnome",
            "GITHUB_OUTPUT": str(github_output),
            "USER": os.environ.get("USER", "runner"),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert capture.read_text().split(":", 2)[:2] == ["yellowfin", "gnome"]


