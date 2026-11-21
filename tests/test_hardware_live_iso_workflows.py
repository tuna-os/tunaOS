"""Workflows route hardware-profile live ISOs the way build-iso-tacklebox.sh does.

bonito gnome-x13s is arm64-only and its live ISO comes from
`tacklebox build --x13s-live` (scripts/lib/hardware-live.sh). Two workflow
paths would otherwise treat it as a generic ISO:

- publish-isos.yml builds every build_iso flavor on linux/amd64, where the
  X13s route does not exist, so its emergency dispatch would fail on the
  X13s cell.
- the ISO boot gate in reusable-build-artifacts.yml waits for the live
  desktop marker, which X13s media never prints in QEMU: the ADSP barrier
  stops the boot first, by design.

Falsification: drop the platform filter from publish-isos.yml, or stop
exporting LIVE_MARKER from the route in the boot gate, and a test fails.
"""
from __future__ import annotations

import json
import pathlib
import subprocess

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
PUBLISH = ROOT / ".github" / "workflows" / "publish-isos.yml"
ARTIFACTS = ROOT / ".github" / "workflows" / "reusable-build-artifacts.yml"


def _step(path: pathlib.Path, name: str) -> dict:
    workflow = yaml.safe_load(path.read_text())
    return next(step for job in workflow["jobs"].values() for step in job.get("steps", []) if step.get("name") == name)


def _publish_matrix_program() -> str:
    run = _step(PUBLISH, "Build matrix from build-config.yml")["run"]
    start = run.index("'. as $root")
    end = run.index("}' \"$CONFIG_JSON\"", start)
    return run[start + 1 : end + 1]


def test_publish_isos_skips_flavors_without_an_amd64_build(tmp_path):
    config = {
        "config": {"global_platforms": ["linux/amd64", "linux/arm64"]},
        "variants": [
            {
                "id": "bonito",
                "flavors": [
                    {"id": "gnome", "build_iso": True},
                    {"id": "gnome-x13s", "build_iso": True, "platforms": ["linux/arm64"]},
                    {"id": "kde", "build_iso": False},
                ],
            }
        ],
    }
    path = tmp_path / "build-config.json"
    path.write_text(json.dumps(config))
    out = subprocess.run(
        ["jq", "-c", "--arg", "v", "all", "--arg", "f", "all", _publish_matrix_program(), str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    cells = [(c["variant"], c["flavor"], c["platform"]) for c in json.loads(out)["include"]]
    assert cells == [("bonito", "gnome", "linux/amd64")]


def test_boot_gate_takes_its_marker_from_the_live_route():
    step = _step(ARTIFACTS, "Boot gate: verify ISO readiness")
    assert step["env"]["PLATFORM"] == "${{ inputs.platform }}"
    run = step["run"]
    route = run.index('ROUTE="$(tunaos_live_iso_route "$(tunaos_flavor_hardware "$VARIANT" "$FLAVOR")" "$PLATFORM")"')
    marker = run.index('LIVE_MARKER="$(tunaos_live_iso_boot_marker "$ROUTE")"')
    export = run.index("export LIVE_MARKER")
    gate = run.index("./scripts/iso-e2e.sh")
    assert route < marker < export < gate
    assert "sudo --preserve-env" in run
