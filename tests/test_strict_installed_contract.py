"""Inert strict boot gate regressions: no guest or network."""

import os
import subprocess
from pathlib import Path

import pytest

SOURCE = (Path(__file__).parents[1] / "scripts/iso-e2e.sh").read_text()


def function(name):
    if name == "verify_strict_installed_boot":
        return SOURCE[SOURCE.index(name + "() {") : SOURCE.index("emit_qualification_evidence() {")]
    return name + "() {" + SOURCE.split(name + "() {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"


@pytest.mark.parametrize(
    "markers,expected",
    [
        ("", 7),
        ("TUNAOS_DESKTOP_CONTRACT_OK\n[service] TUNAOS_DESKTOP_CONTRACT_FAIL desktop=gnome", 7),
        ("TUNAOS_DESKTOP_CONTRACT_OKAY", 7),
        ("echo TUNAOS_DESKTOP_CONTRACT_OK", 7),
        ("TUNAOS_DESKTOP_CONTRACT_FAIL", 7),
        ("TUNAOS_DESKTOP_CONTRACT_OK", 0),
        ("TUNAOS_DESKTOP_CONTRACT_OK\nTUNAOS_DESKTOP_CONTRACT_FAIL", 7),
        ("TUNAOS_DESKTOP_CONTRACT_FAIL\nTUNAOS_DESKTOP_CONTRACT_OK", 7),
        ("LUKS_FIRST_BOOT_DESKTOP_CONTRACT=ok", 7),
    ],
)
def test_actual_contract_gate(tmp_path, markers, expected):
    log = tmp_path / "serial.log"
    log.write_text(markers)
    result = subprocess.run(
        [
            "bash",
            "-c",
            function("strict_require_desktop_contract") + '\nstrict_require_desktop_contract "$1"',
            "test",
            str(log),
        ],
        capture_output=True,
        check=False,
        timeout=5,
    )
    assert result.returncode == expected


@pytest.mark.parametrize("phase", ["cold", "warm"])
@pytest.mark.parametrize(
    "digest,ref,expected",
    [
        ("a" * 64, "ghcr.io/tuna-os/skipjack:gnome", 0),
        ("b" * 64, "ghcr.io/tuna-os/skipjack:gnome", 1),
        ("a" * 64, "ghcr.io/other/image:gnome", 1),
        ("invalid", "ghcr.io/tuna-os/skipjack:gnome", 1),
    ],
)
def test_identity_gate_serial_fallback(tmp_path, phase, digest, ref, expected):
    log = tmp_path / "serial.log"
    log.write_text(f"TUNAOS_IMAGE_IDENTITY digest=sha256:{digest} targetImgref={ref}\n")
    harness = (
        function("strict_verify_installed_identity")
        + """
check_ssh() { return 1; }
sleep() { :; }
strict_poweroff_installed() { :; }
strict_offline_evidence() { :; }
strict_verify_installed_identity luks "$1" ghcr.io/tuna-os/skipjack:gnome 1 "$2"
"""
    )
    result = subprocess.run(
        ["bash", "-c", harness, "test", str(log), phase],
        env={**os.environ, "STRICT_SOURCE_DIGEST": "sha256:" + "a" * 64},
        capture_output=True,
        check=False,
        timeout=5,
    )
    assert result.returncode == expected
def test_identity_gate_serial_fallback_waits_for_live_serial_log(tmp_path):
    installed_log = tmp_path / "installed.log"
    installed_log.write_text("contract ok without identity line\n")
    live_log = tmp_path / "live.log"
    live_log.write_text(
        "contract ok without identity line\n"
        f"TUNAOS_IMAGE_IDENTITY digest=sha256:{'a' * 64} targetImgref=ghcr.io/tuna-os/skipjack:gnome\n"
    )
    harness = (
        function("strict_verify_installed_identity")
        + """
check_ssh() { return 1; }
sleep() { :; }
strict_poweroff_installed() { :; }
strict_offline_evidence() { :; }
SERIAL_LOG="$3" strict_verify_installed_identity luks "$1" ghcr.io/tuna-os/skipjack:gnome 1 "$2"
"""
    )
    result = subprocess.run(
        ["bash", "-c", harness, "test", str(installed_log), "cold", str(live_log)],
        env={**os.environ, "STRICT_SOURCE_DIGEST": "sha256:" + "a" * 64},
        capture_output=True,
        check=False,
        timeout=5,
    )
    assert result.returncode == 0
    assert "TUNAOS_IMAGE_IDENTITY" in installed_log.read_text()


@pytest.mark.parametrize("phase", ["cold", "warm"])
@pytest.mark.parametrize("late_event", ["identity", "failure"])
def test_plain_boot_waits_for_identity_before_snapshot(tmp_path, phase, late_event):
    (tmp_path / "strict-plain-disk.qcow2").touch()
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    resolver = scripts / "published-image-ref.sh"
    resolver.write_text("#!/bin/sh\necho ghcr.io/tuna-os/skipjack:gnome\n")
    resolver.chmod(0o700)
    harness = (
        "set -o pipefail\n"
        + "\n".join(
            function(name)
            for name in (
                "strict_require_unmodified_boot",
                "strict_require_desktop_contract",
                "verify_strict_installed_boot",
            )
        )
        + r'''
OUTPUT_DIR="$1"
SCRIPT_DIR="$2"
SERIAL_LOG="$OUTPUT_DIR/serial.log"
QEMU_PIDFILE="$OUTPUT_DIR/qemu.pid"
TIMEOUT=120
VARIANT=skipjack
FLAVOR=gnome
LATE_PHASE="$3"
LATE_EVENT="$4"
BOOT_PHASE=cold
EVENT_POLLS=0
IDENTITY="TUNAOS_IMAGE_IDENTITY digest=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa targetImgref=ghcr.io/tuna-os/skipjack:gnome"
strict_launch_installed() {
    if [[ "$3" == installed-plain-cold ]]; then
        BOOT_PHASE=cold
    else
        BOOT_PHASE=warm
    fi
    printf '%s\n' TUNAOS_DESKTOP_CONTRACT_OK >>"$SERIAL_LOG"
    if [[ "$BOOT_PHASE" != "$LATE_PHASE" ]]; then
        printf '%s\n' "$IDENTITY" >>"$SERIAL_LOG"
    fi
}
sleep() {
    if [[ "$BOOT_PHASE" == "$LATE_PHASE" && "$EVENT_POLLS" == 0 ]]; then
        EVENT_POLLS=1
        if [[ "$LATE_EVENT" == identity ]]; then
            printf '%s\n' "$IDENTITY" >>"$SERIAL_LOG"
        else
            printf '%s\n' TUNAOS_DESKTOP_CONTRACT_FAIL >>"$SERIAL_LOG"
        fi
    fi
}
boot_failed_on_serial() { return 1; }
strict_poweroff_installed() { :; }
screenshot() { :; }
strict_offline_evidence() { printf '%s\n' "$*" >>"$OUTPUT_DIR/evidence.log"; }
strict_verify_installed_identity() {
    grep -aEq 'TUNAOS_IMAGE_IDENTITY digest=sha256:[0-9a-fA-F]{64} targetImgref=[^[:space:]]+' "$2" || return 1
    STRICT_VERIFIED_BOOTED_DIGEST=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    STRICT_VERIFIED_BOOTED_REF="$3"
}
verify_strict_installed_boot plain
'''
    )
    result = subprocess.run(
        ["bash", "-c", harness, "test", str(tmp_path), str(scripts), phase, late_event],
        env={**os.environ, "STRICT_SOURCE_DIGEST": "sha256:" + "a" * 64},
        capture_output=True,
        check=False,
        timeout=5,
    )
    installed_log = tmp_path / "strict-plain-installed-serial.log"
    warm_log = tmp_path / "strict-plain-warm-serial.log"
    expected = 0 if late_event == "identity" else 7
    assert result.returncode == expected, result.stderr.decode()
    assert installed_log.exists() == (late_event == "identity" or phase == "warm")
    assert warm_log.exists() == (late_event == "identity")
    if late_event == "identity":
        assert "TUNAOS_IMAGE_IDENTITY" in installed_log.read_text()
        assert "TUNAOS_IMAGE_IDENTITY" in warm_log.read_text()
        assert "installed_plain_boot_times" in (tmp_path / "evidence.log").read_text()
        assert (tmp_path / "strict-qual-plain.json").exists()
    else:
        assert not (tmp_path / "strict-qual-plain.json").exists()


def test_cold_and_warm_gates_precede_success_evidence():
    body = function("verify_strict_installed_boot")
    assert body.index('strict_require_desktop_contract "$installed_log"') < body.index(
        "installed_${mode}_contract=ok"
    )
    assert body.index('strict_verify_installed_identity "$mode" "$installed_log"') < body.index(
        "cold1="
    )
    assert body.index('strict_require_desktop_contract "$warm_log"') < body.index("warm1=")
    assert body.index('strict_verify_installed_identity "$mode" "$warm_log"') < body.index("warm1=")
    assert "append_installed_serial_kargs" not in body


@pytest.mark.parametrize(
    "fault,expected",
    [
        ("none", 0),
        ("cold_absent", 7),
        ("cold_fail", 7),
        ("warm_absent", 7),
        ("warm_fail", 7),
        ("warm_identity", 1),
        ("cold_helper_fail", 4),
        ("warm_helper_fail", 4),
        ("cold_grub_edit", 2),
        ("warm_grub_edit", 2),
        ("cold_grub_attempt", 2),
        ("warm_grub_attempt", 2),
        ("cold_unbranded", 1),
        ("warm_unbranded", 1),
        ("cold_no_screen", 1),
        ("warm_no_screen", 1),
    ],
)
def test_inert_full_luks_flow_never_emits_false_fragment(tmp_path, fault, expected):
    (tmp_path / "strict-luks-disk.qcow2").touch()
    # Stale successful logs must not satisfy the new cold or warm boot.
    for name in ("strict-luks-installed-serial.log", "strict-luks-warm-serial.log"):
        (tmp_path / name).write_text("TUNAOS_DESKTOP_CONTRACT_OK\n")
    resolver = tmp_path / "published-image-ref.sh"
    resolver.write_text("#!/bin/sh\necho ghcr.io/tuna-os/skipjack:gnome\n")
    resolver.chmod(0o700)
    harness = (
        "set -o pipefail\n"
        + "\n".join(
            function(name)
            for name in (
                "strict_require_desktop_contract",
                "strict_luks_unlock_bound",
                "strict_screen_prompt",
                "strict_require_branded_prompt",
                "strict_require_unmodified_boot",
                "strict_verify_installed_identity",
                "verify_strict_installed_boot",
            )
        )
        + r"""
sleep() { :; }
check_ssh() { return 1; }
start_swtpm() { :; }
strict_launch_installed() { PHASE="$3"; }
strict_poweroff_installed() { :; }
strict_offline_evidence() { :; }
screenshot() { echo "$1" >>"$OUTPUT_DIR/screenshots"; }
env() {
    # The real helper boundary removes these variables; preserve the inert
    # shell-function double after checking the exact sanitizing invocation.
    [[ "$1 $2 $3 $4 $5 $6" == '-u TUNAOS_XFCE_PASSWORD -u TUNAOS_WALKTHROUGH_LUKS_PASS -u E2E_LUKS_PASS' ]] || return 99
    shift 6
    "$@"
}
python3() {
    if [[ "$1" == "-" ]]; then
        cat >/dev/null
        touch "$OUTPUT_DIR/fragment-emitted"
        return 0
    fi
    local phase=cold digest="$STRICT_SOURCE_DIGEST" wrong_first=1
    [[ "$PHASE" == *warm ]] && phase=warm wrong_first=0
    # The screen gate is wired per boot: its own evidence directory, the VNC
    # socket, and the wrong-passphrase check on the cold boot only.
    [[ "$TUNAOS_LUKS_SCREEN_OUTPUT" == "$OUTPUT_DIR/strict-luks-${phase}-observation" ]] || return 98
    [[ "$TUNAOS_LUKS_SCREEN_VNC" == "$OUTPUT_DIR/vnc.sock" ]] || return 98
    [[ "$TUNAOS_LUKS_SCREEN_WRONG_FIRST" == "$wrong_first" ]] || return 98
    local prompt=prompt_observed_branded
    [[ "$FAULT" == "${phase}_unbranded" ]] && prompt=prompt_observed_unbranded
    [[ "$FAULT" == "${phase}_no_screen" ]] || echo "LUKS_SCREEN prompt=$prompt"
    [[ "$FAULT" == "${phase}_grub_edit" ]] && echo ">>> GRUB entry edited; booting"
    [[ "$FAULT" == "${phase}_grub_attempt" ]] && echo ">>> GRUB menu seen; appending for this boot only"
    if [[ "$FAULT" != "${phase}_absent" ]]; then
        echo TUNAOS_DESKTOP_CONTRACT_OK
    fi
    [[ "$FAULT" == "${phase}_fail" ]] && echo TUNAOS_DESKTOP_CONTRACT_FAIL
    [[ "$FAULT" == warm_identity && "$phase" == warm ]] && digest="sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    echo "TUNAOS_IMAGE_IDENTITY digest=$digest targetImgref=ghcr.io/tuna-os/skipjack:gnome"
    [[ "$FAULT" == "${phase}_helper_fail" ]] && return 3
    return 0
}
verify_strict_installed_boot luks
"""
    )
    env = {
        **os.environ,
        "OUTPUT_DIR": str(tmp_path),
        "SCRIPT_DIR": str(tmp_path),
        "SERIAL_LOG": str(tmp_path / "serial.log"),
        "TPM_PIDFILE": str(tmp_path / "tpm.pid"),
        "STRICT_SOURCE_DIGEST": "sha256:" + "a" * 64,
        "FAULT": fault,
    }
    result = subprocess.run(
        ["bash", "-c", harness], env=env, capture_output=True, check=False, timeout=5
    )
    assert result.returncode == expected, result.stderr.decode()
    assert (tmp_path / "fragment-emitted").exists() == (expected == 0)
    # A failed LUKS boot may have stopped mid-entry with bullets on screen:
    # no failure frame is ever taken on that leg.
    shots = (tmp_path / "screenshots").read_text().split() if (tmp_path / "screenshots").exists() else []
    assert not [shot for shot in shots if shot.endswith("-failed")]


def test_plain_installed_failure_still_takes_the_failure_screenshot(tmp_path):
    (tmp_path / "strict-plain-disk.qcow2").touch()
    resolver = tmp_path / "published-image-ref.sh"
    resolver.write_text("#!/bin/sh\necho ghcr.io/tuna-os/skipjack:gnome\n")
    resolver.chmod(0o700)
    harness = function("verify_strict_installed_boot") + r"""
boot_failed_on_serial() { return 1; }
strict_launch_installed() { :; }
strict_poweroff_installed() { :; }
screenshot() { echo "$1" >>"$OUTPUT_DIR/screenshots"; }
verify_strict_installed_boot plain
"""
    result = subprocess.run(
        ["bash", "-c", harness],
        env={**os.environ, "OUTPUT_DIR": str(tmp_path), "SCRIPT_DIR": str(tmp_path),
             "SERIAL_LOG": str(tmp_path / "serial.log"), "TIMEOUT": "0",
             "QEMU_PIDFILE": str(tmp_path / "qemu.pid")},
        capture_output=True, text=True, check=False, timeout=5,
    )
    assert result.returncode == 7, result.stderr
    assert (tmp_path / "screenshots").read_text().split() == ["strict-plain-installed-failed"]


@pytest.mark.parametrize("kind", ["missing", "directory", "io_error"])
def test_unmodified_boot_attestation_requires_readable_log(tmp_path, kind):
    log = tmp_path / "serial.log"
    if kind == "directory":
        log.mkdir()
    elif kind == "io_error":
        log.write_text("normal boot")
    body = function("strict_require_unmodified_boot")
    if kind == "io_error":
        body += "\ngrep() { return 2; }\n"
    body += '\nstrict_require_unmodified_boot "$1"\n'
    result = subprocess.run(
        ["bash", "-c", body, "test", str(log)], capture_output=True, check=False, timeout=5
    )
    assert result.returncode == 2


@pytest.mark.parametrize('resolver_body', ['exit 1', 'exit 0'])
def test_unresolved_tracking_identity_stops_before_any_boot(tmp_path, resolver_body):
    (tmp_path / 'strict-luks-disk.qcow2').write_bytes(b'ordinary fixture')
    resolver = tmp_path / 'published-image-ref.sh'
    resolver.write_text('#!/bin/sh\n' + resolver_body + '\n')
    resolver.chmod(0o700)
    harness = function('verify_strict_installed_boot') + '''
start_swtpm() { echo FORBIDDEN_BOOT; exit 99; }
strict_launch_installed() { echo FORBIDDEN_BOOT; exit 99; }
verify_strict_installed_boot luks
'''
    result = subprocess.run(['bash', '-c', harness],
        env={'PATH': '/usr/bin:/bin', 'OUTPUT_DIR': str(tmp_path),
             'SCRIPT_DIR': str(tmp_path), 'VARIANT': 'skipjack', 'FLAVOR': 'gnome'},
        text=True, capture_output=True, timeout=5)
    assert result.returncode == 1
    assert 'refusing strict installed boot' in result.stderr
    assert 'FORBIDDEN_BOOT' not in result.stdout + result.stderr
    assert not (tmp_path / 'strict-qual-luks.json').exists()
