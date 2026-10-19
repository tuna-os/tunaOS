"""Static strict-offline-GUI qualification checks (no VMs, no KVM).

Asserts source-text properties of the harness, walkthrough, and parity
workflow plus argument-parsing behavior only. Never boots QEMU.
"""

import re
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


def test_r2_strict_path_resolves_source_and_installer_inputs_before_boot():
    text = _text(ISO_WORKFLOW)
    provenance = text.split("name: Resolve immutable R2 qualification inputs", 1)[1]
    assert "skopeo inspect" in provenance
    assert "TUNAOS_QUAL_SOURCE_DIGEST" in provenance
    assert "TUNAOS_QUAL_INSTALLER_DIGEST" in provenance
    assert 'sha256sum live-iso/common/src/customize-live.sh' in provenance

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
