"""tunaOS#2696: flounder-sid *-nvidia died when sid's kernel outran the driver.

sid moved linux-image-amd64 to 7.2.7 while nvidia-kernel-dkms stayed at
550.163.01, which does not compile against 7.2 (`strncpy` is gone). dkms
failed in the postinst and every flounder-sid *-nvidia cell went red (run
36083457907). Measured in debian:sid: 550.163.01 builds on 7.1.13, and no
Debian suite has a driver that builds on 7.2.

The overlay now swaps the kernel down to the newest archive kernel under the
driver's measured ceiling (build_scripts/overlay/debian-nvidia-kernel-hold.sh).
An end-to-end run of nvidia.sh in ghcr.io/tuna-os/flounder:kde-sid with the
fix held 7.1.13, built nvidia-current.ko.xz, and passed verify-nvidia-debian.

Falsification: behavioural — the real hold script runs with apt-cache and
apt-get stubbed on PATH against a scratch /usr/lib/modules. On the unfixed
tree the script does not exist and 20-nvidia.sh builds straight against 7.2.7;
the first test fails. The last test is structural: remove the hold call from
20-nvidia.sh (or move it after the headers install) and it fails.
"""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOLD = ROOT / "build_scripts/overlay/debian-nvidia-kernel-hold.sh"
INSTALL = ROOT / "build_scripts/overlay/overrides/nvidia-debian/20-nvidia.sh"

SID_KERNELS = ["7.1.12+deb14-amd64", "7.1.13+deb14-amd64", "7.2.7+deb14-amd64"]


def _stub(bindir: Path, name: str, body: str) -> None:
    path = bindir / name
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(0o755)


def _run(tmp_path: Path, kver: str, driver: str, archive: list[str]):
    modules = tmp_path / "modules"
    boot = tmp_path / "boot"
    bindir = tmp_path / "bin"
    for d in (modules / kver, boot, bindir):
        d.mkdir(parents=True, exist_ok=True)
    (modules / kver / "initramfs.img").write_bytes(b"old")
    log = tmp_path / "apt.log"
    pkgnames = "\n".join(
        [f"linux-image-{k}" for k in archive]
        + [f"linux-image-{k}-unsigned" for k in archive]
        + ["linux-image-amd64", "linux-image-cloud-amd64"]
    )
    headers = " ".join(f"linux-headers-{k}" for k in archive)
    _stub(
        bindir,
        "apt-cache",
        f"""case "$1" in
pkgnames) printf '%s\\n' '{pkgnames}' ;;
show)
  if [[ "$2" == --no-all-versions ]]; then echo 'Version: {driver}'; exit 0; fi
  for h in {headers}; do [[ "$2" == "$h" ]] && exit 0; done; exit 100 ;;
esac
""",
    )
    # install: materialise the new tree as the kernel postinst would (vmlinuz
    # in /boot only, as 7.1.13 does). purge: drop the package's files only.
    _stub(
        bindir,
        "apt-get",
        f"""echo "$*" >> {log}
pkg="${{@: -1}}"; k="${{pkg#linux-image-}}"
case "$1" in
install) mkdir -p {modules}/"$k"/kernel; echo vmlinuz > {boot}/vmlinuz-"$k" ;;
purge) rm -rf {modules}/"$k"/kernel ;;
esac
""",
    )
    env = dict(
        os.environ,
        PATH=f"{bindir}:{os.environ['PATH']}",
        TUNAOS_MODULES_ROOT=str(modules),
        TUNAOS_BOOT_DIR=str(boot),
    )
    proc = subprocess.run(
        ["bash", str(HOLD), kver], capture_output=True, text=True, env=env
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return proc, sorted(p.name for p in modules.iterdir()), calls, modules


def test_sid_7_2_is_swapped_for_the_newest_7_1_kernel(tmp_path):
    proc, trees, calls, modules = _run(
        tmp_path, "7.2.7+deb14-amd64", "550.163.01-5.1", SID_KERNELS
    )
    assert proc.returncode == 0, proc.stderr
    assert trees == ["7.1.13+deb14-amd64"], "exactly one tree, the held one"
    assert any("install" in c and "linux-image-7.1.13+deb14-amd64" in c for c in calls)
    assert any(c.startswith("purge") and "linux-image-7.2.7+deb14-amd64" in c for c in calls)
    assert (modules / "7.1.13+deb14-amd64" / "vmlinuz").read_text() == "vmlinuz\n"


def test_trixie_kernel_is_left_alone(tmp_path):
    proc, trees, calls, _ = _run(
        tmp_path, "6.12.107+deb13-amd64", "550.163.01-2", ["6.12.107+deb13-amd64"]
    )
    assert proc.returncode == 0, proc.stderr
    assert trees == ["6.12.107+deb13-amd64"] and calls == []


def test_an_unmeasured_driver_builds_against_the_shipped_kernel(tmp_path):
    proc, trees, calls, _ = _run(
        tmp_path, "7.2.7+deb14-amd64", "580.95.05-1", SID_KERNELS
    )
    assert proc.returncode == 0, proc.stderr
    assert trees == ["7.2.7+deb14-amd64"] and calls == []


def test_no_kernel_under_the_ceiling_fails_loudly(tmp_path):
    proc, trees, calls, _ = _run(
        tmp_path, "7.2.7+deb14-amd64", "550.163.01-5.1", ["7.2.6+deb14-amd64", "7.2.7+deb14-amd64"]
    )
    assert proc.returncode != 0
    assert "does not build on kernel 7.2" in proc.stderr
    assert trees == ["7.2.7+deb14-amd64"] and calls == []


def test_an_empty_kernel_name_is_refused_before_any_rm(tmp_path):
    proc = subprocess.run(["bash", str(HOLD), ""], capture_output=True, text=True)
    assert proc.returncode != 0 and "expected a kernel release" in proc.stderr


def test_20_nvidia_holds_before_installing_headers_and_rereads_kver():
    text = INSTALL.read_text(encoding="utf-8")
    call = text.index('debian-nvidia-kernel-hold.sh "$KVER"')
    assert text.index("apt-get update -y") < call < text.index('HEADERS_PKG="linux-headers-${KVER}"')
    reread = text.index('KVER="$(basename', call)
    assert reread < text.index('HEADERS_PKG="linux-headers-${KVER}"')
