"""Hardware checks accept installed built-in evidence, never configuration alone."""

import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "config,builtin,module,expected",
    [
        ("CONFIG_MFD_MACSMC=y\n", "kernel/drivers/mfd/macsmc.ko\n", "", True),
        ("CONFIG_MFD_MACSMC=y\n", "", "", False),
        ("CONFIG_MFD_MACSMC=m\n", "kernel/drivers/mfd/macsmc.ko\n", "", False),
        ("", "kernel/drivers/mfd/macsmc.ko\n", "", False),
        ("CONFIG_MFD_MACSMC=y\n", "kernel/drivers/mfd/macsmc-other.ko\n", "", False),
        ("CONFIG_MFD_MACSMC=m\n", "", "kernel/drivers/mfd/macsmc.ko.zst:\n", True),
    ],
)
def test_macsmc_requires_matching_installed_evidence(tmp_path, config, builtin, module, expected):
    source = (ROOT / "scripts/verify-asahi-image.sh").read_text()
    start = source.index('for mod in asahi.ko')
    end = source.index('\necho "== devicetrees =="', start)
    for name, contents in (("config", config), ("modules.builtin", builtin), ("modules.dep", module)):
        (tmp_path / name).write_text(contents)
    script = (
        'M="$1"; deps="$M/modules.dep"; is_el10=false\n'
        'ok() { printf "ok %s\\n" "$*"; }\n'
        'bad() { printf "bad %s\\n" "$*"; }\n'
        'note() { printf "warn %s\\n" "$*"; }\n'
        + source[start:end]
    )
    result = subprocess.run(["bash", "-c", script, "verify", str(tmp_path)],
                            capture_output=True, text=True, check=True)
    lines = [line for line in result.stdout.splitlines() if "macsmc.ko" in line]
    assert len(lines) == 1
    assert lines[0].startswith("ok " if expected else "bad ")
    assert "warn" not in lines[0]


def test_sailfin_requires_split_native_boot_packages():
    source = (ROOT / "build_scripts/overlay/asahi.sh").read_text()
    branch = source.split('opensuse* | *suse*)', 1)[1].split('\ngentoo)', 1)[0]
    transaction = branch.split('for attempt in 1 2 3; do', 1)[1].split('&& break', 1)[0]
    for package in ("kernel-asahi", "dtb-apple", "m1n1", "u-boot-asahi", "asahi-scripts",
                    "update-m1n1", "asahi-fwupdate"):
        assert package in transaction.split()
    assert '--no-recommends' in transaction
    assert 'install -D -m 0644 /boot/u-boot-nodtb.bin /usr/lib/asahi-boot/u-boot-nodtb.bin' in branch
    assert 'test -s /usr/lib/asahi-boot/u-boot-nodtb.bin' in branch


@pytest.mark.parametrize("payload,success", [(b"native-u-boot", True), (b"", False), (None, False)])
def test_sailfin_retains_nonempty_payload_or_fails(tmp_path, payload, success):
    source = (ROOT / "build_scripts/overlay/asahi.sh").read_text()
    start = source.index('\tinstall -D -m 0644 /boot/u-boot-nodtb.bin')
    end = source.index('\n\tinstall_best_effort', start)
    boot = tmp_path / "boot"
    boot.mkdir()
    if payload is not None:
        (boot / "u-boot-nodtb.bin").write_bytes(payload)
    retained = tmp_path / "usr/lib/asahi-boot/u-boot-nodtb.bin"
    script = source[start:end].replace('/boot/u-boot-nodtb.bin', str(boot / "u-boot-nodtb.bin"))
    script = script.replace('/usr/lib/asahi-boot/u-boot-nodtb.bin', str(retained))
    result = subprocess.run(["bash", "-e", "-c", script], capture_output=True, text=True)
    assert (result.returncode == 0) is success
    if success:
        (boot / "u-boot-nodtb.bin").unlink()
        assert retained.read_bytes() == payload
