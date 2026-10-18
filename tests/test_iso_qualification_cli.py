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


def test_first_boot_account_service_targets_the_ostree_deployment(tmp_path):
    function = shell_section(
        "qualification_deployment_root() {",
        "activate_qualification_volume_group() {",
    )
    deployment = tmp_path / "ostree/deploy/tunaos/deploy/deadbeef.0"
    deployment.mkdir(parents=True)
    proc = subprocess.run(
        ["bash", "-eu", "-c", (
            f"{function}\n"
            f'E2E_INSTALL_USER=qualification E2E_INSTALL_PASSWORD=offline-password\n'
            f'deployment="$(qualification_deployment_root {tmp_path})"\n'
            'install_qualification_account_service "$deployment"\n'
        )],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr

    account_dir = deployment / "etc/tunaos-qualification"
    unit_dir = deployment / "etc/systemd/system"
    assert (account_dir / "password").read_text() == "offline-password"
    assert (unit_dir / "graphical.target.wants/tunaos-qualification-account.service").is_symlink()
    assert (
        deployment / "etc/systemd/system-preset/10-tunaos-qualification.preset"
    ).read_text() == "enable tunaos-qualification-account.service\n"

    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    useradd_log = tmp_path / "useradd.log"
    password_log = tmp_path / "password.log"
    commands = {
        "getent": "#!/bin/sh\nexit 2\n",
        "useradd": f"#!/bin/sh\nprintf '%s\\n' \"$*\" > {useradd_log}\n",
        "chpasswd": f"#!/bin/sh\ncat > {password_log}\n",
        "restorecon": "#!/bin/sh\nexit 0\n",
    }
    for name, body in commands.items():
        command = fakebin / name
        command.write_text(body, encoding="utf-8")
        command.chmod(0o755)
    env = os.environ | {
        "PATH": f"{fakebin}:{os.environ['PATH']}",
        "TUNAOS_QUALIFICATION_ETC_ROOT": str(deployment),
    }
    helper = subprocess.run(
        ["/bin/bash", str(account_dir / "create-account")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert helper.returncode == 0, helper.stderr
    assert "--create-home" in useradd_log.read_text()
    assert password_log.read_text() == "qualification:offline-password\n"
    assert not (account_dir / "password").exists()

def test_account_service_prefers_composefs_native_deployment(tmp_path):
    function = shell_section(
        "qualification_deployment_root() {",
        "label_qualification_account_files() {",
    )
    ostree = tmp_path / "ostree/deploy/tunaos/deploy/deadbeef.0"
    composefs = tmp_path / "state/deploy/abcdef"
    ostree.mkdir(parents=True)
    composefs.mkdir(parents=True)
    proc = subprocess.run(
        ["bash", "-eu", "-c", f'{function}\nqualification_deployment_root "{tmp_path}"'],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == str(composefs)


def test_staged_account_files_are_labeled_with_guest_policy(tmp_path):
    functions = shell_section(
        "label_qualification_account_files() {",
        "activate_qualification_volume_group() {",
    )
    deployment = tmp_path / "deployment"
    (deployment / "etc/selinux").mkdir(parents=True)
    restorecon = deployment / "usr/sbin/restorecon"
    restorecon.parent.mkdir(parents=True)
    restorecon.write_text("#!/bin/sh\n", encoding="utf-8")
    restorecon.chmod(0o755)
    calls = tmp_path / "chroot.log"
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    chroot = fakebin / "chroot"
    chroot.write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"$*\" > {calls}\n", encoding="utf-8"
    )
    chroot.chmod(0o755)
    proc = subprocess.run(
        ["bash", "-eu", "-c", (
            f"{functions}\n"
            f"E2E_INSTALL_USER=qualification E2E_INSTALL_PASSWORD=offline-password "
            f"install_qualification_account_service {deployment}"
        )],
        env=os.environ | {"PATH": f"{fakebin}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "/usr/sbin/restorecon -RF" in calls.read_text()
    assert "/etc/tunaos-qualification" in calls.read_text()


def test_mapper_cleanup_only_closes_mapping_opened_by_this_run(tmp_path):
    function = shell_section(
        "close_qualification_mapper() {",
        "# Inspect the disk the GUI wrote",
    )
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    calls = tmp_path / "cryptsetup.log"
    cryptsetup = fakebin / "cryptsetup"
    cryptsetup.write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {calls}\n", encoding="utf-8"
    )
    cryptsetup.chmod(0o755)
    proc = subprocess.run(
        ["/bin/bash", "-eu", "-c", (
            f"{function}\n"
            "close_qualification_mapper tunaos-qualification-root-111 0\n"
            "close_qualification_mapper tunaos-qualification-root-222 1\n"
        )],
        env=os.environ | {"PATH": str(fakebin)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert calls.read_text().splitlines() == [
        "close tunaos-qualification-root-222"
    ]

def test_lvm_activation_and_cleanup_are_scoped_to_owned_device(tmp_path):
    functions = shell_section(
        "activate_qualification_volume_group() {",
        "# Inspect the disk the GUI wrote",
    )
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    calls = tmp_path / "vgchange.log"
    (fakebin / "pvs").write_text(
        "#!/bin/sh\nprintf ' qualification-vg\\n'\n", encoding="utf-8"
    )
    (fakebin / "vgchange").write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {calls}\n", encoding="utf-8"
    )
    for command in ("pvs", "vgchange"):
        (fakebin / command).chmod(0o755)
    env = os.environ | {"PATH": f"{fakebin}:{os.environ['PATH']}"}
    proc = subprocess.run(
        ["bash", "-eu", "-o", "pipefail", "-c", (
            f"{functions}\n"
            'vg="$(activate_qualification_volume_group /dev/nbd7p2)"\n'
            '[[ "$vg" == qualification-vg ]]\n'
            'deactivate_qualification_volume_group /dev/nbd7p2 "$vg"\n'
        )],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert calls.read_text().splitlines() == [
        "--devices /dev/nbd7p2 -ay qualification-vg",
        "--devices /dev/nbd7p2 -an qualification-vg",
    ]


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


def test_session_wait_fits_inside_generated_service_timeouts():
    root = Path(__file__).parents[1]
    verify = (
        root / "build_scripts/checks/verify-desktop-experience.sh"
    ).read_text(encoding="utf-8")
    runtime = (
        root / "build_scripts/desktop/configure-desktop-runtime.sh"
    ).read_text(encoding="utf-8")
    install = (
        root / "build_scripts/desktop/install-desktop.sh"
    ).read_text(encoding="utf-8")
    assert "session_deadline=$((SECONDS + 210))" in verify
    assert "TimeoutStartSec=300" in runtime
    assert "TimeoutStartSec=300" in install


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
