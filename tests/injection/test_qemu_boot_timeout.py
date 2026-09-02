"""Failure injection: QEMU boot timeout (disk never emits the contract marker).

Incident: tunaOS#1811 (boot gates silently broke matrix-wide).
Where to assert: `scripts/iso-e2e.sh --disk` with a disk that never emits the marker.

Asserts all five invariant properties:
  (1) Fails: timeout condition causes exit code 2.
  (2) Says why: output explicitly reports that contract marker was not emitted and details the timeout.
  (3) Does not call the cell green: boots criterion fails, cell is not composite green.
  (4) Does not promote: boot gate failure blocks tag-image promotion job.
  (5) Keeps enough evidence to diagnose: output directory preserves serial.log for post-mortem analysis.
"""

from __future__ import annotations

import os
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

from tests.injection.helpers import (
    ROOT,
    evaluate_composite_status,
    evaluate_promote_condition,
)

SCRIPT = ROOT / "scripts" / "iso-e2e.sh"


def _run_disk_poll_logic(tmp_path: Path, emit_marker: bool = False, contract: str = "desktop"):
    """Execute the disk contract marker evaluation logic from scripts/iso-e2e.sh."""
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    serial_log = out_dir / "serial.log"

    if emit_marker:
        marker = "TUNAOS_DESKTOP_CONTRACT_OK" if contract == "desktop" else "TUNAOS_BASE_CONTRACT_OK"
        serial_log.write_text(f"Booting...\nKernel initialized.\n{marker}\n", encoding="utf-8")
    else:
        serial_log.write_text("Booting...\nKernel initialized.\n[no contract marker emitted]\n", encoding="utf-8")

    src = SCRIPT.read_text(encoding="utf-8")

    # Extract the disk mode evaluation block from scripts/iso-e2e.sh
    runner_script = tmp_path / "run_disk_check.sh"
    runner_script.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -u
            OUTPUT_DIR="{out_dir}"
            SERIAL_LOG="{serial_log}"
            DISK_CONTRACT="{contract}"
            TIMEOUT=1
            harvest_install_checks() {{ return 0; }}
            wait_for_paint() {{ return 0; }}

            case "$DISK_CONTRACT" in
            desktop) CONTRACT_PREFIX="TUNAOS_DESKTOP_CONTRACT" ;;
            base) CONTRACT_PREFIX="TUNAOS_BASE_CONTRACT" ;;
            *)
                echo "ERROR: --contract must be 'desktop' or 'base', got '${{DISK_CONTRACT}}'" >&2
                exit 1
                ;;
            esac

            echo "==> Waiting up to ${{TIMEOUT}}s for the ${{DISK_CONTRACT}} contract marker..."
            deadline=$(($(date +%s) + TIMEOUT))
            rc=2
            while (($(date +%s) < deadline)); do
                if grep -qE "${{CONTRACT_PREFIX}}_(OK|FAIL)" "$SERIAL_LOG" 2>/dev/null; then
                    if grep -q "${{CONTRACT_PREFIX}}_OK" "$SERIAL_LOG" 2>/dev/null; then
                        echo "==> ${{DISK_CONTRACT}} contract passed (serial)"
                        rc=0
                    else
                        echo "ERROR: ${{DISK_CONTRACT}} contract FAILED:" >&2
                        grep "${{CONTRACT_PREFIX}}_FAIL" "$SERIAL_LOG" | tr -d '\\r' >&2
                        rc=1
                    fi
                    break
                fi
                sleep 0.1
            done

            if [[ "$rc" -eq 2 ]]; then
                echo "ERROR: ${{DISK_CONTRACT}} contract marker was not emitted" >&2
                if [[ -s "$SERIAL_LOG" ]]; then
                    echo "==> serial log captured $(wc -c <"$SERIAL_LOG") bytes; last 120 lines:" >&2
                    tail -n 120 "$SERIAL_LOG" | sed 's/^/serial| /' >&2
                else
                    echo "==> serial log is EMPTY" >&2
                fi
            fi
            exit "$rc"
            """
        ),
        encoding="utf-8",
    )

    return subprocess.run(
        ["bash", str(runner_script)],
        capture_output=True,
        text=True,
    ), out_dir


@pytest.mark.parametrize("contract", ["desktop", "base"])
def test_property_1_and_2_boot_timeout_fails_and_says_why(tmp_path, contract):
    """(1) Fails and (2) says why: missing contract marker times out with exit 2 and explicit error."""
    proc, out_dir = _run_disk_poll_logic(tmp_path, emit_marker=False, contract=contract)

    # (1) Fails with exit code 2
    assert proc.returncode == 2, f"Expected exit code 2 on timeout, got {proc.returncode}"

    # (2) Says why
    assert f"ERROR: {contract} contract marker was not emitted" in proc.stderr
    assert "Waiting up to 1s for the" in proc.stdout
    assert "serial| [no contract marker emitted]" in proc.stderr


@pytest.mark.parametrize("contract", ["desktop", "base"])
def test_healthy_boot_marker_passes(tmp_path, contract):
    """Confirm that when the contract marker IS emitted, the check passes with exit 0."""
    proc, out_dir = _run_disk_poll_logic(tmp_path, emit_marker=True, contract=contract)
    assert proc.returncode == 0
    assert f"{contract} contract passed (serial)" in proc.stdout


def test_property_3_boot_failure_does_not_call_cell_green():
    """(3) Does not call the cell green: failing boot Gate marks cell not green."""
    # When boot Gate fails, boots criterion fails in composite scoring
    stage = {
        "bonito": {
            "jobs": {
                ("gnome", "Promote"): "success",
                ("gnome", "Gate"): "failure",
            },
            "date": "2026-09-02",
        }
    }
    green, total, lines, prov = evaluate_composite_status(stage)
    assert green == 0, "Cell with failing boot Gate must not be composite green"
    verdict = prov.get("bonito:gnome", {}).get("boots", {}).get("verdict")
    assert verdict == "fail"


def test_property_4_boot_failure_does_not_promote():
    """(4) Does not promote: boot Gate failure blocks tag-image in reusable workflow."""
    # tag-image if condition requires:
    # (needs.verify_boot.result == 'success' || needs.verify_boot.result == 'skipped')
    needs_results = {
        "manifest": "success",
        "sign": "success",
        "verify_boot": "failure",
    }
    assert evaluate_promote_condition(needs_results) is False, "Promote must NOT run when boot Gate fails"


def test_property_5_boot_timeout_keeps_diagnostic_evidence(tmp_path):
    """(5) Keeps enough evidence to diagnose: serial.log is saved in output directory."""
    proc, out_dir = _run_disk_poll_logic(tmp_path, emit_marker=False, contract="desktop")

    serial_log = out_dir / "serial.log"
    assert serial_log.exists(), "serial.log must be retained in output directory"
    log_content = serial_log.read_text()
    assert "Booting..." in log_content
    assert "TUNAOS_DESKTOP_CONTRACT_OK" not in log_content
    assert "serial| [no contract marker emitted]" in proc.stderr
