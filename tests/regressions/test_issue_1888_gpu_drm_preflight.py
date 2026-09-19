"""tunaOS#1888: GPU-less runners made desktop defects indistinguishable.

Run 33041330231 measured that the GPU Gate never acquired a runner because the
account's g4dn vCPU quota was zero. When a runner did attach, the Gate could
silently fall back to plain virtio and recorded no QEMU/Mesa/DRM fingerprint.
These tests hold the pre-image capability verdict, summary, evidence artifact,
and strict virgl selection.

Falsification: behavioural tests run the real preflight with and without a
render node; the structural test fails when the preflight is removed, moved
after image execution, or its evidence/strict mode is disconnected.
"""
from __future__ import annotations

import os
import pathlib
import subprocess

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "gpu-drm-preflight.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "reusable-build-image.yml"


def _qemu_stub(tmp_path: pathlib.Path) -> pathlib.Path:
    stub = tmp_path / "qemu"
    stub.write_text(
        """#!/bin/sh
case "$1 $2" in
  "--version ") echo 'QEMU emulator version 9.2.0-test' ;;
  "-device help") echo 'name "virtio-vga-gl"' ;;
  "-display help") echo 'egl-headless' ;;
esac
"""
    )
    stub.chmod(0o755)
    return stub


def _environment(tmp_path: pathlib.Path, qemu: pathlib.Path) -> dict[str, str]:
    dev = tmp_path / "dev"
    (dev / "dri").mkdir(parents=True)
    kvm = dev / "kvm"
    kvm.touch()
    kvm.chmod(0o666)
    summary = tmp_path / "summary.md"
    env = os.environ.copy()
    env.update(
        {
            "QEMU": str(qemu),
            "TUNAOS_PREFLIGHT_DEV_ROOT": str(dev),
            "TUNAOS_PREFLIGHT_KVM_DEVICE": str(kvm),
            "TUNAOS_PREFLIGHT_SYS_ROOT": str(tmp_path / "sys"),
            "GITHUB_STEP_SUMMARY": str(summary),
        }
    )
    return env


def test_capable_runner_records_the_fingerprint_and_display_mode(tmp_path):
    qemu = _qemu_stub(tmp_path)
    env = _environment(tmp_path, qemu)
    render = tmp_path / "dev" / "dri" / "renderD128"
    render.touch()
    output = tmp_path / "evidence" / "runner-capability.txt"

    result = subprocess.run(
        [str(SCRIPT), "--require-virgl", "--output", str(output)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    evidence = output.read_text()
    assert "status=available mode=virgl required_virgl=1" in evidence
    assert "QEMU emulator version 9.2.0-test" in evidence
    assert "drm:" in evidence and "renderD128" in evidence
    assert "mesa:" in evidence
    summary = pathlib.Path(env["GITHUB_STEP_SUMMARY"]).read_text()
    assert "Verdict: **available**" in summary
    assert "QEMU display mode: `virgl`" in summary


def test_missing_render_node_is_infrastructure_unavailable_not_a_desktop_failure(
    tmp_path,
):
    qemu = _qemu_stub(tmp_path)
    env = _environment(tmp_path, qemu)

    result = subprocess.run(
        [str(SCRIPT), "--require-virgl"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 78
    assert "status=infrastructure-unavailable mode=plain" in result.stdout
    assert "DRM render node is missing" in result.stdout
    assert "GPU/DRM infrastructure unavailable" in result.stderr


def test_missing_qemu_is_unavailable_even_when_virgl_is_not_required(tmp_path):
    missing_qemu = tmp_path / "missing-qemu"
    env = _environment(tmp_path, missing_qemu)

    result = subprocess.run(
        [str(SCRIPT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 78
    assert "status=infrastructure-unavailable mode=plain" in result.stdout
    assert "QEMU is unavailable" in result.stdout


def test_gate_runs_the_preflight_before_building_or_booting_the_image():
    document = yaml.safe_load(WORKFLOW.read_text())
    steps = document["jobs"]["verify_boot"]["steps"]
    names = [step.get("name") for step in steps]

    preflight = names.index("Record GPU/DRM runner capability")
    assert preflight < names.index("Build qcow2 from testing image")
    assert preflight < names.index("Boot and verify")

    preflight_step = steps[preflight]
    assert "--require-virgl" in preflight_step["run"]
    assert "GITHUB_STEP_SUMMARY" in SCRIPT.read_text()

    boot = steps[names.index("Boot and verify")]
    assert "TBOX_E2E_GPU" in boot["env"]
    assert "virgl" in boot["env"]["TBOX_E2E_GPU"]

    upload = steps[names.index("Upload boot evidence")]
    assert "verify-out/runner-capability.txt" in upload["with"]["path"]
