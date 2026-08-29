"""The smoke ISO build must not ask for GPU capacity it never uses.

#1929 split this workflow in two: `build-iso` builds and uploads the ISO,
`smoke` downloads it, boots it and asserts. The DRM render node the
compositor checks need belongs to the second half -- which runs on
ubuntu-latest and drives scripts/iso-e2e.sh, not iso-e2e-gpu.sh.

The `gpu` routing for cosmic/niri/xfwl4/kde survived that split as a no-op
that still provisions a g4dn spot instance per cell. That is not free: g4dn
capacity is quota-limited (the on-demand increase was declined on
2026-08-21), so a no-op GPU request is the difference between those four
flavors being testable and not.

These tests pin both halves of the claim -- that the build asks for no GPU,
and that it is entitled to ask for none.
"""
from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "installer-smoke.yml"


def jobs():
    doc = yaml.safe_load(WORKFLOW.read_text())
    return doc["jobs"]


def test_no_cell_is_routed_to_the_gpu_group() -> None:
    """The regression: four flavors provisioning a g4dn to run podman."""
    body = WORKFLOW.read_text()
    assert '"gpu"' not in body, (
        "the smoke ISO build routes a cell to the gpu group; it builds an "
        "image and uploads it, and touches no DRM device"
    )


def test_the_build_job_touches_no_drm_device() -> None:
    """What entitles the build to run without a render node."""
    build = jobs()["build-iso"]
    steps = yaml.dump(build["steps"])
    for token in ("/dev/dri", "renderD", "iso-e2e-gpu"):
        assert token not in steps, f"build-iso references {token}"


def test_the_boot_half_runs_where_the_render_node_question_lives() -> None:
    """The split is the whole argument, so pin it.

    If `smoke` ever moves back onto RunsOn, the reasoning above stops
    holding and this file should be revisited rather than quietly passing.
    """
    assert jobs()["smoke"]["runs-on"] == "ubuntu-latest"


def test_the_boot_half_uses_the_non_gpu_harness() -> None:
    steps = yaml.dump(jobs()["smoke"]["steps"])
    assert "iso-e2e.sh" in steps
    assert "iso-e2e-gpu.sh" not in steps


def _matrix_script() -> str:
    """The generate-matrix job's shell, where runner names are minted.

    Scoped to that job rather than the whole file. The previous version
    scanned every line of the workflow for "runner: " and therefore read
    COMMENTS too -- adding a comment containing the words `build_runner:
    github` invented a runner called "github` sends this job to" and failed
    the build. A check that reads prose is measuring the wrong surface; the
    matrix is built in exactly one place and that is the place to look.
    """
    gen = jobs()["generate-matrix"]
    script = "\n".join(step.get("run", "") for step in gen["steps"])
    assert "include" in script, (
        "the generate-matrix script no longer builds a matrix include list; "
        "every assertion below would pass vacuously"
    )
    return script


def _declared_runners() -> set[str]:
    return {
        line.split("runner: ")[1].split("}")[0].strip().strip('"').strip("'")
        for line in _matrix_script().splitlines()
        if "runner: " in line and "matrix.runner" not in line
    }


def test_every_flavor_builds_on_the_same_runner() -> None:
    """A per-flavor runner split is what drifted last time."""
    runners = _declared_runners()
    assert runners, "no runner assignment found in the matrix script"
    assert runners == {"build-amd64"}, f"mixed build runners: {runners}"


def test_a_comment_cannot_invent_a_runner() -> None:
    """Regression for the scan itself.

    The workflow gained a comment reading

        # `build_runner: github` sends this job to ubuntu-latest instead

    and the old whole-file scan turned that prose into a runner name. The
    scan must see the matrix script and nothing else, so a comment that
    mentions a runner anywhere else in the file is inert.
    """
    body = WORKFLOW.read_text(encoding="utf-8")
    prose = [
        line for line in body.splitlines()
        if "runner: " in line and line.lstrip().startswith("#")
    ]
    assert prose, (
        "no commented 'runner: ' line left in the workflow -- this test can "
        "no longer demonstrate that comments are excluded; point it at a "
        "line that still exists rather than deleting it"
    )
    assert _declared_runners() == {"build-amd64"}
