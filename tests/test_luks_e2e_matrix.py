"""Regression tests for the matrix emitted by luks-e2e.yml."""
from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "luks-e2e.yml"


def generator_script() -> str:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return next(
        step["run"]
        for step in workflow["jobs"]["generate-matrix"]["steps"]
        if step.get("id") == "gen"
    )


def install_yq_shim(directory: Path) -> None:
    """The workflow only needs ``yq -o=json . FILE``; provide that in tests."""
    shim = directory / "yq"
    shim.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys, yaml\n"
        "with open(sys.argv[-1], encoding='utf-8') as stream:\n"
        "    print(json.dumps(yaml.safe_load(stream)))\n",
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)


def run_generator(tmp_path: Path, variant: str = "all", flavor: str = "all"):
    install_yq_shim(tmp_path)
    output = tmp_path / "github-output"
    summary = tmp_path / "summary"
    proc = subprocess.run(
        ["bash", "-c", generator_script()],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=dict(
            os.environ,
            PATH=f"{tmp_path}:{os.environ['PATH']}",
            FILTER_VARIANT=variant,
            FILTER_FLAVOR=flavor,
            TPM_DISPATCH="false",
            TPM_SCHEDULE="false",
            GITHUB_OUTPUT=str(output),
            GITHUB_STEP_SUMMARY=str(summary),
        ),
    )
    return proc, output


def matrix_from(output: Path) -> list[dict[str, str]]:
    line = next(
        line for line in output.read_text(encoding="utf-8").splitlines()
        if line.startswith("matrix=")
    )
    return json.loads(line.removeprefix("matrix="))["include"]


def output_values(output: Path) -> dict[str, str]:
    return {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in output.read_text(encoding="utf-8").splitlines()
        if "=" in line
    }


def test_default_matrix_never_schedules_headless_base_derivatives(tmp_path):
    """base-hwe/base-nvidia cannot satisfy this workflow's login gate.

    Run 33506738063 spent two jobs on each applicable variant even though those
    images deliberately have no graphical login target. They are base kernel
    and driver overlays, not desktop cells.
    """
    proc, output = run_generator(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    cells = matrix_from(output)
    flavors = {cell["flavor"] for cell in cells}

    headless = {
        flavor for flavor in flavors
        if flavor == "base" or flavor.startswith("base-")
    }
    assert not headless
    # Control: graphical derivatives remain covered; this is not an accidental
    # return to the five unqualified desktop names only.
    assert "gnome-hwe" in flavors
    assert "gnome-nvidia" in flavors


def test_headless_base_dispatch_fails_before_runner_fanout(tmp_path):
    proc, _ = run_generator(tmp_path, variant="yellowfin", flavor="base-hwe")
    assert proc.returncode != 0
    assert "No matching variant/flavor cells" in proc.stdout + proc.stderr


def test_timelapse_outputs_cover_plain_desktops_only(tmp_path):
    proc, output = run_generator(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    values = output_values(output)
    desktops = set(json.loads(values["base_desktops"]))
    assert {"gnome", "kde", "cosmic", "niri", "xfce", "pantheon"} <= desktops
    assert not any(
        desktop.endswith(("-hwe", "-nvidia", "-asahi", "-t2", "-zfs", "-cachyos"))
        for desktop in desktops
    )

    cells = json.loads(values["base_cells"])
    assert cells
    assert all(
        not cell.endswith(
            ("-hwe", "-nvidia", "-asahi", "-t2", "-zfs", "-cachyos")
        )
        for cell in cells
    )


def test_timelapse_publication_is_only_enabled_for_the_full_matrix(tmp_path):
    proc, output = run_generator(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert output_values(output)["publish_latest"] == "true"

    filtered = tmp_path / "filtered"
    filtered.mkdir()
    proc, output = run_generator(filtered, variant="yellowfin")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert output_values(output)["publish_latest"] == "false"
