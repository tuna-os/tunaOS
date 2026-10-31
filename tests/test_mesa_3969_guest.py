"""Source-only evidence and lifecycle regressions; never a native experiment.

Renderer fixtures validate hypothetical source-backed data formats, NOT native
producer compatibility. Released Smithay's lazy info! query has no demonstrated
enabled logger/sink; no fixture claims the shipped Tuna can currently emit it.
Lifecycle cases use test-owned process groups, temporary evidence and a stateful
storage adapter. They do not boot a VM, run Podman or prove native compatibility.
"""

import copy
import errno
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest


MANUAL = Path(__file__).resolve().parent / "manual"
CONTROL_BOOT = "1" * 32
CANDIDATE_BOOT = "2" * 32
RENDERER = "llvmpipe (LLVM 19.1.7, 256 bits)"
MESSAGE = "[WINSYS] Checking features\n  GL_VENDOR: Mesa\n  GL_RENDERER: " + RENDERER + "\n  GL_VERSION: 4.5"
TUNA_MESSAGE = "GL Renderer: " + json.dumps(RENDERER)
EGL = "/usr/lib64/libEGL_mesa.so.0.0.0"
GALLIUM = "/usr/lib64/libgallium-25.2.7.so"
# Digests of run 41051314549's transferred mesa-libEGL payloads and the Alma
# vault build: three different libEGL_mesa byte strings for one NEVRA.
EGL_BYTES = {
    "control": "09d52c835e2e99cf34ec0e64034c9367f3d6a4dbd7ebfcfa5022e9a43d95b0a5",
    "candidate": "b5fbea34f40e4ab649df9da06f072b52181b40d4626d83cd3d7ffadd476a394e",
    "vault": "3c1d37e482d7ef83c09bf3eb922e02f8d333f88662320d0cf32d24a45bde2c1c",
}
GALLIUM_BYTES = "9a" * 32  # The patch touches src/egl only: shared by both arms.


def payload_tables():
    return {arm: {
        EGL: {"sha256": EGL_BYTES[arm], "size": 317672, "package": "mesa-libEGL"},
        GALLIUM: {"sha256": GALLIUM_BYTES, "size": 4096, "package": "mesa-dri-drivers"},
        "/usr/share/glvnd/egl_vendor.d/50_mesa.json": {"sha256": "cd" * 32, "size": 105, "package": "mesa-libEGL"},
    } for arm in ("control", "candidate")}


def mapped(path, digest, inode=4242):
    return {"path": path, "device": "fd:01", "inode": inode, "deleted": False,
            "source": "map_files", "inode_matches": True, "sha256": digest, "size": 4096}


def loaded(arm):
    return [mapped(EGL, EGL_BYTES[arm]), mapped(GALLIUM, GALLIUM_BYTES, inode=4343)]


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
    compositor = "gnome-shell" if role == "greeter" else "tuna-compositor"
    process = {
        "uid": uid, "start_ticks": 1200, "comm": compositor,
        "exe": "/usr/bin/" + compositor, "cgroups": [f"0::/user.slice/user-{uid}.slice/{scope}"],
    }
    environment = {"LIBGL_ALWAYS_SOFTWARE": "1", "COGL_DEBUG": "winsys", "XDG_SESSION_TYPE": "wayland"}
    if role == "greeter":
        environment.update(GNOME_SHELL_SESSION_MODE="gdm", WAYLAND_DISPLAY="wayland-0")
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
        "drm_cards": ["/dev/dri/card0"], "drm_cards_after": ["/dev/dri/card0"],
        "journal": {
            "_BOOT_ID": boot, "_PID": str(pid), "_UID": str(uid),
            "_EXE": "/usr/bin/" + compositor, "__MONOTONIC_TIMESTAMP": "13000000",
            "MESSAGE": MESSAGE if role == "greeter" else TUNA_MESSAGE},
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
                      "stdout": "eglInitialize=success version=1.5" if code == 0 else "", "stderr": "",
                      "trace": "ptrace", "mapped_mesa": loaded(arm)}
                     for index, (case, code) in enumerate(zip(("clean", "software", "override", "combined"), exits))
                 ]}
        reports[arm] = {
            "arm": arm, "baseline_inventory": copy.deepcopy(baseline), "gate_exit": 1 if arm == "control" else 0,
            "observer_errors": [], "transitions": {"login": True, "lock": True, "unlock": True,
                                                    "same_session": True, "session": "c2"},
            "screenshots": {"ready": True, "logged-in": True, "locked": True, "unlocked": True},
            "rpm_payload": payload_tables(),
            "snapshots": [{"boot_id": boot, "inventory": [installed, dict(unrelated)], "file_verification": [],
                           "software_policy_sha256": "d" * 64, "selinux": "Enforcing", "probe": probe,
                           "crashes": [], "kernel_crash": False, "renderer_records": [
                               renderer_record("greeter", boot, "g1"), renderer_record("user", boot, "c2")
                           ], "mapped_libraries": [{
                               "pid": 471, "role": "greeter", "libraries": loaded(arm),
                               "process": {"uid": 42, "start_ticks": 1200, "comm": "gnome-shell",
                                           "exe": "/usr/bin/gnome-shell", "cgroups": []}}]}],
        }
    return manifest, reports


@pytest.mark.parametrize("role", ["greeter", "user"])
def test_bound_source_backed_software_renderer_is_accepted(guest, role):
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
    reports["candidate"]["snapshots"][0]["renderer_records"] = [
        item for item in reports["candidate"]["snapshots"][0]["renderer_records"] if item["role"] == "greeter"
    ]
    result = guest.compare(manifest, reports)
    # tuna-desktop is pre-alpha: a missing user-session renderer is advisory only.
    assert result["ok"] is True
    assert result["arms"]["candidate"]["advisories"] == ["tuna-user-renderer-unobserved"]


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
    ("kernel_crash", True, "candidate-compositor-crash"),
    ("crashes", [{"COREDUMP_EXE": "/usr/bin/gnome-shell", "COREDUMP_SIGNAL": "11"}], "candidate-compositor-crash"),
    ("crashes", [{"COREDUMP_EXE": "/usr/bin/tuna-compositor", "COREDUMP_SIGNAL": "11"}], "candidate-compositor-crash"),
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


def test_wayland_is_required_for_the_greeter_renderer_and_advisory_for_tuna_user(guest, pair):
    manifest, reports = pair
    records = reports["candidate"]["snapshots"][0]["renderer_records"]
    greeter = next(item for item in records if item["role"] == "greeter")
    greeter["session"]["Type"] = "x11"
    result = guest.compare(manifest, reports)
    assert result["ok"] is False
    assert "missing-bound-software-greeter-renderer" in result["arms"]["candidate"]["failures"]
    greeter["session"]["Type"] = "wayland"
    next(item for item in records if item["role"] == "user")["session"]["Type"] = "x11"
    result = guest.compare(manifest, reports)
    assert result["ok"] is True
    assert result["arms"]["candidate"]["advisories"] == ["tuna-user-renderer-unobserved"]


def test_foreign_boot_user_renderer_is_advisory_and_cannot_pass_as_observed(guest, pair):
    manifest, reports = pair
    records = reports["candidate"]["snapshots"][0]["renderer_records"]
    records[1]["session"]["id"] = "other-session"
    records.append(renderer_record("user", "3" * 32, "c2"))
    result = guest.compare(manifest, reports)
    assert result["ok"] is True
    assert result["arms"]["candidate"]["advisories"] == ["tuna-user-renderer-unobserved"]


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
    assert result["arms"]["candidate"]["failures"] == ["missing-bound-software-greeter-renderer"]
    assert result["arms"]["candidate"]["advisories"] == ["tuna-user-renderer-unobserved"]


def test_gnome_user_renderer_cannot_stand_in_for_gate_selected_tuna(guest):
    # The pinned login gate selects Session=tuna; a GNOME user session is
    # therefore wrong even when its actual Cogl software report is well bound.
    record = renderer_record("user")
    record["process"].update(exe="/usr/bin/gnome-shell", comm="gnome-shell")
    record["identity_after"] = copy.deepcopy(record["process"])
    record["journal"] = renderer_record("greeter")["journal"]
    record["journal"].update(_PID=str(record["pid"]), _UID="1000")
    assert guest.validate_renderer(record, CANDIDATE_BOOT) is False


def test_host_evidence_survives_raw_work_directory_removal(guest, tmp_path):
    raw = tmp_path / "work" / "control"
    selected = tmp_path / "selected" / "control"
    raw.mkdir(parents=True)
    selected.mkdir(parents=True)
    # Opaque test bytes: retention is the behavior, not a claimed host run.
    contents = b"opaque helper-produced host report\nqemu command line:\n"
    (raw / "vm-host-evidence.txt").write_bytes(contents)
    (raw / "gate.log").write_text("gate ended\n")
    report = {"snapshots": [], "gate_exit": 143}
    guest.finish_arm_evidence(report, raw, selected, observer_count=0)
    guest.shutil.rmtree(raw)
    assert (selected / "vm-host-evidence.txt").read_bytes() == contents


def test_oversized_host_evidence_is_not_silently_dropped(guest, tmp_path):
    raw, selected = tmp_path / "raw", tmp_path / "selected"
    raw.mkdir()
    selected.mkdir()
    with (raw / "vm-host-evidence.txt").open("wb") as stream:
        stream.truncate(8 * 1024 * 1024 + 1)
    with pytest.raises(guest.LabError, match="evidence.*bound"):
        guest.finish_arm_evidence({"snapshots": []}, raw, selected, observer_count=0)
    assert not (selected / "vm-host-evidence.txt").exists()


def test_undecodable_console_bytes_do_not_make_the_bundle_unpublishable(guest, tmp_path):
    core = sys.modules["mesa_3969"]
    raw, selected = tmp_path / "raw", tmp_path / "selected" / "candidate"
    raw.mkdir()
    selected.mkdir(parents=True)
    # Actual QEMU consoles emit non-UTF-8 bytes; core publication decodes
    # every selected log strictly, so retention must not strand the bundle.
    (raw / "serial.log").write_bytes(b"boot log \xff\xfe tail\n")
    (raw / "gate.log").write_text("gate ended\n")
    guest.finish_arm_evidence({"snapshots": [], "gate_exit": 1}, raw, selected, observer_count=0)
    receipt = core.pack_evidence(tmp_path / "selected", tmp_path / "public")
    assert receipt["files"] == ["candidate/gate.log", "candidate/report.json", "candidate/serial.log"]
    assert (tmp_path / "public/candidate/serial.log").read_text(encoding="utf-8").startswith("boot log ")


# Every descendant self-expires as well as being killed in the test's finally.
# Its parent exits before the child emits bytes, reproducing the lost-leader
# case without a timing assumption about subprocess startup.
ORPHAN_WRITER = """
import os
from pathlib import Path
import signal
import sys
import time

parent = os.getpid()
child = os.fork()
if child:
    os._exit(0)
signal.signal(signal.SIGTERM, signal.SIG_IGN)
Path(sys.argv[1]).write_text(str(os.getpid()))
deadline = time.monotonic() + 20
while os.getppid() == parent and time.monotonic() < deadline:
    time.sleep(0.01)
if sys.argv[2] == "overflow":
    os.write(1, b"x" * 4096)
if sys.argv[2] == "normal":
    os.close(1)
    os.close(2)
while time.monotonic() < deadline:
    time.sleep(0.05)
"""


def live_group_members(pgid):
    members = []
    for path in Path("/proc").glob("[0-9]*/stat"):
        try:
            fields = path.read_text().rsplit(") ", 1)[1].split()
            if int(fields[2]) == pgid and fields[0] not in ("Z", "X"):
                members.append(int(path.parent.name))
        except (FileNotFoundError, ProcessLookupError):
            continue
    return members


@pytest.mark.parametrize("failure", ["normal", "timeout", "overflow", "cancel"])
def test_exited_leader_cannot_leave_sigterm_ignoring_pipe_owner(
    guest, monkeypatch, tmp_path, failure
):
    child_file = tmp_path / "child.pid"
    owned = []
    popen = subprocess.Popen

    def capture_owned_process(*args, **kwargs):
        process = popen(*args, **kwargs)
        owned.append(process)
        return process

    # Observe actual Popen objects, not command results or fake children.
    monkeypatch.setattr(guest.subprocess, "Popen", capture_owned_process)
    handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        argv = [sys.executable, "-c", ORPHAN_WRITER, str(child_file), failure]
        if failure == "cancel":
            process = subprocess.Popen(argv, start_new_session=True)
            guest.CHILDREN.add(process)
            process.wait(timeout=5)
            deadline = time.monotonic() + 5
            while not child_file.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert child_file.exists(), "test child did not reach signal-ready state"
            with pytest.raises(SystemExit) as stopped:
                guest.cancel(signal.SIGTERM, None)
            assert stopped.value.code == 143
        elif failure == "normal":
            assert guest.bounded_command(argv, timeout=2, limit=128) == (0, "", "")
        else:
            with pytest.raises(guest.LabError, match="timeout" if failure == "timeout" else "output exceeds"):
                guest.bounded_command(argv, timeout=2, limit=128)
        assert len(owned) == 1
        assert child_file.exists(), "test never reached the descendant-held pipe"
        deadline = time.monotonic() + 1
        while live_group_members(owned[0].pid) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert live_group_members(owned[0].pid) == []
    finally:
        # Never trust the cleanup function under test to clean its own fixture.
        for process in owned:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
            guest.CHILDREN.discard(process)
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


@pytest.fixture
def runtime_storage(guest, monkeypatch, tmp_path):
    """Temporary storage adapter, not a Podman/Corral/native compatibility test."""
    run_id, head = "123456", "a" * 40
    monkeypatch.setenv("GITHUB_RUN_ID", run_id)
    monkeypatch.setenv("GITHUB_SHA", head)
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("MESA_3969_ARTIFACT_ID", "999")
    monkeypatch.setenv("MESA_3969_ARTIFACT_DIGEST", "sha256:" + "f" * 64)
    root = tmp_path / f"mesa-3969-{run_id}-runtime"
    # This storage-only adapter has no real sockets. Dedicated runtime-layout
    # regressions bind the production paths against the kernel.
    monkeypatch.setattr(guest, "check_runtime_path_budget", lambda *_args: None)
    inputs = root / "work" / "inputs"
    inputs.mkdir(parents=True)
    baseline_tag = f"localhost/mesa3969-{run_id}:baseline"
    manifest = {"baseline": {"image_tag": baseline_tag, "image_id": "sha256:" + "b" * 64}}
    (inputs / "manifest.json").write_text(json.dumps(manifest))
    (inputs / "baseline-inventory.json").write_text("[]")
    storage = {}
    removals = []
    containers = {}
    baseline_labels = {"io.tunaos.mesa3969": f"{run_id}-{head}"}
    payload_files = {arm: {EGL: f"committed {arm} bytes".encode(), GALLIUM: b"gallium"}
                     for arm in ("control", "candidate")}
    payload = {arm: {path: {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "package": "mesa-libEGL"}
                     for path, data in files.items()} for arm, files in payload_files.items()}
    state = {"root": root, "storage": storage, "removals": removals, "containers": containers,
             "baseline_tag": baseline_tag, "baseline_labels": baseline_labels,
             "run_id": run_id, "fail_verification": False, "commands": [], "fail_removals": set(),
             "trees": {}, "mounted": [], "mountpoints": {}, "payload_files": payload_files,
             "payload": payload, "commit_mutation": None}

    def image(name):
        if name in storage:
            return name, storage[name]
        for tag, metadata in storage.items():
            if name.removeprefix("sha256:") == metadata["Id"].removeprefix("sha256:"):
                return tag, metadata
        raise guest.LabError(f"test storage image absent: {name}")

    def container(name):
        if name in containers:
            return name, containers[name]
        for tag, metadata in containers.items():
            if name.removeprefix("sha256:") == metadata["Id"]:
                return tag, metadata
        raise guest.LabError(f"test storage container absent: {name}")

    def command(argv, **kwargs):
        argv = [str(value) for value in argv]
        if argv[0] == sys.executable:
            if argv[2] == "fetch-inputs":
                state["fetch_started"] = True
                return 0, json.dumps({"directory": str(inputs)}), ""
            if argv[2] == "validate-root":
                return 0, str(root), ""
            assert argv[2] in ("admit", "pack-evidence"), argv
            return 0, "", ""
        assert argv[:3] == ["sudo", "-n", "podman"], argv
        args = argv[3:]
        state["commands"].append(args)
        if len(args) >= 2 and args[1] == "exists":
            try:
                (image if args[0] == "image" else container)(args[-1])
            except guest.LabError:
                return 1, "", ""
            return 0, "", ""
        if args[0] == "load":
            storage[baseline_tag] = {
                "Id": "b" * 64, "Parent": "",
                "RootFS": {"Type": "layers", "Layers": ["sha256:" + "1" * 64]},
                "Config": {"Labels": dict(baseline_labels)},
            }
        elif args[:2] in (["image", "inspect"], ["container", "inspect"]):
            try:
                _, metadata = (image if args[0] == "image" else container)(args[-1])
            except guest.LabError:
                if kwargs.get("check") is False:
                    return 125, "", "no such object"
                raise
            field = args[args.index("--format") + 1].replace(" ", "")
            values = {"{{.Id}}": metadata["Id"], "{{.ID}}": metadata["Id"],
                      "{{json.}}": json.dumps(metadata),
                      "{{json.Config}}": json.dumps(metadata["Config"]),
                      "{{json.Config.Labels}}": json.dumps(metadata["Config"]["Labels"])}
            return 0, values[field], ""
        elif args[:2] == ["image", "rm"]:
            tag, metadata = image(args[-1])
            if tag in state["fail_removals"]:
                raise guest.LabError(f"injected image removal failure: {tag}")
            layers = metadata.get("RootFS", {}).get("Layers", [])
            dependents = [
                name for name, entry in storage.items()
                if len(entry.get("RootFS", {}).get("Layers", [])) > len(layers)
                and entry["RootFS"]["Layers"][:len(layers)] == layers
            ]
            if dependents:
                raise guest.LabError(f"test storage parent still referenced: {dependents}")
            removals.append(tag)
            del storage[tag]
        elif args[0] == "run":
            if state["fail_verification"]:
                raise guest.LabError("injected offline transfer failure")
            assert args[-3:-2] == ["payload-digests"], args
            return 0, json.dumps(state["payload"]), ""
        elif args[0] == "info":
            return 0, json.dumps({"GraphDriverName": "test-adapter", "GraphOptions": {}}), ""
        elif args[0] == "mount" or args[:2] == ["image", "mount"]:
            if args[0] == "mount":
                tag, _ = container(args[-1])
                arm = "control" if tag.endswith("-control-install") else "candidate"
                mountpoint = tmp_path / "mounts" / tag
                if tag not in state["mountpoints"]:
                    mountpoint.mkdir(parents=True)
                    image_tag = f"localhost/mesa3969-{run_id}:{arm}"
                    write_tree(mountpoint, state["payload_files"][arm] | state["trees"].get(image_tag, {}))
                    state["mountpoints"][tag] = mountpoint
            else:
                tag, _ = image(args[-1])
                mountpoint = state["mountpoints"][tag]
            state["mounted"].append(tag)
            return 0, str(mountpoint) + "\n", ""
        elif args[0] == "unmount" or args[:2] == ["image", "unmount"]:
            tag, _ = (container if args[0] == "unmount" else image)(args[-1])
            state["mounted"].remove(tag)
        elif args[0] == "create":
            containers[args[args.index("--name") + 1]] = {
                "Id": "e" * 64, "Image": "b" * 64,
                "Config": {"Labels": dict(baseline_labels, **{"io.tunaos.mesa3969.runtime": run_id})},
            }
        elif args[0] == "start":
            assert args[-1] in containers
        elif args[0] == "inspect":
            assert args[-1] in containers
            return 0, "0", ""
        elif args[0] == "commit":
            assert args[-2] in containers and "--squash" in args
            storage[args[-1]] = {
                "Id": "c" * 64, "Parent": "",
                "RootFS": {"Type": "layers", "Layers": ["sha256:" + "2" * 64]},
                "Config": {"Labels": dict(baseline_labels, **{"io.tunaos.mesa3969.runtime": run_id})},
            }
            destination = tmp_path / "mounts" / args[-1].replace("/", "_")
            shutil.copytree(state["mountpoints"][args[-2]], destination, symlinks=True)
            state["mountpoints"][args[-1]] = destination
            if state["commit_mutation"]:
                state["commit_mutation"](destination)
        elif args[0] == "rm":
            del containers[args[-1]]
        elif args[:2] == ["container", "rm"]:
            # Podman container commands take a name or raw hex ID, never
            # image-digest notation (sha256:...).
            if args[-1].startswith("sha256:"):
                raise guest.LabError("podman: no container with name or ID " + args[-1])
            tag, _ = container(args[-1])
            del containers[tag]
        else:
            raise AssertionError(f"unexpected storage operation: {args}")
        return 0, "", ""

    monkeypatch.setattr(guest, "bounded_command", command)
    monkeypatch.setattr(guest, "stage_helpers", lambda _repo, target: target / "gate.sh")
    monkeypatch.setattr(guest.shutil, "which", lambda _name: "/test-only/corral")
    return state


def test_runtime_socket_budget_precedes_fetch_or_storage_effects(guest, monkeypatch, runtime_storage):
    state = runtime_storage
    core = sys.modules["mesa_3969"]
    monkeypatch.setattr(core, "UNIX_SOCKET_PATH_BYTES", 1)
    monkeypatch.setattr(guest, "check_runtime_path_budget", core.check_runtime_path_budget)
    with pytest.raises(guest.LabError, match="UNIX socket path exceeds"):
        guest.run_runtime(state["root"])
    assert not state.get("fetch_started", False)
    assert state["commands"] == []


@pytest.mark.parametrize("owned", [True, False])
def test_failed_transfer_removes_only_owned_normalized_baseline(
    guest, runtime_storage, owned
):
    state = runtime_storage
    state["fail_verification"] = True
    if not owned:
        state["baseline_labels"]["io.tunaos.mesa3969"] = "another-run-and-head"
    with pytest.raises(guest.LabError):
        guest.run_runtime(state["root"])
    assert (state["baseline_tag"] in state["storage"]) is not owned
    assert state["removals"] == ([state["baseline_tag"]] if owned else [])


@pytest.mark.parametrize("cancelled", [False, True])
def test_derived_user_image_is_removed_before_installed_parent_on_unwind(
    guest, monkeypatch, runtime_storage, cancelled
):
    state = runtime_storage
    arm_tag = f'localhost/mesa3969-{state["run_id"]}:control'
    derived_tag = f'localhost/corral-vmtest/mesa-{state["run_id"]}-a:latest'
    failure = SystemExit(143) if cancelled else guest.LabError("injected arm failure")

    def interrupted_arm(_arm, image_id, *_args):
        parent = state["storage"][arm_tag]
        assert image_id == "sha256:" + parent["Id"]
        state["storage"][derived_tag] = {
            "Id": "d" * 64, "Parent": "",
            "RootFS": {"Type": "layers", "Layers": parent["RootFS"]["Layers"] + ["sha256:" + "3" * 64]},
            "Config": {"Labels": dict(parent["Config"]["Labels"])},
        }
        raise failure

    monkeypatch.setattr(guest, "run_arm", interrupted_arm)
    with pytest.raises(type(failure)) as raised:
        guest.run_runtime(state["root"])
    if cancelled:
        assert raised.value.code == 143
    assert derived_tag not in state["storage"]
    assert arm_tag not in state["storage"]
    assert state["removals"][:2] == [derived_tag, arm_tag]


@pytest.mark.parametrize("message,expected", [
    (TUNA_MESSAGE, RENDERER),
    ("INFO smithay::backend::renderer::gles: " + TUNA_MESSAGE, RENDERER),
    (MESSAGE, None),
    ("GL_RENDERER: " + RENDERER, None),
    ("LIBGL_ALWAYS_SOFTWARE=1", None),
    ("<ret><string>" + RENDERER + "</string></ret>", None),
    ('GL Renderer: "' + RENDERER + '"\nforeign extra message', None),
])
def test_conditional_smithay_format_is_not_cogl_or_driver_inference(guest, message, expected):
    # A genuine source-format consumer, not a claim that beta1 has a sink.
    assert guest.tuna_renderer_value(message) == expected


@pytest.mark.parametrize("mutation", ["hardware", "changed-card", "second-card", "nested", "trace-request"])
def test_tuna_renderer_requires_actual_software_native_context(guest, mutation):
    record = renderer_record()
    if mutation == "hardware":
        record["journal"]["MESSAGE"] = 'GL Renderer: "virgl (Mesa Intel)"'
        record["renderer"] = "virgl (Mesa Intel)"
    elif mutation == "changed-card":
        record["drm_cards_after"] = ["/dev/dri/card1"]
    elif mutation == "second-card":
        record["drm_cards"] = record["drm_cards_after"] = ["/dev/dri/card0", "/dev/dri/card1"]
    else:
        key, value = ("DISPLAY", ":1") if mutation == "nested" else ("GALLIUM_TRACE", "stderr")
        record["environment"][key] = value
        record["environment_after"] = dict(record["environment"])
    assert guest.validate_renderer(record, CANDIDATE_BOOT) is False


@pytest.fixture
def ssh_endpoint(guest, monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_RUN_ID", "123456")
    name = "mesa-123456-a"
    home, raw = tmp_path / "home", tmp_path / "gate"
    vm = home / ".local/share/corral/vms" / name
    vm.mkdir(parents=True)
    metadata = vm / "metadata.json"
    metadata.write_text(json.dumps({
        "name": name, "ssh_port": 2242, "tailscale_ip": "127.0.0.1",
        "serial_log": str(vm / "serial.log"),
    }))
    identity = raw / "corral/ssh/id_ed25519"
    identity.parent.mkdir(parents=True)
    identity.write_text("opaque fixture identity; not a generated key")
    identity.chmod(0o600)
    return home, raw, name, metadata, identity


def test_observer_uses_only_owned_direct_loopback_identity(guest, ssh_endpoint):
    home, raw, name, _, identity = ssh_endpoint
    argv = guest.owned_ssh_argv(home, raw, name)
    assert argv[0:3] == ["ssh", "-F", "/dev/null"]
    assert argv[argv.index("-i") + 1] == str(identity)
    assert argv[argv.index("-p") + 1] == "2242"
    assert argv[-1] == "root@127.0.0.1"
    assert "IdentitiesOnly=yes" in argv
    assert "IdentityAgent=none" in argv
    assert "BatchMode=yes" in argv
    assert "GlobalKnownHostsFile=/dev/null" in argv


@pytest.mark.parametrize("field,value", [
    ("name", "foreign"), ("tailscale_ip", "203.0.113.1"), ("ssh_port", True),
    ("ssh_port", 22), ("ssh_port", "2242"), ("serial_log", "/tmp/foreign"),
])
def test_observer_rejects_foreign_or_malformed_endpoint(guest, ssh_endpoint, field, value):
    home, raw, name, path, _ = ssh_endpoint
    metadata = json.loads(path.read_text())
    metadata[field] = value
    path.write_text(json.dumps(metadata))
    with pytest.raises(guest.LabError, match="endpoint differs"):
        guest.owned_ssh_argv(home, raw, name)


@pytest.mark.parametrize("unsafe", ["symlink-key", "symlink-metadata", "public-key", "oversized-metadata"])
def test_observer_rejects_unowned_identity_paths(guest, ssh_endpoint, unsafe, tmp_path):
    home, raw, name, metadata, identity = ssh_endpoint
    if unsafe.startswith("symlink"):
        target = identity if unsafe == "symlink-key" else metadata
        foreign = tmp_path / "foreign"
        foreign.write_bytes(target.read_bytes())
        foreign.chmod(0o600)
        target.unlink()
        target.symlink_to(foreign)
    elif unsafe == "public-key":
        identity.chmod(0o644)
    else:
        metadata.write_bytes(b"x" * 65537)
    with pytest.raises(guest.LabError):
        guest.owned_ssh_argv(home, raw, name)


def test_storage_adapter_models_missing_container_inspect(guest, runtime_storage):
    code, output, error = guest.bounded_command([
        "sudo", "-n", "podman", "container", "inspect", "--format", "{{json .}}", "absent",
    ], check=False)
    assert (code, output, error) == (125, "", "no such object")
    assert guest.stored_metadata(["sudo", "-n", "podman"], "container", "absent") is None


@pytest.mark.parametrize("which", ["baseline", "derived"])
def test_preexisting_storage_names_are_never_claimed(guest, runtime_storage, which):
    state = runtime_storage
    tag = state["baseline_tag"] if which == "baseline" else f'localhost/corral-vmtest/mesa-{state["run_id"]}-a:latest'
    state["storage"][tag] = {
        "Id": "9" * 64, "Config": {"Labels": {"io.tunaos.mesa3969.runtime": "foreign"}},
        "RootFS": {"Layers": ["sha256:" + "9" * 64]},
    }
    with pytest.raises(guest.LabError, match="preexisting"):
        guest.run_runtime(state["root"])
    assert tag in state["storage"]
    assert tag not in state["removals"]
    if which == "baseline":
        assert not any(args[0] == "load" for args in state["commands"])


@pytest.mark.parametrize("unsafe", ["foreign-run", "foreign-head", "malformed-id", "wrong-rootfs", "missing-rootfs", "matching-parent-without-ancestry"])
def test_unsafe_derived_images_are_retained_not_pruned(guest, monkeypatch, runtime_storage, unsafe):
    state = runtime_storage
    arm_tag = f'localhost/mesa3969-{state["run_id"]}:control'
    derived_tag = f'localhost/corral-vmtest/mesa-{state["run_id"]}-a:latest'

    def interrupted_arm(*_args):
        parent = state["storage"][arm_tag]
        metadata = {
            "Id": "d" * 64, "Parent": "",
            "RootFS": {"Layers": parent["RootFS"]["Layers"] + ["sha256:" + "3" * 64]},
            "Config": {"Labels": dict(parent["Config"]["Labels"])},
        }
        if unsafe == "foreign-run":
            metadata["Config"]["Labels"]["io.tunaos.mesa3969.runtime"] = "foreign"
        elif unsafe == "foreign-head":
            metadata["Config"]["Labels"]["io.tunaos.mesa3969"] = "another-head"
        elif unsafe == "malformed-id":
            metadata["Id"] = "not-an-image-id"
        elif unsafe == "wrong-rootfs":
            metadata["RootFS"]["Layers"][0] = "sha256:" + "9" * 64
        elif unsafe == "missing-rootfs":
            del metadata["RootFS"]
        else:
            metadata["Parent"] = parent["Id"]
            metadata["RootFS"]["Layers"][0] = "sha256:" + "9" * 64
        state["storage"][derived_tag] = metadata
        raise guest.LabError("injected incomplete arm")

    monkeypatch.setattr(guest, "run_arm", interrupted_arm)
    with pytest.raises(guest.LabError, match="incomplete arm"):
        guest.run_runtime(state["root"])
    assert derived_tag in state["storage"]
    assert derived_tag not in state["removals"]
    comparison = json.loads((state["root"] / "work/selected/comparison.json").read_text())
    assert comparison["ok"] is False
    assert comparison["cleanup_errors"]
    assert not any("prune" in args for args in state["commands"])


def test_cleanup_failure_attempts_remaining_resources_and_preserves_cancel(guest, monkeypatch, runtime_storage):
    state = runtime_storage
    arm_tag = f'localhost/mesa3969-{state["run_id"]}:control'
    derived_tag = f'localhost/corral-vmtest/mesa-{state["run_id"]}-a:latest'
    state["fail_removals"].add(derived_tag)

    def interrupted_arm(*_args):
        parent = state["storage"][arm_tag]
        state["storage"][derived_tag] = {
            "Id": "d" * 64, "Parent": "",
            "RootFS": {"Layers": parent["RootFS"]["Layers"] + ["sha256:" + "3" * 64]},
            "Config": {"Labels": dict(parent["Config"]["Labels"])},
        }
        raise SystemExit(143)

    monkeypatch.setattr(guest, "run_arm", interrupted_arm)
    with pytest.raises(SystemExit) as cancelled:
        guest.run_runtime(state["root"])
    assert cancelled.value.code == 143
    attempted = [args[-1] for args in state["commands"] if args[:2] == ["image", "rm"]]
    assert attempted == ["sha256:" + value * 64 for value in ("d", "c", "b")]
    comparison = json.loads((state["root"] / "work/selected/comparison.json").read_text())
    assert comparison["ok"] is False


def test_native_intermediate_parent_field_is_not_base_provenance(guest, runtime_storage):
    state = runtime_storage
    labels = dict(state["baseline_labels"], **{"io.tunaos.mesa3969.runtime": state["run_id"]})
    parent = {"Id": "c" * 64, "RootFS": {"Layers": ["sha256:" + "1" * 64]}}
    child = {"Id": "d" * 64, "Parent": "sha256:" + "9" * 64,
             "RootFS": {"Layers": parent["RootFS"]["Layers"] + ["sha256:" + "2" * 64]},
             "Config": {"Labels": labels}}
    assert guest.runtime_image(child, parent) == "sha256:" + "d" * 64


def test_cancel_aggregates_process_cleanup_without_skipping_owned_groups(guest, monkeypatch):
    processes = [object(), object()]
    stopped = []
    handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    guest.CHILDREN.update(processes)

    def stop(process):
        stopped.append(process)
        raise guest.LabError("injected group cleanup failure")

    monkeypatch.setattr(guest, "stop_process", stop)
    try:
        with pytest.raises(SystemExit) as cancelled:
            guest.cancel(signal.SIGTERM, None)
        assert cancelled.value.code == 143
        assert set(stopped) == set(processes)
        assert len(guest.PROCESS_CLEANUP_ERRORS) == 2
        assert not guest.CHILDREN
    finally:
        guest.CHILDREN.clear()
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


def test_partial_install_container_is_inspected_and_removed_on_unwind(guest, monkeypatch, runtime_storage):
    state = runtime_storage
    command = guest.bounded_command

    def fail_start(argv, **kwargs):
        if [str(value) for value in argv][3:5] == ["start", "--attach"]:
            raise guest.LabError("injected container start failure")
        return command(argv, **kwargs)

    monkeypatch.setattr(guest, "bounded_command", fail_start)
    with pytest.raises(guest.LabError, match="container start failure"):
        guest.run_runtime(state["root"])
    assert state["containers"] == {}
    assert any(args[:2] == ["container", "inspect"] for args in state["commands"])
    assert any(args[:2] == ["container", "rm"] for args in state["commands"])
    assert state["storage"] == {}


@pytest.mark.parametrize("mismatch", ["name", "base", "image", "derived"])
def test_corral_result_cannot_claim_foreign_derived_provenance(guest, monkeypatch, runtime_storage, mismatch):
    state = runtime_storage
    arm_tag = f'localhost/mesa3969-{state["run_id"]}:control'
    derived_tag = f'localhost/corral-vmtest/mesa-{state["run_id"]}-a:latest'

    def interrupted_arm(*args):
        parent = state["storage"][arm_tag]
        state["storage"][derived_tag] = {
            "Id": "d" * 64, "RootFS": {"Layers": parent["RootFS"]["Layers"] + ["sha256:" + "3" * 64]},
            "Config": {"Labels": dict(parent["Config"]["Labels"])},
        }
        result = {
            "name": f'mesa-{state["run_id"]}-a',
            "layer": {"base": "sha256:" + parent["Id"], "image": derived_tag, "derived": True},
        }
        if mismatch == "name":
            result["name"] = "foreign-vm"
        else:
            result["layer"][mismatch] = False if mismatch == "derived" else "foreign-image"
        path = args[6]["result"]
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(result))
        raise guest.LabError("injected post-result failure")

    monkeypatch.setattr(guest, "run_arm", interrupted_arm)
    with pytest.raises(guest.LabError, match="post-result failure"):
        guest.run_runtime(state["root"])
    assert derived_tag in state["storage"]
    assert derived_tag not in state["removals"]


@pytest.mark.parametrize("emitted", [False, True])
def test_conditional_collector_preserves_raw_smithay_record_or_missing_evidence(
    guest, monkeypatch, proc_directory, emitted
):
    # Data-format wiring only: this temporary /proc tree is not a running
    # compositor, and emitted=True does not establish a shipped logging sink.
    (proc_directory / "comm").write_text("tuna-compositor\n")
    (proc_directory / "exe").unlink()
    (proc_directory / "exe").symlink_to("/usr/bin/tuna-compositor")
    (proc_directory / "fd").mkdir()
    (proc_directory / "fd/3").symlink_to("/dev/dri/card0")
    real_path = guest.Path
    monkeypatch.setattr(guest, "Path", lambda path: proc_directory.parent if str(path) == "/proc" else real_path(path))
    monkeypatch.setattr(guest, "session_records", lambda: [renderer_record()["session"]])
    monkeypatch.setattr(guest, "bounded_command", lambda *args, **kwargs: (0, "", ""))
    monkeypatch.setattr(guest.os, "sysconf", lambda _key: 100)
    monkeypatch.setattr(guest.time, "monotonic_ns", lambda: 15_000_000_000)
    raw = dict(renderer_record()["journal"], __CURSOR="fixture-journal-cursor")

    def journal(*matches, **kwargs):
        assert "_PID=829" in matches and "_UID=1000" in matches
        assert "_EXE=/usr/bin/tuna-compositor" in matches
        assert "--grep=GL Renderer:" in matches
        return [dict(raw)] if emitted else []

    monkeypatch.setattr(guest, "journal_entries", journal)
    collector, records = guest.collect_renderers(CANDIDATE_BOOT)
    assert collector == ""
    if emitted:
        assert len(records) == 1
        assert records[0]["journal"] == raw
        assert records[0]["software_verified"] is True
    else:
        assert records == []


def test_partial_corral_layer_failure_can_clean_reserved_owned_child(guest, runtime_storage, tmp_path):
    state = runtime_storage
    parent = {"Id": "c" * 64, "RootFS": {"Layers": ["sha256:" + "1" * 64]}}
    tag = f'localhost/corral-vmtest/mesa-{state["run_id"]}-a:latest'
    name = f'mesa-{state["run_id"]}-a'
    state["storage"][tag] = {
        "Id": "d" * 64, "Parent": "",
        "RootFS": {"Layers": parent["RootFS"]["Layers"] + ["sha256:" + "2" * 64]},
        "Config": {"Labels": dict(state["baseline_labels"], **{"io.tunaos.mesa3969.runtime": state["run_id"]})},
    }
    result = tmp_path / "partial-result.json"
    result.write_text(json.dumps({
        "name": name, "status": "failed", "exitCode": 3,
        "layer": {"derived": True, "base": "sha256:" + parent["Id"], "image": "sha256:" + parent["Id"]},
    }))
    guest.remove_runtime_image(["sudo", "-n", "podman"], {
        "tag": tag, "parent": parent, "name": name, "result": result,
    })
    assert state["removals"] == [tag]


def test_stop_never_signals_a_recycled_pid_that_is_not_our_process_group(guest):
    # Real unrelated session leader: its pid stands in for a recycled number
    # that an exited command of ours used to own.
    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True,
    )
    try:
        actual = guest.process_start_ticks(unrelated.pid)
        assert actual is not None
        ours = SimpleNamespace(
            pid=unrelated.pid, mesa_start_ticks=actual + 12345,
            poll=lambda: None, wait=lambda timeout=None: 0,
        )
        guest.stop_process(ours)
        assert unrelated.poll() is None, "stop_process signalled a group it does not own"
    finally:
        os.killpg(unrelated.pid, signal.SIGKILL)
        unrelated.wait(timeout=5)


FAKE_JOURNALCTL = """#!/bin/sh
# systemd 257 journalctl-show.c: an unmatched --grep exits 1, and -o json
# implies --quiet, so nothing is printed on either stream.
case "$FAKE_JOURNAL" in
error) echo "Failed to open journal: Permission denied" >&2; exit 1 ;;
match)
    for arg in "$@"; do
        [ "$arg" = -k ] && { echo '{"MESSAGE":"gnome-shell[1952]: segfault at 8"}'; exit 0; }
    done ;;
esac
for arg in "$@"; do
    case "$arg" in --grep=*) exit 1 ;; esac
done
exit 0
"""

FAKE_RPM = """#!/bin/sh
printf '%s\\n' "$@" > "$FAKE_RPM_ARGS"
case "$FAKE_RPM" in
mismatch) echo "S.5......    /usr/lib64/libEGL_mesa.so.0.0.0"; exit 1 ;;
error) echo "error: rpmdb: damaged header" >&2; exit 1 ;;
silent-failure) exit 1 ;;
esac
exit 0
"""


FAKE_OSTREE = """#!/bin/sh
[ "$*" = "admin --print-current-dir" ] || exit 2
[ -n "$FAKE_DEPLOYMENT" ] || { echo "error: not an ostree system" >&2; exit 1; }
echo "$FAKE_DEPLOYMENT"
"""


@pytest.fixture
def guest_commands(guest, monkeypatch, tmp_path):
    """Real subprocesses on PATH standing in for the guest's journalctl, rpm, ostree and getenforce."""
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    for name, body in (("journalctl", FAKE_JOURNALCTL), ("rpm", FAKE_RPM), ("ostree", FAKE_OSTREE),
                       ("loginctl", "#!/bin/sh\nexit 0\n"),
                       ("getenforce", "#!/bin/sh\necho Enforcing\n")):
        (fakebin / name).write_text(body)
        (fakebin / name).chmod(0o755)
    monkeypatch.setenv("PATH", f"{fakebin}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_RPM_ARGS", str(tmp_path / "rpm-args"))
    monkeypatch.delenv("FAKE_DEPLOYMENT", raising=False)
    policy = tmp_path / "60-tunaos-software-gl"
    policy.write_text("policy\n")
    monkeypatch.setattr(guest, "POLICY", policy)
    (tmp_path / "root").mkdir()
    monkeypatch.setattr(guest, "GUEST_ROOT", tmp_path / "root")
    monkeypatch.setattr(guest, "read_json", lambda _path: {"status": "collected"})
    mesa = {"name": "mesa-libEGL", "epoch": 0, "version": "25.2.7", "release": "4.el10.alma.5",
            "arch": "x86_64", "source_rpm": guest.INPUTS["source_rpm"], "header_sha256": "f" * 64}
    unrelated = dict(mesa, name="gnome-shell", source_rpm="gnome-shell-49.4-9.el10_2.alma.1.src.rpm")
    monkeypatch.setattr(sys.modules["mesa_3969_packages"], "query_inventory", lambda: [mesa, unrelated])
    return tmp_path


def test_guest_without_compositor_crash_is_observed_not_refused(guest, guest_commands, monkeypatch):
    # Run 41051314549: the control guest had no gnome-shell segfault, so the
    # kernel --grep exited 1 and every observation of that arm was refused.
    monkeypatch.setenv("FAKE_JOURNAL", "no-match")
    snapshot = guest.collect_snapshot(identity_only=True)
    assert snapshot["kernel_crash"] is False
    assert snapshot["crashes"] == []
    assert snapshot["selinux"] == "Enforcing"


def test_matched_kernel_crash_is_still_recorded(guest, guest_commands, monkeypatch):
    monkeypatch.setenv("FAKE_JOURNAL", "match")
    assert guest.collect_snapshot(identity_only=True)["kernel_crash"] is True


def test_journal_failure_with_diagnostics_still_refuses(guest, guest_commands, monkeypatch):
    monkeypatch.setenv("FAKE_JOURNAL", "error")
    with pytest.raises(guest.LabError, match="Permission denied"):
        guest.collect_snapshot(identity_only=True)


def test_unmatched_grep_is_empty_only_for_grep_queries(guest, guest_commands, monkeypatch):
    monkeypatch.setenv("FAKE_JOURNAL", "no-match")
    assert guest.journal_entries("_PID=1", "--grep=GL_RENDERER") == []
    monkeypatch.setenv("FAKE_JOURNAL", "error")
    with pytest.raises(guest.LabError):
        guest.journal_entries("_PID=1")


def test_snapshot_records_installed_bytes_that_differ_from_headers(guest, guest_commands, monkeypatch):
    monkeypatch.setenv("FAKE_JOURNAL", "no-match")
    monkeypatch.setenv("FAKE_RPM", "mismatch")
    snapshot = guest.collect_snapshot(identity_only=True)
    assert snapshot["file_verification"] == ["S.5......    /usr/lib64/libEGL_mesa.so.0.0.0"]
    arguments = (guest_commands / "rpm-args").read_text().split()
    # Only the pinned source's packages, and only size and digest are judged.
    assert arguments[0] == "-V" and arguments[-1] == "mesa-libEGL" and "gnome-shell" not in arguments
    assert {"--nomtime", "--nouser", "--nogroup", "--nomode"} <= set(arguments)
    assert "--nofiledigest" not in arguments and "--nosize" not in arguments


@pytest.mark.parametrize("mode", ["error", "silent-failure"])
def test_unverifiable_installed_bytes_refuse_the_observation(guest, guest_commands, monkeypatch, mode):
    monkeypatch.setenv("FAKE_JOURNAL", "no-match")
    monkeypatch.setenv("FAKE_RPM", mode)
    with pytest.raises(guest.LabError, match="installed file verification failed"):
        guest.collect_snapshot(identity_only=True)


@pytest.mark.parametrize("verification", [["S.5......    /usr/lib64/libEGL_mesa.so.0.0.0"], None])
@pytest.mark.parametrize("arm", ["control", "candidate"])
def test_header_identity_without_installed_bytes_cannot_compare(guest, pair, arm, verification):
    manifest, reports = pair
    snapshot = reports[arm]["snapshots"][0]
    if verification is None:
        del snapshot["file_verification"]
    else:
        snapshot["file_verification"] = verification
    result = guest.compare(manifest, reports)
    assert result["ok"] is False
    assert "installed-files-differ-from-package-headers" in result["arms"][arm]["failures"]


# --- Loaded Mesa bytes (run 41051314549: rpmdb named the candidate, the guest
# ran unpatched libEGL_mesa) ---------------------------------------------------


def test_matching_mapped_bytes_pass_and_shared_bytes_are_not_candidate_only(guest, pair):
    manifest, reports = pair
    result = guest.compare(manifest, reports)
    assert result["ok"] is True
    # The control maps the identical libgallium both arms ship: not candidate bytes.
    assert result["arms"]["control"]["failures"] == []
    rows = result["arms"]["candidate"]["byte_provenance"]["files"]
    assert set(rows) == {EGL, GALLIUM}
    assert rows[EGL]["mapped"] == [EGL_BYTES["candidate"]]
    assert rows[EGL]["first_divergence"] is None


@pytest.mark.parametrize("source", ["probe", "greeter"])
@pytest.mark.parametrize("bytes_seen", ["control", "vault", "unreadable", "replaced-path"])
def test_candidate_mapping_other_bytes_is_library_not_loaded(guest, pair, source, bytes_seen):
    manifest, reports = pair
    snapshot = reports["candidate"]["snapshots"][0]
    libraries = (snapshot["probe"]["cases"][2]["mapped_mesa"] if source == "probe"
                 else snapshot["mapped_libraries"][0]["libraries"])
    library = libraries[0]
    if bytes_seen == "unreadable":
        del library["sha256"]
        library.update(source="unavailable", error="unreadable-13")
    elif bytes_seen == "replaced-path":
        # The path now names patched bytes, but not the inode that is mapped.
        library.update(source="path", inode_matches=False)
    else:
        library["sha256"] = EGL_BYTES[bytes_seen]
    result = guest.compare(manifest, reports)
    assert result["ok"] is False
    assert "candidate-library-not-loaded" in result["arms"]["candidate"]["failures"]


def test_control_mapping_candidate_only_bytes_refuses(guest, pair):
    manifest, reports = pair
    reports["control"]["snapshots"][0]["probe"]["cases"][1]["mapped_mesa"][0]["sha256"] = EGL_BYTES["candidate"]
    failures = guest.compare(manifest, reports)["arms"]["control"]["failures"]
    assert {"control-maps-candidate-bytes", "control-library-not-loaded"} <= set(failures)


@pytest.mark.parametrize("arm", ["control", "candidate"])
@pytest.mark.parametrize("mutation", ["absent", "empty-candidate"])
def test_loaded_bytes_require_transferred_payload_digests(guest, pair, arm, mutation):
    manifest, reports = pair
    if mutation == "absent":
        del reports[arm]["rpm_payload"]
    else:
        reports[arm]["rpm_payload"]["candidate"] = {}
    result = guest.compare(manifest, reports)
    assert result["ok"] is False
    assert "missing-rpm-payload-digests" in result["arms"][arm]["failures"]


@pytest.mark.parametrize("arm,source,gating", [
    ("candidate", "probe", True), ("candidate", "greeter", True), ("candidate", "user-shell", True),
    ("control", "probe", True), ("control", "greeter", False),
])
def test_unobserved_patched_library_mapping(guest, pair, arm, source, gating):
    manifest, reports = pair
    snapshot = reports[arm]["snapshots"][0]
    if source == "probe":
        for case in snapshot["probe"]["cases"]:
            case["mapped_mesa"] = [item for item in case["mapped_mesa"] if item["path"] != EGL]
    elif source == "greeter":
        snapshot["mapped_libraries"] = []
    else:
        # A non-greeter gnome-shell cannot stand in for the greeter's mapping.
        snapshot["mapped_libraries"][0]["role"] = "other"
    reason = f"{arm}-{'probe' if source == 'probe' else 'greeter'}-mapped-library-unobserved"
    result = guest.compare(manifest, reports)["arms"][arm]
    assert (reason in result["failures"]) is gating
    assert (reason in result["advisories"]) is not gating
    assert result["ok"] is not gating


def stage_files(lost_at, stage):
    order = list(PROVENANCE_ORDER)
    lost = order.index(stage) >= order.index(lost_at)
    return {EGL: {"sha256": EGL_BYTES["vault" if lost else "candidate"], "size": 317672}}


PROVENANCE_ORDER = ("committed_image", "derived_image", "guest_deployment", "guest_root")


@pytest.mark.parametrize("lost_at", PROVENANCE_ORDER)
def test_provenance_names_the_stage_that_lost_patched_bytes(guest, pair, lost_at):
    manifest, reports = pair
    report = reports["candidate"]
    report["provenance"] = {
        "committed_image": {"image": "sha256:" + "c" * 64, "files": stage_files(lost_at, "committed_image")},
        "derived_image": {"image": "sha256:" + "d" * 64, "files": stage_files(lost_at, "derived_image")},
    }
    snapshot = report["snapshots"][0]
    snapshot["provenance"] = {
        "root": {"files": stage_files(lost_at, "guest_root")},
        "deployment": {"directory": "/sysroot/ostree/deploy/default/deploy/abc.0",
                       "files": stage_files(lost_at, "guest_deployment")},
    }
    for case in snapshot["probe"]["cases"]:
        case["mapped_mesa"][0]["sha256"] = EGL_BYTES["vault"]
    snapshot["mapped_libraries"][0]["libraries"][0]["sha256"] = EGL_BYTES["vault"]
    result = guest.compare(manifest, reports)["arms"]["candidate"]
    assert "candidate-library-not-loaded" in result["failures"]
    row = result["byte_provenance"]["files"][EGL]
    assert row["first_divergence"] == lost_at
    assert row["rpm_payload"] == EGL_BYTES["candidate"]
    assert row["mapped"] == [EGL_BYTES["vault"]]


def test_unrecorded_provenance_stage_is_reported_not_inferred(guest, pair):
    manifest, reports = pair
    report = reports["candidate"]
    report["provenance"] = {
        "committed_image": {"image": "sha256:" + "c" * 64, "files": stage_files("guest_deployment", "committed_image")},
        "derived_image": {"image": "sha256:" + "d" * 64, "error": "podman image mount failed"},
    }
    report["snapshots"][0]["provenance"] = {
        "root": {"files": {EGL: {"error": "absent"}}}, "deployment": {"error": "error: not an ostree system"},
    }
    result = guest.compare(manifest, reports)["arms"]["candidate"]["byte_provenance"]
    assert result["stage_errors"]["derived_image"] == "podman image mount failed"
    assert result["stage_errors"]["guest_deployment"] == "error: not an ostree system"
    row = result["files"][EGL]
    assert row["derived_image"] is None and row["guest_deployment"] is None
    assert row["guest_root"] == "absent" and row["first_divergence"] == "guest_root"


MAPPER = """
import mmap, os, resource, signal, sys, time
path, mode = sys.argv[1], sys.argv[2]
with open(path, "rb") as stream:
    mapping = mmap.mmap(stream.fileno(), 0, prot=mmap.PROT_READ)
print("eglInitialize=success mapped", flush=True)
if mode == "unmap":
    mapping.close()  # dlclose before exit: no outside sample would see it
elif mode == "crash":
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.kill(os.getpid(), signal.SIGSEGV)
elif mode == "hang":
    time.sleep(60)
elif mode == "wait":
    sys.stdin.readline()
"""


@pytest.fixture
def fake_library(guest, monkeypatch, tmp_path):
    library = tmp_path / "libEGL_mesa.so.0.0.0"
    library.write_bytes(b"patched libEGL_mesa bytes\n" * 4096)
    monkeypatch.setattr(guest, "MESA_LIBRARY", re.compile(re.escape(str(library))))
    script = tmp_path / "mapper.py"
    script.write_text(MAPPER)
    return library, script


@pytest.mark.parametrize("mode,code", [("exit", 0), ("unmap", 0), ("crash", 139)])
def test_traced_probe_hashes_bytes_the_process_actually_mapped(guest, fake_library, mode, code):
    library, script = fake_library
    rc, stdout, _, libraries, trace = guest.traced_probe(
        [sys.executable, str(script), str(library), mode], {"PATH": os.environ["PATH"]}, deadline=30,
    )
    assert (rc, trace) == (code, "ptrace")
    assert "eglInitialize=success" in stdout
    assert [(item["path"], item["sha256"], item["inode"]) for item in libraries] == [
        (str(library), hashlib.sha256(library.read_bytes()).hexdigest(), library.stat().st_ino)]


def test_traced_probe_deadline_kills_and_reports_timeout(guest, fake_library):
    library, script = fake_library
    started = time.monotonic()
    rc, _, _, libraries, _ = guest.traced_probe(
        [sys.executable, str(script), str(library), "hang"], {"PATH": os.environ["PATH"]}, deadline=2,
    )
    assert rc == 137 and time.monotonic() - started < 15
    assert [item["path"] for item in libraries] == [str(library)]


def test_refused_ptrace_runs_the_probe_but_records_no_mapping(guest, fake_library, monkeypatch, pair):
    library, script = fake_library
    real = guest._ptrace

    def refusing():
        ptrace = real()

        def call(request, pid=0, data=0):
            if request == guest.PTRACE_TRACEME:
                raise OSError(errno.EPERM, "ptrace denied")
            return ptrace(request, pid, data)
        return call

    monkeypatch.setattr(guest, "_ptrace", refusing)
    rc, stdout, _, libraries, trace = guest.traced_probe(
        [sys.executable, str(script), str(library), "exit"], {"PATH": os.environ["PATH"]}, deadline=30,
    )
    assert (rc, libraries, trace) == (0, [], "untraced: ptrace refused")
    assert "eglInitialize=success" in stdout
    manifest, reports = pair
    for case in reports["candidate"]["snapshots"][0]["probe"]["cases"]:
        case.update(mapped_mesa=libraries, trace=trace)
    failures = guest.compare(manifest, reports)["arms"]["candidate"]["failures"]
    assert "candidate-probe-mapped-library-unobserved" in failures


def test_probe_cases_record_mapped_bytes_with_their_exit(guest, fake_library, monkeypatch, tmp_path):
    library, _ = fake_library
    probe = tmp_path / "repro-egldevice-swrast"
    probe.write_text(f"#!{sys.executable}\n" + MAPPER.replace(
        "path, mode = sys.argv[1], sys.argv[2]",
        f"path = {str(library)!r}\nmode = 'crash' if os.environ.get('LIBGL_ALWAYS_SOFTWARE') "
        "or os.environ.get('MESA_LOADER_DRIVER_OVERRIDE') else 'unmap'",
    ).replace('"eglInitialize=success mapped"', '"eglInitialize=success version=1.5"'))
    probe.chmod(0o755)
    monkeypatch.setattr(guest, "boot_id", lambda: CONTROL_BOOT)
    monkeypatch.setattr(guest, "virtio_device", lambda: ("/dev/dri/card0", []))
    monkeypatch.setattr(guest, "bounded_command", lambda argv, **_kwargs: (3, "inactive\n", ""))
    result = guest.collect_probe(binary=probe)
    assert [case["exit"] for case in result["cases"]] == [0, 139, 139, 139]
    assert [case["status"] for case in result["cases"]] == ["initialized", "crashed", "crashed", "crashed"]
    digest = hashlib.sha256(library.read_bytes()).hexdigest()
    assert all([item["sha256"] for item in case["mapped_mesa"]] == [digest] for case in result["cases"])


@pytest.mark.parametrize("replaced", [False, True])
def test_live_process_mapping_is_hashed_through_the_mapping(guest, fake_library, replaced):
    library, script = fake_library
    original = hashlib.sha256(library.read_bytes()).hexdigest()
    process = subprocess.Popen([sys.executable, str(script), str(library), "wait"],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        assert process.stdout.readline().startswith(b"eglInitialize=success")
        if replaced:
            replacement = library.with_name("replacement")
            replacement.write_bytes(b"other bytes")
            os.replace(replacement, library)
        fd = os.open(f"/proc/{process.pid}", os.O_RDONLY | os.O_DIRECTORY)
        try:
            [record] = guest.mapped_mesa_libraries(fd, {})
        finally:
            os.close(fd)
    finally:
        process.communicate(b"\n", timeout=10)
    assert record["path"] == str(library) and record["deleted"] is replaced
    if record["source"] == "map_files":  # root: always the mapped file
        assert record["sha256"] == original
    else:  # unprivileged fallback: a replaced path is flagged, never trusted
        assert record["source"] == "path"
        assert record["inode_matches"] is (not replaced)
        if not replaced:
            assert record["sha256"] == original


def write_tree(root, files):
    for path, data in files.items():
        target = root / path.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            target.write_bytes(data)
        else:
            target.symlink_to(data["symlink"])


def test_guest_provenance_separates_running_root_from_ostree_deployment(guest, guest_commands, monkeypatch):
    monkeypatch.setenv("FAKE_JOURNAL", "no-match")
    dri = "/usr/lib64/dri/swrast_dri.so"
    write_tree(guest_commands / "root", {EGL: b"patched", "/usr/lib64/libEGL_mesa.so.0": {"symlink": "libEGL_mesa.so.0.0.0"},
                                         dri: b"driver", "/usr/lib64/libunrelated.so": b"x"})
    deployment = guest_commands / "sysroot/ostree/deploy/default/deploy/abc.0"
    write_tree(deployment, {EGL: b"vault", dri: {"symlink": "/etc/passwd"}})
    monkeypatch.setenv("FAKE_DEPLOYMENT", str(deployment))
    provenance = guest.collect_snapshot(identity_only=True)["provenance"]
    assert provenance["root"]["files"] == {
        EGL: {"sha256": hashlib.sha256(b"patched").hexdigest(), "size": 7},
        dri: {"sha256": hashlib.sha256(b"driver").hexdigest(), "size": 6},
    }
    assert provenance["deployment"] == {"directory": str(deployment), "files": {
        EGL: {"sha256": hashlib.sha256(b"vault").hexdigest(), "size": 5}, dri: {"error": "symlink"},
    }}
    monkeypatch.delenv("FAKE_DEPLOYMENT")
    provenance = guest.collect_snapshot(identity_only=True)["provenance"]
    assert "not an ostree system" in provenance["deployment"]["error"]
    assert EGL in provenance["root"]["files"]


def newc(entries, trailer=b""):
    archive = b""
    for name, mode, inode, nlink, data in [*entries, ("TRAILER!!!", 0, 0, 1, b"")]:
        encoded = name.encode() + b"\0"
        fields = [inode, mode, 0, 0, nlink, 0, len(data), 8, 1, 0, 0, len(encoded), 0]
        archive += b"070701" + b"".join(b"%08X" % value for value in fields) + encoded
        archive += b"\0" * (-(110 + len(encoded)) % 4) + data + b"\0" * (-len(data) % 4)
    return archive + b"\0" * (-len(archive) % 512) + trailer


@pytest.fixture
def rpm2cpio(tmp_path):
    tool = tmp_path / "rpm2cpio"
    tool.write_text('#!/bin/sh\n[ -n "$FAKE_RPM2CPIO_FAIL" ] && { echo "error: damaged payload" >&2; exit 1; }\nexec cat "$1"\n')
    tool.chmod(0o755)
    return tool


def test_payload_digests_are_read_from_the_rpm_archive(guest, rpm2cpio, tmp_path):
    packages = sys.modules["mesa_3969_packages"]
    archive = tmp_path / "mesa.rpm"
    archive.write_bytes(newc([
        ("./usr/lib64", 0o40755, 1, 2, b""),
        ("./usr/lib64/libEGL_mesa.so.0.0.0", 0o100755, 2, 1, b"egl bytes"),
        ("./usr/lib64/libEGL_mesa.so.0", 0o120777, 3, 1, b"libEGL_mesa.so.0.0.0"),
        # A hard-link set carries its data on one member only.
        ("./usr/lib64/dri/a_dri.so", 0o100755, 4, 2, b""),
        ("./usr/lib64/dri/b_dri.so", 0o100755, 4, 2, b"driver bytes"),
    ]))
    assert packages.rpm_payload_digests(archive, rpm2cpio=str(rpm2cpio)) == {
        EGL: {"sha256": hashlib.sha256(b"egl bytes").hexdigest(), "size": 9},
        "/usr/lib64/dri/a_dri.so": {"sha256": hashlib.sha256(b"driver bytes").hexdigest(), "size": 12},
        "/usr/lib64/dri/b_dri.so": {"sha256": hashlib.sha256(b"driver bytes").hexdigest(), "size": 12},
    }


@pytest.mark.parametrize("damage", ["magic", "truncated", "after-trailer", "traversal", "tool-failure"])
def test_unreadable_rpm_payload_refuses(guest, rpm2cpio, tmp_path, monkeypatch, damage):
    packages = sys.modules["mesa_3969_packages"]
    entries = [("./usr/lib64/libEGL_mesa.so.0.0.0", 0o100755, 2, 1, b"egl bytes")]
    if damage == "traversal":
        entries.append(("./usr/../etc/shadow", 0o100644, 5, 1, b"x"))
    data = newc(entries, trailer=b"extra" if damage == "after-trailer" else b"")
    if damage == "magic":
        data = b"070702" + data[6:]
    elif damage == "truncated":
        data = data[:150]
    elif damage == "tool-failure":
        monkeypatch.setenv("FAKE_RPM2CPIO_FAIL", "1")
    archive = tmp_path / "mesa.rpm"
    archive.write_bytes(data)
    with pytest.raises(packages.LabError):
        packages.rpm_payload_digests(archive, rpm2cpio=str(rpm2cpio))


@pytest.mark.parametrize("mutation", ["arm-missing", "relative-path", "short-digest", "extra-field"])
def test_payload_digest_table_shape_is_validated(guest, mutation):
    packages = sys.modules["mesa_3969_packages"]
    tables = payload_tables()
    assert packages.validate_payload_digests(copy.deepcopy(tables)) == tables
    if mutation == "arm-missing":
        del tables["control"]
    elif mutation == "relative-path":
        tables["candidate"]["usr/lib64/x.so"] = tables["candidate"].pop(EGL)
    elif mutation == "short-digest":
        tables["candidate"][EGL]["sha256"] = "ab"
    else:
        tables["candidate"][EGL]["build_id"] = "x"
    with pytest.raises(packages.LabError):
        packages.validate_payload_digests(tables)


def test_committed_image_bytes_are_recorded_before_the_arm_runs(guest, monkeypatch, runtime_storage):
    state = runtime_storage
    arm_tag = f'localhost/mesa3969-{state["run_id"]}:control'
    state["trees"][arm_tag] = {EGL: b"committed control bytes"}
    seen = {}

    def stop_after_control(arm, _image, *args):
        seen.update(payload=args[-2], provenance=copy.deepcopy(args[-1]))
        raise guest.LabError("stop after the control arm's inputs")

    monkeypatch.setattr(guest, "run_arm", stop_after_control)
    with pytest.raises(guest.LabError, match="stop after"):
        guest.run_runtime(state["root"])
    assert seen["payload"] == state["payload"]
    files = seen["provenance"]["committed_image"]["files"]
    assert files[EGL] == {"sha256": hashlib.sha256(b"committed control bytes").hexdigest(), "size": 23}
    assert files[GALLIUM]["sha256"] == hashlib.sha256(b"gallium").hexdigest()
    assert seen["provenance"]["installed_container"]["full_rootfs"] == seen["provenance"]["committed_image"]["full_rootfs"]
    assert state["mounted"] == []  # every container/image mount was released


# --- Teardown ordering: the gate's EXIT trap vs a live observation ----------


SLOW_GATE = """#!/usr/bin/env bash
trap '"$CORRAL" delete "$GATE_NAME" -f >/dev/null 2>&1 || true' EXIT
sleep 1.5
exit 1
"""


@pytest.fixture
def slow_gate(guest, monkeypatch, tmp_path):
    """Real gate/trap/Corral processes; only SSH observation and storage are faked."""
    monkeypatch.setenv("GITHUB_RUN_ID", "123456")
    root = tmp_path / "runtime"
    (root / "work").mkdir(parents=True)
    alive = tmp_path / "vm-alive"
    alive.touch()
    deletes = tmp_path / "deletes"
    corral = tmp_path / "corral"
    corral.write_text(
        f"#!{sys.executable}\nimport pathlib, sys, time\n"
        "if sys.argv[1] == 'delete':\n"
        f"    pathlib.Path({str(deletes)!r}).open('a').write(f'{{time.monotonic_ns()}}\\n')\n"
        f"    pathlib.Path({str(alive)!r}).unlink()\n"
        "    time.sleep(2)\n"
        f"    pathlib.Path({str(deletes)!r}).with_name('deleted').write_text('done')\n"
    )
    corral.chmod(0o755)
    gate = tmp_path / "gate.sh"
    gate.write_text(SLOW_GATE)
    monkeypatch.setattr(guest, "privileged_environment",
                        lambda environment: ["env", "-i", *[f"{key}={value}" for key, value in environment.items()]])
    monkeypatch.setattr(guest, "owned_ssh_argv", lambda *_args: ["ssh-test-only"])
    monkeypatch.setattr(guest, "stored_metadata", lambda *_args: None)
    state = {"samples": [], "fail": set(), "alive": alive, "deletes": deletes, "done": deletes.with_name("deleted")}
    snapshot = {"greeter_evidence": "", "boot_id": CANDIDATE_BOOT, "inventory": [], "file_verification": [],
                "software_policy_sha256": "d" * 64, "selinux": "Enforcing", "probe": {}, "renderer_records": [],
                "crashes": [], "kernel_crash": False, "renderer_collection": "sampled", "mapped_libraries": []}

    def observe(argv, **_kwargs):
        index = len(state["samples"])
        begin = time.monotonic_ns()
        time.sleep(0.05 if index == 0 else 2.0)
        state["samples"].append((begin, time.monotonic_ns()))
        if not alive.exists() or index in state["fail"]:
            raise guest.LabError("command failed (255): ssh: connect to host 127.0.0.1 port 2285: Connection refused")
        return 0, json.dumps(snapshot), ""

    monkeypatch.setattr(guest, "bounded_command", observe)

    def run():
        return guest.run_arm("candidate", "sha256:" + "c" * 64, root, gate, [], str(corral),
                             {"tag": "localhost/corral-vmtest/x:latest", "parent": {}}, payload_tables(), {})
    state["run"] = run
    return state


def test_gate_teardown_waits_for_the_in_flight_observation(guest, slow_gate):
    report = slow_gate["run"]()
    [deleted_at] = [int(value) for value in slow_gate["deletes"].read_text().split()]
    # The VM outlived every observation: no sample met a deleted guest.
    assert all(end <= deleted_at for _, end in slow_gate["samples"])
    assert "live-observer-gap-after-first-observation" not in report["observer_errors"]
    assert report["gate_exit"] == 1 and len(report["snapshots"]) == 1
    events = report["teardown"]["events"]
    names = [event["event"] for event in events]
    assert names.index("delete-requested") < names.index("deleted")
    outcome = next(event for event in events if event["event"].startswith("observer-")
                   and event["event"] != "observer-stopped-for-teardown")
    requested = next(event["monotonic_ns"] for event in events if event["event"] == "delete-requested")
    if any(begin <= requested <= end for begin, end in slow_gate["samples"]):
        assert outcome["event"] == "observer-finished"  # the observation won; delete waited
    assert outcome["event"] != "observer-wait-timeout"
    assert report["teardown"]["last_sample"]["ok"] is True


def test_root_barrier_files_cannot_abort_the_arm_mid_delete(guest, slow_gate, monkeypatch):
    """The gate and its EXIT-trap barrier run through sudo; the orchestrator may not.

    A barrier-created events.jsonl is root's 0600 file. This process cannot be
    another user, so os.open models that: an events file this process did not
    create itself is refused with EACCES, exactly as root's 0600 file would be.
    """
    real_open = os.open
    ours = set()

    def open_as_runner(path, flags, mode=0o777, *, dir_fd=None):
        name = os.fspath(path)
        if dir_fd is None and name.endswith("teardown/events.jsonl"):
            if flags & os.O_CREAT and not os.path.exists(name):
                ours.add(name)
            elif name not in ours:
                raise PermissionError(errno.EACCES, "Permission denied (root-owned 0600)", name)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", open_as_runner)
    report = slow_gate["run"]()
    # The gate finished its own delete; nothing killed it mid-teardown.
    assert slow_gate["done"].read_text() == "done"
    assert report["gate_exit"] == 1
    names = [event["event"] for event in report["teardown"]["events"]]
    assert names[0] == "delete-requested" and "deleted" in names
    assert "observer-stopped-for-teardown" in names
    assert guest.PROCESS_CLEANUP_ERRORS == []


def test_unwritable_teardown_evidence_is_recorded_not_raised(guest, slow_gate, monkeypatch):
    real_open = os.open

    def refusing(path, flags, mode=0o777, *, dir_fd=None):
        name = os.fspath(path)
        # Pre-creation succeeds; every later orchestrator write/read is refused.
        if dir_fd is None and name.endswith("teardown/events.jsonl") and not flags & os.O_EXCL:
            raise PermissionError(errno.EACCES, "Permission denied", name)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", refusing)
    report = slow_gate["run"]()
    assert slow_gate["done"].read_text() == "done" and report["gate_exit"] == 1
    assert report["teardown"]["events"] == []
    assert any("teardown event unwritable" in error for error in guest.PROCESS_CLEANUP_ERRORS)
    assert any("teardown evidence unreadable" in error for error in guest.PROCESS_CLEANUP_ERRORS)


def test_real_observer_failure_is_still_a_gap(guest, slow_gate):
    slow_gate["fail"].add(1)  # The guest stops answering while the VM is live.
    report = slow_gate["run"]()
    assert "live-observer-gap-after-first-observation" in report["observer_errors"]
    assert report["teardown"]["last_sample"]["ok"] is False


@pytest.mark.parametrize("busy", [False, True])
def test_teardown_barrier_bounds_its_wait_and_records_overlap(guest, tmp_path, busy):
    state = tmp_path / "teardown"
    state.mkdir()
    calls = tmp_path / "calls"
    corral = tmp_path / "corral"
    corral.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> {calls}\n')
    corral.chmod(0o755)
    shim = guest.corral_teardown_shim(tmp_path / "shim", str(corral), state)
    # Every other Corral call passes straight through, without the barrier.
    subprocess.run([str(shim), "screenshot", "vm", "-o", "x.png"], check=True)
    assert not (state / "events.jsonl").exists()
    lock = os.open(state / "observer.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        if busy:
            fcntl.flock(lock, fcntl.LOCK_EX)  # An observation that never finishes.
        assert guest.teardown_barrier(state, str(corral), ["delete", "vm", "-f"], wait=0.3) == 0
    finally:
        os.close(lock)
    assert calls.read_text().splitlines() == ["screenshot vm -o x.png", "delete vm -f"]
    report = {"observer_errors": []}
    guest.teardown_evidence(report, state)
    names = [event["event"] for event in report["teardown"]["events"]]
    assert names == ["delete-requested", "observer-wait-timeout" if busy else "observer-idle", "deleted"]
    assert report["observer_errors"] == (["teardown-overlapped-live-observation"] if busy else [])
    assert (state / "teardown-requested").exists()


def test_crash_looping_greeter_mappings_merge_by_bytes_not_pid(guest):
    first = {"boot_id": CANDIDATE_BOOT, "inventory": [], "file_verification": [], "software_policy_sha256": "d",
             "selinux": "Enforcing", "probe": {}, "renderer_records": [], "crashes": [], "kernel_crash": False,
             "renderer_collection": "not-requested",
             "mapped_libraries": [{"pid": 10, "role": "greeter", "libraries": loaded("control")}]}
    later = copy.deepcopy(first)
    later["mapped_libraries"] = [{"pid": 11, "role": "greeter", "libraries": loaded("control")},
                                 {"pid": 12, "role": "greeter", "libraries": loaded("candidate")}]
    report = {"observer_errors": []}
    guest.merge_snapshot(first, later, report)
    assert [item["pid"] for item in first["mapped_libraries"]] == [10, 12]
    assert report["observer_errors"] == []


def test_full_rootfs_identity_is_portable_and_covers_hardlinks(guest, tmp_path):
    roots = [tmp_path / "before", tmp_path / "after"]
    for root in roots:
        root.mkdir()
        (root / "a").write_bytes(b"private bytes never retained")
        os.link(root / "a", root / "b")
        (root / "link").symlink_to("a")
        for path in [root, *root.iterdir()]:
            os.utime(path, ns=(1771891200000000000, 1771891200000000000), follow_symlinks=False)
    before, after = [guest.full_rootfs_digest(root) for root in roots]
    assert before == after
    assert before["entries"] == 4
    assert before["regular_bytes"] == len(b"private bytes never retained")
    assert "private bytes" not in json.dumps(before)
    # Same files/content/modes/mtime, but lost hardlink topology is a mismatch.
    original = (roots[1] / "b").read_bytes()
    (roots[1] / "b").unlink()
    (roots[1] / "b").write_bytes(original)
    for path in [roots[1], *roots[1].iterdir()]:
        os.utime(path, ns=(1771891200000000000, 1771891200000000000), follow_symlinks=False)
    assert guest.full_rootfs_digest(roots[1]) != before


@pytest.mark.parametrize("change", ["same-size-same-mtime-bytes", "mode", "mtime", "link", "xattr", "extra-file"])
def test_full_rootfs_proof_rejects_unrelated_byte_or_metadata_loss(guest, tmp_path, change):
    before = tmp_path / "before"
    before.mkdir()
    (before / "file").write_bytes(b"old\n")
    (before / "link").symlink_to("file")
    for path in [before, *before.iterdir()]:
        os.utime(path, ns=(1771891200000000000, 1771891200000000000), follow_symlinks=False)
    after = tmp_path / "after"
    shutil.copytree(before, after, symlinks=True)
    expected = guest.full_rootfs_digest(before)
    assert guest.full_rootfs_digest(after) == expected
    if change == "same-size-same-mtime-bytes":
        (after / "file").write_bytes(b"new\n")
        os.utime(after / "file", ns=(1771891200000000000, 1771891200000000000))
    elif change == "mode":
        (after / "file").chmod(0o600)
    elif change == "mtime":
        os.utime(after / "file", ns=(1771891200000000000, 1771891201000000000))
    elif change == "link":
        (after / "link").unlink()
        (after / "link").symlink_to("other")
    elif change == "xattr":
        os.setxattr(after / "file", "user.mesa-test", b"changed")
    else:
        (after / "extra").write_bytes(b"x")
    assert guest.full_rootfs_digest(after) != expected


@pytest.mark.parametrize("change,reason", [
    ("payload", "committed-image-payload-mismatch"),
    ("unrelated-bytes", "commit-full-rootfs-identity-changed"),
    ("metadata", "commit-full-rootfs-identity-changed"),
])
def test_commit_identity_refuses_before_any_vm_gate(guest, monkeypatch, runtime_storage, change, reason):
    state = runtime_storage
    entered = []
    monkeypatch.setattr(guest, "run_arm", lambda *args: entered.append(args))

    def mutate(root):
        target = root / EGL.lstrip("/")
        if change == "payload":
            old = target.stat()
            target.write_bytes(b"x" * old.st_size)
            os.utime(target, ns=(old.st_atime_ns, old.st_mtime_ns))
        elif change == "metadata":
            target.chmod(0o600)
        else:
            (root / "unrelated").write_bytes(b"unexpected")

    state["commit_mutation"] = mutate
    with pytest.raises(guest.LabError, match=reason):
        guest.run_runtime(state["root"])
    assert entered == []
    assert state["mounted"] == []
    report = json.loads((state["root"] / "work/selected/control/report.json").read_text())
    assert report["provenance"]["storage"]["GraphDriverName"] == "test-adapter"
    assert "installed_container" in report["provenance"] and "committed_image" in report["provenance"]


@pytest.mark.parametrize("field", ["Image", "run", "head"])
def test_install_container_must_be_the_exact_owned_baseline(guest, runtime_storage, field):
    state = runtime_storage
    value = {"Image": "b" * 64, "Config": {"Labels": dict(state["baseline_labels"], **{
        "io.tunaos.mesa3969.runtime": state["run_id"]})}}
    guest.require_install_base(value, "sha256:" + "b" * 64)
    if field == "Image":
        value["Image"] = "a" * 64
    else:
        key = "io.tunaos.mesa3969.runtime" if field == "run" else "io.tunaos.mesa3969"
        value["Config"]["Labels"][key] = "foreign"
    with pytest.raises(guest.LabError, match="exact owned baseline"):
        guest.require_install_base(value, "sha256:" + "b" * 64)


def test_single_layer_install_proof_does_not_replace_derived_ancestry(guest, runtime_storage):
    state = runtime_storage
    base = {"Id": "b" * 64, "RootFS": {"Layers": ["sha256:" + "1" * 64]}}
    image = {"Id": "c" * 64, "RootFS": {"Layers": ["sha256:" + "2" * 64]},
             "Config": {"Labels": dict(state["baseline_labels"], **{
                 "io.tunaos.mesa3969.runtime": state["run_id"]})}}
    assert guest.installed_image(image, base) == "sha256:" + "c" * 64
    # Corral's derived image is still required to contain the installed layers.
    with pytest.raises(guest.LabError, match="ancestry"):
        guest.runtime_image(image, base)
    derived = copy.deepcopy(image)
    derived["Id"] = "d" * 64
    derived["RootFS"]["Layers"].append("sha256:" + "3" * 64)
    assert guest.runtime_image(derived, image) == "sha256:" + "d" * 64


@pytest.mark.parametrize("change", ["foreign-run", "foreign-head", "same-id", "multiple-layers", "bad-layer"])
def test_full_rootfs_image_ownership_and_shape_cannot_be_claimed(guest, runtime_storage, change):
    state = runtime_storage
    base = {"Id": "b" * 64}
    image = {"Id": "c" * 64, "RootFS": {"Layers": ["sha256:" + "2" * 64]},
             "Config": {"Labels": dict(state["baseline_labels"], **{
                 "io.tunaos.mesa3969.runtime": state["run_id"]})}}
    if change.startswith("foreign-"):
        key = "io.tunaos.mesa3969.runtime" if change == "foreign-run" else "io.tunaos.mesa3969"
        image["Config"]["Labels"][key] = "foreign"
    elif change == "same-id":
        image["Id"] = base["Id"]
    elif change == "multiple-layers":
        image["RootFS"]["Layers"].append("sha256:" + "3" * 64)
    else:
        image["RootFS"]["Layers"] = ["not-a-diff-id"]
    with pytest.raises(guest.LabError, match="ownership or single-layer"):
        guest.installed_image(image, base)


@pytest.mark.parametrize("before_ns,after_ns,equal", [
    (123456789, 0, True),
    (750000000, 1000000000, True),
    (499999999, 500000000, False),
    (123456789, 1123456789, False),
])
def test_full_rootfs_proof_declares_nearest_second_tar_precision(guest, tmp_path, before_ns, after_ns, equal):
    before = tmp_path / "before"
    before.mkdir()
    (before / "generated").write_bytes(b"generated, not an RPM file")
    os.utime(before, ns=(1771891200000000000, 1771891200000000000))
    after = tmp_path / "after"
    shutil.copytree(before, after)
    epoch = 1771891200000000000
    os.utime(before / "generated", ns=(epoch + before_ns, epoch + before_ns))
    os.utime(after / "generated", ns=(epoch + after_ns, epoch + after_ns))
    first, second = guest.full_rootfs_digest(before), guest.full_rootfs_digest(after)
    assert first["schema_version"] == second["schema_version"] == 2
    assert first["mtime_precision"] == second["mtime_precision"] == "nearest-second"
    assert first["root_mtime_policy"] == second["root_mtime_policy"] == "mountpoint-not-an-image-entry"
    assert (first == second) is equal


@pytest.mark.parametrize("fractional_selected", [False, True])
def test_tar_precision_never_relaxes_selected_rpm_mtime_identity(guest, tmp_path, fractional_selected):
    before = tmp_path / "before"
    before.mkdir()
    (before / "selected").write_bytes(b"RPM payload")
    (before / "generated").write_bytes(b"non-RPM generated file")
    epoch = 1771891200000000000
    for path in [before, *before.iterdir()]:
        os.utime(path, ns=(epoch, epoch))
    after = tmp_path / "after"
    shutil.copytree(before, after)
    # The whole-tree proof permits the exporter's declared precision for all
    # nodes. The selected RPM's exact metadata has an independent strict gate.
    os.utime(before / "generated", ns=(epoch + 750000000, epoch + 750000000))
    os.utime(after / "generated", ns=(epoch + 1000000000, epoch + 1000000000))
    if fractional_selected:
        os.utime(before / "selected", ns=(epoch + 123456789, epoch + 123456789))
    snapshots = []
    for root in (before, after):
        info = (root / "selected").stat()
        snapshots.append({
            "full_rootfs": guest.full_rootfs_digest(root),
            "files": guest.tree_digests(root, ["/selected"]),
            "file_metadata": {"/selected": {"mtime_ns": info.st_mtime_ns, "size": info.st_size,
                                            "mode": info.st_mode, "uid": info.st_uid, "gid": info.st_gid}},
        })
    assert snapshots[0]["full_rootfs"] == snapshots[1]["full_rootfs"]
    expected = {"/selected": {"sha256": hashlib.sha256(b"RPM payload").hexdigest()}}
    if fractional_selected:
        with pytest.raises(guest.LabError, match="commit-rpm-file-metadata-changed"):
            guest.require_commit_bytes("candidate", expected, *snapshots)
    else:
        guest.require_commit_bytes("candidate", expected, *snapshots)


@pytest.mark.parametrize("field,value", [
    ("schema_version", 0), ("mtime_precision", "ignored"), ("root_mtime_policy", "ignore-all-metadata"),
])
def test_unknown_full_rootfs_proof_format_is_refused(guest, field, value):
    proof = {"schema_version": 2, "mtime_precision": "nearest-second",
             "root_mtime_policy": "mountpoint-not-an-image-entry", "sha256": "a" * 64}
    proof[field] = value
    snapshot = {"files": {EGL: {"sha256": "b" * 64}}, "full_rootfs": proof, "file_metadata": {}}
    with pytest.raises(guest.LabError, match="commit-full-rootfs-proof-format-mismatch"):
        guest.require_commit_bytes("candidate", {EGL: {"sha256": "b" * 64}}, snapshot, snapshot)


@pytest.mark.parametrize("change", ["mode", "uid", "gid", "xattr"])
def test_mountpoint_root_excludes_only_mtime_not_other_metadata(guest, tmp_path, monkeypatch, change):
    root = tmp_path / "root"
    root.mkdir()
    (root / "file").write_bytes(b"unchanged")
    before = guest.full_rootfs_digest(root)
    root_stat = root.stat()
    os.utime(root, ns=(root_stat.st_atime_ns, root_stat.st_mtime_ns + 10_000_000_000))
    # Extraction creates a new mountpoint root with an unrelated mtime.
    assert guest.full_rootfs_digest(root) == before
    if change == "mode":
        root.chmod(0o700 if root_stat.st_mode & 0o777 != 0o700 else 0o755)
    elif change == "xattr":
        os.setxattr(root, "user.mesa-test", b"changed root metadata")
    else:
        # Exercise root uid/gid comparison without requiring chown privilege.
        real_lstat = Path.lstat

        def lstat(path, *args, **kwargs):
            value = real_lstat(path, *args, **kwargs)
            if path != root:
                return value
            return SimpleNamespace(st_mode=value.st_mode, st_mtime_ns=value.st_mtime_ns,
                                   st_uid=value.st_uid + (change == "uid"),
                                   st_gid=value.st_gid + (change == "gid"))

        monkeypatch.setattr(Path, "lstat", lstat)
    assert guest.full_rootfs_digest(root) != before


@pytest.mark.parametrize("kind", ["container", "image"])
@pytest.mark.parametrize("failure", ["cancel", "scan-error", "none-inside-caller-except"])
def test_commit_snapshot_unmount_never_replaces_an_active_failure(guest, monkeypatch, tmp_path, kind, failure):
    root = tmp_path / "mounted"
    root.mkdir()
    (root / "proof").write_bytes(b"payload")
    calls = []
    cleanup_error = guest.LabError("unmount timeout: owned snapshot")
    monkeypatch.setattr(guest, "PROCESS_CLEANUP_ERRORS", [])
    prefix = ["podman-test", *(["image"] if kind == "image" else [])]

    def command(argv, **kwargs):
        assert kwargs["timeout"] == 120
        calls.append(argv)
        if argv == [*prefix, "mount", "owned"]:
            return 0, str(root) + "\n", ""
        assert argv == [*prefix, "unmount", "owned"]
        raise cleanup_error

    monkeypatch.setattr(guest, "bounded_command", command)
    original = (SystemExit(143) if failure == "cancel" else
                guest.LabError("rootfs scan failed") if failure == "scan-error" else None)
    if original is not None:
        def failed_scan(_root):
            raise original

        monkeypatch.setattr(guest, "full_rootfs_digest", failed_scan)
        with pytest.raises(type(original)) as raised:
            guest.commit_snapshot(["podman-test"], kind, "owned", ["/proof"])
        assert raised.value is original
        if failure == "cancel":
            assert raised.value.code == 143
    else:
        # This caller's active exception must NOT cause a clean snapshot to
        # swallow its own unmount failure (sys.exc_info() would see the caller).
        try:
            raise LookupError("unrelated caller exception")
        except LookupError:
            with pytest.raises(guest.LabError) as raised:
                guest.commit_snapshot(["podman-test"], kind, "owned", ["/proof"])
        assert raised.value is cleanup_error
    assert calls == [[*prefix, "mount", "owned"], [*prefix, "unmount", "owned"]]
    assert guest.PROCESS_CLEANUP_ERRORS == ["unmount timeout: owned snapshot"]
