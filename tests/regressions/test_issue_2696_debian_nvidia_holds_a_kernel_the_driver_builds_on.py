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
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOLD = ROOT / "build_scripts/overlay/debian-nvidia-kernel-hold.sh"
INSTALL = ROOT / "build_scripts/overlay/overrides/nvidia-debian/20-nvidia.sh"
SNAPSHOT = ROOT / "build_scripts/overlay/debian-nvidia-snapshot.sh"

SID_KERNELS = ["7.1.12+deb14-amd64", "7.1.13+deb14-amd64", "7.2.7+deb14-amd64"]


def _snapshot_metadata():
    metadata = dict(
        re.findall(
            r"^(linux-\S+)\s+([0-9a-f]{64})$",
            SNAPSHOT.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
    )
    assert len(metadata) == 7
    return metadata


def _stub(bindir: Path, name: str, body: str) -> None:
    path = bindir / name
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(0o755)


def _run(tmp_path: Path, kver: str, driver: str, archive: list[str], snapshot_kernel: str | None = None):
    modules = tmp_path / "modules"
    apt_root = tmp_path / "apt"
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
        f"""while [[ "${{1:-}}" == -o ]]; do shift 2; done
case "$1" in
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
        f"""while [[ "${{1:-}}" == -o ]]; do shift 2; done
echo "$*" >> {log}
pkg="${{@: -1}}"; k="${{pkg#linux-image-}}"
case "$1" in
install) mkdir -p {modules}/"$k"/kernel; echo vmlinuz > {boot}/vmlinuz-"$k" ;;
purge) rm -rf {modules}/"$k"/kernel ;;
esac
""",
    )
    snapshot = bindir / "snapshot"
    snapshot.write_text(
        "#!/bin/bash\n"
        + (
            'mkdir -p "$TUNAOS_APT_ROOT/sources.list.d" "$TUNAOS_APT_ROOT/preferences.d"\n'
            'touch "$TUNAOS_APT_ROOT/sources.list.d/tunaos-nvidia-kernel-snapshot.fake.sources"\n'
            'touch "$TUNAOS_APT_ROOT/preferences.d/tunaos-nvidia-kernel-snapshot.fake"\n'
            f"echo '{snapshot_kernel}'\n"
            if snapshot_kernel
            else "exit 1\n"
        )
    )
    snapshot.chmod(0o644)
    env = dict(
        os.environ,
        PATH=f"{bindir}:{os.environ['PATH']}",
        TUNAOS_MODULES_ROOT=str(modules),
        TUNAOS_BOOT_DIR=str(boot),
        TUNAOS_APT_ROOT=str(apt_root),
        TUNAOS_DEBIAN_NVIDIA_SNAPSHOT_SCRIPT=str(snapshot),
    )
    proc = subprocess.run(
        ["bash", str(HOLD), kver], capture_output=True, text=True, env=env
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return proc, sorted(p.name for p in modules.iterdir()), calls, modules


def _run_snapshot(
    tmp_path: Path,
    *,
    metadata_mode: str = "valid",
    update_status: int = 0,
    os_release_id: str = "debian",
    architecture: str = "amd64",
    driver: str = "550.163.01-5.1",
    kernel: str = "7.2.7+deb14-amd64",
):
    bindir = tmp_path / "snapshot-bin"
    apt_root = tmp_path / "apt"
    bindir.mkdir()
    os_release = tmp_path / "os-release"
    os_release.write_text(f"ID={os_release_id}\n")
    keyring = tmp_path / "archive-keyring.gpg"
    keyring.write_bytes(b"fixture keyring")
    log = tmp_path / "snapshot-apt.log"
    metadata_cases = []
    for package, digest in _snapshot_metadata().items():
        if metadata_mode == "missing" and package == "linux-kbuild-7.1.13+deb14":
            continue
        if metadata_mode == "mismatch" and package == "linux-image-7.1.13+deb14-amd64":
            digest = "0" * 64
        metadata_cases.append(
            f'  {package}) printf "Version: 7.1.13-1\\\\nSHA256: {digest}\\\\n" ;;'
        )
    _stub(
        bindir,
        "apt-cache",
        'while [[ "${1:-}" == -o ]]; do shift 2; done\n'
        'if [[ "$1" == show ]]; then\n'
        '  package="${2%%=*}"\n'
        '  case "$package" in\n'
        + "\n".join(metadata_cases)
        + '\n    *) exit 1 ;;\n  esac\nfi\n',
    )
    _stub(
        bindir,
        "apt-get",
        f'printf "%s\\\\n" "$*" >> "{log}"\n'
        f'[[ "$*" == *update* ]] && exit {update_status}\n'
        "exit 0\n",
    )
    _stub(
        bindir,
        "dpkg",
        f'[[ "$1" == --print-architecture ]] && printf "%s\\\\n" "{architecture}"\n',
    )
    env = dict(
        os.environ,
        PATH=f"{bindir}:{os.environ['PATH']}",
        TUNAOS_APT_ROOT=str(apt_root),
        TUNAOS_OS_RELEASE_FILE=str(os_release),
        TUNAOS_DEBIAN_KEYRING=str(keyring),
    )
    proc = subprocess.run(
        ["bash", str(SNAPSHOT), driver, kernel],
        capture_output=True,
        text=True,
        env=env,
    )
    return proc, log.read_text().splitlines() if log.exists() else [], apt_root


def test_snapshot_helper_selects_the_pinned_kernel_from_verified_metadata(tmp_path):
    proc, calls, apt_root = _run_snapshot(tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "7.1.13+deb14-amd64"
    assert any(f"Dir::State::lists={apt_root}/lists" in call for call in calls)
    assert list((apt_root / "sources.list.d").glob("tunaos-nvidia-kernel-snapshot.*.sources"))
    assert list((apt_root / "preferences.d").glob("tunaos-nvidia-kernel-snapshot.*"))


def test_snapshot_update_failure_stops_before_any_package_change(tmp_path):
    proc, calls, apt_root = _run_snapshot(tmp_path, update_status=23)

    assert proc.returncode != 0
    assert calls and all("install" not in call and "purge" not in call for call in calls)
    assert not list((apt_root / "sources.list.d").glob("tunaos-nvidia-kernel-snapshot.*.sources"))
    assert not list((apt_root / "preferences.d").glob("tunaos-nvidia-kernel-snapshot.*"))


@pytest.mark.parametrize("metadata_mode", ["missing", "mismatch"])
def test_snapshot_bad_metadata_stops_before_any_package_change(tmp_path, metadata_mode):
    proc, calls, apt_root = _run_snapshot(tmp_path, metadata_mode=metadata_mode)

    assert proc.returncode != 0
    assert calls and all("install" not in call and "purge" not in call for call in calls)
    assert not list((apt_root / "sources.list.d").glob("tunaos-nvidia-kernel-snapshot.*.sources"))
    assert not list((apt_root / "preferences.d").glob("tunaos-nvidia-kernel-snapshot.*"))


@pytest.mark.parametrize(
    ("os_release_id", "architecture", "driver", "kernel"),
    [
        ("ubuntu", "amd64", "550.163.01-5.1", "7.2.7+deb14-amd64"),
        ("debian", "arm64", "550.163.01-5.1", "7.2.7+deb14-amd64"),
        ("debian", "amd64", "580.95.05-1", "7.2.7+deb14-amd64"),
        ("debian", "amd64", "550.163.01-5.1", "7.2.7+deb14-arm64"),
    ],
)
def test_snapshot_rejects_unsupported_inputs_before_apt(tmp_path, os_release_id, architecture, driver, kernel):
    proc, calls, apt_root = _run_snapshot(
        tmp_path,
        os_release_id=os_release_id,
        architecture=architecture,
        driver=driver,
        kernel=kernel,
    )

    assert proc.returncode != 0
    assert not list((apt_root / "sources.list.d").glob("tunaos-nvidia-kernel-snapshot.*.sources"))
    assert not list((apt_root / "preferences.d").glob("tunaos-nvidia-kernel-snapshot.*"))
    assert calls == []


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


def test_snapshot_fallback_supplies_a_kernel_when_archive_has_none(tmp_path):
    proc, trees, calls, modules = _run(
        tmp_path,
        "7.2.7+deb14-amd64",
        "550.163.01-5.1",
        ["7.2.6+deb14-amd64", "7.2.7+deb14-amd64"],
        snapshot_kernel="7.1.13+deb14-amd64",
    )
    assert proc.returncode == 0, proc.stderr
    assert trees == ["7.1.13+deb14-amd64"]
    assert any("install" in c and "linux-image-7.1.13+deb14-amd64" in c for c in calls)
    assert (modules / "7.1.13+deb14-amd64" / "vmlinuz").read_text() == "vmlinuz\n"
    assert not list((tmp_path / "apt/sources.list.d").glob("tunaos-nvidia-kernel-snapshot.*"))
    assert not list((tmp_path / "apt/preferences.d").glob("tunaos-nvidia-kernel-snapshot.*"))


def test_no_kernel_under_the_ceiling_fails_loudly(tmp_path):
    proc, trees, calls, _ = _run(
        tmp_path, "7.2.7+deb14-amd64", "550.163.01-5.1", ["7.2.6+deb14-amd64", "7.2.7+deb14-amd64"]
    )
    assert proc.returncode != 0
    assert "snapshot fallback" in proc.stderr
    assert trees == ["7.2.7+deb14-amd64"] and calls == []


def test_shipped_snapshot_helper_is_invocable_without_execute_bits():
    assert SNAPSHOT.stat().st_mode & 0o111 == 0
    assert 'HELD="$(bash "$SNAPSHOT_SCRIPT"' in HOLD.read_text(encoding="utf-8")


def test_an_empty_kernel_name_is_refused_before_any_rm(tmp_path):
    proc = subprocess.run(["bash", str(HOLD), ""], capture_output=True, text=True)
    assert proc.returncode != 0 and "expected a kernel release" in proc.stderr


def test_20_nvidia_holds_before_installing_headers_and_rereads_kver():
    text = INSTALL.read_text(encoding="utf-8")
    call = text.index('debian-nvidia-kernel-hold.sh "$KVER"')
    assert text.index("apt-get update -y") < call < text.index('HEADERS_PKG="linux-headers-${KVER}"')
    reread = text.index('KVER="$(basename', call)
    assert reread < text.index('HEADERS_PKG="linux-headers-${KVER}"')
