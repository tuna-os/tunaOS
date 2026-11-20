"""A hardware overlay cannot be promoted on Sign alone.

bonito:gnome-x13s is arm64-only, so the x86 boot Gate and the Desktop contract
both skip it, and Promote reads a skip as a pass: Sign was the only job between
its build and its bare tag. The Hardware overlay gate runs for every flavor
with a `hardware` profile, on a runner of the image's architecture, and checks
the pushed bytes (scripts/verify-hardware-overlay.sh) and a real `bootc install
to-disk` plus a generic-machine boot (scripts/hardware-overlay-install-smoke.sh).

Falsification: behavioural -- drop `verify_hardware` from Promote's `needs` or
its result check, stop passing `hardware-profile` from build-variant.yml, or
make verify-hardware-overlay.sh ignore the package diff or an unresolvable
parent label, and the matching tests below fail.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
VARIANT_WORKFLOW = ROOT / ".github/workflows/build-variant.yml"
REUSABLE = ROOT / ".github/workflows/reusable-build-image.yml"
VERIFY = ROOT / "scripts/verify-hardware-overlay.sh"
SMOKE = ROOT / "scripts/hardware-overlay-install-smoke.sh"

DIGEST = "sha256:" + "1" * 64
IMAGE = "ghcr.io/tuna-os/bonito:gnome-x13s-candidate"
PARENT = "ghcr.io/tuna-os/bonito:gnome"


def workflow(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


# ── wiring ───────────────────────────────────────────────────────────────────

def test_promote_waits_for_the_hardware_gate():
    jobs = workflow(REUSABLE)["jobs"]
    promote = jobs["tag-image"]
    assert "verify_hardware" in promote["needs"]
    assert ("(needs.verify_hardware.result == 'success' || "
            "needs.verify_hardware.result == 'skipped')") in promote["if"]
    gate = jobs["verify_hardware"]
    assert gate["needs"] == "manifest"
    assert "inputs.hardware-profile != ''" in gate["if"]
    assert "ubuntu-24.04-arm" in gate["runs-on"]
    runs = "\n".join(step.get("run", "") for step in gate["steps"])
    assert "scripts/verify-hardware-overlay.sh" in runs
    assert "scripts/hardware-overlay-install-smoke.sh" in runs
    assert "${DEFAULT_TAG}-candidate" in runs


def test_every_stage_passes_the_flavor_hardware_profile():
    jobs = workflow(VARIANT_WORKFLOW)["jobs"]
    calls = {name: job for name, job in jobs.items()
             if str(job.get("uses", "")).endswith("reusable-build-image.yml")}
    assert {"build_base", "build_stage2", "build_stage3", "build_stage4"} <= set(calls)
    for name, job in calls.items():
        assert job["with"]["hardware-profile"] == "${{ matrix.hardware }}", name
    doc = workflow(REUSABLE)
    inputs = doc.get("on", doc.get(True))["workflow_call"]["inputs"]
    assert inputs["hardware-profile"]["default"] == ""


def _matrix_program() -> str:
    text = VARIANT_WORKFLOW.read_text()
    start = text.index("FULL_MATRIX=$(jq -c --arg event ")
    first = text.index("'", start) + 1
    return text[first: text.index("' \"$CONFIG_JSON\"", first)]


def test_the_matrix_row_carries_the_profile(tmp_path):
    jq = shutil.which("jq")
    if jq is None:
        pytest.skip("jq is not installed")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"variants": [{"id": "bonito", "platforms": ["linux/arm64"], "flavors": [
        {"id": "gnome", "stage": 2, "build_image": True},
        {"id": "gnome-x13s", "hardware": "x13s", "parent": "gnome", "stage": 3, "build_image": True},
    ]}]}))
    rows = {}
    for flavor in ("gnome", "gnome-x13s"):
        out = subprocess.run(
            [jq, "-c", "--arg", "event", "workflow_dispatch", "--argjson", "dow", "3", _matrix_program(), str(config)],
            env={"FILTER_VARIANT": "bonito", "FILTER_FLAVOR": flavor, "PATH": os.environ["PATH"]},
            capture_output=True, text=True, check=True).stdout
        rows.update({r["flavor"]: r for r in map(json.loads, out.splitlines())})
    assert rows["gnome-x13s"]["hardware"] == "x13s"
    assert rows["gnome"]["hardware"] == ""
    stage_matrix = VARIANT_WORKFLOW.read_text().split("make_image_matrix() {", 1)[1].split("}'", 1)[0]
    assert "hardware:      .hardware" in stage_matrix


# ── verify-hardware-overlay.sh: what it concludes from what the image says ───

def run_verify(tmp_path: Path, *, label: str = DIGEST, parent_resolves: bool = True,
               inner: str = "PASS inventory: ok", added: str = "qcom-firmware", removed: str = ""):
    """Stub podman/skopeo: the image is the parent's packages plus `added` minus `removed`."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    base = ["bash", "glibc", "kernel", "mesa"]
    image_pkgs = sorted(set(base) - set(removed.split()) | set(added.split()))
    (tmp_path / "parent.txt").write_text("\n".join(base) + "\n")
    (tmp_path / "image.txt").write_text("\n".join(image_pkgs) + "\n")
    podman = bin_dir / "podman"
    podman.write_text("#!/usr/bin/env bash\n" + textwrap.dedent(f"""\
        case "$1" in
        pull) exit 0 ;;
        image)
            case "$*" in
            *base-digest*) echo '{label}' ;;
            *base-image*) echo '{PARENT}' ;;
            esac ;;
        run)
            for arg in "$@"; do last="$arg"; done
            if [[ "$last" == rpm* ]]; then
                if [[ "$*" == *"{PARENT}@"* ]]; then cat {tmp_path}/parent.txt; else cat {tmp_path}/image.txt; fi
            else
                printf '%s\\n' {json.dumps(inner)}
            fi ;;
        esac
    """))
    podman.chmod(0o755)
    skopeo = bin_dir / "skopeo"
    skopeo.write_text(f"#!/usr/bin/env bash\nexit {0 if parent_resolves else 1}\n")
    skopeo.chmod(0o755)
    return subprocess.run(["bash", str(VERIFY), IMAGE, "x13s"],
                          env=os.environ | {"PODMAN": str(podman), "SKOPEO": str(skopeo)},
                          text=True, capture_output=True)


def test_an_image_that_is_its_parent_plus_the_profile_passes(tmp_path):
    proc = run_verify(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert f"PASS labels: parent {PARENT}@{DIGEST}" in proc.stdout
    assert "PASS packages: parent + qcom-firmware" in proc.stdout


@pytest.mark.parametrize("kwargs,expected", [
    ({"label": ""}, "FAIL labels"),
    ({"parent_resolves": False}, "FAIL labels: parent"),
    ({"added": "qcom-firmware tunaos-extra"}, "FAIL packages: added 'qcom-firmware tunaos-extra'"),
    ({"removed": "mesa"}, "removed 'mesa'"),
    ({"inner": "FAIL initramfs: missing msm"}, "FAIL initramfs: missing msm"),
], ids=["no-label", "parent-gone", "extra-package", "removed-package", "inner-check"])
def test_anything_else_fails_the_gate(tmp_path, kwargs, expected):
    proc = run_verify(tmp_path, **kwargs)
    assert proc.returncode == 1, proc.stdout
    assert expected in proc.stdout


def test_the_in_image_checks_cover_the_profile():
    text = VERIFY.read_text()
    for check in ("FAIL inventory", "FAIL kargs", "FAIL devicetree", "FAIL devicetree-hook", "FAIL initramfs"):
        assert check in text


# ── hardware-overlay-install-smoke.sh ────────────────────────────────────────

def test_the_smoke_checks_the_entry_before_it_boots_a_generic_machine():
    text = SMOKE.read_text()
    install = text.index("bootc install to-disk --via-loopback")
    devicetree = text.index("FAIL entry: no devicetree line")
    drop = text.index("sed -i '/^devicetree[[:space:]]/d'")
    boot = text.index('"${qemu[@]}"')
    assert install < devicetree < drop < boot
    assert "probe_image_backend" in text  # sealed images install on ext4


def test_the_smoke_refuses_a_bad_profile_before_touching_a_disk(tmp_path):
    proc = subprocess.run(["bash", str(SMOKE), IMAGE, "no-such-profile", str(tmp_path / "w")],
                          text=True, capture_output=True)
    assert proc.returncode != 0
    assert not (tmp_path / "w" / "disk.raw").exists()
