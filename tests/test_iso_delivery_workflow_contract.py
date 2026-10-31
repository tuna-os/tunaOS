"""Behavioral platform matching and least-privilege caller checks."""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def catalog_platform_matchers(expected_arch: str, expected_variant: str):
    workflow = load("catalog-facts.yml")
    step = next(
        step for step in workflow["jobs"]["facts"]["steps"]
        if step.get("name") == "Probe this variant's catalog images"
    )
    python_body = step["run"].split("python3 <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    tree = ast.parse(python_body)
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"config_matches", "descriptor_matches"}
    ]
    namespace = {"expected_arch": expected_arch, "expected_variant": expected_variant}
    module = ast.Module(body=functions, type_ignores=[])
    exec(compile(module, "catalog-facts", "exec"), namespace)
    return namespace["descriptor_matches"], namespace["config_matches"]


def test_amd64_v2_index_descriptor_can_prove_platform_without_config_variant():
    descriptor_matches, config_matches = catalog_platform_matchers("amd64", "v2")

    assert descriptor_matches("linux", "amd64", "v2")
    assert config_matches("linux", "amd64")
    assert not descriptor_matches("linux", "amd64", None)
    assert not descriptor_matches("linux", "arm64", "v2")


def test_single_manifest_v2_requires_the_variant_to_be_proven():
    descriptor_matches, _ = catalog_platform_matchers("amd64", "v2")

    assert descriptor_matches("linux", "amd64", "v2")
    assert not descriptor_matches("linux", "amd64", "v3")
    assert not descriptor_matches("linux", "amd64", None)


def test_reusable_build_callers_grant_only_actions_read_for_artifact_access():
    build = load("build-variant.yml")
    flavor = load("build-flavor.yml")
    tuna_pr_images = load("tuna-pr-images.yml")

    assert build["permissions"]["actions"] == "read"
    assert flavor["jobs"]["build"]["permissions"]["actions"] == "read"
    assert tuna_pr_images["jobs"]["tuna_pr_images"]["permissions"]["actions"] == "read"
    for path in WORKFLOWS.glob("build-*.yml"):
        if path.name in {"build-variant.yml", "build-flavor.yml"}:
            continue
        wrapper = load(path.name)
        callers = [
            job for job in wrapper.get("jobs", {}).values()
            if job.get("uses") == "./.github/workflows/build-variant.yml"
        ]
        if callers:
            assert wrapper["permissions"]["actions"] == "read", path.name


def test_compatible_overlay_index_uses_canonical_oci_platform_descriptors():
    run = next(
        step["run"] for step in load("live-overlay.yml")["jobs"]["publish-compatible-index"]["steps"]
        if step.get("name") == "Publish complete current-run platform groups"
    )
    lines = run.splitlines()
    start = next(index for index, line in enumerate(lines) if line.strip() == "overlay_platform_fields() {")
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = next(index for index in range(start + 1, len(lines))
               if lines[index].strip() == "}" and len(lines[index]) - len(lines[index].lstrip()) == indent)
    function = "\n".join(line[indent:] for line in lines[start:end + 1])
    expected = {
        "linux/amd64": ("linux", "amd64", ""),
        "linux/amd64/v2": ("linux", "amd64", "v2"),
        "linux/arm64": ("linux", "arm64", "v8"),
    }
    for canonical, descriptor in expected.items():
        result = subprocess.run(
            ["bash", "-c", f'{function}\noverlay_platform_fields "$1"', "bash", canonical],
            capture_output=True,
            text=True,
            check=True,
        )
        assert tuple(result.stdout.rstrip("\n").split("\t")) == descriptor
    unsupported = subprocess.run(
        ["bash", "-c", f'{function}\noverlay_platform_fields "$1"', "bash", "linux/amd64/v3"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert unsupported.returncode != 0

