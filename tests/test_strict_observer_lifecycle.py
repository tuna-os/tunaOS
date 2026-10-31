"""Strict VM lifecycle with owned local dummy processes; no guest, sockets, or network."""

import os
import re
import subprocess
from pathlib import Path

import pytest

SOURCE = (Path(__file__).parents[1] / "scripts/iso-e2e.sh").read_text()


def function(name):
    start = SOURCE.index(name + "() {")
    body_start = start + len(name + "() {")
    # Python heredocs contain unindented closing braces too. Bound the shell
    # function by the next top-level shell declaration, not the first brace.
    next_function = re.search(r"(?m)^[A-Za-z_][A-Za-z0-9_]*\(\) \{", SOURCE[body_start:])
    if next_function is None:
        raise ValueError(f"no following shell function after {name}")
    return SOURCE[start:body_start + next_function.start()]


@pytest.mark.parametrize("launcher", ["run_strict_gui_install", "strict_launch_installed"])
def test_next_vm_refuses_live_owner_before_touching_disk_or_sockets(tmp_path, launcher):
    disk = tmp_path / "strict-plain-disk.qcow2"
    disk.write_bytes(b"previous owned disk")
    monitor = tmp_path / "monitor.sock"
    monitor.write_bytes(b"previous endpoint")
    trace = tmp_path / "trace"
    body = (
        function("strict_require_vm_stopped") + function(launcher) + """
candidate_require_no_injected_access() { :; }
reset_qemu_sockets() { echo reset >>"$TRACE"; }
qemu-img() { echo disk >>"$TRACE"; }
echo $$ >"$QEMU_PIDFILE"
rc=0
""" + (f'{launcher} plain' if launcher == "run_strict_gui_install"
       else f'{launcher} "$OUTPUT_DIR/strict-plain-disk.qcow2" "" cold')
        + """
rc=$?
exit "$rc"
"""
    )
    result = subprocess.run(
        ["bash", "-c", body], capture_output=True, check=False, timeout=5,
        env={**os.environ, "OUTPUT_DIR": str(tmp_path), "QEMU_PIDFILE": str(tmp_path/"qemu.pid"),
             "TRACE": str(trace)},
    )
    assert result.returncode == 6, result.stderr
    assert disk.read_bytes() == b"previous owned disk"
    assert monitor.read_bytes() == b"previous endpoint"
    assert not trace.exists()


@pytest.mark.parametrize("first_failure", [0, 9])
def test_live_shutdown_failure_is_enforced_without_replacing_first_failure(tmp_path, first_failure):
    body = (
        function("run_strict_gui_install") + """
strict_require_vm_stopped() { :; }
qemu-img() { :; }
boot_live_iso() { return "$FIRST_FAILURE"; }
strict_offline_verify_netdev() { :; }
wait_for_strict_live_ready() { :; }
strict_capture_live_inputs() { :; }
e2e_phase() { :; }
python3() { :; }
check_ssh() { return 1; }
poweroff_and_wait_vm() { return 6; }
INSTALL_DISK=original
rc=0
run_strict_gui_install plain || rc=$?
[[ "$INSTALL_DISK" == original ]] || exit 99
exit "$rc"
"""
    )
    result = subprocess.run(
        ["bash", "-c", body], capture_output=True, check=False, timeout=5,
        env={**os.environ, "OUTPUT_DIR": str(tmp_path), "FIRST_FAILURE": str(first_failure),
             "SCRIPT_DIR": str(Path(__file__).parents[1]/"scripts"), "FLAVOR": "gnome",
             "SERIAL_LOG": str(tmp_path/"serial.log"), "STRICT_PUBLISHED_MEDIA": "1"},
    )
    assert result.returncode == (first_failure or 6), result.stderr


def test_installed_shutdown_failure_cannot_be_ignored_by_helper():
    body = function("strict_poweroff_installed") + """
poweroff_and_wait_vm() { return 6; }
strict_poweroff_installed
"""
    result = subprocess.run(["bash", "-c", body], capture_output=True, check=False, timeout=5)
    assert result.returncode == 6, result.stderr


def test_surviving_plain_vm_blocks_next_firmware_and_tpm_reset(tmp_path):
    iso = tmp_path / "media.iso"
    iso.write_bytes(b"fixture media")
    stale_receipts = [
        tmp_path / relative
        for mode in ("plain", "luks")
        for relative in (
            f"session-{mode}-cold.json", f"session-{mode}-warm.json",
            f"frontend-{mode}.json", f"strict-qual-{mode}.json",
            f"walkthrough-{mode}/walkthrough-gnome.json",
            f"walkthrough-{mode}/walkthrough-xfce.json",
        )
    ]
    for receipt in stale_receipts:
        receipt.parent.mkdir(exist_ok=True)
        receipt.write_bytes(b"obsolete receipt")
    body = (
        function("strict_require_vm_stopped") + function("run_strict_offline_gui") + """
e2e_phase() { :; }
qemu-img() { :; }
strict_offline_evidence() { :; }
strict_require_digest() { :; }
reset_uefi_vars() { echo reset >>"$TRACE"; }
start_swtpm() { echo tpm >>"$TRACE"; }
run_strict_gui_install() {
    echo "install:$1" >>"$TRACE"
    echo $$ >"$QEMU_PIDFILE"
    return 1
}
run_strict_offline_gui
"""
    )
    result = subprocess.run(
        ["bash", "-c", body], capture_output=True, check=False, timeout=5,
        env={**os.environ, "OUTPUT_DIR": str(tmp_path), "TRACE": str(tmp_path/"trace"),
             "QEMU_PIDFILE": str(tmp_path/"qemu.pid"), "ISO_PATH": str(iso), "QEMU": "/bin/true",
             "QUAL_EVIDENCE_JSON": str(tmp_path/"qualification-evidence.json"),
             "STRICT_EVIDENCE_LOG": str(tmp_path/"evidence.log"),
             "STRICT_OFFLINE_GUI_MODES": "plain,luks",
             "TUNAOS_QUAL_OVERLAY_DIGEST": "sha256:"+"a"*64,
             "TUNAOS_QUAL_ENGINE_DIGEST": "sha256:"+"b"*64},
    )
    assert result.returncode == 6, result.stderr
    assert (tmp_path/"trace").read_text().splitlines() == ["reset", "install:plain"]
    assert all(not receipt.exists() for receipt in stale_receipts)


@pytest.mark.parametrize("modes", ["plain", "luks", "plain,luks"])
def test_strict_refusal_removes_only_owned_stale_aggregate(tmp_path, modes):
    aggregate = tmp_path / "qualification-evidence.json"
    aggregate.write_bytes(b"stale aggregate must not survive a new run")
    unrelated = tmp_path / "other-qualification-evidence.json"
    unrelated.write_bytes(b"not owned by this invocation")
    result = subprocess.run(
        ["bash", "-c", function("run_strict_offline_gui") + "run_strict_offline_gui\n"],
        capture_output=True, check=False, timeout=5,
        env={**os.environ, "QUAL_EVIDENCE_JSON": str(aggregate),
             "STRICT_OFFLINE_GUI_MODES": modes, "TUNAOS_LUKS_GRUB_APPEND": "console=ttyS0"},
    )
    assert result.returncode == 2, result.stderr
    assert not aggregate.exists()
    assert unrelated.read_bytes() == b"not owned by this invocation"


@pytest.mark.parametrize("present_mode", [None, "plain", "luks"])
def test_full_emitter_requires_both_mode_fragments(tmp_path, present_mode):
    if present_mode is not None:
        # Deliberately unreadable: the missing-mode guard must run before parsing.
        (tmp_path / f"strict-qual-{present_mode}.json").write_bytes(b"not JSON")
    aggregate = tmp_path / "qualification-evidence.json"
    result = subprocess.run(
        ["bash", "-c", function("emit_qualification_evidence") + "emit_qualification_evidence\n"],
        capture_output=True, check=False, timeout=5,
        env={**os.environ, "OUTPUT_DIR": str(tmp_path),
             "QUAL_EVIDENCE_JSON": str(aggregate), "TUNAOS_QUAL_EXECUTION_KIND": "browser"},
    )
    assert result.returncode == 1, result.stderr
    assert b"missing per-mode qualification fragments" in result.stderr
    assert not aggregate.exists()
