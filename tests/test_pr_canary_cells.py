"""TUNA-2: four desktop canary cells build and pass the desktop contract on image-input PRs."""
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/tuna-pr-images.yml"
DETECTOR = ROOT / ".github/scripts/canary-cell-inputs.sh"


def workflow():
    return yaml.safe_load(WORKFLOW.read_text())


def canary_job():
    return workflow()["jobs"]["canary_cells"]


def workflow_cells():
    return [f"{c['variant']}:{c['flavor']}" for c in canary_job()["strategy"]["matrix"]["include"]]


def justfile_cells():
    text = (ROOT / "just/utilities.just").read_text()
    match = re.search(r"^test-canary-cells:.*?for cell in ([^;]+);", text, re.S | re.M)
    assert match, "test-canary-cells no longer loops over a literal cell list"
    return match.group(1).split()


def matches(*paths):
    result = subprocess.run(
        ["bash", str(DETECTOR)], input="".join(p + "\n" for p in paths), text=True, capture_output=True
    )
    return result.returncode == 0


def test_the_pr_cells_are_the_published_canary_cells():
    assert workflow_cells() == justfile_cells() == [
        "albacore:gnome", "bonito:kde", "marlin:cosmic", "flounder:xfce",
    ]


def test_every_canary_cell_is_a_built_amd64_cell_published_under_its_own_name():
    config = yaml.safe_load((ROOT / ".github/build-config.yml").read_text())
    variants = {v["id"]: v for v in config["variants"]}
    for cell in workflow_cells():
        variant_id, flavor_id = cell.split(":")
        variant = variants[variant_id]
        flavor = next((f for f in variant["flavors"] if f["id"] == flavor_id), None)
        assert flavor is not None, f"{cell} is not a cell in build-config"
        assert flavor.get("build_image"), f"{cell} is not built"
        assert "linux/amd64" in (flavor.get("platforms") or variant["platforms"]), cell
        # image-name and default-tag are passed as the bare variant and flavor.
        assert variant.get("publish_name", variant_id) == variant_id, cell
        assert not variant.get("tag_suffix"), cell


def test_the_canary_runs_on_pull_requests_only_and_never_publishes():
    doc = workflow()
    assert set(doc.get("on", doc.get(True))) == {"pull_request"}
    detector = doc["jobs"]["tuna_build_inputs"]
    assert detector["outputs"]["canary"] == "${{ steps.filter.outputs.canary }}"
    assert "canary-cell-inputs.sh" in detector["steps"][-1]["run"]
    job = canary_job()
    assert job["needs"] == "tuna_build_inputs"
    assert job["if"] == (
        "github.event_name == 'pull_request' && "
        "needs.tuna_build_inputs.outputs.canary == 'true'"
    )
    assert job["uses"] == "./.github/workflows/reusable-build-image.yml"
    assert "secrets" not in job
    assert job["strategy"]["fail-fast"] is False
    assert job["with"]["publish"] is False
    assert job["with"]["sbom"] is False
    assert job["with"]["pr-desktop-contract"] is True
    assert job["with"]["platforms"] == "linux/amd64"


def test_the_pr_path_runs_the_desktop_contract_on_the_built_image():
    image = yaml.safe_load((ROOT / ".github/workflows/reusable-build-image.yml").read_text())
    steps = image["jobs"]["build_push"]["steps"]
    names = [s.get("name") for s in steps]
    step = steps[names.index("Desktop contract (PR gate)")]
    assert "inputs.pr-desktop-contract" in step["if"]
    assert "github.event_name == 'pull_request'" in step["if"]
    assert "verify-desktop-experience.sh" in step["run"]
    assert 'localhost/${IMAGE_VARIANT}:${DEFAULT_TAG}' in step["run"]
    assert names.index("Build Image") < names.index("Desktop contract (PR gate)") < names.index(
        "Boot-verify image (PR gate)"
    )


def test_canary_detector_fires_on_image_recipe_changes():
    for path in (
        "Containerfile.final",
        "Containerfile.el10",
        "Containerfile.overlay",
        "Containerfile.arch",
        "build_scripts/desktop/configure-desktop-runtime.sh",
        "build_scripts/checks/verify-desktop-experience.sh",
        "tunaos.toml",
    ):
        assert matches(path), path
    assert matches("README.md", "build_scripts/10-base-packages.sh")


def test_canary_detector_ignores_everything_else():
    for path in (
        "docs/CI_SPEC.md",
        "README.md",
        ".github/workflows/tuna-pr-images.yml",
        ".github/scripts/canary-cell-inputs.sh",
        "system_files/usr/lib/os-release",
        "custom/Containerfile",
        "docs/build_scripts/notes.md",
        "tunaos.toml.example",
        "Justfile",
    ):
        assert not matches(path), path
    assert not matches()
