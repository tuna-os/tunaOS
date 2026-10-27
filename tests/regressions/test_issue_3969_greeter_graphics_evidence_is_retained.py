"""tunaOS#3969: a GDM greeter that crashes must leave the evidence that explains it.

What failed. `albacore:tuna / linux-amd64` run 40236971341 (job 121303794669)
stopped at `GDM did not start an active Wayland session for tuna-ci-login`.
The retained journal showed one frame of the gnome-shell crash,
`meta_render_device_egl_stream_create_egl_display`, because the gate filtered
lines for `gdm|gnome-shell|mutter`. Four failed runs and twelve passed runs
shared the base digest, every package version, the QEMU build, the runner
image and the VM arguments, so the retained files could not say what differed.

What was measured. The full trace is in `corral/diagnostics/journal-warnings.txt`:
`eglInitialize` (libEGL_mesa) -> `dri2_initialize_device` ->
`drisw_init_screen` (libgallium-25.2.7.so + 0x35d6f), kernel line
`segfault at 8 ... error 4`, a NULL `swrast_loader` dereference. The exact base
image (mesa 25.2.7-4.el10.alma.5), booted under QEMU `-vga virtio` without
virgl, reproduces that signature when `LIBGL_ALWAYS_SOFTWARE=1` or
`MESA_LOADER_DRIVER_OVERRIDE=swrast` is in the process environment, and does
not crash without either. Nothing retained says which environment the crashing
greeter had, so the cause of the variable, and of the boots that lack it,
stays open.

What this test holds. The gate keeps a report of the greeter's renderer
environment, the DRM devices, the software-GL decision, the core dump's
recorded environment and the full trace, for a boot that fails and for one
that passes; the report is read-only and cannot change the verdict.

Falsification: behavioural for the report (the real
`scripts/greeter-graphics-evidence.sh` runs against a fixture guest whose
gnome-shell carries, or lacks, the variable) and for the wiring (the real
`scripts/gdm-login-gate.sh` runs a failing login). Delete the script, or the
two `collect_greeter_evidence` calls in the gate, and the tests fail.
"""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "scripts/greeter-graphics-evidence.sh"
GATE = ROOT / "scripts/gdm-login-gate.sh"

CRASH_ENV = [
    "LANG=C.UTF-8",
    "HOME=/var/lib/gdm",
    "XDG_SESSION_TYPE=wayland",
    "GNOME_SHELL_SESSION_MODE=gdm",
    "LIBGL_ALWAYS_SOFTWARE=1",
    "SECRET_TOKEN=hunter2",
]
CLEAN_ENV = [line for line in CRASH_ENV if not line.startswith("LIBGL_")]

# The line virtio_gpu logs without virgl, early in the kernel log.
VIRGL_LINE = "[    1.600000] [drm] features: -virgl +edid -resource_blob -host_visible"


def shim(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(0o755)


def build_guest(tmp_path: Path, *, greeter_env, dmesg_lines):
    """A fixture guest: /proc, sysfs, /dev/dri and the commands the report calls."""
    proc = tmp_path / "proc"
    for pid, comm, uid, env in (
        (100, "gnome-shell", 42, greeter_env),
        (101, "gdm-wayland-ses", 0, ["HOME=/root"]),
        (102, "gdm-session-wor", 0, ["HOME=/root"]),
        (103, "gnome-session-b", 42, greeter_env),
        (104, "dbus-daemon", 42, greeter_env),
        # Even the greeter UID is insufficient without session membership.
        (105, "gnome-shell", 42, ["HOME=/unrelated-gdm-session"]),
        (201, "gnome-shell", 1000, ["HOME=/home/other"]),
        (202, "gnome-session-b", 1000, ["HOME=/home/other"]),
        (401, "gdm-wayland-ses", 0, ["HOME=/unrelated-root-worker"]),
        (402, "gdm-session-wor", 0, ["HOME=/unrelated-root-worker"]),
        # A user's own bus daemon must not be reported as the greeter's.
        (200, "dbus-daemon", 1000, ["LIBGL_ALWAYS_SOFTWARE=1", "HOME=/home/other"]),
        (300, "sleep", 1000, ["LIBGL_ALWAYS_SOFTWARE=1"]),
    ):
        entry = proc / str(pid)
        entry.mkdir(parents=True)
        (entry / "comm").write_text(comm + "\n")
        parent = {100: 103, 103: 101, 101: 102}.get(pid, 1)
        (entry / "status").write_text(
            f"Name:\t{comm}\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\nPPid:\t{parent}\n"
        )
        scope = "session-c12.scope" if pid in (100, 103, 104) else "other.scope"
        (entry / "cgroup").write_text(f"0::/user.slice/{scope}\n")
        (entry / "stat").write_text(f"{pid} ({comm}) S " + "0 " * 18 + f"{pid} 0\n")
        (entry / "environ").write_bytes("\0".join(env).encode() + b"\0")
    (proc / "cmdline").write_bytes(b"root=UUID=x\0rw\0")

    sysfs = tmp_path / "sys-class-drm"
    driver_dir = tmp_path / "drivers" / "virtio_gpu"
    driver_dir.mkdir(parents=True)
    card = sysfs / "card0" / "device"
    card.mkdir(parents=True)
    (card / "driver").symlink_to(driver_dir)
    (card / "vendor").write_text("0x1af4\n")
    (card / "device").write_text("0x1050\n")
    (sysfs / "card0-Virtual-1").mkdir()

    dev_dri = tmp_path / "dev-dri"
    dev_dri.mkdir()
    (dev_dri / "card0").write_text("")
    (dev_dri / "renderD128").write_text("")

    flag = tmp_path / "run" / "tunaos-software-gl"
    flag.parent.mkdir()
    flag.write_text("")

    bindir = tmp_path / "bin"
    bindir.mkdir()
    calls = tmp_path / "calls.log"
    shim(bindir, "sleep", "exit 0\n")
    if dmesg_lines > 200:
        # A real dmesg writes a long log in many small writes.
        dmesg_body = (
            f'printf "%s\\n" "{VIRGL_LINE}"\n'
            f"for i in $(seq 1 {dmesg_lines}); do\n"
            '  printf "[%9.6f] filler line %s of the kernel ring buffer padding it out to size\\n" "$i" "$i"\n'
            "done\n"
        )
    else:
        # A short log leaves in one write, so grep -q can never outrun it.
        filler = "\n".join(f"[{i:9.6f}] filler line {i}" for i in range(dmesg_lines))
        dmesg_body = f"cat <<'DMESG'\n{VIRGL_LINE}\n{filler}\nDMESG\n"
    shim(bindir, "dmesg", dmesg_body)
    shim(bindir, "rpm", 'echo "mesa-libEGL-25.2.7-4.el10.alma.5.x86_64"\n')
    shim(
        bindir,
        "systemctl",
        f'echo "systemctl $*" >>"{calls}"\n'
        'case "$1" in\n'
        '  show-environment) printf "%s\\n" "LANG=C.UTF-8" "AWS_SECRET_ACCESS_KEY=manager-hunter2" "LIBGL_ALWAYS_SOFTWARE=1" ;;\n'
        '  status) echo "tunaos-software-gl-detect.service - Detect whether TunaOS sessions need software rendering" ;;\n'
        "esac\n",
    )
    shim(
        bindir, "loginctl", f'echo "loginctl $*" >>"{calls}"\n'
        'case "$1" in\n'
        'list-sessions) echo "c12 42 gdm seat0" ;;\n'
        'show-session) printf "%s\\n" "Class=greeter" "Service=gdm-launch-environment" "Seat=seat0" "User=42" "Scope=session-c12.scope" ;;\n'
        "esac\n",
    )
    shim(bindir, "getent", 'if [[ "$*" == "passwd gdm" ]]; then echo "gdm:x:42:42:GDM:/var/lib/gdm:/sbin/nologin"; else exit 2; fi\n')
    entry = {
        "_BOOT_ID": "a" * 32,
        "COREDUMP_PID": "2709",
        "COREDUMP_TIMESTAMP": "1000000",
        "COREDUMP_UID": "42",
        "COREDUMP_SESSION": "c12",
        "COREDUMP_CGROUP": "/user.slice/user-42.slice/session-c12.scope",
        "MESSAGE_ID": "fc2e22bc6ee647b6b90729ab34a250b1",
        "COREDUMP_EXE": "/usr/bin/gnome-shell",
        "COREDUMP_UNIT": "gdm.service",
        "COREDUMP_SIGNAL_NAME": "SIGSEGV",
        "COREDUMP_CMDLINE": "/usr/bin/gnome-shell",
        "COREDUMP_ENVIRON": list("\n".join(greeter_env).encode()),
    }
    records = tmp_path / "core-records.jsonl"
    records.write_text(json.dumps(entry) + "\n")
    shim(bindir, "journalctl", f'echo "journalctl $*" >>"{calls}"\ncat "{records}"\n')
    shim(
        bindir,
        "coredumpctl",
        f'echo "coredumpctl $*" >>"{calls}"\n'
        'echo "           PID: 2709 (gnome-shell)"\n'
        'echo "#6  0x1 meta_render_device_egl_stream_create_egl_display (libmutter-17.so.0 + 0x153c84)"\n'
        'echo "#13 0x2 meta_backend_native_init_basic (libmutter-17.so.0 + 0x1b35ee)"\n'
        'for i in $(seq 1 250); do echo "module metadata frame $i"; done\n',
    )

    env = dict(os.environ)
    env.update(
        PATH=f"{bindir}:{os.environ['PATH']}",
        TUNAOS_EVIDENCE_PROC=str(proc),
        TUNAOS_EVIDENCE_SYSFS_DRM=str(sysfs),
        TUNAOS_EVIDENCE_DEV_DRI=str(dev_dri),
        TUNAOS_EVIDENCE_FLAG=str(flag),
    )
    return env, calls


def report(tmp_path, *, greeter_env=CRASH_ENV, dmesg_lines=6000, mode=("sample", "3")):
    env, calls = build_guest(tmp_path, greeter_env=greeter_env, dmesg_lines=dmesg_lines)
    result = subprocess.run(
        ["bash", str(EVIDENCE), *mode], env=env, capture_output=True, text=True, check=False
    )
    return result, calls


def test_report_names_the_renderer_environment_of_the_crashing_greeter(tmp_path):
    result, _ = report(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "--- pid 100 comm=gnome-shell uid=42" in result.stdout
    assert "LIBGL_ALWAYS_SOFTWARE=1" in result.stdout
    # The greeter chain is reported by name, in the order it starts.
    assert "--- pid 101 comm=gdm-wayland-ses uid=0" in result.stdout


def test_report_does_not_print_variables_it_has_no_reason_to_print(tmp_path):
    result, _ = report(tmp_path)
    assert "hunter2" not in result.stdout
    assert "SECRET_TOKEN" not in result.stdout
    assert "AWS_SECRET_ACCESS_KEY" not in result.stdout
    assert "manager-hunter2" not in result.stdout


def test_report_ignores_other_users_processes(tmp_path):
    result, _ = report(tmp_path)
    assert "pid 200" not in result.stdout
    for pid in (105, 201, 202, 300, 401, 402):
        assert f"pid {pid} " not in result.stdout
    assert "/home/other" not in result.stdout
    assert "/unrelated-gdm-session" not in result.stdout
    assert "/unrelated-root-worker" not in result.stdout



def test_greeter_membership_retains_root_ancestors_and_owned_chain(tmp_path):
    result, _ = report(tmp_path, dmesg_lines=1)
    for pid in (100, 101, 102, 103, 104):
        assert f"--- pid {pid} " in result.stdout


@pytest.mark.parametrize("properties", [
    "", "Class=user\nService=gdm-password\nSeat=seat0\nUser=42\nScope=session-c12.scope",
    "Class=greeter\nService=other\nSeat=seat0\nUser=42\nScope=session-c12.scope",
    "Class=greeter\nService=gdm-launch-environment\nSeat=seat1\nUser=42\nScope=session-c12.scope",
])
def test_unverified_greeter_session_does_not_collect_process_environments(tmp_path, properties):
    env, _ = build_guest(tmp_path, greeter_env=CRASH_ENV, dmesg_lines=1)
    bindir = Path(env["PATH"].split(":", 1)[0])
    shim(bindir, "loginctl", 'if [[ "$1" == list-sessions ]]; then echo "c12 42 gdm seat0"; else cat <<"PROPERTIES"\n' + properties + "\nPROPERTIES\nfi\n")
    result = subprocess.run(
        ["bash", str(EVIDENCE), "once", "0"], env=env,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    assert "--- pid " not in result.stdout
    assert "(no verified greeter process was found)" in result.stdout


def test_root_worker_in_greeter_scope_needs_no_live_descendant(tmp_path):
    env, _ = build_guest(tmp_path, greeter_env=CRASH_ENV, dmesg_lines=1)
    proc = Path(env["TUNAOS_EVIDENCE_PROC"])
    (proc / "401/cgroup").write_text("0::/user.slice/session-c12.scope\n")
    result = subprocess.run(
        ["bash", str(EVIDENCE), "once", "0"], env=env,
        capture_output=True, text=True, check=False,
    )
    assert "--- pid 401 comm=gdm-wayland-ses uid=0" in result.stdout
    assert "--- pid 402 " not in result.stdout


@pytest.mark.parametrize("pid", [201, 202, 105])
def test_wrong_owner_or_scope_cannot_borrow_greeter_membership(tmp_path, pid):
    env, _ = build_guest(tmp_path, greeter_env=CRASH_ENV, dmesg_lines=1)
    proc = Path(env["TUNAOS_EVIDENCE_PROC"])
    # Cross-user candidates remain excluded even inside the greeter scope.
    # A same-UID candidate in a similar-looking scope is not a member either.
    scope = "session-c12.scope" if pid != 105 else "session-c12.scope-extra"
    (proc / str(pid) / "cgroup").write_text(f"0::/user.slice/{scope}\n")
    result = subprocess.run(
        ["bash", str(EVIDENCE), "once", "0"], env=env,
        capture_output=True, text=True, check=False,
    )
    assert f"--- pid {pid} " not in result.stdout


def test_greeter_owner_is_resolved_instead_of_assuming_uid_42(tmp_path):
    env, _ = build_guest(tmp_path, greeter_env=CRASH_ENV, dmesg_lines=1)
    proc = Path(env["TUNAOS_EVIDENCE_PROC"])
    bindir = Path(env["PATH"].split(":", 1)[0])
    loginctl = bindir / "loginctl"
    loginctl.write_text(loginctl.read_text().replace("42", "121"))
    for pid in (100, 103, 104):
        status = proc / str(pid) / "status"
        status.write_text(status.read_text().replace("42", "121"))
    result = subprocess.run(
        ["bash", str(EVIDENCE), "once", "0"], env=env,
        capture_output=True, text=True, check=False,
    )
    assert "--- pid 100 comm=gnome-shell uid=121" in result.stdout
    assert "--- pid 101 comm=gdm-wayland-ses uid=0" in result.stdout
    assert "--- pid 105 " not in result.stdout


@pytest.mark.parametrize("pid,unit,expected", [
    (100, "org.gnome.Shell@gdm.service", True),
    (104, "dbus.service", True),
    (100, "org.gnome.Shell@wayland.service", False),
    (103, "unrelated.service", False),
    (201, "org.gnome.Shell@gdm.service", False),
])
def test_only_explicit_gdm_user_units_are_members(tmp_path, pid, unit, expected):
    env, _ = build_guest(tmp_path, greeter_env=CRASH_ENV, dmesg_lines=1)
    proc = Path(env["TUNAOS_EVIDENCE_PROC"])
    (proc / str(pid) / "cgroup").write_text(f"0::/user.slice/user-42.slice/user@42.service/session.slice/{unit}\n")
    result = subprocess.run(
        ["bash", str(EVIDENCE), "once", "0"], env=env,
        capture_output=True, text=True, check=False,
    )
    assert (f"--- pid {pid} " in result.stdout) is expected


def test_process_replacement_after_selection_does_not_reopen_environment(tmp_path):
    env, _ = build_guest(tmp_path, greeter_env=CRASH_ENV, dmesg_lines=1)
    bindir = Path(env["PATH"].split(":", 1)[0])
    # Replace the synthetic process after Python has selected and collected it,
    # but before the shell consumes its output. No real process is inspected.
    shim(bindir, "python3", f'"{sys.executable}" "$@" >"{tmp_path}/python-output"\n'
         'if [[ -n "${PROCESSES:-}" ]]; then\n'
         'printf "Name: gnome-shell\\nUid: 1000 1000 1000 1000\\nPPid: 1\\n" >"$TUNAOS_EVIDENCE_PROC/100/status"\n'
         'printf "HOME=/home/unrelated-reused-pid\\0" >"$TUNAOS_EVIDENCE_PROC/100/environ"\n'
         'fi\n' + f'cat "{tmp_path}/python-output"\n')
    result = subprocess.run(
        ["bash", str(EVIDENCE), "once", "0"], env=env,
        capture_output=True, text=True, check=False,
    )
    assert "--- pid 100 comm=gnome-shell uid=42" in result.stdout
    assert "unrelated-reused-pid" not in result.stdout


def test_identity_change_during_environment_read_discards_record(tmp_path):
    env, _ = build_guest(tmp_path, greeter_env=CRASH_ENV, dmesg_lines=1)
    process = Path(env["TUNAOS_EVIDENCE_PROC"]) / "100"
    (process / "environ").unlink()
    os.mkfifo(process / "environ")

    def replace_while_reading():
        with (process / "environ").open("wb") as stream:
            (process / "status").write_text("Name: gnome-shell\nUid: 1000 1000 1000 1000\nPPid: 1\n")
            stream.write(b"HOME=/home/unrelated-during-read\0")

    writer = threading.Thread(target=replace_while_reading, daemon=True)
    writer.start()
    result = subprocess.run(
        ["bash", str(EVIDENCE), "once", "0"], env=env,
        capture_output=True, text=True, check=False, timeout=20,
    )
    writer.join(timeout=1)
    assert not writer.is_alive()
    assert "--- pid 100 " not in result.stdout
    assert "unrelated-during-read" not in result.stdout

def test_a_greeter_without_forced_software_rendering_is_reported_without_it(tmp_path):
    # Negative control: the report must not invent the variable.
    result, _ = report(tmp_path, greeter_env=CLEAN_ENV)
    assert "--- pid 100 comm=gnome-shell uid=42" in result.stdout
    gnome_shell = result.stdout.split("--- pid 100", 1)[1].split("---", 1)[0]
    assert "HOME=/var/lib/gdm" in gnome_shell
    assert "LIBGL_ALWAYS_SOFTWARE" not in gnome_shell
    assert "LIBGL_ALWAYS_SOFTWARE" not in result.stdout.split("gnome-shell core dumps", 1)[1]


def test_report_lists_the_drm_devices_with_their_drivers(tmp_path):
    result, _ = report(tmp_path)
    assert "card0 driver=virtio_gpu vendor=0x1af4 device=0x1050" in result.stdout
    assert "renderD128" in result.stdout
    # A connector entry is not a card.
    assert "card0-Virtual-1 driver" not in result.stdout


def test_report_records_the_core_dump_environment_and_the_full_trace(tmp_path):
    result, _ = report(tmp_path)
    after_dump = result.stdout.split("environment systemd-coredump recorded", 1)[1]
    assert "COREDUMP_ENVIRON renderer and session variables:" in after_dump
    assert "LIBGL_ALWAYS_SOFTWARE=1" in after_dump
    assert "SECRET_TOKEN" not in after_dump
    assert "meta_render_device_egl_stream_create_egl_display" in result.stdout
    assert "meta_backend_native_init_basic" in result.stdout
    assert "module metadata frame 250" in result.stdout



def core_report(tmp_path, mutate):
    env, calls = build_guest(tmp_path, greeter_env=CRASH_ENV, dmesg_lines=1)
    records = tmp_path / "core-records.jsonl"
    original = json.loads(records.read_text())
    records.write_text("\n".join(json.dumps(entry) for entry in mutate(original)) + "\n")
    result = subprocess.run(
        ["bash", str(EVIDENCE), "once", "0"], env=env,
        capture_output=True, text=True, check=False,
    )
    return result, calls


def test_newer_other_user_core_cannot_replace_verified_greeter(tmp_path):
    def records(greeter):
        other = dict(greeter, COREDUMP_UID="1000", COREDUMP_PID="9999",
                     COREDUMP_TIMESTAMP="2000000", COREDUMP_CMDLINE="unrelated-user-core",
                     COREDUMP_ENVIRON="GNOME_SHELL_SESSION_MODE=gdm\nHOME=/home/unrelated-core")
        return [greeter, other]

    result, calls = core_report(tmp_path, records)
    assert result.returncode == 0
    assert "COREDUMP_PID=2709" in result.stdout
    assert "unrelated-user-core" not in result.stdout
    assert "/home/unrelated-core" not in result.stdout
    trace_calls = [line for line in calls.read_text().splitlines() if line.startswith("coredumpctl ")]
    assert len(trace_calls) == 1
    for match in ("_BOOT_ID=" + "a" * 32, "COREDUMP_PID=2709", "COREDUMP_TIMESTAMP=1000000",
                  "COREDUMP_UID=42", "COREDUMP_EXE=/usr/bin/gnome-shell"):
        assert match in trace_calls[0]
    assert "coredumpctl list" not in calls.read_text()


@pytest.mark.parametrize("field,value", [
    ("COREDUMP_UID", "1000"), ("COREDUMP_UID", None),
    ("COREDUMP_ENVIRON", "GNOME_SHELL_SESSION_MODE=user\nHOME=/home/unrelated-core"),
    ("COREDUMP_ENVIRON", None), ("COREDUMP_CGROUP", "/unrelated.scope"),
    ("COREDUMP_SESSION", "c99"), ("COREDUMP_PID", None),
    ("COREDUMP_TIMESTAMP", None), ("_BOOT_ID", None),
])
def test_unattributed_core_never_reads_a_trace_or_prints_its_environment(tmp_path, field, value):
    def records(entry):
        entry["COREDUMP_CMDLINE"] = "unattributed-core"
        entry[field] = value
        return [entry]

    result, calls = core_report(tmp_path, records)
    assert "no verified GDM gnome-shell core dump" in result.stdout
    assert "unattributed-core" not in result.stdout
    assert "/home/unrelated-core" not in result.stdout
    assert "coredumpctl " not in calls.read_text()


def test_gdm_core_in_explicit_user_unit_can_be_attributed_without_session_scope(tmp_path):
    def records(entry):
        entry.pop("COREDUMP_SESSION")
        entry["COREDUMP_CGROUP"] = "/user.slice/user-42.slice/user@42.service/session.slice/org.gnome.Shell@gdm.service"
        return [entry]

    result, calls = core_report(tmp_path, records)
    assert "COREDUMP_PID=2709" in result.stdout
    assert "coredumpctl info" in calls.read_text()


def test_missing_gdm_account_fails_closed_for_core_attribution(tmp_path):
    env, calls = build_guest(tmp_path, greeter_env=CRASH_ENV, dmesg_lines=1)
    bindir = Path(env["PATH"].split(":", 1)[0])
    shim(bindir, "getent", "exit 2\n")
    result = subprocess.run(
        ["bash", str(EVIDENCE), "once", "0"], env=env,
        capture_output=True, text=True, check=False,
    )
    assert "no verified GDM gnome-shell core dump" in result.stdout
    assert "coredumpctl " not in calls.read_text()

def test_coredump_environment_journal_request_preserves_large_fields(tmp_path):
    _, calls = report(tmp_path)
    assert "--all" in calls.read_text()


def test_detector_replay_shows_a_long_kernel_log_defeating_the_detector(tmp_path):
    """tunaos-software-gl-detect reads `dmesg | grep -Eq` under pipefail.

    A long log makes dmesg die of SIGPIPE when grep -q leaves at its first
    match, so the detector sees "no match" for a line that is there.
    """
    result, _ = report(tmp_path, dmesg_lines=6000)
    for i in range(1, 6):
        assert f"detector pipeline replay {i}: exit=141" in result.stdout
    assert "-virgl lines (whole stream): 1" in result.stdout


def test_detector_replay_is_clean_when_the_kernel_log_is_short(tmp_path):
    # Negative control: 141 comes from the log's length, not from the script.
    result, _ = report(tmp_path, dmesg_lines=1)
    for i in range(1, 6):
        assert f"detector pipeline replay {i}: exit=0" in result.stdout


def test_report_only_reads_guest_state(tmp_path):
    result, calls = report(tmp_path)
    assert result.returncode == 0
    recorded = calls.read_text()
    for verb in ("restart", "start", "stop", "enable", "disable", "set-environment", "kill", "mask"):
        assert f"systemctl {verb}" not in recorded
    assert "systemctl status tunaos-software-gl-detect.service" in recorded
    assert "systemctl show-environment" in recorded


def test_report_never_fails_the_caller_when_every_tool_is_missing(tmp_path):
    env, _ = build_guest(tmp_path, greeter_env=CRASH_ENV, dmesg_lines=1)
    bindir = Path(env["PATH"].split(":", 1)[0])
    for name in ("dmesg", "rpm", "systemctl", "loginctl", "journalctl", "coredumpctl"):
        shim(bindir, name, "exit 1\n")
    result = subprocess.run(
        ["bash", str(EVIDENCE), "once", "0"], env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0
    assert "==> gnome-shell core dumps" in result.stdout


def test_report_survives_being_piped_into_bash_s(tmp_path):
    # The gate runs it as `ssh ... bash -s -- MODE N < script`. A command that
    # read stdin would swallow the rest of the script.
    env, _ = build_guest(tmp_path, greeter_env=CRASH_ENV, dmesg_lines=1)
    result = subprocess.run(
        ["bash", "-s", "--", "once", "0"],
        env=env,
        input=EVIDENCE.read_text(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "==> gnome-shell core dumps" in result.stdout
    assert "environment systemd-coredump recorded" in result.stdout


def run_failing_login(tmp_path, gate=GATE):
    """Run the real gate to a failed login: nobody ever gets a session."""
    out = tmp_path / "out"
    (out / "corral").mkdir(parents=True)
    (out / "corral" / "result.json").write_text(
        json.dumps({"ssh": {"host": "127.0.0.1", "port": 2222, "user": "root", "identityFile": "/tmp/id"}})
    )
    env, _ = build_guest(tmp_path, greeter_env=CRASH_ENV, dmesg_lines=1)
    bindir = Path(env["PATH"].split(":", 1)[0])
    shim(
        bindir,
        "corral",
        'case "$1" in\n'
        "  screenshot)\n"
        '    while [[ $# -gt 0 ]]; do [[ "$1" == -o ]] && { shift; : >"$1"; echo "Screenshot written to $1 (1280x800, deviation 0.5000 — painted)"; break; }; shift; done ;;\n'
        "esac\n",
    )
    shim(
        bindir,
        "ssh",
        'while [[ $# -gt 0 ]]; do\n  case "$1" in\n    *@*) shift; break ;;\n    -F|-i|-p|-o) shift 2 ;;\n    -*) shift ;;\n    *) break ;;\n  esac\ndone\nexec "$@"\n',
    )
    shim(bindir, "id", 'exec /usr/bin/id "$@"\n')
    shim(bindir, "busctl", "exit 1\n")
    shim(bindir, "systemctl", 'if [[ "${1:-}" == show-environment ]]; then echo "AWS_SECRET_ACCESS_KEY=manager-hunter2"; fi\nif [[ "${1:-}" == is-active ]]; then exit 0; fi\nexit 0\n')
    env.update(
        CORRAL=str(bindir / "corral"),
        TUNAOS_GDM_TEST_PASSWORD="test-password",
        TUNAOS_GDM_ACCOUNTS_DIR=str(tmp_path / "accts"),
    )
    result = subprocess.run(
        ["bash", str(gate), "testvm", str(out), "tuna-ci-login"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, out


def test_a_failed_login_keeps_the_greeter_report_from_before_and_after(tmp_path):
    result, out = run_failing_login(tmp_path)
    # The verdict is unchanged: a login that never gets a session fails the gate.
    assert result.returncode == 1, result.stderr
    assert "GDM did not start an active Wayland session for tuna-ci-login" in result.stdout + result.stderr
    before = out / "greeter-graphics-evidence.txt"
    after = out / "greeter-graphics-evidence-after-failure.txt"
    assert before.is_file() and after.is_file()
    assert "mode=sample samples=40" in before.read_text()
    assert "--- pid 100 comm=gnome-shell uid=42" in before.read_text()
    assert "mode=once samples=0" in after.read_text()
    assert "manager-hunter2" not in after.read_text()

def test_paint_failure_collects_after_failure_report(tmp_path):
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "corral").mkdir()
    (out / "corral" / "result.json").write_text(
        json.dumps({"ssh": {"host": "127.0.0.1", "port": 2222, "user": "root", "identityFile": "/tmp/id"}})
    )
    env, _ = build_guest(tmp_path, greeter_env=CRASH_ENV, dmesg_lines=1)
    bindir = Path(env["PATH"].split(":", 1)[0])
    shim(bindir, "corral", 'if [[ "$1" == screenshot ]]; then echo "blank frame"; return 0; fi\n')
    shim(
        bindir,
        "ssh",
        'while [[ $# -gt 0 ]]; do\n  case "$1" in\n    *@*) shift; break ;;\n    -F|-i|-p|-o) shift 2 ;;\n    -*) shift ;;\n    *) break ;;\n  esac\ndone\nexec "$@"\n',
    )
    shim(bindir, "id", 'exec /usr/bin/id "$@"\n')
    shim(bindir, "busctl", "exit 1\n")
    shim(bindir, "loginctl", "exit 0\n")
    shim(bindir, "systemctl", 'if [[ "${1:-}" == is-active ]]; then exit 0; fi\nexit 0\n')
    env.update(CORRAL=str(bindir / "corral"), TUNAOS_GDM_TEST_PASSWORD="test-password", TUNAOS_GDM_ACCOUNTS_DIR=str(tmp_path / "accts"))
    result = subprocess.run(
        ["bash", str(GATE), "testvm", str(out), "tuna-ci-login"],
        env=env, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert "no painted frame appeared" in result.stderr
    after = out / "greeter-graphics-evidence-after-failure.txt"
    assert after.is_file()
    assert "mode=once samples=0" in after.read_text()



def test_evidence_collection_cannot_fail_the_gate(tmp_path):
    # Copy the gate somewhere with no report script beside it: the redirect from
    # the missing file fails, and the gate must still reach its own verdict.
    gate_dir = tmp_path / "gate-copy"
    gate_dir.mkdir()
    gate_copy = gate_dir / "gdm-login-gate.sh"
    gate_copy.write_text(GATE.read_text())
    gate_copy.chmod(0o755)
    result, out = run_failing_login(tmp_path, gate=gate_copy)
    assert result.returncode == 1
    assert "GDM did not start an active Wayland session for tuna-ci-login" in result.stdout + result.stderr
    assert not (out / "greeter-graphics-evidence.txt").exists()


@pytest.mark.parametrize("path", [EVIDENCE])
def test_the_report_script_is_executable_and_parses(path):
    assert os.access(path, os.X_OK)
    subprocess.run(["bash", "-n", str(path)], check=True)
