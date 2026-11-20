"""A hardware overlay is its promoted parent plus one profile, rebuilt on Promote.

bonito:gnome-x13s is bonito:gnome plus [hardware.x13s]. Every build of it failed
the inventory gate on `MISSING pcie_qcom` (run 42266581085), and when it did
build it was scheduled weekly, chained on the unpromoted gnome-candidate, and
re-laid system_files, so it differed from its parent in more than the hardware.
Now Promote of the parent dispatches the overlay
(scripts/dispatch-hardware-overlays.sh), build-variant.yml builds a hardware
flavor only when a dispatch names it, the overlay is built FROM the promoted
parent pinned by digest and labelled with it (scripts/pin-image-digest.sh,
build-image-inner.sh), and Containerfile.overlay re-lays nothing for it.

Falsification: behavioural -- drop the `(.hardware // "") == ""` select from
build-variant.yml's matrix, the parent match from the dispatch script's yq
filter, or the `[ "${OVERLAY_TYPE}" = hardware ] ||` guards from
Containerfile.overlay, and the matching tests below fail; put pcie_qcom back
in [hardware.x13s.require].modules and the last test fails.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
DISPATCH = ROOT / "scripts/dispatch-hardware-overlays.sh"
PIN = ROOT / "scripts/pin-image-digest.sh"
VARIANT_WORKFLOW = ROOT / ".github/workflows/build-variant.yml"
REUSABLE = ROOT / ".github/workflows/reusable-build-image.yml"
OVERLAY = ROOT / "Containerfile.overlay"

CONFIG = {
    "variants": [
        {
            "id": "bonito",
            "weekly_day": 2,
            "platforms": ["linux/amd64", "linux/arm64"],
            "flavors": [
                {"id": "base", "stage": 1, "build_image": True},
                {"id": "gnome", "stage": 2, "build_image": True, "build_iso": True},
                {"id": "kde", "stage": 2, "build_image": True},
                {"id": "gnome-x13s", "hardware": "x13s", "parent": "gnome", "stage": 3,
                 "platforms": ["linux/arm64"], "build_image": True, "build_iso": True},
                {"id": "gnome-t2", "hardware": "t2", "parent": "gnome", "stage": 3,
                 "platforms": ["linux/amd64"], "build_image": False},
            ],
        },
    ],
}

PROMOTE = {
    "EVENT_NAME": "schedule",
    "REPOSITORY": "tuna-os/tunaOS",
    "REF": "refs/heads/main",
    "PROMOTED": "true",
    "VARIANT": "bonito",
    "FLAVOR": "gnome",
    "RETRY_SLEEP": "0",
}


@pytest.fixture
def config(tmp_path: Path) -> Path:
    path = tmp_path / "build-config.yml"
    path.write_text(yaml.safe_dump(CONFIG))
    return path


def stub(bin_dir: Path, name: str, body: str) -> Path:
    bin_dir.mkdir(exist_ok=True)
    path = bin_dir / name
    path.write_text("#!/usr/bin/env bash\n" + textwrap.dedent(body))
    path.chmod(0o755)
    return path


# ── Promote dispatches the overlays whose parent it moved ────────────────────

def dispatch(tmp_path: Path, config: Path, gh_exit: int = 0, **overrides):
    # The dispatch script reads the build config with yq; CI and `just test` have it.
    assert shutil.which("yq"), "yq is required"
    calls = tmp_path / "gh-calls"
    gh = stub(tmp_path / "bin", "gh", f"""\
        printf '%s\\n' "$*" >> {calls}
        exit {gh_exit}
    """)
    env = os.environ | PROMOTE | overrides | {"TUNAOS_BUILD_CONFIG": str(config), "GH": str(gh)}
    proc = subprocess.run(["bash", str(DISPATCH)], env=env, text=True, capture_output=True)
    lines = calls.read_text().splitlines() if calls.exists() else []
    return proc, lines


def test_a_promoted_parent_dispatches_its_enabled_hardware_overlay(tmp_path, config):
    proc, runs = dispatch(tmp_path, config)
    assert proc.returncode == 0, proc.stderr
    # gnome-t2 also names gnome as parent but is not built (build_image false).
    assert runs == ["workflow run build-bonito.yml --repo tuna-os/tunaOS --ref main -f flavor=gnome-x13s"]


@pytest.mark.parametrize("overrides", [
    {"EVENT_NAME": "pull_request"},
    {"REPOSITORY": "someone/tunaOS"},
    {"REF": "refs/heads/feature"},
    {"PROMOTED": ""},
    {"FLAVOR": "kde"},
    {"FLAVOR": "gnome-x13s"},
], ids=["pull-request", "fork", "branch", "not-promoted", "no-overlay", "overlay-itself"])
def test_nothing_is_dispatched_without_a_promoted_parent(tmp_path, config, overrides):
    proc, runs = dispatch(tmp_path, config, **overrides)
    assert proc.returncode == 0, proc.stderr
    assert runs == []
    assert "not dispatching" in proc.stdout


def test_a_failed_dispatch_is_reported_after_three_attempts(tmp_path, config):
    proc, runs = dispatch(tmp_path, config, gh_exit=1)
    assert proc.returncode == 1
    assert len(runs) == 3
    assert "::error::could not dispatch build-bonito.yml flavor=gnome-x13s" in proc.stderr


def test_promote_runs_the_dispatch_with_permission_to_dispatch():
    job = yaml.safe_load(REUSABLE.read_text())["jobs"]["live_overlay"]
    assert job["needs"] == "tag-image"
    assert "needs.tag-image.outputs.promoted == 'true'" in job["if"]
    assert job["permissions"]["actions"] == "write"
    step = next(s for s in job["steps"] if s.get("run") == "bash scripts/dispatch-hardware-overlays.sh")
    assert step["env"]["VARIANT"] == "${{ inputs.image-variant }}"
    assert step["env"]["FLAVOR"] == "${{ inputs.flavor }}"
    assert step["env"]["PROMOTED"] == "${{ needs.tag-image.outputs.promoted }}"


# ── the matrix builds a hardware flavor only when a dispatch names it ─────────

def _matrix_program() -> str:
    text = VARIANT_WORKFLOW.read_text()
    start = text.index("FULL_MATRIX=$(jq -c --arg event ")
    first = text.index("'", start) + 1
    return text[first: text.index("' \"$CONFIG_JSON\"", first)]


def matrix(config: Path, event: str, dow: int, flavor: str = "all", actor: str = "someone") -> dict[str, dict]:
    jq = shutil.which("jq")
    assert jq, "jq is required"
    data = config.with_suffix(".json")
    data.write_text(json.dumps(yaml.safe_load(config.read_text())))
    out = subprocess.run(
        [jq, "-c", "--arg", "event", event, "--argjson", "dow", str(dow), _matrix_program(), str(data)],
        env={"FILTER_VARIANT": "bonito", "FILTER_FLAVOR": flavor, "TRIGGERING_ACTOR": actor,
             "PATH": os.environ["PATH"]},
        capture_output=True, text=True, check=True,
    ).stdout
    return {row["flavor"]: row for line in out.splitlines() for row in [json.loads(line)]}


@pytest.mark.parametrize("event", ["schedule", "workflow_dispatch"])
def test_schedules_and_all_dispatches_leave_hardware_flavors_out(config, event):
    rows = matrix(config, event, 2)
    assert "gnome-x13s" not in rows
    assert {"base", "gnome", "kde"} <= set(rows)


def test_a_dispatch_naming_the_overlay_builds_it_and_its_iso(config):
    rows = matrix(config, "workflow_dispatch", 5, flavor="gnome-x13s")
    assert set(rows) == {"gnome-x13s"}
    assert rows["gnome-x13s"]["build_iso"] is True


def test_a_promotion_dispatch_builds_the_overlay_iso_only_on_the_weekly_day(config):
    bot = "github-actions[bot]"
    off_day = matrix(config, "workflow_dispatch", 5, flavor="gnome-x13s", actor=bot)
    on_day = matrix(config, "workflow_dispatch", 2, flavor="gnome-x13s", actor=bot)
    assert off_day["gnome-x13s"]["build_iso"] is False
    assert on_day["gnome-x13s"]["build_iso"] is True
    # The thinning is for hardware flavors only: a bot dispatch of gnome is not.
    assert matrix(config, "workflow_dispatch", 5, flavor="gnome", actor=bot)["gnome"]["build_iso"] is True


def test_the_matrix_step_receives_the_triggering_actor():
    steps = yaml.safe_load(VARIANT_WORKFLOW.read_text())["jobs"]["generate_matrix"]["steps"]
    step = next(s for s in steps if s.get("id") == "set-matrix")
    assert step["env"]["TRIGGERING_ACTOR"] == "${{ github.triggering_actor }}"


# ── the overlay is built FROM one pinned parent and says which ───────────────

def pin(tmp_path: Path, ref: str, manifest: bytes | None):
    skopeo = tmp_path / "bin/skopeo"
    if manifest is None:
        stub(tmp_path / "bin", "skopeo", "exit 1\n")
    else:
        (tmp_path / "manifest").write_bytes(manifest)
        stub(tmp_path / "bin", "skopeo", f"""\
            [[ "$*" == "inspect --raw --retry-times 3 docker://{ref}" ]] || exit 9
            cat {tmp_path / 'manifest'}
        """)
    return subprocess.run(["bash", str(PIN), ref], env=os.environ | {"SKOPEO": str(skopeo)},
                          text=True, capture_output=True)


def test_the_parent_is_pinned_to_the_digest_of_the_manifest_it_serves(tmp_path):
    manifest = b'{"schemaVersion":2,"manifests":[]}'
    digest = "sha256:" + hashlib.sha256(manifest).hexdigest()
    proc = pin(tmp_path, "ghcr.io/tuna-os/bonito:gnome", manifest)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == f"ghcr.io/tuna-os/bonito:gnome@{digest} {digest}\n"


def test_a_pinned_ref_is_kept_and_an_unreadable_one_fails(tmp_path):
    digest = "sha256:" + "a" * 64
    kept = pin(tmp_path, f"ghcr.io/tuna-os/bonito:gnome@{digest}", None)
    assert kept.stdout == f"ghcr.io/tuna-os/bonito:gnome@{digest} {digest}\n"
    failed = pin(tmp_path, "ghcr.io/tuna-os/bonito:gnome", None)
    assert failed.returncode == 1
    assert failed.stdout == ""
    empty = pin(tmp_path, "ghcr.io/tuna-os/bonito:gnome", b"")
    assert empty.returncode == 1


def test_the_build_labels_every_image_pass_with_the_pinned_parent():
    text = (ROOT / "scripts/build-image-inner.sh").read_text()
    assert 'BUILD_ARGS=("${HARDWARE_PARENT_LABELS[@]}")' in text
    assert "org.tunaos.hardware-overlay.base-digest=${hardware_parent_digest}" in text
    # Both the primary build and the post-rechunk relabel pass take BUILD_ARGS;
    # chunkah drops config labels, so the relabel pass must carry them.
    assert text.count('"${BUILD_ARGS[@]}"') == 2
    justfile = (ROOT / "Justfile").read_text()
    hardware = justfile.index('"${OVERLAY_TYPE}" == "hardware" ]]; then')
    assert 'published-image-ref.sh "{{ variant }}" "${PARENT_FLAVOR}" ghcr' in justfile[hardware:hardware + 600]


# ── Containerfile.overlay adds the profile and nothing else ───────────────────

def overlay_runs() -> dict[str, str]:
    """script name -> the shell command of the RUN that calls it."""
    text = OVERLAY.read_text().replace("\\\n", " ")
    runs = {}
    for line in text.splitlines():
        match = re.search(r"--mount=type=bind,from=context,source=/,target=/run/context\s+(.*/build_scripts/"
                          r"(00-copy-files|install-tunaos-overrides|90-image-info)\.sh)\s*$", line)
        if line.startswith("RUN") and match:
            runs[match.group(2)] = match.group(1)
    return runs


@pytest.mark.parametrize("overlay_type,ran", [("hardware", False), ("nvidia", True), ("hwe", True)])
def test_a_hardware_overlay_does_not_relay_the_parent(tmp_path, overlay_type, ran):
    runs = overlay_runs()
    assert set(runs) == {"00-copy-files", "install-tunaos-overrides", "90-image-info"}
    context = tmp_path / "context"
    (context / "build_scripts").mkdir(parents=True)
    for name, command in runs.items():
        marker = tmp_path / name
        script = context / "build_scripts" / f"{name}.sh"
        script.write_text(f"#!/bin/sh\ntouch {marker}\n")
        script.chmod(0o755)
        subprocess.run(["sh", "-c", command.replace("/run/context", str(context))],
                       env={"OVERLAY_TYPE": overlay_type, "PATH": os.environ["PATH"]}, check=True)
        assert marker.exists() is ran, f"{name} for OVERLAY_TYPE={overlay_type}"


def test_the_desktop_stage_declares_the_overlay_type_it_tests():
    stage = OVERLAY.read_text().split("FROM overlay-base AS desktop", 1)[1]
    assert "\nARG OVERLAY_TYPE\n" in stage.split("\nRUN", 1)[0]


# ── the x13s inventory asks only for what a module list can show ─────────────

def test_x13s_requires_no_bool_driver_as_a_module():
    """CONFIG_PCIE_QCOM is a bool: built in, absent from modules.builtin, so
    listing pcie_qcom as a required module failed every build (run 42266581085)."""
    # The generated file is what hardware-profile.sh reads; just check pins it to tunaos.toml.
    profiles = json.loads((ROOT / "build_scripts/lib/hardware-profiles.json").read_text())
    profile = profiles["profiles"]["x13s"]["require"]
    assert "pcie_qcom" not in profile["modules"]
    assert "CONFIG_PCIE_QCOM" in profile["kconfig"]
