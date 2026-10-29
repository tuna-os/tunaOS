"""Synthetic evidence tests, not observations of actual GDM, Cogl logging or EGL.

Only pure evidence validators and temporary proc-like files run here. Positive
verdicts qualify these fixtures only; no guest, probe binary or graphics runs.
"""

import copy
import importlib.util
import os
from pathlib import Path
import sys

import pytest


MANUAL = Path(__file__).resolve().parent / "manual"
CONTROL_BOOT = "1" * 32
CANDIDATE_BOOT = "2" * 32
RENDERER = "llvmpipe (LLVM 19.1.7, 256 bits)"
MESSAGE = "[WINSYS] Checking features\n  GL_VENDOR: Mesa\n  GL_RENDERER: " + RENDERER + "\n  GL_VERSION: 4.5"


@pytest.fixture
def guest(monkeypatch):
    # Restore module identities and import paths after each test; no suite-global
    # sys.path insertion or collision with the independently loaded lab tests.
    monkeypatch.syspath_prepend(str(MANUAL))
    for name in ("mesa_3969", "mesa_3969_packages", "mesa_3969_guest"):
        spec = importlib.util.spec_from_file_location(name, MANUAL / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
    return sys.modules["mesa_3969_guest"]


def renderer_record(role="user", boot=CANDIDATE_BOOT, session_id="c2"):
    uid, pid = (42, 471) if role == "greeter" else (1000, 829)
    scope = f"session-{session_id}.scope"
    process = {
        "uid": uid, "start_ticks": 1200, "comm": "gnome-shell",
        "exe": "/usr/bin/gnome-shell", "cgroups": [f"0::/user.slice/user-{uid}.slice/{scope}"],
    }
    environment = {"LIBGL_ALWAYS_SOFTWARE": "1", "COGL_DEBUG": "winsys", "XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0"}
    if role == "greeter":
        environment["GNOME_SHELL_SESSION_MODE"] = "gdm"
    return {
        "role": role, "pid": pid, "boot_id": boot, "process": process,
        "identity_after": copy.deepcopy(process), "environment": environment,
        "environment_after": dict(environment), "clock_ticks": 100,
        "observed_us": 15_000_000, "collector_greeter_pids": [471],
        "renderer": RENDERER,
        "session": {"id": session_id, "Class": "greeter" if role == "greeter" else "user",
                    "Service": "gdm-launch-environment" if role == "greeter" else "gdm-password",
                    "Seat": "seat0", "User": str(uid), "Scope": scope,
                    "Name": "gdm" if role == "greeter" else "tuna-ci-login",
                    "Type": "wayland", "Active": "yes"},
        "journal": {"_BOOT_ID": boot, "_PID": str(pid), "_UID": str(uid),
                    "_EXE": "/usr/bin/gnome-shell", "__MONOTONIC_TIMESTAMP": "13000000", "MESSAGE": MESSAGE},
    }


@pytest.fixture
def pair(guest):
    baseline_mesa = {"name": "mesa-libEGL", "epoch": 0, "version": "25.2.7",
                     "release": "4.el10.alma.5", "arch": "x86_64",
                     "source_rpm": guest.INPUTS["source_rpm"], "header_sha256": "a" * 64}
    unrelated = {"name": "gnome-shell", "epoch": 0, "version": "48.3", "release": "1.el10",
                 "arch": "x86_64", "source_rpm": "gnome-shell-48.3-1.el10.src.rpm", "header_sha256": "b" * 64}
    baseline = [baseline_mesa, unrelated]
    manifest = {"probe": {"binary_sha256": "c" * 64},
                "baseline": {"software_policy_sha256": "d" * 64}, "arms": {}}
    reports = {}
    for arm, boot, header, exits in (
        ("control", CONTROL_BOOT, "e" * 64, [0, 139, 139, 139]),
        ("candidate", CANDIDATE_BOOT, "f" * 64, [0, 0, 0, 0]),
    ):
        installed = dict(baseline_mesa, header_sha256=header)
        package = dict(installed, path=f"rpms/{arm}/mesa-libEGL-25.2.7-4.el10.alma.5.x86_64.rpm",
                       sha256="9" * 64, bytes=2048)
        manifest["arms"][arm] = {"packages": [package]}
        probe = {"schema_version": 1, "boot_id": boot, "binary_sha256": "c" * 64,
                 "status": "collected", "device": "/dev/dri/card0", "cases": [
                     {"case": case, "exit": code, "status": "initialized" if code == 0 else "crashed",
                      "started_us": 1_000_000 + index * 1000, "ended_us": 1_000_500 + index * 1000,
                      "stdout": "eglInitialize=success version=1.5" if code == 0 else "", "stderr": ""}
                     for index, (case, code) in enumerate(zip(("clean", "software", "override", "combined"), exits))
                 ]}
        reports[arm] = {
            "arm": arm, "baseline_inventory": copy.deepcopy(baseline), "gate_exit": 1 if arm == "control" else 0,
            "observer_errors": [], "transitions": {"login": True, "lock": True, "unlock": True,
                                                    "same_session": True, "session": "c2"},
            "screenshots": {"ready": True, "logged-in": True, "locked": True, "unlocked": True},
            "snapshots": [{"boot_id": boot, "inventory": [installed, dict(unrelated)],
                           "software_policy_sha256": "d" * 64, "selinux": "Enforcing", "probe": probe,
                           "crashes": [], "kernel_crash": False, "renderer_records": [
                               renderer_record("greeter", boot, "g1"), renderer_record("user", boot, "c2")
                           ]}],
        }
    return manifest, reports


@pytest.mark.parametrize("role", ["greeter", "user"])
def test_bound_cogl_software_renderer_is_accepted(guest, role):
    record = renderer_record(role)
    assert guest.validate_renderer(record, CANDIDATE_BOOT) is True


@pytest.mark.parametrize("path,value", [
    (("journal", "_PID"), "830"),
    (("journal", "_UID"), "1001"),
    (("journal", "_BOOT_ID"), CONTROL_BOOT),
    (("boot_id",), CONTROL_BOOT),
    (("journal", "_EXE"), "/tmp/gnome-shell"),
    (("process", "exe"), "/usr/bin/other-shell"),
    (("process", "comm"), "other-shell"),
    (("journal", "__MONOTONIC_TIMESTAMP"), "11999999"),
    (("journal", "__MONOTONIC_TIMESTAMP"), "15000001"),
    (("identity_after", "start_ticks"), 1400),
    (("identity_after", "uid"), 1001),
    (("environment_after", "LIBGL_ALWAYS_SOFTWARE"), "0"),
    (("session", "User"), "1001"),
    (("session", "Seat"), "seat1"),
    (("session", "Type"), "x11"),
    (("session", "Active"), "no"),
    (("session", "Name"), "someone-else"),
    (("session", "Class"), "greeter"),
    (("session", "Scope"), "session-unrelated.scope"),
    (("environment", "LIBGL_ALWAYS_SOFTWARE"), "0"),
    (("environment", "COGL_DEBUG"), ""),
    (("environment", "XDG_SESSION_TYPE"), "x11"),
    (("environment", "MESA_LOADER_DRIVER_OVERRIDE"), "swrast"),
    (("environment", "LD_PRELOAD"), "/tmp/renderer.so"),
])
def test_renderer_rejects_unbound_or_changed_identity(guest, path, value):
    record = renderer_record()
    target = record
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    # Environment restrictions must fail independently of the stability check.
    if path[0] == "environment":
        record["environment_after"] = dict(record["environment"])
    assert guest.validate_renderer(record, CANDIDATE_BOOT) is False


def test_reused_pid_cannot_reuse_predecessor_renderer_log(guest):
    record = renderer_record()
    record["process"]["start_ticks"] = 1400
    record["identity_after"] = copy.deepcopy(record["process"])
    assert guest.validate_renderer(record, CANDIDATE_BOOT) is False


@pytest.mark.parametrize("field,value", [
    ("collector_greeter_pids", []),
    ("session", {"Service": "gdm-password"}),
    ("environment", {"GNOME_SHELL_SESSION_MODE": "user"}),
])
def test_greeter_requires_existing_collector_and_real_gdm_session(guest, field, value):
    record = renderer_record("greeter")
    if isinstance(value, dict):
        record[field].update(value)
    else:
        record[field] = value
    record["environment_after"] = dict(record["environment"])
    assert guest.validate_renderer(record, CANDIDATE_BOOT) is False


@pytest.mark.parametrize("message,actual", [
    ("LIBGL_ALWAYS_SOFTWARE=1 COGL_DEBUG=winsys", RENDERER),
    ("GL_RENDERER: " + RENDERER, RENDERER),
    ("[WINSYS] Checking features\nGL_RENDERER: virgl (Mesa Intel)", "virgl (Mesa Intel)"),
    ("[WINSYS] Checking features\nGL_RENDERER: NVIDIA RTX 4090", "NVIDIA RTX 4090"),
    (MESSAGE, "softpipe"),
])
def test_requested_flags_or_hardware_are_not_actual_software_proof(guest, message, actual):
    record = renderer_record()
    record["journal"]["MESSAGE"] = message
    record["renderer"] = actual
    record["software_verified"] = True  # Stored conclusions are not authority.
    assert guest.validate_renderer(record, CANDIDATE_BOOT) is False


@pytest.fixture
def proc_directory(tmp_path):
    process = tmp_path / "829"
    process.mkdir()
    (process / "status").write_text("Name:\tgnome-shell\nUid:\t1000\t1000\t1000\t1000\n")
    # stat field 22 is starttime; parentheses within comm are legal.
    (process / "stat").write_text("829 (gnome (shell)) S " + "0 " * 18 + "1200 0 0\n")
    (process / "comm").write_text("gnome-shell\n")
    (process / "cgroup").write_text("0::/user.slice/user-1000.slice/session-c2.scope\n")
    (process / "exe").symlink_to("/usr/bin/gnome-shell")
    (process / "environ").write_bytes(b"LIBGL_ALWAYS_SOFTWARE=1\0COGL_DEBUG=winsys\0XDG_SESSION_TYPE=wayland\0TOKEN=private\0")
    return process


def test_proc_reader_extracts_start_credentials_and_only_relevant_environment(guest, proc_directory):
    fd = os.open(proc_directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert guest.process_identity(fd) == {
            "uid": 1000, "start_ticks": 1200, "comm": "gnome-shell", "exe": "/usr/bin/gnome-shell",
            "cgroups": ["0::/user.slice/user-1000.slice/session-c2.scope"],
        }
        assert guest.process_environment(fd) == {"LIBGL_ALWAYS_SOFTWARE": "1", "COGL_DEBUG": "winsys", "XDG_SESSION_TYPE": "wayland"}
    finally:
        os.close(fd)


@pytest.mark.parametrize("uids", ["0 0 0 0", "1000 0 1000 1000", "1000 1000 1000"])
def test_proc_reader_refuses_root_or_unstable_credentials(guest, proc_directory, uids):
    (proc_directory / "status").write_text(f"Uid:\t{uids}\n")
    fd = os.open(proc_directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(guest.LabError, match="credentials"):
            guest.process_identity(fd)
    finally:
        os.close(fd)


def test_proc_reader_refuses_duplicate_renderer_environment(guest, proc_directory):
    (proc_directory / "environ").write_bytes(b"LIBGL_ALWAYS_SOFTWARE=1\0LIBGL_ALWAYS_SOFTWARE=0\0")
    fd = os.open(proc_directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(guest.LabError, match="duplicate"):
            guest.process_environment(fd)
    finally:
        os.close(fd)


def test_fixture_pair_requires_control_reproduction_and_retains_failed_control_gate(guest, pair):
    manifest, reports = pair
    result = guest.compare(manifest, reports)
    assert result["ok"] is True
    assert result["verdict"] == "lab-repair-demonstrated"
    assert result["distinct_arm_boots"] is True
    assert result["arms"]["control"]["gate_exit"] == 1
    assert result["arms"]["control"]["probe"]["exits"] == [0, 139, 139, 139]
    assert result["arms"]["candidate"]["failures"] == []
    assert result["arms"]["candidate"]["renderer_record_count"] == 2


@pytest.mark.parametrize("code,outcome", [
    (3, "unexercised-egldevice-enumeration"), (4, "unexercised-no-matching-egldevice"),
])
def test_unavailable_egldevice_is_labelled_unexercised_with_complete_fixture_ui_proof(guest, pair, code, outcome):
    manifest, reports = pair
    cases = reports["candidate"]["snapshots"][0]["probe"]["cases"]
    for case in cases[1:]:
        case.update(exit=code, status="egldevice-unavailable", stdout="")
    result = guest.compare(manifest, reports)
    assert result["ok"] is True
    assert result["arms"]["candidate"]["probe"]["cases"] == [
        {"case": name, "exit": code, "outcome": outcome} for name in ("software", "override", "combined")
    ]
    reports["candidate"]["snapshots"][0]["renderer_records"] = []
    result = guest.compare(manifest, reports)
    assert result["ok"] is False
    assert "missing-bound-software-user-renderer" in result["arms"]["candidate"]["failures"]


@pytest.mark.parametrize("arm,mutation,reason", [
    ("control", "absent", "missing-or-wrong-probe"),
    ("candidate", "absent", "missing-or-wrong-probe"),
    ("control", "not-run", "probe-not-run"),
    ("candidate", "wrong-binary", "missing-or-wrong-probe"),
    ("candidate", "missing-case", "missing-or-reordered-probe-cases"),
    ("candidate", "reordered", "missing-or-reordered-probe-cases"),
    ("control", "not-reproduced", "control-reproduction"),
    ("candidate", "clean-unavailable", "candidate-clean-did-not-initialize"),
    ("candidate", "crash", "candidate-probe-crash-or-failure"),
    ("candidate", "timeout", "candidate-probe-crash-or-failure"),
    ("candidate", "mislabelled-unavailable", "candidate-probe-crash-or-failure"),
])
def test_probe_failure_never_becomes_repair(guest, pair, arm, mutation, reason):
    manifest, reports = pair
    snapshot = reports[arm]["snapshots"][0]
    probe = snapshot["probe"]
    if mutation == "absent":
        del snapshot["probe"]
    elif mutation == "not-run":
        probe.update(status="not-run", device=None, reason="no-virtio-gpu-primary-node")
    elif mutation == "wrong-binary":
        probe["binary_sha256"] = "0" * 64
    elif mutation == "missing-case":
        probe["cases"].pop()
    elif mutation == "reordered":
        probe["cases"].reverse()
    elif mutation == "not-reproduced":
        probe["cases"][1].update(exit=0, status="initialized")
    elif mutation == "clean-unavailable":
        probe["cases"][0].update(exit=3, status="egldevice-unavailable")
    elif mutation == "crash":
        probe["cases"][1].update(exit=139, status="crashed")
    elif mutation == "timeout":
        probe["cases"][1].update(exit=124, status="timeout")
    elif mutation == "mislabelled-unavailable":
        probe["cases"][1].update(exit=3, status="initialized")
    result = guest.compare(manifest, reports)
    assert result["ok"] is False
    assert result["verdict"] == "repair-not-demonstrated"
    assert reason in result["arms"][arm]["failures"]


@pytest.mark.parametrize("field,value,reason", [
    ("software_policy_sha256", None, "software-policy-changed"),
    ("software_policy_sha256", "0" * 64, "software-policy-changed"),
    ("selinux", "Permissive", "selinux-not-enforcing"),
    ("selinux", "Disabled", "selinux-not-enforcing"),
    ("kernel_crash", True, "candidate-gnome-shell-crash"),
    ("crashes", [{"COREDUMP_EXE": "/usr/bin/gnome-shell", "COREDUMP_SIGNAL": "11"}], "candidate-gnome-shell-crash"),
    ("renderer_records", [], "missing-bound-software-greeter-renderer"),
])
def test_candidate_policy_security_and_crash_boundaries(guest, pair, field, value, reason):
    manifest, reports = pair
    reports["candidate"]["snapshots"][0][field] = value
    result = guest.compare(manifest, reports)
    assert result["ok"] is False
    assert reason in result["arms"]["candidate"]["failures"]


@pytest.mark.parametrize("section,key,reason", [
    ("transitions", "login", "missing-real-wayland-ui-transitions"),
    ("transitions", "lock", "missing-real-wayland-ui-transitions"),
    ("transitions", "unlock", "missing-real-wayland-ui-transitions"),
    ("transitions", "same_session", "missing-real-wayland-ui-transitions"),
    ("screenshots", "ready", "missing-visible-ui-evidence"),
    ("screenshots", "logged-in", "missing-visible-ui-evidence"),
    ("screenshots", "locked", "missing-visible-ui-evidence"),
    ("screenshots", "unlocked", "missing-visible-ui-evidence"),
])
def test_each_ui_transition_and_visible_state_is_required(guest, pair, section, key, reason):
    manifest, reports = pair
    del reports["candidate"][section][key]
    result = guest.compare(manifest, reports)
    assert result["ok"] is False
    assert reason in result["arms"]["candidate"]["failures"]


@pytest.mark.parametrize("role", ["greeter", "user"])
def test_wayland_is_required_for_both_actual_renderer_roles(guest, pair, role):
    manifest, reports = pair
    record = next(item for item in reports["candidate"]["snapshots"][0]["renderer_records"] if item["role"] == role)
    record["session"]["Type"] = "x11"
    result = guest.compare(manifest, reports)
    assert result["ok"] is False
    assert f"missing-bound-software-{role}-renderer" in result["arms"]["candidate"]["failures"]


def test_foreign_boot_renderer_cannot_bind_the_gate_login_session(guest, pair):
    manifest, reports = pair
    records = reports["candidate"]["snapshots"][0]["renderer_records"]
    records[1]["session"]["id"] = "other-session"
    records.append(renderer_record("user", "3" * 32, "c2"))
    result = guest.compare(manifest, reports)
    assert result["ok"] is False
    assert "renderer-not-bound-to-gate-user-session" in result["arms"]["candidate"]["failures"]


@pytest.mark.parametrize("mutation,reason", [
    ("gate-failed", "candidate-real-gdm-gate-failed"),
    ("no-observation", "no-live-guest-observation"),
    ("observer-gap", "live-observer-gap-after-first-observation"),
    ("wrong-probe-boot", "probe-boot-identity-mismatch"),
    ("probe-drift", "probe-record-changed"),
    ("boot-drift", "guest-boot-identity-changed"),
    ("wrong-installed-header", "installed-package-identity:"),
])
def test_comparator_requires_stable_observation_and_exact_installed_arm(guest, pair, mutation, reason):
    manifest, reports = pair
    report = reports["candidate"]
    if mutation == "gate-failed":
        report["gate_exit"] = 1
    elif mutation == "no-observation":
        report["snapshots"] = []
    elif mutation == "observer-gap":
        report["observer_errors"].append(reason)
    elif mutation == "wrong-probe-boot":
        report["snapshots"][0]["probe"]["boot_id"] = CONTROL_BOOT
    elif mutation in ("probe-drift", "boot-drift"):
        snapshot = copy.deepcopy(report["snapshots"][0])
        report["snapshots"].append(snapshot)
        if mutation == "probe-drift":
            snapshot["probe"]["device"] = "/dev/dri/card1"
        else:
            snapshot["boot_id"] = "3" * 32
    elif mutation == "wrong-installed-header":
        report["snapshots"][0]["inventory"][0]["header_sha256"] = "e" * 64
    result = guest.compare(manifest, reports)
    assert result["ok"] is False
    assert any(item.startswith(reason) for item in result["arms"]["candidate"]["failures"])


def test_same_vm_boot_cannot_supply_both_comparison_arms(guest, pair):
    manifest, reports = pair
    candidate = reports["candidate"]["snapshots"][0]
    candidate["boot_id"] = CONTROL_BOOT
    candidate["probe"]["boot_id"] = CONTROL_BOOT
    candidate["renderer_records"] = [renderer_record("greeter", CONTROL_BOOT, "g1"), renderer_record("user", CONTROL_BOOT, "c2")]
    result = guest.compare(manifest, reports)
    assert result["arms"]["candidate"]["ok"] is True
    assert result["distinct_arm_boots"] is False
    assert result["ok"] is False


@pytest.mark.parametrize("sessions,order,valid", [
    (("c2", "c2", "c2"), ("LOGIN", "LOCK", "UNLOCK"), True),
    (("c2", "c3", "c2"), ("LOGIN", "LOCK", "UNLOCK"), False),
    (("c2", "c2", "c2"), ("LOCK", "LOGIN", "UNLOCK"), False),
    (("c2", "c2", "c2"), ("LOGIN", "LOCK"), False),
])
def test_transition_parser_requires_ordered_same_session_markers(guest, sessions, order, valid):
    ids = dict(zip(("LOGIN", "LOCK", "UNLOCK"), sessions))
    log = "\n".join(f"TUNAOS_GDM_{kind}_OK user=tuna-ci-login session={ids[kind]}" for kind in order)
    assert guest.transition_evidence(log)["same_session"] is valid


def test_transition_parser_does_not_accept_another_users_markers(guest):
    log = "\n".join(f"TUNAOS_GDM_{kind}_OK user=someone-else session=c2" for kind in ("LOGIN", "LOCK", "UNLOCK"))
    assert guest.transition_evidence(log) == {"login": False, "lock": False, "unlock": False, "same_session": False, "session": None}


@pytest.mark.parametrize("arm", ["control", "candidate"])
def test_policy_proof_is_mandatory_in_each_arm(guest, pair, arm):
    manifest, reports = pair
    del reports[arm]["snapshots"][0]["software_policy_sha256"]
    result = guest.compare(manifest, reports)
    assert result["ok"] is False
    assert "software-policy-changed" in result["arms"][arm]["failures"]


def test_environment_only_renderer_claim_cannot_make_candidate_pass(guest, pair):
    manifest, reports = pair
    for record in reports["candidate"]["snapshots"][0]["renderer_records"]:
        record["software_verified"] = True
        record["journal"]["MESSAGE"] = "LIBGL_ALWAYS_SOFTWARE=1 COGL_DEBUG=winsys"
    result = guest.compare(manifest, reports)
    assert result["ok"] is False
    assert {
        "missing-bound-software-greeter-renderer",
        "missing-bound-software-user-renderer",
    } <= set(result["arms"]["candidate"]["failures"])
