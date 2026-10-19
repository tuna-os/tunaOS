"""Native Grouper canary: common boot proof must precede family exits."""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "build_scripts/40-services.sh"


def _block():
    source = SERVICES.read_text()
    start = source.index("# Base boot contract (")
    end = source.index("systemctl enable tunaos-base-contract.service", start)
    return source[start:end] + "systemctl enable tunaos-base-contract.service\n"


def test_common_contract_precedes_every_family_return():
    source = SERVICES.read_text()
    installed = source.index("systemctl enable tunaos-base-contract.service")
    assert installed < source.index('if [[ "${PKG_MGR:-}" == "apt" ]]; then')
    assert source.count("systemctl enable tunaos-base-contract.service") == 1


@pytest.mark.parametrize("manager", ["apt", "dnf", "pacman", "zypper", "emerge"])
def test_real_install_block_runs_for_every_family(tmp_path, manager):
    script = _block()
    check = tmp_path / "context/build_scripts/checks/verify-base-contract.sh"
    check.parent.mkdir(parents=True)
    check.write_text("#!/bin/sh\necho checked >>\"$TRACE\"\n")
    check.chmod(0o755)
    units = tmp_path / "usr/lib/systemd/system"
    units.mkdir(parents=True)
    script = script.replace("/run/context", str(tmp_path / "context"))
    script = script.replace("/usr/lib", str(tmp_path / "usr/lib"))
    trace = tmp_path / "trace"
    result = subprocess.run(
        ["bash", "-euc", 'systemctl() { echo "$*" >>"$TRACE"; };\n' + script],
        env={**os.environ, "TRACE": str(trace), "PKG_MGR": manager},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert trace.read_text().splitlines() == ["checked", "enable tunaos-base-contract.service"]
    assert (tmp_path / "usr/libexec/tunaos/verify-base-contract").is_file()
    assert "TimeoutStartSec=300" in (units / "tunaos-base-contract.service").read_text()


@pytest.mark.skipif(not shutil.which("systemd-analyze"), reason="systemd-analyze unavailable")
def test_base_contract_graph_has_no_ordering_cycle(tmp_path):
    unit = re.search(r"<<'UNIT'\n(.*?)\nUNIT", _block(), re.S).group(1)
    # Use an executable present on the test host; validate the real ordering.
    unit = re.sub(r"ExecStart=.*", "ExecStart=/bin/true", unit)
    (tmp_path / "tunaos-base-contract.service").write_text(unit)
    (tmp_path / "multi-user.target").write_text(
        "[Unit]\nDescription=Test multi-user\nWants=tunaos-base-contract.service\n"
    )
    result = subprocess.run(
        ["systemd-analyze", "--user", "verify", str(tmp_path / "multi-user.target")],
        env={**os.environ, "SYSTEMD_UNIT_PATH": f"{tmp_path}:/usr/lib/systemd/user", "XDG_RUNTIME_DIR": str(tmp_path)},
        text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert "cycle" not in result.stderr.lower()


@pytest.mark.parametrize("runtime", [True, False])
def test_marker_only_mirrors_to_character_device_at_runtime(tmp_path, runtime):
    import pty
    master, slave = pty.openpty()
    try:
        device = os.ttyname(slave)
        source = (ROOT / "build_scripts/checks/verify-base-contract.sh").read_text()
        prefix = source[:source.index("\nfail() {")].replace("/dev/ttyS0", device)
        result = subprocess.run(
            ["bash", "-c", prefix + '\nemit_marker "TUNAOS_BASE_CONTRACT_OK test=yes"',
             "test", "--runtime" if runtime else ""], capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == "TUNAOS_BASE_CONTRACT_OK test=yes\n"
        os.set_blocking(master, False)
        if runtime:
            assert b"TUNAOS_BASE_CONTRACT_OK test=yes" in os.read(master, 1024)
        else:
            with pytest.raises(BlockingIOError):
                os.read(master, 1024)
    finally:
        os.close(master)
        os.close(slave)


def test_marker_never_creates_a_missing_serial_device(tmp_path):
    device = tmp_path / "ttyS0"
    source = (ROOT / "build_scripts/checks/verify-base-contract.sh").read_text()
    prefix = source[:source.index("\nfail() {")].replace("/dev/ttyS0", str(device))
    result = subprocess.run(
        ["bash", "-c", prefix + '\nemit_marker "TUNAOS_BASE_CONTRACT_FAIL test=yes"',
         "test", "--runtime"], capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert not device.exists()
