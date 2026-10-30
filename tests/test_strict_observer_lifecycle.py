"""Run owned local dummy processes only; no guest, sockets, or network."""

import os
import signal
import subprocess
from pathlib import Path

import pytest

SOURCE = (Path(__file__).parents[1] / "scripts/iso-e2e.sh").read_text()


def function(name):
    return name + "() {" + SOURCE.split(name + "() {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"


@pytest.mark.parametrize(
    "mode",
    [
        "normal",
        "already_exited",
        "ignore_term",
        "exit_trap",
        "term_trap",
        "orphan_child",
        "term_during_stop",
    ],
)
def test_owned_observer_cleanup_preserves_authoritative_status(tmp_path, mode):
    script = tmp_path / "observe-installed-boot.py"
    script.write_text("""import os, signal, time
from pathlib import Path
if os.environ['MODE'] in ('ignore_term', 'term_during_stop'):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
if os.environ['MODE'] == 'orphan_child':
    child = os.fork()
    if child == 0:
        time.sleep(30)
        raise SystemExit(0)
    Path(os.environ['READY'] + '-child').write_text(str(child))
Path(os.environ['READY']).write_text(str(os.getpid()))
if os.environ['MODE'] == 'orphan_child':
    release = Path(os.environ['RELEASE'])
    while not release.exists():
        time.sleep(0.01)
    raise SystemExit(7)
if os.environ['MODE'] == 'already_exited':
    raise SystemExit(7)
time.sleep(30)
""")
    body = (
        "\n".join(
            function(name)
            for name in (
                "strict_observer_starttime",
                "strict_observer_identity_matches",
                "strict_stop_boot_observer",
                "strict_start_boot_observer",
                "cleanup_vm",
            )
        )
        + """
strict_start_boot_observer cold
for _ in $(seq 1 100); do
    [[ -f "$READY" ]] && break
    sleep 0.01
done
[[ -f "$READY" ]] || exit 99
case "$MODE" in
    term_during_stop) trap cleanup_vm EXIT; trap 'exit 143' TERM; (sleep 0.15; kill -TERM $$) & strict_stop_boot_observer; exit 99 ;;
    exit_trap) trap cleanup_vm EXIT; exit 42 ;;
    term_trap) trap cleanup_vm EXIT; trap 'exit 143' TERM; kill -TERM $$ ;;
    orphan_child)
        # The file gate holds the leader until the harness verifies launch identity.
        [[ -n "$STRICT_OBSERVER_STARTTIME" ]] || exit 96
        : >"$RELEASE"
        wait "$STRICT_OBSERVER_PID" 2>/dev/null || true
        [[ ! -e "/proc/${STRICT_OBSERVER_PID}" ]] || exit 98
        child="$(<"${READY}-child")"
        child_stat="$(<"/proc/${child}/stat")" || exit 97
        child_pgid="$(awk '{print $3}' <<<"${child_stat##*) }")"
        [[ "$child_pgid" == "$STRICT_OBSERVER_PID" ]] || exit 97
        strict_stop_boot_observer
        exit 42
        ;;
    *) strict_stop_boot_observer; strict_stop_boot_observer; exit 42 ;;
esac
"""
    )
    env = {
        **os.environ,
        "OUTPUT_DIR": str(tmp_path),
        "SCRIPT_DIR": str(tmp_path),
        "MODE": mode,
        "READY": str(tmp_path / "ready"),
        "RELEASE": str(tmp_path / "release"),
        "KEEP_VM": "1",
        "MONITOR_SOCK": str(tmp_path / "never-open-monitor.sock"),
    }
    try:
        result = subprocess.run(
            ["bash", "-c", body], env=env, capture_output=True, check=False, timeout=6
        )
        assert result.returncode == (143 if mode in ("term_trap", "term_during_stop") else 42), (
            result.stderr
        )
        pid = int((tmp_path / "ready").read_text())
        assert not Path(f"/proc/{pid}").exists(), "owned observer must be reaped"
        if mode == "orphan_child":
            child = int((tmp_path / "ready-child").read_text())
            status = Path(f"/proc/{child}/stat")
            assert not status.exists() or status.read_text().split()[2] == "Z"
        log = (tmp_path / "strict-luks-cold-observer.log").read_text()
        assert "observer_cleanup" in log and "qualified=false" in log
        if mode == "ignore_term":
            assert "forced=1" in log
    finally:
        if (tmp_path / "ready").exists():
            try:
                os.killpg(int((tmp_path / "ready").read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_cleanup_runs_before_any_vm_teardown():
    body = function("cleanup_vm")
    assert body.index("strict_stop_boot_observer") < body.index("TIMELAPSE_DIR")
    assert body.index("strict_stop_boot_observer") < body.index("system_powerdown")
    start = function("strict_start_boot_observer")
    assert "--vnc" in start and "--monitor" not in start
    for forbidden in ("sendkey", "system_powerdown", "screendump"):
        assert forbidden not in start


def test_both_legs_stop_observer_before_failure_actions():
    body = SOURCE[
        SOURCE.index("verify_strict_installed_boot() {") : SOURCE.index(
            "emit_qualification_evidence() {"
        )
    ]
    for phase in ("cold", "warm"):
        part = body.split("strict_start_boot_observer " + phase, 1)[1]
        assert part.index("strict_stop_boot_observer") < part.index(
            f'if [[ "${phase}_unlock_rc" -ne 0 ]]'
        )
    assert body.count("900 300") == 2


def test_recycled_pid_never_receives_a_signal(tmp_path):
    body = (
        function("strict_stop_boot_observer")
        + """
strict_observer_identity_matches() { return 1; }
kill() { echo forbidden >> "$TRACE"; return 0; }
wait() { echo forbidden >> "$TRACE"; return 0; }
STRICT_OBSERVER_PID=123
STRICT_OBSERVER_STARTTIME=111
strict_stop_boot_observer
[[ -z "$STRICT_OBSERVER_PID" ]]
"""
    )
    result = subprocess.run(
        ["bash", "-c", body],
        capture_output=True,
        check=False,
        timeout=5,
        env={
            **os.environ,
            "TRACE": str(tmp_path / "trace"),
            "STRICT_OBSERVER_LOG": str(tmp_path / "observer.log"),
        },
    )
    assert result.returncode == 0
    assert not (tmp_path / "trace").exists()
    assert "identity_unavailable_or_changed" in (tmp_path / "observer.log").read_text()


@pytest.mark.parametrize(
    "read_failure",
    [True, False],
    ids=["unreadable-stat", "changed-starttime"],
)
def test_live_observer_identity_races_never_signal(tmp_path, read_failure):
    body = (
        "\n".join(
            function(name)
            for name in (
                "strict_observer_starttime",
                "strict_observer_identity_matches",
                "strict_stop_boot_observer",
            )
        )
        + """
observer_pid=$$
STRICT_OBSERVER_PID="$observer_pid"
STRICT_OBSERVER_STARTTIME="$(strict_observer_starttime "$observer_pid")"
[[ -n "$STRICT_OBSERVER_STARTTIME" ]]
if [[ "$READ_FAILURE" == "1" ]]; then
    cat() { return 1; }
else
    STRICT_OBSERVER_STARTTIME="$((STRICT_OBSERVER_STARTTIME + 1))"
fi
kill() { printf 'kill %s\\n' "$*" >>"$TRACE"; return 0; }
wait() { printf 'wait %s\\n' "$*" >>"$TRACE"; return 0; }
strict_stop_boot_observer
[[ -e "/proc/${observer_pid}/stat" ]]
[[ -z "$STRICT_OBSERVER_PID" && -z "$STRICT_OBSERVER_STARTTIME" ]]
"""
    )
    trace = tmp_path / "signals"
    result = subprocess.run(
        ["bash", "-c", body],
        capture_output=True,
        check=False,
        timeout=5,
        env={
            **os.environ,
            "READ_FAILURE": "1" if read_failure else "0",
            "TRACE": str(trace),
            "STRICT_OBSERVER_LOG": str(tmp_path / "observer.log"),
        },
    )
    assert result.returncode == 0, result.stderr
    assert not trace.exists(), (
        "ambiguous or changed identity must not signal any PID/PGID"
    )


def test_confirmed_observer_leader_disappearance_remains_owned():
    pid_max = int(Path("/proc/sys/kernel/pid_max").read_text())
    missing_pid = pid_max + 1
    assert not Path(f"/proc/{missing_pid}").exists()
    body = (
        function("strict_observer_starttime")
        + function("strict_observer_identity_matches")
        + (
            f"\nSTRICT_OBSERVER_STARTTIME=1\n"
            f"strict_observer_identity_matches {missing_pid}\n"
        )
    )
    result = subprocess.run(
        ["bash", "-c", body], capture_output=True, check=False, timeout=5
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("identity", ["", "different"])
def test_missing_or_changed_launch_identity_refuses_live_process(identity):
    body = (
        function("strict_observer_identity_matches")
        + """
strict_observer_starttime() { echo actual; }
strict_observer_identity_matches $$
"""
    )
    result = subprocess.run(
        ["bash", "-c", body],
        capture_output=True,
        check=False,
        timeout=5,
        env={**os.environ, "STRICT_OBSERVER_STARTTIME": identity},
    )
    assert result.returncode == 1


@pytest.mark.parametrize("launcher", ["run_strict_gui_install", "strict_launch_installed"])
def test_next_vm_refuses_live_owner_before_touching_disk_or_sockets(tmp_path, launcher):
    disk = tmp_path / "strict-plain-disk.qcow2"
    disk.write_bytes(b"previous owned disk")
    monitor = tmp_path / "monitor.sock"
    monitor.write_bytes(b"previous endpoint")
    trace = tmp_path / "trace"
    body = (
        function("strict_require_vm_stopped") + function(launcher) + """
candidate_require_no_injected_access() { :; }
reset_qemu_sockets() { echo reset >>"$TRACE"; }
qemu-img() { echo disk >>"$TRACE"; }
echo $$ >"$QEMU_PIDFILE"
rc=0
""" + (f'{launcher} plain' if launcher == "run_strict_gui_install"
       else f'{launcher} "$OUTPUT_DIR/strict-plain-disk.qcow2" "" cold')
        + """
rc=$?
exit "$rc"
"""
    )
    result = subprocess.run(
        ["bash", "-c", body], capture_output=True, check=False, timeout=5,
        env={**os.environ, "OUTPUT_DIR": str(tmp_path), "QEMU_PIDFILE": str(tmp_path/"qemu.pid"),
             "TRACE": str(trace)},
    )
    assert result.returncode == 6, result.stderr
    assert disk.read_bytes() == b"previous owned disk"
    assert monitor.read_bytes() == b"previous endpoint"
    assert not trace.exists()


@pytest.mark.parametrize("first_failure", [0, 9])
def test_live_shutdown_failure_is_enforced_without_replacing_first_failure(tmp_path, first_failure):
    body = (
        function("run_strict_gui_install") + """
strict_require_vm_stopped() { :; }
qemu-img() { :; }
boot_live_iso() { return "$FIRST_FAILURE"; }
strict_offline_verify_netdev() { :; }
wait_for_strict_live_ready() { :; }
strict_capture_live_inputs() { :; }
e2e_phase() { :; }
python3() { :; }
check_ssh() { return 1; }
poweroff_and_wait_vm() { return 6; }
INSTALL_DISK=original
rc=0
run_strict_gui_install plain || rc=$?
[[ "$INSTALL_DISK" == original ]] || exit 99
exit "$rc"
"""
    )
    result = subprocess.run(
        ["bash", "-c", body], capture_output=True, check=False, timeout=5,
        env={**os.environ, "OUTPUT_DIR": str(tmp_path), "FIRST_FAILURE": str(first_failure),
             "SCRIPT_DIR": str(Path(__file__).parents[1]/"scripts"), "FLAVOR": "gnome",
             "SERIAL_LOG": str(tmp_path/"serial.log"), "STRICT_PUBLISHED_MEDIA": "1"},
    )
    assert result.returncode == (first_failure or 6), result.stderr


def test_installed_shutdown_failure_cannot_be_ignored_by_helper():
    body = function("strict_poweroff_installed") + """
poweroff_and_wait_vm() { return 6; }
strict_poweroff_installed
"""
    result = subprocess.run(["bash", "-c", body], capture_output=True, check=False, timeout=5)
    assert result.returncode == 6, result.stderr


def test_surviving_plain_vm_blocks_next_firmware_and_tpm_reset(tmp_path):
    iso = tmp_path / "media.iso"
    iso.write_bytes(b"fixture media")
    body = (
        function("strict_require_vm_stopped") + function("run_strict_offline_gui") + """
e2e_phase() { :; }
qemu-img() { :; }
strict_offline_evidence() { :; }
strict_require_digest() { :; }
reset_uefi_vars() { echo reset >>"$TRACE"; }
start_swtpm() { echo tpm >>"$TRACE"; }
run_strict_gui_install() {
    echo "install:$1" >>"$TRACE"
    echo $$ >"$QEMU_PIDFILE"
    return 1
}
run_strict_offline_gui
"""
    )
    result = subprocess.run(
        ["bash", "-c", body], capture_output=True, check=False, timeout=5,
        env={**os.environ, "OUTPUT_DIR": str(tmp_path), "TRACE": str(tmp_path/"trace"),
             "QEMU_PIDFILE": str(tmp_path/"qemu.pid"), "ISO_PATH": str(iso), "QEMU": "/bin/true",
             "QUAL_EVIDENCE_JSON": str(tmp_path/"qualification-evidence.json"),
             "STRICT_EVIDENCE_LOG": str(tmp_path/"evidence.log"),
             "STRICT_OFFLINE_GUI_MODES": "plain,luks",
             "TUNAOS_QUAL_OVERLAY_DIGEST": "sha256:"+"a"*64,
             "TUNAOS_QUAL_ENGINE_DIGEST": "sha256:"+"b"*64},
    )
    assert result.returncode == 6, result.stderr
    assert (tmp_path/"trace").read_text().splitlines() == ["reset", "install:plain"]
