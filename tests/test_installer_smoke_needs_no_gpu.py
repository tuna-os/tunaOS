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


def test_every_flavor_builds_on_the_same_runner() -> None:
    """A per-flavor runner split is what drifted last time."""
    body = WORKFLOW.read_text()
    runners = {
        line.split('runner: ')[1].split('}')[0].strip().strip('"').strip("'")
        for line in body.splitlines()
        if "runner: " in line and "matrix.runner" not in line
    }
    assert runners == {"build-amd64"}, f"mixed build runners: {runners}"
