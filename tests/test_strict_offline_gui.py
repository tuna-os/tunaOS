"""Static strict-offline-GUI qualification checks (no VMs, no KVM).

Asserts source-text properties of the harness, walkthrough, and parity
workflow plus argument-parsing behavior only. Never boots QEMU.
"""

import re
import json
import os

import pytest
import yaml
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
E2E = ROOT / "scripts" / "iso-e2e.sh"
WALKTHROUGH = ROOT / "scripts" / "installer-walkthrough.py"
WORKFLOW = ROOT / ".github" / "workflows" / "iso-builder-parity.yml"
ISO_WORKFLOW = ROOT / ".github" / "workflows" / "iso-e2e.yml"

HEAVY_SUFFIXES = (".qcow2", ".iso", ".ppm")


def _text(path):
    return path.read_text(encoding="utf-8")


def test_e2e_refuses_fisherman_override_with_exit_2():
    text = _text(E2E)
    assert "FISHERMAN_OVERRIDE" in text
    assert re.search(
        r"FISHERMAN_OVERRIDE.*\n.*exit 2|--strict-offline-gui refuses FISHERMAN_OVERRIDE",
        text,
    )
    assert "--strict-offline-gui refuses FISHERMAN_OVERRIDE" in text


def test_e2e_refuses_host_image_generic_cli_with_exit_2():
    text = _text(E2E)
    assert "TBOX_E2E_IMAGE" in text
    assert "--strict-offline-gui refuses TBOX_E2E_IMAGE" in text
    assert (
        "--strict-offline-gui refuses the generic bootc install CLI fallback"
        in text
    )


def test_e2e_install_phase_netdev_lines_carry_restrict():
    text = _text(E2E)
    assert 'STRICT_NETDEV_RESTRICT=",restrict=on"' in text
    netdev_lines = [
        line for line in text.splitlines() if '-netdev "user' in line
    ]
    assert netdev_lines, "expected QEMU user-netdev lines"
    for line in netdev_lines:
        assert "STRICT_NETDEV_RESTRICT" in line, f"line lacks restrict suffix: {line}"


def test_walkthrough_bogus_mode_exits_2():
    proc = subprocess.run(
        [sys.executable, str(WALKTHROUGH), "--mode=bogus"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 2
    assert "--mode must be plain|luks" in proc.stderr


def test_walkthrough_strict_sequence_covers_install():
    text = _text(WALKTHROUGH)
    for screen in ("welcome", "disk", "encryption", "summary", "install", "done"):
        assert f'"{screen}"' in text


def test_parity_workflow_runs_strict_mode_for_both_sources():
    text = _text(WORKFLOW)
    assert text.count("--strict-offline-gui") >= 2
    assert "qualification-evidence.json" in text
    assert "verify-experience-manifest.py" in text

def test_iso_e2e_strict_failure_cannot_become_green():
    text = _text(ISO_WORKFLOW)
    strict_step = text.split("name: Run strict offline GUI qualification", 1)[1]
    assert "--strict-offline-gui" in strict_step
    assert "qualification-evidence.json" in strict_step
    assert 'if [[ "$rc" -ne 0 ]]' in strict_step
    assert 'exit "$rc"' in strict_step
    assert "name: Fail on e2e error" in strict_step


def test_iso_strict_path_uses_embedded_source_and_separate_media_identity():
    text = _text(ISO_WORKFLOW)
    provenance = text.split("name: Resolve immutable ISO qualification inputs", 1)[1]
    assert "live-source.json" in provenance
    assert "TUNAOS_QUAL_SOURCE_DIGEST" in provenance
    assert "TUNAOS_QUAL_OVERLAY_DIGEST" in provenance
    assert "TUNAOS_QUAL_ENGINE_DIGEST" in provenance
    assert "TUNAOS_QUAL_MEDIA_DIGEST" in provenance
    assert "TUNAOS_QUAL_INSTALLER_DIGEST" in provenance
    assert "engine_digest" in provenance
    assert 'unsquashfs -cat' in provenance
    assert 'etc/tunaos/live-installer-info' in provenance
    assert 'INSTALLER_BUNDLE_SHA256' in provenance
    assert 'INSTALLER_REVISION' in provenance
    assert 'sha256sum "$ISO_PATH"' in provenance
    assert 'sha256sum live-iso/common/src/customize-live.sh' not in provenance
    assert "sha256sum --check --strict" in text


def test_published_media_has_bounded_display_and_serial_identity_fallback():
    workflow = _text(ISO_WORKFLOW)
    harness = _text(E2E)
    assert "wait_for_strict_live_ready" in harness
    assert "screenshot_sane" in harness
    assert "TUNAOS_IMAGE_IDENTITY digest=" in _text(
        ROOT / "build_scripts" / "checks" / "e2e-runtime-checks.sh"
    )
    assert "STRICT_PUBLISHED_MEDIA=1" in workflow
    assert "STRICT_PUBLISHED_MEDIA=0" in workflow
    assert "TUNAOS_QUAL_BROWSER_NAME=native" not in workflow
    assert "TUNAOS_QUAL_EXECUTION_KIND=native-qemu" in workflow

def test_parity_workflow_upload_has_no_disk_suffixed_paths():
    text = _text(WORKFLOW)
    upload = text.split("Upload parity evidence", 1)[1]
    path_block = upload.split("path: |", 1)[1].split("if-no-files-found", 1)[0]
    for line in path_block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        assert not stripped.endswith(HEAVY_SUFFIXES), f"heavy upload path: {stripped}"


def test_parity_workflow_sets_retention_and_compression():
    text = _text(WORKFLOW)
    assert "retention-days: 1" in text
    assert "compression-level: 0" in text


def test_strict_job_budget_covers_both_input_paths():
    text = _text(ISO_WORKFLOW)
    assert "&& 130 || 70) }}" in text
    assert "inputs.source == 'native-artifact' && 160" in text
    assert text.count("timeout-minutes: 60") == 2


def test_runtime_hashes_do_not_substitute_for_builder_or_frontend_identity():
    script = (ROOT / "scripts/iso-e2e.sh").read_text()
    assert 'STRICT_ENGINE_DIGEST="sha256:$(sha256sum "$QEMU"' not in script
    assert 'STRICT_OVERLAY_DIGEST="sha256:$(sha256sum "$ISO_PATH"' not in script
    strict_capture = script.split('strict_capture_live_inputs() {', 1)[1].split('\n}', 1)[0]
    assert 'sha256sum /usr/local/bin/fisherman' not in strict_capture
    assert "TUNAOS_QUAL_BROWSER_NAME must identify the measured browser" in script
    assert "TUNAOS_QUAL_BROWSER_VERSION must identify the measured browser version" in script


@pytest.mark.parametrize("outcome,rc,expected", [
    ("success", "0", "success"),
    ("success", "1", "failure"),
    ("failure", "0", "failure"),
    ("cancelled", "0", "failure"),
    ("skipped", "", "failure"),
    ("pending", "0", "failure"),
    ("", "", "failure"),
    ("success", "", "failure"),
    ("success", "00", "failure"),
    ("success", "false", "failure"),
    ("success", " 0", "failure"),
])
def test_iso_evidence_status_requires_completed_success(tmp_path, outcome, rc, expected):
    document = yaml.safe_load(ISO_WORKFLOW.read_text())
    step = next(step for job in document["jobs"].values()
                for step in job.get("steps", []) if step.get("name") == "Collect evidence")
    assert step["env"]["E2E_OUTCOME"] == "${{ steps.e2e.outcome }}"
    assert step["env"]["E2E_RC"] == "${{ steps.e2e.outputs.rc }}"
    script = step["run"].replace("${{ matrix.variant }}", "albacore").replace(
        "${{ matrix.flavor }}", "gnome")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/evidence-bundle.sh").symlink_to(ROOT / "scripts/evidence-bundle.sh")
    (tmp_path / "iso-e2e-out").mkdir()
    result = subprocess.run(["bash", "-e", "-c", script], cwd=tmp_path,
                            env={**os.environ, "E2E_OUTCOME": outcome, "E2E_RC": rc,
                                 "EVIDENCE_ARCH": "amd64",
                                 "EVIDENCE_ROOT": str(tmp_path / "evidence")},
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    metadata = json.loads((tmp_path / "evidence/albacore/gnome/amd64/metadata.json").read_text())
    assert metadata["status"] == expected
