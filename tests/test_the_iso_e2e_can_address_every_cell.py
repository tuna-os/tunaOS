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


def preflight_script() -> str:
    steps = workflow()["jobs"]["e2e"]["steps"]
    body = next(s["run"] for s in steps if s.get("id") == "filter")
    assert "NEEDS_R2" in body, body
    return body


def run_preflight(tmp_path: Path, needs_r2: str, creds: bool) -> dict:
    """Run the real preflight body and return what it wrote to GITHUB_OUTPUT."""
    out = tmp_path / "gh_output"
    out.write_text("", encoding="utf-8")
    script = tmp_path / "filter.sh"
    script.write_text(preflight_script(), encoding="utf-8")
    env = dict(os.environ, NEEDS_R2=needs_r2, GITHUB_OUTPUT=str(out))
    for name in ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
                 "R2_ENDPOINT", "R2_BUCKET"):
        env[name] = "set" if creds else ""
    proc = subprocess.run(["bash", str(script)], capture_output=True,
                          text=True, env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return dict(
        l.split("=", 1) for l in out.read_text(encoding="utf-8").splitlines() if "=" in l
    )


def test_a_dispatched_cell_is_not_skipped():
    """The bug this replaces, asserted by RUNNING the filter.

    The dispatch filter compared `inputs.variant` against `matrix.variant`
    back when the matrix was two hardcoded cells. Once the matrix was
    generated from those same inputs the comparison was redundant, and
    blanking its inputs rather than deleting it made `"" != "marlin"` true —
    so it set skip=true on EVERY dispatched cell. Every later step was
    skipped and the job reported SUCCESS. Run 32791464847 swept six cells
    that way and came back green in twenty seconds having booted nothing.

    The previous guard asserted the OLD wiring string was absent from the
    file. That is the shape of the old symptom, not the property that
    matters, and it passed while the workflow skipped everything.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        # source=build: NEEDS_R2 is false, and no cell may be skipped.
        got = run_preflight(Path(td), needs_r2="false", creds=False)
    assert got.get("skip") != "true", got


def test_the_r2_credential_guard_survived():
    """The half that must NOT be deleted: fork PRs get no secrets, and
    without this they burn ~3.5 minutes on a bogus S3 endpoint (#1129)."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        got = run_preflight(Path(td), needs_r2="true", creds=False)
    assert got.get("skip") == "true", got
    assert got.get("no_r2_credentials") == "true", got

    with tempfile.TemporaryDirectory() as td:
        ok = run_preflight(Path(td), needs_r2="true", creds=True)
    assert ok.get("skip") != "true", ok


def test_nothing_compares_dispatch_inputs_to_a_matrix_cell_any_more():
    """Belt and braces: the comparison itself must be gone from the job,
    not merely neutralised, since neutralising it is what broke the sweep."""
    steps = workflow()["jobs"]["e2e"]["steps"]
    blob = yaml.dump(steps)
    assert "DISPATCH_FLAVOR:" not in blob, blob[:400]
    assert "matrix.variant }}\" ]]" not in blob


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
    """Adding a second source must not weaken the first.

    The message moved when the lookup learned the grouped naming scheme;
    what must not move is that a missing published ISO is still a hard
    failure rather than a silently skipped cell.
    """
    body = WORKFLOW.read_text(encoding="utf-8")
    assert "::error::No ISO in R2 under either name" in body


# ── Two naming schemes in one bucket ─────────────────────────────────────
# The legacy per-flavor pipeline wrote `<variant>-<flavor>-latest.iso`; the
# grouped dedup pipeline that replaced it writes `<basename>-latest.iso`,
# where basename is the VARIANT ALONE for the gnome group. Measured against
# the live bucket on 2026-08-24:
#
#     albacore-gnome-latest.iso   200   (legacy)
#     albacore-kde-latest.iso     200   (legacy; grouped agrees by accident)
#     albacore-latest.iso         404   (grouped gnome — never published)
#     yellowfin-latest.iso        404
#
# So publishing the grouped ISOs would NOT have turned E2E yellowfin:gnome
# green on its own: the object lands under a key nothing looks up.

def download_step() -> dict:
    steps = workflow()["jobs"]["e2e"]["steps"]
    step = next(s for s in steps if "rclone copy" in str(s.get("run", "")))
    assert "live-isos" in step["run"], step["run"][:200]
    return step


def test_the_lookup_tries_both_naming_schemes():
    run = download_step()["run"]
    assert '${VARIANT}-${FLAVOR}-latest.iso' in run, run[-800:]
    assert '${VARIANT}-latest.iso' in run, run[-800:]
    assert '${VARIANT}-${DESKTOP}-latest.iso' in run, run[-800:]


def test_gnome_maps_to_the_bare_variant_name():
    """The whole asymmetry. Every other desktop keeps its suffix; gnome's
    grouped ISO is `<variant>-latest.iso` with no desktop in the name."""
    run = download_step()["run"]
    assert 'DESKTOP="${FLAVOR%%-*}"' in run, run[-800:]
    gnome_branch = run[run.index('if [[ "$DESKTOP" == "gnome" ]]'):]
    head = gnome_branch[:gnome_branch.index("else")]
    assert '${VARIANT}-latest.iso' in head, head
    assert "${DESKTOP}" not in head, head


def test_a_flavor_variant_resolves_to_its_group():
    """gnome-hwe and kde-nvidia ride inside their group's offline store, so
    they must resolve to that group's ISO rather than to a per-flavor image
    that the grouped pipeline never publishes."""
    run = download_step()["run"]
    # `%%-*` strips at the FIRST hyphen: gnome-nvidia-hwe -> gnome.
    assert "%%-*" in run, run[-800:]


def test_it_still_fails_loudly_when_neither_name_exists():
    """Two chances to find it is not a licence to boot nothing."""
    run = download_step()["run"]
    assert "::error::No ISO in R2 under either name" in run, run[-800:]
    assert "exit 1" in run
    # And it must name BOTH keys it tried, or the next reader cannot tell
    # which pipeline was supposed to have produced the ISO.
    err = run[run.index("::error::No ISO in R2"):]
    assert "${OBJECT}" in err and "${GROUP_OBJECT}" in err, err[:300]


def test_the_rclone_failure_does_not_abort_before_the_fallback():
    """`set -euo pipefail` plus a failing rclone would kill the step before
    the second candidate was ever tried — the fallback would be dead code."""
    run = download_step()["run"]
    copy_lines = [l for l in run.splitlines() if "rclone copy" in l]
    assert copy_lines, run[-800:]
    idx = run.index("for candidate in")
    assert "|| true" in run[idx:], run[idx:idx + 600]
