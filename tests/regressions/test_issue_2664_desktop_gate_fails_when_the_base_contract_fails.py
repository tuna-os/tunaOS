"""tunaOS#2664: a desktop Gate must not pass a boot whose base contract failed.

A desktop image runs two contracts on one boot: tunaos-base-contract.service
at multi-user (it asserts the system bus) and the desktop contract at
graphical. `scripts/iso-e2e.sh --disk` waited for the desktop marker alone.
yellowfin:kde (run 35957716969) and skipjack:kde (run 34705564876) promoted
with dbus-broker and dbus.socket failed, because SDDM starts without the bus
and the desktop contract printed OK anyway. #2664 found the same shape on an
installed yellowfin:niri.

Falsification: behavioural for the helper (the real
`base_contract_failed_on_serial` is sliced out of iso-e2e.sh and run against
a serial log carrying DESKTOP_CONTRACT_OK plus BASE_CONTRACT_FAIL; it must
report the failure). Structural for the wiring: confirmed red by deleting the
`base_contract_failed_on_serial` call from the disk arm, which fails
`test_the_disk_arm_checks_the_base_contract_before_it_passes`.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (ROOT / "scripts" / "iso-e2e.sh").read_text(encoding="utf-8")


def _helper() -> str:
    m = re.search(
        r"^base_contract_failed_on_serial\(\) \{\n.*?^\}\n", SCRIPT, re.S | re.M
    )
    assert m, "base_contract_failed_on_serial is not defined in iso-e2e.sh"
    return m.group(0)


def _run(tmp_path: Path, serial: str, grace: int = 0) -> subprocess.CompletedProcess:
    log = tmp_path / "serial.log"
    log.write_text(serial, encoding="utf-8")
    script = (
        f"DISK_POLL_INTERVAL=0.05\n{_helper()}\n"
        f"base_contract_failed_on_serial '{log}' {grace}\n"
    )
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True)


# The serial shape from the false-green yellowfin:kde boot, trimmed.
DEAD_BUS = (
    "dbus-broker-launch: Access denied in /etc/selinux/targeted/contexts/dbus_contexts +1\r\n"
    "TUNAOS_BASE_CONTRACT_FAIL reason=system-bus-inactive unit=dbus-broker.service state=failed\r\n"
    "TUNAOS_DESKTOP_CONTRACT_OK desktop=kde experience=full\r\n"
)


def test_a_failed_base_contract_is_reported_as_failed(tmp_path):
    proc = _run(tmp_path, DEAD_BUS)
    assert proc.returncode == 0, "a BASE_CONTRACT_FAIL on the serial log must count"
    assert "system-bus-inactive" in proc.stderr, "the reason must reach the job log"


def test_a_passing_base_contract_does_not_fail_the_gate(tmp_path):
    proc = _run(
        tmp_path,
        "TUNAOS_BASE_CONTRACT_OK state=running bus=dbus-broker.service\n"
        "TUNAOS_DESKTOP_CONTRACT_OK desktop=kde experience=full\n",
    )
    assert proc.returncode == 1


def test_an_image_without_the_base_unit_only_warns(tmp_path):
    proc = _run(tmp_path, "TUNAOS_DESKTOP_CONTRACT_OK desktop=kde\n", grace=0)
    assert proc.returncode == 1, "an image with no base unit must not be failed"
    assert "system bus unverified" in proc.stderr


def test_a_late_base_verdict_is_waited_for(tmp_path):
    # The base unit can still be running when the desktop marker lands.
    log = tmp_path / "serial.log"
    log.write_text("TUNAOS_DESKTOP_CONTRACT_OK desktop=kde\n", encoding="utf-8")
    script = (
        f"DISK_POLL_INTERVAL=0.05\n{_helper()}\n"
        f"( sleep 0.3; echo 'TUNAOS_BASE_CONTRACT_FAIL reason=bootc-status-failed' >> '{log}' ) &\n"
        f"base_contract_failed_on_serial '{log}' 5\n"
    )
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert proc.returncode == 0
    assert "bootc-status-failed" in proc.stderr


def test_the_disk_arm_checks_the_base_contract_before_it_passes():
    dispatch = SCRIPT.rsplit('case "$MODE" in', 1)[1]
    disk_arm = dispatch.split("\ndisk)", 1)[1].split("\nready)", 1)[0]
    ok = disk_arm.index('contract passed (serial)"')
    call = disk_arm.index("base_contract_failed_on_serial")
    harvest = disk_arm.index("harvest_install_checks")
    assert ok < call < harvest
    # Only the desktop contract needs the second check; the base contract IS
    # the verdict for base cells.
    assert '"$DISK_CONTRACT" == desktop' in disk_arm[ok:harvest]
