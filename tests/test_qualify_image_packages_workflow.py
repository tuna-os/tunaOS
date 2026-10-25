"""The six-route package qualification harness must actually be invoked (#3802 (d)).

scripts/qualify-image-packages.py shipped with #3846 and nothing ran it, so no
native six-Containerfile build with package additions was proven. These tests
pin the manual workflow that runs it, and run scripts/package-qualification.py
against a real git repository so the stock/modified pair it creates is accepted
by the harness's own source validation. They do not build an image.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/qualify-image-packages.yml"
FIXTURE = ROOT / "tests/fixtures/package-qualification-cells.json"


def load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


HARNESS = load("qualify_image_packages", "scripts/qualify-image-packages.py")
LANE = load("package_qualification", "scripts/package-qualification.py")
ROUTES = list(HARNESS.ROUTES)


def workflow_document() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def triggers(document: dict) -> dict:
    """PyYAML reads the bare `on` key as the boolean True."""
    return document.get("on", document.get(True))


def problems(document: dict, text: str) -> list[str]:
    """Everything that would make the workflow not prove the six routes, or unsafe."""
    found = []
    on = triggers(document)
    if set(on) != {"workflow_dispatch"}:
        found.append(f"triggers must be workflow_dispatch only, got {sorted(on)}")
    if document.get("permissions") != {"contents": "read"}:
        found.append("top-level permissions must be exactly contents: read")
    for job_id, job in document["jobs"].items():
        if "permissions" in job:
            found.append(f"job {job_id} must inherit the read-only permissions")
        if "environment" in job:
            found.append(f"job {job_id} must not attach a deployment environment")
    default = json.loads(on["workflow_dispatch"]["inputs"]["routes"]["default"])
    if sorted(default) != sorted(ROUTES):
        found.append(f"default routes {default} differ from the harness routes {ROUTES}")
    matrix = document["jobs"]["qualify"]["strategy"]["matrix"]["route"]
    if "fromJson(inputs.routes)" not in matrix:
        found.append("the matrix must come from the routes input")
    if document["jobs"]["qualify"]["strategy"].get("fail-fast") is not False:
        found.append("one failing route must not cancel the others")
    steps = document["jobs"]["qualify"]["steps"]
    harness = [s for s in steps if "qualify-image-packages.py" in s.get("run", "")]
    if len(harness) != 1 or not all(
        flag in harness[0]["run"] for flag in ('--plan "$PLAN"', '--source "$PWD"', '--output "$EVIDENCE"')
    ):
        found.append("the harness must run once with --plan, --source and --output")
    gates = [s for s in steps if "package-qualification.py gate" in s.get("run", "")]
    gated_after_harness = (
        len(gates) == 1 and len(harness) == 1 and steps.index(gates[0]) > steps.index(harness[0])
    )
    if not gated_after_harness:
        found.append("a gate step must read the harness report after the harness ran")
    uploads = [s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
    evidence = [s for s in uploads if "package-qualification-evidence" in s["with"]["path"]]
    if len(evidence) != 1 or evidence[0].get("if") != "always()":
        found.append("the evidence directory must be uploaded even when a route fails")
    for forbidden in ("secrets.", "id-token", "packages: write", "ghcr-login", "docker push",
                      "podman push", "skopeo copy", "cosign", "gh release", "git push", "schedule:"):
        if forbidden in text:
            found.append(f"workflow must not contain {forbidden!r}")
    return found


def test_the_workflow_is_manual_read_only_and_runs_every_harness_route():
    assert problems(workflow_document(), WORKFLOW.read_text()) == []


def test_a_missing_route_is_a_violation():
    document = workflow_document()
    routes = json.loads(triggers(document)["workflow_dispatch"]["inputs"]["routes"]["default"])
    routes.remove("gentoo")
    triggers(document)["workflow_dispatch"]["inputs"]["routes"]["default"] = json.dumps(routes)
    assert any("gentoo" in item or "differ" in item for item in problems(document, WORKFLOW.read_text()))


@pytest.mark.parametrize("trigger", ["schedule", "push", "pull_request", "workflow_run"])
def test_an_extra_trigger_is_a_violation(trigger):
    document = workflow_document()
    triggers(document)[trigger] = {}
    assert any("workflow_dispatch only" in item for item in problems(document, WORKFLOW.read_text()))


def test_write_permissions_secrets_and_a_dropped_upload_are_violations():
    document = workflow_document()
    document["permissions"] = {"contents": "read", "packages": "write"}
    assert any("contents: read" in item for item in problems(document, WORKFLOW.read_text()))

    document = workflow_document()
    document["jobs"]["qualify"]["permissions"] = {"id-token": "write"}
    assert any("inherit" in item for item in problems(document, WORKFLOW.read_text()))

    assert any("secrets." in item for item in problems(workflow_document(), WORKFLOW.read_text() + "${{ secrets.X }}"))

    document = workflow_document()
    document["jobs"]["qualify"]["steps"] = [
        s for s in document["jobs"]["qualify"]["steps"] if "upload-artifact" not in str(s.get("uses"))
    ]
    assert any("evidence directory" in item for item in problems(document, WORKFLOW.read_text()))

    document = workflow_document()
    for step in document["jobs"]["qualify"]["steps"]:
        step["run"] = step.get("run", "").replace('--output "$EVIDENCE"', "")
    assert any("--output" in item for item in problems(document, WORKFLOW.read_text()))


def test_the_fixture_names_each_harness_route_once_with_a_variant_that_resolves_there():
    cells = LANE.load_cells(FIXTURE)
    assert [cell["route"] for cell in cells] == ROUTES
    assert len({cell["variant"] for cell in cells}) == len(ROUTES)
    if shutil.which("yq") is None:
        pytest.skip("scripts/resolve-flavor.sh needs yq")
    for cell in cells:
        for flavor in ("base", cell["desktop"]):
            routed = HARNESS.parse_route(subprocess.run(
                ["bash", "scripts/resolve-flavor.sh", cell["variant"], flavor],
                cwd=ROOT, capture_output=True, check=True,
            ).stdout)
            assert routed["CONTAINERFILE"] == HARNESS.ROUTES[cell["route"]], cell
        if cell["overlay"]:
            overlay = HARNESS.parse_route(subprocess.run(
                ["bash", "scripts/resolve-flavor.sh", cell["variant"], cell["overlay"]],
                cwd=ROOT, capture_output=True, check=True,
            ).stdout)
            assert overlay["PARENT_FLAVOR"] == cell["desktop"]


def test_a_fixture_missing_a_route_is_rejected(tmp_path):
    cells = json.loads(FIXTURE.read_text())
    cells["cells"].pop()
    broken = tmp_path / "cells.json"
    broken.write_text(json.dumps(cells))
    with pytest.raises(LANE.PrepareError, match="routes must equal the harness routes"):
        LANE.load_cells(broken)


@pytest.fixture(scope="module")
def checkout(tmp_path_factory):
    """A real clone of this repository's committed tree with a fake `skopeo` on PATH."""
    root = tmp_path_factory.mktemp("qualify") / "source"
    subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(ROOT), str(root)], check=True)
    bin_dir = root.parent / "bin"
    bin_dir.mkdir()
    skopeo = bin_dir / "skopeo"
    skopeo.write_text('#!/bin/sh\nprintf "manifest-of-%s" "$3"\n')
    skopeo.chmod(0o755)
    return root, bin_dir


def run_prepare(checkout, route, tmp_path, monkeypatch):
    root, bin_dir = checkout
    monkeypatch.setenv("PATH", f"{bin_dir}:{__import__('os').environ['PATH']}")
    subprocess.run(["git", "reset", "-q", "--hard", "origin/HEAD"], cwd=root, check=True)
    plan = tmp_path / "plan.json"
    result = LANE.prepare(root, LANE.load_cells(FIXTURE), route, plan)
    return root, result, json.loads(plan.read_text())


@pytest.mark.parametrize("route", ROUTES)
def test_prepare_makes_the_exact_pair_the_harness_accepts(checkout, tmp_path, monkeypatch, route):
    root, result, plan = run_prepare(checkout, route, tmp_path, monkeypatch)
    stock, modified = result["stockCommit"], result["modifiedCommit"]
    git = lambda *args: subprocess.check_output(["git", *args], cwd=root, text=True).strip()  # noqa: E731

    assert git("rev-list", "--parents", "-n", "1", modified).split() == [modified, stock]
    assert set(git("diff-tree", "--no-commit-id", "--name-only", "-r", modified).splitlines()) == set(LANE.SOURCE_FILES)
    assert git("rev-parse", "HEAD") == modified and git("status", "--porcelain") == ""
    assert HARNESS.validate_plan(plan) == plan

    # The harness's own source validation accepts the pair before any image exists.
    with HARNESS.CommandLog(tmp_path / "source.log") as log:
        source = HARNESS.validate_source(plan, root, log)
    assert sorted(source["managers"]) == sorted(cell["variant"] for cell in plan["cells"])

    by_route = {cell["route"]: cell for cell in plan["cells"]}
    assert [name for name, cell in by_route.items() if cell["images"] is not None] == [route]
    roles = set(by_route[route]["images"])
    assert roles == {"stockBase", "modifiedBase", "modifiedDesktop", *(["modifiedOverlay"] if route == "el10" else [])}
    assert {build["role"] for build in result["builds"]} == roles
    stock_builds = [b for b in result["builds"] if b["role"] == "stockBase"]
    assert [b["commit"] for b in stock_builds] == [stock]
    assert all(b["commit"] == modified for b in result["builds"] if b["role"] != "stockBase")
    assert {b["tag"] for b in result["builds"]} == {
        record["ref"].split(":", 1)[1] for record in by_route[route]["images"].values()
    }


def test_prepare_pins_only_the_mutable_base_and_the_overlay_builds_on_the_local_desktop(
    checkout, tmp_path, monkeypatch
):
    root, result, plan = run_prepare(checkout, "el10", tmp_path, monkeypatch)
    by_route = {cell["route"]: cell for cell in plan["cells"]}
    for cell in by_route.values():
        assert LANE.PINNED.search(cell["baseImage"]), cell
    git = lambda *args: subprocess.check_output(["git", *args], cwd=root, text=True)  # noqa: E731
    # The stock commit may differ from the checkout only by digest-pinned base_image rows.
    changed = [line for line in git("diff", "-U0", "origin/HEAD", result["stockCommit"], "--", "tunaos.toml").splitlines()
               if line[:1] in "+-" and line[:3] not in ("+++", "---")]
    removed = [line for line in changed if line[0] == "-"]
    added = [line for line in changed if line[0] == "+"]
    assert len(removed) == len(added) and all(line.startswith(("-base_image", "+base_image")) for line in changed)
    assert all(LANE.PINNED.search(line) for line in added)
    overlay = next(b for b in result["builds"] if b["role"] == "modifiedOverlay")
    desktop = next(b for b in result["builds"] if b["role"] == "modifiedDesktop")
    assert overlay["chain"] == f"localhost/{desktop['variant']}:{desktop['tag']}" and overlay["isCi"] == "0"
    assert desktop["isCi"] == "1"


def test_prepare_refuses_a_dirty_checkout_and_existing_package_tables(checkout, tmp_path, monkeypatch):
    root, _bin = checkout
    run_prepare(checkout, "ubuntu", tmp_path, monkeypatch)
    (root / "stray").write_text("x\n")
    with pytest.raises(LANE.PrepareError, match="must be clean"):
        LANE.prepare(root, LANE.load_cells(FIXTURE), "ubuntu", tmp_path / "again.json")
    (root / "stray").unlink()

    with pytest.raises(LANE.PrepareError, match="already exists"):
        LANE.add_package("[variants.grouper.packages]\nadd = []\n", "grouper", "tree")
    with pytest.raises(LANE.PrepareError, match="unknown route"):
        LANE.prepare(root, LANE.load_cells(FIXTURE), "freebsd", tmp_path / "x.json")


def report(statuses: dict, images: int = 3) -> dict:
    return {"routes": [
        {"route": name, "status": status, "images": [{}] * images, "reason": "boom"}
        for name, status in statuses.items()
    ]}


def test_the_gate_requires_the_selected_route_to_pass_and_the_rest_to_be_not_run(tmp_path):
    only = {name: "not-run" for name in ROUTES}
    path = tmp_path / "report.json"

    path.write_text(json.dumps(report({**only, "arch": "passed"})))
    assert LANE.gate(path, "arch").startswith("arch: passed")

    path.write_text(json.dumps(report({**only, "arch": "failed"})))
    with pytest.raises(LANE.PrepareError, match="arch: failed: boom"):
        LANE.gate(path, "arch")

    path.write_text(json.dumps(report({**only, "arch": "passed", "ubuntu": "passed"})))
    with pytest.raises(LANE.PrepareError, match="not left not-run"):
        LANE.gate(path, "arch")

    incomplete = copy.deepcopy(report({**only, "arch": "passed"}))
    incomplete["routes"].pop()
    path.write_text(json.dumps(incomplete))
    with pytest.raises(LANE.PrepareError, match="every route"):
        LANE.gate(path, "arch")

    with pytest.raises(LANE.PrepareError, match="unreadable report"):
        LANE.gate(tmp_path / "missing.json", "arch")
