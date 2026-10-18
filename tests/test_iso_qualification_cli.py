import os
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "iso-e2e.sh"

SCRIPT_SOURCE = SCRIPT.read_text(encoding="utf-8")


def shell_section(start: str, end: str) -> str:
    return SCRIPT_SOURCE[SCRIPT_SOURCE.index(start):SCRIPT_SOURCE.index(end)]


def run_qualification(tmp_path, profile="plain", **environment):
    iso = tmp_path / "yellowfin-gnome-test.iso"
    manifest = tmp_path / "experience-manifest.json"
    iso.touch()
    manifest.write_text("{}", encoding="utf-8")
    env = os.environ | environment
    return subprocess.run(
        [
            "bash",
            str(SCRIPT),
            str(iso),
            "--qualification",
            profile,
            "--manifest",
            str(manifest),
            "--output",
            str(tmp_path / "out"),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


@pytest.mark.parametrize("variable", ["FISHERMAN_OVERRIDE", "TBOX_E2E_IMAGE"])
def test_qualification_rejects_host_installer_or_image_injection(tmp_path, variable):
    proc = run_qualification(tmp_path, **{variable: "/tmp/injected"})
    assert proc.returncode == 1
    assert "qualification forbids FISHERMAN_OVERRIDE and TBOX_E2E_IMAGE" in proc.stderr


def test_qualification_rejects_unknown_profile_before_starting_qemu(tmp_path):
    proc = run_qualification(tmp_path, profile="automatic")
    assert proc.returncode == 1
    assert "--qualification must be plain or encrypted" in proc.stderr


def test_qualification_requires_manifest_before_starting_qemu(tmp_path):
    iso = tmp_path / "yellowfin-gnome-test.iso"
    iso.touch()
    proc = subprocess.run(
        ["bash", str(SCRIPT), str(iso), "--qualification", "plain"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    assert "--qualification requires --manifest FILE" in proc.stderr


@pytest.mark.parametrize(
    ("profile", "inventory", "expected_key"),
    [
        ("plain", "/dev/sda2 ext4\n", None),
        ("encrypted", "/dev/sda2 crypto_LUKS\n", "all:key:tunaose2e"),
    ],
)
def test_account_provisioning_runs_inside_libguestfs(
    tmp_path, profile, inventory, expected_key
):
    function = shell_section(
        "prepare_qualification_disk() {",
        "qualification_frame_text() {",
    )
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    calls = tmp_path / "virt-customize.args"
    captured = tmp_path / "firstboot"
    virt_filesystems = fakebin / "virt-filesystems"
    virt_filesystems.write_text(
        "#!/bin/sh\nprintf '%s' \"$INVENTORY\"\n", encoding="utf-8"
    )
    virt_customize = fakebin / "virt-customize"
    virt_customize.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$@\" > \"$CALLS\"\n"
        "while [ \"$#\" -gt 0 ]; do\n"
        "  if [ \"$1\" = --firstboot ]; then cp \"$2\" \"$CAPTURED\"; exit 0; fi\n"
        "  shift\n"
        "done\n"
        "exit 2\n",
        encoding="utf-8",
    )
    for command in (virt_filesystems, virt_customize):
        command.chmod(0o755)
    disk = tmp_path / "install-disk.qcow2"
    disk.touch()
    env = os.environ | {
        "PATH": f"{fakebin}:{os.environ['PATH']}",
        "INVENTORY": inventory,
        "CALLS": str(calls),
        "CAPTURED": str(captured),
    }
    proc = subprocess.run(
        [
            "bash",
            "-eu",
            "-o",
            "pipefail",
            "-c",
            (
                f"{function}\n"
                f"INSTALL_DISK={str(disk)!r}\n"
                f"QUALIFICATION_PROFILE={profile!r}\n"
                "E2E_INSTALL_USER=qualification\n"
                "E2E_INSTALL_PASSWORD=offline-password\n"
                "prepare_qualification_disk\n"
            ),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    arguments = calls.read_text(encoding="utf-8").splitlines()
    assert arguments[:4] == ["--format", "qcow2", "-a", str(disk)]
    if expected_key is None:
        assert "--key" not in arguments
    else:
        assert arguments[4:6] == ["--key", expected_key]
    script = captured.read_text(encoding="utf-8")
    assert "useradd --create-home" in script
    assert "qualification:offline-password" not in script
    assert "password='offline-password'" in script
    assert 'restorecon -RF "/home/${account}"' in script

def test_qualification_wait_rejects_bootloader_before_session(tmp_path):
    function = shell_section(
        "wait_for_qualification_session_paint() {",
        "wait_for_qualification_text() {",
    )
    calls = tmp_path / "ocr-calls"
    proc = subprocess.run(
        ["/bin/bash", "-eu", "-c", (
            f"{function}\n"
            f"calls={calls}\n"
            'wait_for_paint() { return 0; }\n'
            'qualification_frame_text() {\n'
            '  count=0; [[ -f "$calls" ]] && count="$(cat "$calls")"\n'
            '  count=$((count + 1)); printf "%s" "$count" >"$calls"\n'
            '  [[ "$count" -eq 1 ]] && printf "GNU GRUB\\n" || printf "Welcome\\n"\n'
            '}\n'
            'sleep() { :; }\n'
            'TUNAOS_QUALIFICATION_BOOT_SETTLE=30\n'
            'wait_for_qualification_session_paint ready\n'
        )],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert calls.read_text() == "2"




def test_qualification_ocr_falls_back_to_convert(tmp_path):
    function = shell_section(
        "qualification_frame_text() {",
        "wait_for_qualification_text() {",
    )
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    (fakebin / "convert").write_text(
        "#!/bin/sh\nfor output; do :; done\n/bin/cp \"$1\" \"$output\"\n",
        encoding="utf-8",
    )
    (fakebin / "tesseract").write_text(
        "#!/bin/sh\nprintf 'graphical login\\n'\n", encoding="utf-8"
    )
    (fakebin / "rm").write_text(
        "#!/bin/sh\n/bin/rm \"$@\"\n", encoding="utf-8"
    )
    (fakebin / "rm").chmod(0o755)
    for command in ("convert", "tesseract"):
        (fakebin / command).chmod(0o755)
    env = os.environ | {
        "PATH": str(fakebin),
        "OUTPUT_DIR": str(tmp_path),
    }
    proc = subprocess.run(
        ["/bin/bash", "-eu", "-c", (
            'screenshot() { printf frame >"$OUTPUT_DIR/$1.ppm"; }\n'
            f"{function}\n"
            "qualification_frame_text installed-login"
        )],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "graphical login" in proc.stdout
