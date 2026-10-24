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
if os.environ['MODE'] in ('already_exited', 'orphan_child'):
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
