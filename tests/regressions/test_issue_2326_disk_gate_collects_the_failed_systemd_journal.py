"""tunaOS#2326: a disk Gate failure must preserve the journal it points to.

The yellowfin GNOME Gate serial console only said to run ``systemctl status``.
The harness had already prepared credentialed root-over-vsock access, but its
``--disk`` QEMU command never attached the vsock device, so the failed guest's
journal and dbus-broker coredump metadata disappeared with the VM.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (ROOT / "scripts" / "iso-e2e.sh").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github" / "workflows" / "reusable-build-image.yml").read_text(
    encoding="utf-8"
)


def _between(start: str, end: str) -> str:
    return SCRIPT.split(start, 1)[1].split(end, 1)[0]


def test_disk_qemu_attaches_the_prepared_vsock_credentials():
    disk_boot = _between("boot_disk_image() {", "# ── Main")
    assert '"${VSOCK_ARGS[@]}"' in disk_boot
    assert "vhost-vsock-pci" in SCRIPT
    assert "ssh.ephemeral-authorized_keys-all" in SCRIPT


def test_missing_contract_collects_diagnostics_before_evidence_capture():
    # Slice the DISPATCH arm, not "everything after the first case header".
    # iso-e2e.sh contains three `case "$MODE" in` statements; splitting on the
    # first one grabbed a region starting ~1600 lines above the dispatch, so
    # the .index() calls below matched helper definitions instead of the arm
    # and the test failed whenever anything shifted around them. Anchor on the
    # `disk)` arm of the last one, which is what this test is about.
    dispatch = SCRIPT.rsplit('case "$MODE" in', 1)[1]
    disk_mode = dispatch.split("\ndisk)", 1)[1].split("\n\t;;", 1)[0]
    collect = disk_mode.index("collect_disk_boot_diagnostics")
    paint = disk_mode.index('wait_for_paint "10-ready"')
    assert collect < paint
    assert '[[ "$rc" -eq 2 ]]' in disk_mode[:collect]


def test_diagnostics_include_the_failed_bus_and_coredump_metadata():
    diagnostics = _between("collect_disk_boot_diagnostics() {", "boot_disk_image() {")
    assert "systemctl --failed" in diagnostics
    assert "systemctl status dbus-broker.service dbus.socket" in diagnostics
    assert "journalctl -b" in diagnostics
    assert "coredumpctl" in diagnostics
    assert '${OUTPUT_DIR}/boot-diagnostics.txt' in diagnostics


def test_workflow_uploads_the_diagnostics_even_when_the_gate_fails():
    assert "- name: Upload boot evidence\n        if: always()" in WORKFLOW
    assert "verify-out/boot-diagnostics.txt" in WORKFLOW
