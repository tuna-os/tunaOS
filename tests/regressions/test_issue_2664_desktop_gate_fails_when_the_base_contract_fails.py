"""tunaOS#2664: no desktop may pass its contract without a system message bus.

A desktop image runs two contracts on one boot: tunaos-base-contract.service
at multi-user and the desktop contract at graphical. yellowfin:kde (run
35957716969) and skipjack:kde (run 34705564876) promoted with dbus-broker and
dbus.socket failed because the Gate read only DESKTOP_CONTRACT_OK. #2664 found
the same false desktop verdict on an installed yellowfin:niri.

What this holds: the desktop contract itself rejects an inactive system bus,
and the disk Gate retains the base-contract verdict as a second, independent
guard.

Falsification: behavioural -- the real `verify_system_bus` function is run
with a resolved but failed dbus-broker unit and must report a desktop failure;
the real `base_contract_failed_on_serial` helper is run against the shipped
serial shape and must report the base failure. Structural wiring tests require
both helpers to run before their respective pass paths.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (ROOT / "scripts" / "iso-e2e.sh").read_text(encoding="utf-8")
DESKTOP_SCRIPT = (
    ROOT / "build_scripts" / "checks" / "verify-desktop-experience.sh"
).read_text(encoding="utf-8")


def _helper() -> str:
    m = re.search(
        r"^base_contract_failed_on_serial\(\) \{\n.*?^\}\n", SCRIPT, re.S | re.M
    )
    assert m, "base_contract_failed_on_serial is not defined in iso-e2e.sh"
    return m.group(0)


def _desktop_bus_helper() -> str:
    m = re.search(
        r"^verify_system_bus\(\) \{\n.*?^\}\n", DESKTOP_SCRIPT, re.S | re.M
    )
    assert m, "verify_system_bus is not defined in verify-desktop-experience.sh"
    return m.group(0)


def _run(tmp_path: Path, serial: str, grace: int = 0) -> subprocess.CompletedProcess:
    log = tmp_path / "serial.log"
    log.write_text(serial, encoding="utf-8")
    script = (
        f"DISK_POLL_INTERVAL=0.05\n{_helper()}\n"
        f"base_contract_failed_on_serial '{log}' {grace}\n"
    )
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True)


def _run_desktop_bus(
    tmp_path: Path, resolved_unit: str, state: str
) -> subprocess.CompletedProcess:
    binder = tmp_path / "bin"
    binder.mkdir()
    systemctl = binder / "systemctl"
    systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        f'  "show -P Id dbus.service") echo "{resolved_unit}" ;;\n'
        f'  "is-active --quiet {resolved_unit}") [[ "{state}" == active ]] ;;\n'
        f'  "is-active {resolved_unit}") echo "{state}"; '
        f'[[ "{state}" == active ]] ;;\n'
        "  *) exit 2 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    systemctl.chmod(0o755)
    script = (
        f"PATH='{binder}':/usr/bin:/bin\n"
        'report_fail() { printf "FAIL:%s\\n" "$*"; ok=0; }\n'
        f"{_desktop_bus_helper()}\n"
        "ok=1\n"
        "verify_system_bus\n"
        'printf "ok=%s\\n" "$ok"\n'
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


def test_the_desktop_contract_reports_a_dead_system_bus(tmp_path):
    proc = _run_desktop_bus(tmp_path, "dbus-broker.service", "failed")
    assert proc.returncode == 0, proc.stderr
    assert (
        "FAIL:system_bus_inactive unit=dbus-broker.service state=failed"
        in proc.stdout
    )
    assert "ok=0" in proc.stdout


def test_the_desktop_contract_accepts_an_active_dbus_daemon(tmp_path):
    proc = _run_desktop_bus(tmp_path, "dbus-daemon.service", "active")
    assert proc.returncode == 0, proc.stderr
    assert "FAIL:" not in proc.stdout
    assert "ok=1" in proc.stdout


def test_the_desktop_runtime_checks_the_bus_before_emitting_ok():
    runtime = DESKTOP_SCRIPT.index('if [[ "$mode" == --runtime ]]')
    bus_check = DESKTOP_SCRIPT.index("\tverify_system_bus\n", runtime)
    ok_marker = DESKTOP_SCRIPT.index("TUNAOS_DESKTOP_CONTRACT_OK", bus_check)
    assert runtime < bus_check < ok_marker
