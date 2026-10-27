"""tunaOS#3969: diagnostics must not manufacture a session after failed login.

Falsification: behavioural — the adfdf2d4 gate calls the user-bus proxy even
without a graphical session. The inert proxy creates a fixture session and
prints a marker; the negative test rejects both that call and success markers.
No guest command or process query reaches the host. Journal messages remain
synthetic, and their free-form text must never enter diagnostic output.
"""

import importlib.util
import json
import os
from pathlib import Path
import shlex
import socket
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "scripts/gdm-login-gate.sh"
spec = importlib.util.spec_from_file_location(
    "screenshot_fixture", Path(__file__).with_name("test_issue_3969_late_screenshot_evidence.py")
)
screenshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(screenshot)

VALID = "Name=fixture-user\nType=wayland\nSeat=seat0\nActive=yes\nState=active\n"


def diagnostic_scripts(properties=None, manager_active=True, records=()):
    listing = "41 1000 fixture-user seat0" if properties is not None else ""
    records_text = "\n".join(json.dumps(record) for record in records)
    return {
        "id": "echo 1000",
        "loginctl": 'echo "loginctl $*" >>"$STATE/diagnostic-calls"\n'
        + 'case "$1" in\nlist-sessions) printf "%s\\n" ' + shlex.quote(listing)
        + ' ;;\nshow-session) printf "%s\\n" ' + shlex.quote(properties or "") + ' ;;\nesac',
        "systemctl": 'echo "systemctl $*" >>"$STATE/diagnostic-calls"\n'
        + ('echo ActiveState=active\nexit 0' if manager_active else 'exit 1'),
        "sudo": 'echo "sudo $*" >>"$STATE/diagnostic-calls"\necho USER_MANAGER_DIAGNOSTIC',
        "busctl": '''echo "busctl $*" >>"$STATE/diagnostic-calls"
if [[ "$*" == *--machine=* ]]; then
    touch "$STATE/diagnostic-session"
    echo USER_BUS_DIAGNOSTIC
elif [[ "$*" == *--address=* && "$*" == *--auto-start=no* ]]; then
    echo DIRECT_USER_BUS_DIAGNOSTIC
    echo 'b false'
fi''',
        # Keep source hardcoded configuration reads inert too.
        "cat": 'if [[ $# == 0 ]]; then exec /bin/cat; fi\nexit 1',
        "ls": "exit 0",
        "grep": 'if [[ "${1:-}" == -a ]]; then exit 1; fi\nexec /usr/bin/grep "$@"',
        "journalctl": 'echo "journalctl $*" >>"$STATE/diagnostic-calls"\n'
        + 'python3 - "$@" <<"JOURNAL_FIXTURE"\n'
        + "import json, re, sys\n"
        + f"records = [json.loads(line) for line in {records_text!r}.splitlines()]\n"
        + "args = sys.argv[1:]\n"
        + "pattern = next(arg.split('=', 1)[1] for arg in args if arg.startswith('--grep='))\n"
        + "limit = int(args[args.index('-n') + 1])\n"
        + "selected = [record for record in records if re.search(pattern, record['MESSAGE'])]\n"
        + "for record in selected[-limit:]: print(json.dumps(record))\nJOURNAL_FIXTURE",

    }


def run_diagnostics(tmp_path, properties=None, manager_active=True, records=(), session="41", overrides=None):
    scripts = diagnostic_scripts(properties, manager_active, records)
    scripts.update(overrides or {})
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in scripts.items():
        executable = bindir / name
        executable.write_text("#!/bin/bash\nset -eu\n" + body + "\n")
        executable.chmod(0o755)
    runtime = tmp_path / "run/user/1000"
    runtime.mkdir(parents=True)
    bus = socket.socket(socket.AF_UNIX)
    bus.bind(str(runtime / "bus"))
    source = GATE.read_text().split("<<'GDM_DIAGNOSTICS'\n", 1)[1].split("\nGDM_DIAGNOSTICS", 1)[0]
    source = source.replace("/run/user/", str(tmp_path / "run/user") + "/")
    result = subprocess.run(
        ["/bin/bash", "-s", "--", "fixture-user", session], input=source,
        env=dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", STATE=str(tmp_path)),
        capture_output=True, text=True, check=False, timeout=20,
    )
    bus.close()
    return result, (tmp_path / "diagnostic-calls").read_text()


def test_failed_login_cannot_create_a_diagnostic_session_or_pass():
    result, collections, _, _ = screenshot.run_gate(
        login=False, diagnostics_scripts=diagnostic_scripts()
    )
    assert result.returncode == 1, result.stderr
    assert "no existing active Wayland session" in result.stdout
    assert "USER_BUS_DIAGNOSTIC" not in result.stdout
    assert "USER_MANAGER_DIAGNOSTIC" not in result.stdout
    assert "TUNAOS_GDM_LOGIN_OK" not in result.stdout
    assert "TUNAOS_GDM_LOCK_OK" not in result.stdout
    assert "TUNAOS_GDM_UNLOCK_OK" not in result.stdout
    assert collections == ["sample", "once"]


@pytest.mark.parametrize("properties", [
    None,
    VALID.replace("Type=wayland", "Type=x11"),
    VALID.replace("Seat=seat0", "Seat=seat1"),
    VALID.replace("Active=yes", "Active=no"),
    VALID.replace("Name=fixture-user", "Name=other-user"),
])
def test_only_existing_qualifying_session_permits_user_bus_probe(tmp_path, properties):
    result, calls = run_diagnostics(tmp_path, properties)
    assert result.returncode == 0
    assert "--machine=" not in calls
    assert "--address=" not in calls
    assert "sudo " not in calls
    assert not (tmp_path / "diagnostic-session").exists()
    assert calls.count("loginctl list-sessions") == 1


def test_valid_session_snapshot_precedes_useful_user_bus_diagnostics(tmp_path):
    result, calls = run_diagnostics(tmp_path, VALID)
    assert result.returncode == 0
    assert result.stdout.index("Type=wayland") < result.stdout.index("DIRECT_USER_BUS_DIAGNOSTIC")
    assert calls.index("loginctl show-session") < calls.index("busctl --address=")
    assert "systemctl is-active --quiet user@1000.service" in calls
    assert "systemctl show user@1000.service" in calls
    assert "--machine=" not in calls and "sudo " not in calls
    assert "--auto-start=no --timeout=5s" in calls
    assert "b false" in result.stdout


@pytest.mark.parametrize("manager_active,session", [(False, "41"), (True, "stale")])
def test_inactive_manager_or_stale_session_hint_cannot_activate_user_bus(tmp_path, manager_active, session):
    result, calls = run_diagnostics(tmp_path, VALID, manager_active=manager_active, session=session)
    assert result.returncode == 0
    assert "--machine=" not in calls
    assert "--address=" not in calls
    assert "sudo " not in calls


def test_ibus_flood_cannot_hide_auth_chronology_or_expose_message_text(tmp_path):
    records = [
        {"MESSAGE": "pam(gdm-password): authentication failure password=fixture-secret", "__REALTIME_TIMESTAMP": "1", "_PID": "41"},
        {"MESSAGE": "pam(gdm-password): session closed for user fixture-user", "__REALTIME_TIMESTAMP": "2", "_PID": "41"},
    ] + [
        {"MESSAGE": "gdm IBus error typed-text=fixture-secret", "__REALTIME_TIMESTAMP": str(i + 3), "_PID": "99"}
        for i in range(600)
    ]
    result, calls = run_diagnostics(tmp_path, records=records)
    assert "time_us=1 pid=41 event=authentication failure" in result.stdout
    assert "time_us=2 pid=41 event=session closed" in result.stdout
    assert result.stdout.count("event=IBus diagnostic") == 50
    assert "fixture-secret" not in result.stdout + result.stderr
    assert "typed-text" not in result.stdout
    assert "gdm-password" not in result.stdout
    assert "-n 200 --grep=" in calls and "-n 50 --grep=" in calls


def test_manager_disappears_after_snapshot_before_socket_probe(tmp_path):
    overrides = {
        "systemctl": 'echo "systemctl $*" >>"$STATE/diagnostic-calls"\n'
        'if [[ "$1" == show ]]; then rm -f "$STATE/run/user/1000/bus"; echo ActiveState=inactive; fi\nexit 0',
    }
    result, calls = run_diagnostics(tmp_path, VALID, overrides=overrides)
    assert result.returncode == 0
    assert "Type=wayland" in result.stdout and "Active=yes" in result.stdout
    assert "ActiveState=inactive" in result.stdout
    assert "--address=" not in calls
    assert "--machine=" not in calls and "sudo " not in calls
    assert not (tmp_path / "diagnostic-session").exists()


def vanished_bus_stub():
    return '''echo "busctl $*" >>"$STATE/diagnostic-calls"
if [[ "$*" == *--machine=* ]]; then
    touch "$STATE/diagnostic-session"
    echo ACTIVATED_USER_MANAGER
elif [[ "$*" == *--address=* ]]; then
    rm -f "$STATE/run/user/1000/bus"
    echo DIRECT_BUS_UNAVAILABLE
    exit 17
fi'''


def test_socket_disappears_at_connect_without_activation_fallback(tmp_path):
    result, calls = run_diagnostics(tmp_path, VALID, overrides={"busctl": vanished_bus_stub()})
    assert result.returncode == 0
    assert "DIRECT_BUS_UNAVAILABLE" in result.stdout
    assert "Type=wayland" in result.stdout and "Active=yes" in result.stdout
    assert "--auto-start=no --timeout=5s" in calls
    assert "--machine=" not in calls and "sudo " not in calls
    assert not (tmp_path / "diagnostic-session").exists()


def test_failed_login_verdict_survives_manager_exit_during_diagnostics():
    scripts = diagnostic_scripts(VALID)
    scripts["busctl"] = vanished_bus_stub()
    scripts["systemctl"] = '''echo "systemctl $*" >>"$STATE/diagnostic-calls"
if [[ "$1" == is-active ]]; then
    python3 - <<'CREATE_FIXTURE_SOCKET'
import os, pathlib, socket
path = pathlib.Path(os.environ["STATE"]) / "run/user/1000"
path.mkdir(parents=True, exist_ok=True)
with socket.socket(socket.AF_UNIX) as bus:
    bus.bind(str(path / "bus"))
CREATE_FIXTURE_SOCKET
fi
exit 0'''
    result, collections, _, _ = screenshot.run_gate(login=False, diagnostics_scripts=scripts)
    assert result.returncode == 1, result.stderr
    assert "Type=wayland" in result.stdout and "Active=yes" in result.stdout
    assert "DIRECT_BUS_UNAVAILABLE" in result.stdout
    assert "ACTIVATED_USER_MANAGER" not in result.stdout
    assert "TUNAOS_GDM_LOGIN_OK" not in result.stdout
    assert "TUNAOS_GDM_LOCK_OK" not in result.stdout
    assert "TUNAOS_GDM_UNLOCK_OK" not in result.stdout
    assert collections == ["sample", "once"]
