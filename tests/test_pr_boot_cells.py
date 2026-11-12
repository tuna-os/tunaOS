"""Tuna PR images builds every selected cell but boots only three (CI cost).

A Corral/KVM boot and its KVM, Go and corral setup were ~7 of a cell's ~16
job-minutes, on 11 cells per full run (measured 2026-10-31..11-06: boot 11.8k
job-min of 48k for the workflow). One boot per package family keeps the
signal; the nightly Gate (`reusable-build-image.yml` outside a pull request)
still boots every image. The canary cells boot as before.

Falsification: booting a fourth cell, dropping a family, gating a step the
Gate also uses, or making the canary cells skip the boot each fail below.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PR_IMAGES = yaml.safe_load((ROOT / ".github/workflows/tuna-pr-images.yml").read_text())
BUILD_VARIANT = yaml.safe_load((ROOT / ".github/workflows/build-variant.yml").read_text())
REUSABLE = yaml.safe_load((ROOT / ".github/workflows/reusable-build-image.yml").read_text())
DETECTOR = (ROOT / ".github/scripts/tuna-pr-build-inputs.sh").read_text()

PR_BOOT_STEPS = {
    "Enable KVM for verification",
    "Set up Go for corral (PR gate)",
    "Install corral (PR gate)",
    "Boot-verify image (PR gate)",
}
BOOT_EXPRESSION = re.compile(r"^\$\{\{ contains\(fromJSON\('(\[[^']*\])'\), matrix\.variant\) \}\}$")


def call_inputs(workflow: dict) -> dict:
    # PyYAML resolves the bare key `on:` to the boolean True.
    return (workflow.get("on") or workflow[True])["workflow_call"]["inputs"]


def booted_variants() -> list[str]:
    expression = PR_IMAGES["jobs"]["tuna_pr_images"]["with"]["pr-boot-verify"]
    match = BOOT_EXPRESSION.match(expression)
    assert match, f"the boot set must stay a literal list, got {expression!r}"
    return json.loads(match[1])


def admitted_variants() -> list[str]:
    return re.search(r"^all=\(([^)]*)\)", DETECTOR, re.M)[1].split()


def recipe(variant: str) -> str:
    out = subprocess.run(
        ["bash", str(ROOT / "scripts/resolve-flavor.sh"), variant, "tuna", "0"],
        capture_output=True, text=True, check=True,
    ).stdout
    return re.search(r'CONTAINERFILE="(Containerfile\.[a-z0-9]+)"', out)[1]


def test_exactly_three_cells_boot_and_all_are_admitted_variants():
    booted = booted_variants()
    assert len(booted) == len(set(booted)) == 3
    assert set(booted) <= set(admitted_variants())


def test_the_three_cells_are_one_el10_one_rpm_and_one_apt():
    recipes = {variant: recipe(variant) for variant in booted_variants()}
    assert sorted(recipes.values()) == [
        "Containerfile.el10",  # EL10 (yellowfin)
        "Containerfile.opensuse",  # RPM, not the EL10 recipe (sailfin)
        "Containerfile.ubuntu",  # apt (grouper)
    ], recipes


def test_every_selected_cell_is_still_built():
    job = PR_IMAGES["jobs"]["tuna_pr_images"]
    assert job["name"] == "${{ matrix.variant }}:tuna", "the check name must not change"
    assert job["strategy"]["matrix"]["variant"] == "${{ fromJSON(needs.tuna_build_inputs.outputs.variants) }}"
    assert job["uses"] == "$/.github/workflows/build-variant.yml"
    assert job["with"]["flavor"] == "tuna"


def test_the_canary_cells_still_boot():
    canary = PR_IMAGES["jobs"]["canary_cells"]
    assert "pr-boot-verify" not in canary["with"], "the input defaults to true; do not opt the canaries out"
    default = call_inputs(REUSABLE)["pr-boot-verify"]["default"]
    assert default is True
    default = call_inputs(BUILD_VARIANT)["pr-boot-verify"]["default"]
    assert default is True


def test_only_the_pr_boot_steps_read_the_input_and_all_of_them_do():
    steps = REUSABLE["jobs"]["build_push"]["steps"]
    readers = {s["name"] for s in steps if "inputs.pr-boot-verify" in str(s.get("if", ""))}
    assert PR_BOOT_STEPS <= readers
    assert "Upload PR verification evidence" in readers
    for step in steps:
        if step["name"] in readers:
            # Always a pull_request-only step: the Gate never sees the input.
            assert "github.event_name == 'pull_request'" in step["if"], step["name"]
    # No other job reads it, so the nightly builds and the Gate boot everything.
    for name, job in REUSABLE["jobs"].items():
        if name == "build_push":
            continue
        assert "pr-boot-verify" not in json.dumps(job), name


def test_the_albacore_deferral_evidence_is_still_uploaded_without_a_boot():
    steps = {s["name"]: s for s in REUSABLE["jobs"]["build_push"]["steps"]}
    upload = steps["Upload PR verification evidence"]["if"]
    assert "inputs.image-variant == 'albacore' && inputs.flavor == 'tuna'" in upload


def test_build_variant_passes_the_input_to_its_pull_request_build_only():
    passed = {
        name for name, job in BUILD_VARIANT["jobs"].items()
        if "pr-boot-verify" in (job.get("with") or {})
    }
    assert passed == {"build_base"}
    assert BUILD_VARIANT["jobs"]["build_base"]["with"]["pr-boot-verify"] == "${{ inputs.pr-boot-verify }}"
