"""The installed runtime checks print the kernel boot ID on serial.

The strict browser-ISO harness proves a warm reboot is a distinct boot of the
same deployment by comparing TUNAOS_BOOT_ID across the cold and warm boots. On
an installed boot with no SSH (composefs cells such as sailfin) the serial
console is the only channel, so an image without this line can never pass.
"""

import re
import subprocess
from pathlib import Path

SCRIPT = (Path(__file__).parents[1] / "build_scripts/checks/e2e-runtime-checks.sh").read_text()


def _boot_id_block():
    start = SCRIPT.index("# The kernel's per-boot UUID")
    end = SCRIPT.index("unset runtime_boot_id", start) + len("unset runtime_boot_id")
    return SCRIPT[start:end]


def test_runtime_checks_emit_the_kernel_boot_id():
    result = subprocess.run(
        ["bash", "-c", 'emit() { echo "$1"; }\n' + _boot_id_block()],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    assert result.stdout == f"TUNAOS_BOOT_ID {boot_id}\n"
    assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", boot_id)


def test_runtime_checks_skip_a_malformed_boot_id(tmp_path):
    fake = tmp_path / "boot_id"
    fake.write_text("-" * 36 + "\n")
    block = _boot_id_block().replace("/proc/sys/kernel/random/boot_id", str(fake))
    result = subprocess.run(
        ["bash", "-c", 'emit() { echo "$1"; }\n' + block],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
