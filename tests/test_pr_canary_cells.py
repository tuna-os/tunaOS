"""TUNA-2: four desktop canary cells build and pass the desktop contract on image-input PRs."""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/tuna-pr-images.yml"
DETECTOR = ROOT / ".github/scripts/canary-cell-inputs.sh"
TUNA_DETECTOR = ROOT / ".github/scripts/tuna-pr-build-inputs.sh"


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
    assert job["uses"] == "$/.github/workflows/reusable-build-image.yml"
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


def selected_variants(*paths, script=TUNA_DETECTOR, base=None):
    env = os.environ.copy()
    env.pop("TUNA_PR_BASE_SHA", None)
    if base is not None:
        env["TUNA_PR_BASE_SHA"] = base
    result = subprocess.run(
        ["bash", str(script), "--variants"],
        input="\n".join(paths), text=True, capture_output=True, env=env, check=True,
    )
    return json.loads(result.stdout)


def all_variants():
    return selected_variants("build_scripts/lib.sh")


@pytest.mark.parametrize(("path", "expected"), [
    ("Containerfile.arch", ["marlin"]),
    ("manifests/desktops/tuna-arch.yaml", ["marlin"]),
    ("Containerfile.debian", ["flounder", "flounder-sid"]),
    ("manifests/desktops/tuna-debian.yaml", ["flounder", "flounder-sid"]),
    ("Containerfile.ubuntu", ["grouper"]),
    ("Containerfile.opensuse", ["sailfin"]),
    ("system_files_overrides/marlin/etc/example.conf", ["marlin"]),
    ("system_files_overrides/bonito/etc/example.conf", ["bonito", "bonito-rawhide"]),
    ("system_files_overrides/flounder/etc/example.conf", ["flounder", "flounder-sid"]),
    ("manifests/desktop-contracts/yellowfin/tuna/linux-amd64.json", ["yellowfin"]),
])
def test_tuna_variant_local_inputs_select_their_consumers(path, expected):
    assert selected_variants(path) == expected


def test_tuna_selection_unions_paths_and_keeps_stable_unique_order():
    assert selected_variants(
        "README.md", "Containerfile.debian", "Containerfile.arch",
        "manifests/desktops/tuna-arch.yaml",
    ) == ["marlin", "flounder", "flounder-sid"]


@pytest.mark.parametrize("path", [
    "Containerfile.el10", "Containerfile.final", "Containerfile.overlay",
    "build_scripts/lib.sh", "scripts/resolve-flavor.sh", "image-versions.yaml",
    "registry-map.yaml", ".github/build-config.yml",
    ".github/workflows/tuna-pr-images.yml",
    ".github/workflows/build-variant.yml",
    ".github/workflows/reusable-build-image.yml",
    ".github/scripts/tuna-pr-build-inputs.sh",
    "manifests/desktops/tuna.yaml", "manifests/desktops/tuna-new.yaml",
    "manifests/new-config.yaml", "config/new-config.toml",
    "system_files_overrides/unknown/etc/example.conf",
    "system_files_overrides/nvidia/example.conf",
    "manifests/desktop-contracts/unknown/tuna/linux-amd64.json",
    "system_files/etc/example.conf", "experiences/tuna/files/example.conf",
    "tunaos.toml",
])
def test_shared_or_unknown_inputs_restore_every_tuna_cell(path):
    assert selected_variants("Containerfile.arch", path) == all_variants()
    assert selected_variants(path, "Containerfile.arch") == all_variants()


def test_unrelated_docs_select_no_tuna_images_and_boolean_interface_agrees():
    for paths in [(), ("README.md", "docs/TESTING.md"), ("Containerfile.arch",),
                  ("Containerfile.arch", "build_scripts/lib.sh")]:
        selected = selected_variants(*paths)
        boolean = subprocess.run(
            ["bash", str(TUNA_DETECTOR)], input="\n".join(paths),
            text=True, capture_output=True,
        )
        assert boolean.returncode == (0 if selected else 1)
    assert selected_variants("README.md", "docs/TESTING.md") == []
    assert selected_variants() == []


def test_workflow_uses_one_selector_without_narrowing_the_family_canaries():
    jobs = workflow()["jobs"]
    detector = jobs["tuna_build_inputs"]
    assert detector["outputs"]["variants"] == "${{ steps.filter.outputs.variants }}"
    run = detector["steps"][-1]["run"]
    assert "tuna-pr-build-inputs.sh --variants" in run
    assert ".previous_filename // empty" in run  # renamed-away inputs count too
    assert detector["steps"][-1]["env"]["TUNA_PR_BASE_SHA"] == (
        "${{ github.event.pull_request.base.sha }}"
    )
    tuna = jobs["tuna_pr_images"]
    assert tuna["strategy"]["matrix"]["variant"] == (
        "${{ fromJSON(needs.tuna_build_inputs.outputs.variants) }}"
    )
    assert tuna["with"]["flavor"] == "tuna"
    assert tuna["uses"] == "$/.github/workflows/build-variant.yml"
    assert "secrets" not in tuna
    for job in (tuna, canary_job()):
        assert "max-parallel" not in job["strategy"]
    assert matches("Containerfile.arch")
    assert workflow_cells() == justfile_cells()


@pytest.fixture
def config_selector(tmp_path):
    script = tmp_path / ".github/scripts/tuna-pr-build-inputs.sh"
    script.parent.mkdir(parents=True)
    shutil.copyfile(TUNA_DETECTOR, script)
    parser = tmp_path / "scripts/lib/tunaos_config.py"
    parser.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "scripts/lib/tunaos_config.py", parser)
    shutil.copytree(
        ROOT / "scripts/lib/_vendor/tomli", parser.parent / "_vendor/tomli",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    config = tmp_path / "tunaos.toml"
    initial = (
        '[project]\nname = "TunaOS"\n'
        '[variants.marlin]\nbase_image = "arch:old"\n'
        '[variants.flounder]\nbase_image = "debian:old"\n'
        '[variants.hummingbird]\nbase_image = "hb:old"\n'
    )
    config.write_text(initial)
    env = {**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
           "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com"}
    for args in (["init"], ["add", "tunaos.toml"], ["commit", "-m", "base"]):
        subprocess.run(["git", *args], cwd=tmp_path, env=env, check=True, capture_output=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    return script, config, initial, base


def test_primary_config_variant_edits_select_only_changed_variants(config_selector):
    script, config, initial, base = config_selector
    config.write_text(initial.replace("arch:old", "arch:new"))
    assert selected_variants("tunaos.toml", script=script, base=base) == ["marlin"]
    config.write_text(initial.replace(":old", ":new"))
    assert selected_variants("tunaos.toml", script=script, base=base) == ["marlin", "flounder"]
    # Config is still a canary input even when its Tuna subset is smaller.
    assert matches("tunaos.toml")


def test_unadmitted_variant_edits_select_no_tuna_cell(config_selector):
    # hummingbird is not in the admitted set, so no Tuna cell consumes its table.
    # Its base-image digest bumps used to restore the full matrix.
    script, config, initial, base = config_selector
    config.write_text(initial.replace("hb:old", "hb:new"))
    assert selected_variants("tunaos.toml", script=script, base=base) == []
    config.write_text(initial.replace("hb:old", "hb:new").replace("arch:old", "arch:new"))
    assert selected_variants("tunaos.toml", script=script, base=base) == ["marlin"]
    # Config is still a canary input.
    assert matches("tunaos.toml")


@pytest.mark.parametrize("change", [
    lambda s: s.replace('name = "TunaOS"', 'name = "Fork"'),
    lambda s: s + '\n[unknown]\nsetting = true\n',
    lambda s: s + '\n[variants.newfish]\nbase_image = "new:latest"\n',
    lambda s: s.replace('base_image = "arch:old"', 'base_image = "arch:old"\nunknown = true'),
    lambda s: s + '\n[variants.guppy]\nbase_image = "gentoo:latest"\n',
    lambda s: s.replace('[variants.flounder]\nbase_image = "debian:old"\n', ""),
    lambda s: s + "\ninvalid TOML [",
    lambda s: s + "\n# comment-only diff is not proven variant-local\n",
    lambda s: s.replace("[variants.marlin]", "[unknown.marlin]"),
])
def test_shared_unknown_or_unreadable_config_fails_open(config_selector, change):
    script, config, initial, base = config_selector
    config.write_text(change(initial))
    assert selected_variants("tunaos.toml", script=script, base=base) == all_variants()
    assert selected_variants("tunaos.toml", script=script, base="0" * 40) == all_variants()


def _digest(char):
    return "sha256:" + char * 64


IMAGE_VERSIONS = (
    "images:\n"
    "  - name: common\n    image: ghcr.io/projectbluefin/common\n    tag: latest\n"
    f"    digest: {_digest('a')}\n"
    "  # Hummingbird's GNOME payload.\n"
    "  - name: utah-packages\n    image: ghcr.io/projectbluefin/utah-packages\n    tag: latest\n"
    f"    digest: {_digest('b')}\n"
    "  - name: brew\n    image: ghcr.io/ublue-os/brew\n    tag: latest\n"
    f"    digest: {_digest('c')}\n"
    "packages:\n  foo: 1\n"
)


@pytest.fixture
def image_versions_selector(tmp_path):
    script = tmp_path / ".github/scripts/tuna-pr-build-inputs.sh"
    script.parent.mkdir(parents=True)
    shutil.copyfile(TUNA_DETECTOR, script)
    versions = tmp_path / "image-versions.yaml"
    versions.write_text(IMAGE_VERSIONS)
    env = {**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
           "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com"}
    for args in (["init"], ["add", "image-versions.yaml"], ["commit", "-m", "base"]):
        subprocess.run(["git", *args], cwd=tmp_path, env=env, check=True, capture_output=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    return script, versions, base


def test_el10_only_digest_bumps_select_only_el10_variants(image_versions_selector):
    script, versions, base = image_versions_selector
    el10 = ["yellowfin", "albacore", "skipjack", "bonito", "wahoo", "bonito-rawhide"]
    versions.write_text(IMAGE_VERSIONS.replace(_digest("b"), _digest("d")))
    assert selected_variants("image-versions.yaml", script=script, base=base) == el10
    versions.write_text(IMAGE_VERSIONS.replace(_digest("b"), _digest("d")).replace(_digest("c"), _digest("e")))
    assert selected_variants("image-versions.yaml", script=script, base=base) == el10


@pytest.mark.parametrize("change", [
    # every Containerfile mounts the common stage
    lambda s: s.replace(_digest("a"), _digest("d")),
    # one shared digest next to an el10-only digest still restores everything
    lambda s: s.replace(_digest("a"), _digest("d")).replace(_digest("b"), _digest("e")),
    lambda s: s.replace("tag: latest\n    digest: " + _digest("b"), "tag: stable\n    digest: " + _digest("b")),
    lambda s: s.replace("# Hummingbird's GNOME payload.", "# edited"),
    lambda s: s.replace("packages:\n  foo: 1", "packages:\n  foo: 2"),
    lambda s: s + "  - name: extra\n    image: example.com/x\n    tag: latest\n" + f"    digest: {_digest('f')}\n",
    lambda s: s,
])
def test_other_image_versions_edits_keep_the_full_matrix(image_versions_selector, change):
    script, versions, base = image_versions_selector
    versions.write_text(change(IMAGE_VERSIONS))
    assert selected_variants("image-versions.yaml", script=script, base=base) == all_variants()
    # A missing or unreadable base fails open as well.
    versions.write_text(IMAGE_VERSIONS.replace(_digest("b"), _digest("d")))
    assert selected_variants("image-versions.yaml", script=script, base="0" * 40) == all_variants()
    assert selected_variants("image-versions.yaml", script=script) == all_variants()


@pytest.mark.skipif(shutil.which("jq") is None, reason="resolve-flavor.sh needs jq")
def test_the_el10_variant_list_matches_what_resolve_flavor_sends_to_containerfile_el10():
    text = TUNA_DETECTOR.read_text()
    listed = set(re.search(r"^el10_variants=\(([^)]*)\)", text, re.M).group(1).split())
    admitted = set(all_variants())
    on_el10 = set()
    for variant in sorted(admitted):
        out = subprocess.run(
            ["bash", str(ROOT / "scripts/resolve-flavor.sh"), variant, "tuna", "0"],
            capture_output=True, text=True, check=True,
        ).stdout
        if 'CONTAINERFILE="Containerfile.el10"' in out:
            on_el10.add(variant)
    assert listed == on_el10
