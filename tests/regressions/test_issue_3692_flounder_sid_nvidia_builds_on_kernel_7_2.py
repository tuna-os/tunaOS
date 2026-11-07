"""tunaOS#3692 / #3685: flounder-sid *-nvidia failed nightly once sid dropped 7.1.

debian-nvidia-kernel-hold.sh capped every 550.* driver at kernel 7.1, and sid
no longer carries a linux-image-*-amd64 at or below 7.1, so the hold script
exited 1 (`nvidia-kernel-dkms 550.163.01-6 does not build on kernel 7.2
(ceiling 7.1)`, run 42156541100, xfce/gnome/kde-nvidia).

Debian fixed the driver, not the kernel: 550.163.01-6 (2026-11-01) backports
the strncpy and drm_atomic_commit_struct changes for Linux 7.2. Measured in
debian:sid on 2026-11-06: apt-get install nvidia-kernel-dkms 550.163.01-6
against linux-headers 7.2.15+deb14-amd64 -> `dkms status`: installed. The
ceiling is now keyed on the Debian revision: 550.163.01-6+ -> 7.2, earlier
revisions stay at 7.1 (-5.1 still fails on 7.2.7, tunaOS#2696).

Falsification: on the unfixed script the first test fails (ceiling 7.1, no
archive kernel under it, exit 1). The remaining tests pin what must NOT
change: older revisions are still swapped / still fail closed, and a 7.3
kernel above the new 7.2 ceiling is still held rather than built unmeasured.

The harness (apt-cache/apt-get stubs on PATH, scratch modules root) is the
one from the #2696 test.
"""

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "issue_2696",
    Path(__file__).with_name(
        "test_issue_2696_debian_nvidia_holds_a_kernel_the_driver_builds_on.py"
    ),
)
_M = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_M)
_run = _M._run

SID_NOW = ["7.2.15+deb14-amd64"]


def test_driver_550_163_01_6_builds_on_the_shipped_7_2_kernel(tmp_path):
    proc, trees, calls, _ = _run(
        tmp_path, "7.2.15+deb14-amd64", "550.163.01-6", SID_NOW
    )
    assert proc.returncode == 0, proc.stderr
    assert "ceiling 7.2" in proc.stdout + proc.stderr
    assert "no kernel hold needed" in proc.stdout + proc.stderr
    assert trees == ["7.2.15+deb14-amd64"] and calls == []


def test_a_later_revision_and_an_epoch_keep_the_7_2_ceiling(tmp_path):
    for driver in ("550.163.01-6.1", "1:550.163.01-7", "550.163.01-10"):
        proc, trees, calls, _ = _run(
            tmp_path / driver.replace(":", "_"), "7.2.15+deb14-amd64", driver, SID_NOW
        )
        assert proc.returncode == 0, (driver, proc.stderr)
        assert trees == ["7.2.15+deb14-amd64"] and calls == [], driver


def test_the_old_revision_is_still_swapped_to_7_1(tmp_path):
    proc, trees, calls, _ = _run(
        tmp_path,
        "7.2.15+deb14-amd64",
        "550.163.01-5.1",
        ["7.1.13+deb14-amd64", "7.2.15+deb14-amd64"],
    )
    assert proc.returncode == 0, proc.stderr
    assert trees == ["7.1.13+deb14-amd64"]
    assert any("install" in c and "linux-image-7.1.13+deb14-amd64" in c for c in calls)


def test_the_old_revision_still_fails_closed_when_no_7_1_kernel_remains(tmp_path):
    proc, trees, calls, _ = _run(
        tmp_path, "7.2.15+deb14-amd64", "550.163.01-5.1", SID_NOW
    )
    assert proc.returncode != 0
    assert "does not build on kernel 7.2 (ceiling 7.1)" in proc.stderr
    assert trees == ["7.2.15+deb14-amd64"] and calls == []


def test_a_7_3_kernel_is_held_to_the_measured_7_2_ceiling(tmp_path):
    proc, trees, calls, _ = _run(
        tmp_path,
        "7.3.1+deb14-amd64",
        "550.163.01-6",
        ["7.2.15+deb14-amd64", "7.3.1+deb14-amd64"],
    )
    assert proc.returncode == 0, proc.stderr
    assert trees == ["7.2.15+deb14-amd64"]
    assert any("install" in c and "linux-image-7.2.15+deb14-amd64" in c for c in calls)
