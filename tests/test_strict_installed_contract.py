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
strict_start_boot_observer() { :; }
strict_stop_boot_observer() { :; }
screenshot() { :; }
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
    echo 'Please enter passphrase for disk root:'
    local phase=cold digest="$STRICT_SOURCE_DIGEST"
    [[ "$PHASE" == *warm ]] && phase=warm
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
strict_start_boot_observer() { echo FORBIDDEN_BOOT; exit 99; }
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
