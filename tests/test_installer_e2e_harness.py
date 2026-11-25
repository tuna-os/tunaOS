"""Installer e2e harness units run without KVM or root (tunaOS#4910).

Falsification: a QMP click outside the tablet range, a guest dump that is
not a node list passing validation, a lane without `restrict=on` calling
itself offline, a bootc digest read from the wrong deployment, or a
`--dry-run` that creates files all fail this module.
"""

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
E2E = ROOT / "scripts/installer-e2e"


def load(name):
    """Load a scripts/installer-e2e module once; reuse it after that."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, E2E / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


atspi_match = load("atspi_match")
qmp_input = load("qmp_input")
tree_dump = load("tree_dump")
stages = load("stages")
fisherman_mock = load("fisherman_mock")
ocr_fallback = load("ocr_fallback")
driver_mod = load("driver")
run_e2e = load("run_e2e")
Page = atspi_match.Page
Driver = driver_mod.Driver
DriverError = driver_mod.DriverError


def test_abs_move_maps_corners_to_tablet_range():
    low = qmp_input.abs_move(-5, -5)["arguments"]["events"]
    high = qmp_input.abs_move(99999, 99999)["arguments"]["events"]
    assert [e["data"]["value"] for e in low] == [0, 0]
    assert [e["data"]["value"] for e in high] == [32767, 32767]


def test_click_is_move_press_release_in_order():
    cmds = qmp_input.click_at(640, 400)
    assert len(cmds) == 3
    assert cmds[0]["execute"] == "input-send-event"
    assert cmds[1]["arguments"]["events"][0]["data"]["down"] is True
    assert cmds[2]["arguments"]["events"][0]["data"]["down"] is False


def test_click_node_centers_on_the_node_and_rejects_missing_extents():
    node = {"name": "Next", "ext": [100, 100, 200, 40]}
    x, y = qmp_input.node_center(node)
    assert (x, y) == (200, 120)
    with pytest.raises(ValueError):
        qmp_input.click_node({"name": "Next", "ext": None})


def test_parse_tree_accepts_fixtures_and_rejects_the_rest(tmp_path):
    raw = (ROOT / "tests/fixtures/installer-e2e/disk-page.json").read_text()
    assert len(tree_dump.parse_tree(raw)) == 6
    with pytest.raises(ValueError, match="not JSON"):
        tree_dump.parse_tree("{nope")
    with pytest.raises(TypeError):
        tree_dump.parse_tree(json.dumps({"name": "x"}))
    with pytest.raises(TypeError):
        tree_dump.parse_tree(json.dumps(["ok", 7]))
    with pytest.raises(ValueError, match="misses keys"):
        tree_dump.parse_tree(json.dumps([{"name": "x"}]))


def test_ssh_dump_command_names_port_key_and_app():
    cmd = tree_dump.ssh_dump_command(2222, "/tmp/key", "installer")
    assert "-p" in cmd and "2222" in cmd and "/tmp/key" in cmd
    assert cmd[-1].endswith("dump installer")


def test_offline_lane_keeps_the_ssh_forward_but_drops_egress():
    assert "restrict=on" in run_e2e.build_netdev(2222, offline=True)
    assert "hostfwd" in run_e2e.build_netdev(2222, offline=True)
    assert "restrict=on" not in run_e2e.build_netdev(2222, offline=False)


def test_cdrom_lane_uses_media_cdrom_usb_lane_uses_usb_storage(tmp_path):
    cd = run_e2e.build_qemu_cmd("m.iso", "t.qcow2", tmp_path, 2222, "cdrom", "/code.fd")
    assert "-cdrom" in cd and "usb-storage" not in " ".join(cd)
    usb = run_e2e.build_qemu_cmd(
        "m.iso", "t.qcow2", tmp_path, 2222, "usb", "/code.fd", tpm_sock="/tmp/tpm.sock"
    )
    flat = " ".join(usb)
    assert "usb-storage" in flat and "tpm-crb" in flat
    with pytest.raises(ValueError):
        run_e2e.build_qemu_cmd("m.iso", "t.qcow2", tmp_path, 2222, "nvme", "/code.fd")


def test_bootc_digest_reads_the_booted_deployment():
    status = json.dumps(
        {
            "status": {
                "deployments": [
                    {"digest": "sha256:old", "booted": False},
                    {"digest": "sha256:new", "booted": True},
                ]
            }
        }
    )
    assert run_e2e.bootc_digest(status) == "sha256:new"
    with pytest.raises(DriverError):
        run_e2e.bootc_digest(json.dumps({"status": {"deployments": []}}))
    with pytest.raises(DriverError):
        run_e2e.bootc_digest("not json")


def test_plan_adds_live_file_assert_on_btrfs_and_todo_on_xfs():
    assert len(stages.stage_ids()) == 7
    btrfs = stages.plan_for_cell({"filesystem": "btrfs"})
    install = next(s for s in btrfs if s["id"] == "install")
    assert any("survives" in c for c in install["checks"])
    xfs = stages.plan_for_cell({"filesystem": "xfs"})
    setup = next(s for s in xfs if s["id"] == "first-boot-setup")
    assert any("TODO" in c for c in setup["checks"])
    plain = stages.plan_for_cell({"filesystem": "ext4"})
    assert plain == [dict(s, checks=list(s["checks"])) for s in stages.STAGES]


def test_mock_scenarios_cover_the_spec_list():
    assert set(fisherman_mock.SCENARIOS) >= {"happy-tpm", "rst-present", "requirements-uefi"}
    cmd = fisherman_mock.mock_command("happy-tpm")
    assert "--mock" in cmd and "happy-tpm" in " ".join(cmd)
    with pytest.raises(ValueError):
        fisherman_mock.mock_command("no-such-scenario")


def test_ocr_fallback_keys_and_readability_gate():
    assert ocr_fallback.keys_for("no-such-page") == ()
    assert ocr_fallback.keys_for("welcome")
    assert ocr_fallback.readable("Install TunaOS to the target disk now")
    assert not ocr_fallback.readable("xq zj 1t")
    assert ocr_fallback.ocr_text("/nonexistent-frame.png") == ""


def wait_nodes(pages):
    """A dump callable serving one node list per poll from `pages`."""
    state = {"i": 0}

    def dump(app):
        i = min(state["i"], len(pages) - 1)
        state["i"] += 1
        return pages[i]

    return dump


def test_driver_waits_for_the_wanted_page():
    waiting = [{"name": "Welcome", "role": "label", "states": ["showing"]}]
    disk = [{"name": "Install Location", "role": "heading", "states": ["showing"]}]
    clicks = []
    driver = Driver(wait_nodes([waiting, disk]), clicks.append, poll_interval=0)
    assert driver.wait_for("app", Page.DISK, timeout=5) is Page.DISK


def test_driver_raises_on_failure_before_done():
    failed = [{"name": "Installation failed", "role": "label", "states": ["showing"]}]
    driver = Driver(wait_nodes([failed]), lambda cmds: None, poll_interval=0)
    with pytest.raises(DriverError, match="failed"):
        driver.wait_for("app", Page.COMPLETE, timeout=5)


def test_driver_timeout_reports_the_stuck_page():
    waiting = [{"name": "Welcome", "role": "label", "states": ["showing"]}]
    shots = []
    driver = Driver(wait_nodes([waiting]), lambda cmds: None, shots.append, poll_interval=0)
    with pytest.raises(DriverError, match="timed out"):
        driver.wait_for("app", Page.DISK, timeout=0.01)
    assert shots == ["stuck"]


def test_matrix_lists_promoted_cells_with_input_paths():
    matrix_mod = load("matrix")
    assert matrix_mod.input_for("cosmic") == "ocr-fallback"
    assert matrix_mod.input_for("niri") == "ocr-fallback"
    assert matrix_mod.input_for("gnome") == "atspi"
    assert matrix_mod.input_for("kde") == "atspi"
    assert matrix_mod.input_for("xfce") == "atspi"
    proc = subprocess.run(
        [sys.executable, str(E2E / "matrix.py")],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0
    include = json.loads(proc.stdout)["include"]
    by_cell = {row["cell"]: row for row in include}
    assert by_cell["albacore:gnome"]["filesystem"] == "xfs"
    assert by_cell["albacore:gnome"]["input"] == "atspi"
    assert by_cell["tromso:kde"]["filesystem"] == "ext4"
    assert by_cell["tromso:kde"]["secure_boot"] == "tunaos-key"
    assert by_cell["tromso:kde"]["image"] == "ghcr.io/tuna-os/tromso:latest"
    assert all(":" not in row["tag"] for row in include)


def test_qemu_cmd_swaps_display_for_virgl_cells():
    with tempfile.TemporaryDirectory() as work:
        vga = run_e2e.build_qemu_cmd("m.iso", "t.qcow2", work, 2222, "cdrom", "/code.fd")
        assert "-vga" in vga and "virtio-vga-gl" not in " ".join(vga)
        gl = run_e2e.build_qemu_cmd("m.iso", "t.qcow2", work, 2222, "cdrom", "/code.fd", virgl=True)
        assert "virtio-vga-gl" in " ".join(gl) and "-vga" not in gl


def test_no_kvm_forces_tcg_even_when_kvm_is_usable(monkeypatch):
    monkeypatch.setattr(run_e2e.os, "access", lambda *_a: True)
    monkeypatch.setattr(run_e2e.Path, "exists", lambda _self: True)
    assert run_e2e.kvm_args() == ["-accel", "kvm", "-cpu", "host"]
    assert run_e2e.kvm_args(kvm=False) == ["-accel", "tcg", "-cpu", "max"]
    with tempfile.TemporaryDirectory() as work:
        cmd = run_e2e.build_qemu_cmd("m.iso", "t.qcow2", work, 2222, "cdrom", "/code.fd", kvm=False)
    assert cmd[cmd.index("-accel") + 1] == "tcg"


def test_matrix_marks_gpu_cells_for_the_virgl_path():
    matrix_mod = load("matrix")
    assert matrix_mod.gpu_for("cosmic") and matrix_mod.gpu_for("niri")
    assert not matrix_mod.gpu_for("gnome") and not matrix_mod.gpu_for("kde")


def test_compare_paths_writes_stages_and_notes_missing_baseline(tmp_path):
    compare = load("compare_paths")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "cdrom-stages.json").write_text(
        json.dumps({"boot": "cdrom", "code": 0, "stages": [{"id": "live-boot", "status": "pass"}]})
    )
    medium = tmp_path / "medium.iso"
    medium.write_bytes(b"0" * 64)
    summary = tmp_path / "summary.md"
    out = tmp_path / "comparison.json"
    assert (
        compare.main(
            [
                "--evidence",
                str(evidence),
                "--medium",
                str(medium),
                "--out",
                str(out),
                "--summary",
                str(summary),
            ]
        )
        == 0
    )
    data = json.loads(out.read_text())
    assert data["medium_bytes"] == 64
    assert data["stages"]["cdrom"][0]["status"] == "pass"
    assert data["baseline"] is None
    assert "baseline: none found" in summary.read_text()


def test_driver_names_the_missing_control():
    driver = Driver(wait_nodes([[]]), lambda cmds: None, poll_interval=0)
    with pytest.raises(DriverError, match="no sensitive"):
        driver.click_named("app", "Install", role="push button")


def test_recovery_key_value_returns_the_key_or_none():
    nodes = json.loads((ROOT / "tests/fixtures/installer-e2e/recovery-key-page.json").read_text())
    driver = Driver(wait_nodes([nodes]), lambda cmds: None, poll_interval=0)
    assert driver.recovery_key_value("app").count("-") == 7
    empty = Driver(wait_nodes([[]]), lambda cmds: None, poll_interval=0)
    assert empty.recovery_key_value("app") is None


def test_dry_run_lists_both_boots_and_touches_nothing(tmp_path):
    work = tmp_path / "e2e-out"
    proc = subprocess.run(
        [
            sys.executable,
            str(E2E / "run_e2e.py"),
            "--dry-run",
            "--cell",
            "tromso:kde",
            "--medium",
            "medium.iso",
            "--work",
            str(work),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0
    assert "boot cdrom" in proc.stdout and "boot usb" in proc.stdout
    assert "stage switch-rollback" in proc.stdout
    assert not work.exists()


def test_dry_run_reports_lifecycle_digests(tmp_path, capsys):
    rc = run_e2e.main(
        [
            "--dry-run",
            "--cell",
            "tromso:kde",
            "--medium",
            "medium.iso",
            "--work",
            str(tmp_path / "out"),
            "--baseline",
            "sha256:base",
            "--candidate",
            "sha256:cand",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "baseline=sha256:base candidate=sha256:cand" in out


def test_ocr_text_classifier_fails_before_done():
    assert ocr_fallback.classify_text("Installation failed on vda") is Page.FAILURE
    assert ocr_fallback.classify_text("Restart System now") is Page.COMPLETE
    assert ocr_fallback.classify_text("show your Recovery Key below") is Page.RECOVERY_KEY
    assert ocr_fallback.classify_text("Installing files to vda") is Page.PROGRESS
    assert ocr_fallback.classify_text("") is Page.WAIT


def test_snapshot_names_the_insensitive_control():
    nodes = [
        {"name": "Install", "role": "push button", "states": ["showing"]},
        {"name": "tip", "role": "label", "states": ["showing", "sensitive"]},
    ]
    lines = tree_dump.summarize(nodes)
    assert any("Install" in line and "sensitive=False" in line for line in lines)
    assert atspi_match.is_showing(nodes[0])
    assert not atspi_match.is_sensitive(nodes[0])
    assert atspi_match.is_sensitive(nodes[1])


def test_no_atspi_dry_run_selects_the_ocr_path(tmp_path, capsys):
    rc = run_e2e.main(
        [
            "--dry-run",
            "--no-atspi",
            "--cell",
            "tromso:kde",
            "--medium",
            "medium.iso",
            "--work",
            str(tmp_path / "out"),
        ]
    )
    assert rc == 0
    assert "input=ocr-fallback" in capsys.readouterr().out


def test_atspi_dry_run_selects_the_matcher_path(tmp_path, capsys):
    rc = run_e2e.main(
        [
            "--dry-run",
            "--cell",
            "tromso:kde",
            "--medium",
            "medium.iso",
            "--work",
            str(tmp_path / "out"),
        ]
    )
    assert rc == 0
    assert "input=atspi" in capsys.readouterr().out


def test_dry_run_marks_the_el10_soft_reboot_todo(tmp_path):
    proc = subprocess.run(
        [
            sys.executable,
            str(E2E / "run_e2e.py"),
            "--dry-run",
            "--cell",
            "albacore:gnome",
            "--filesystem",
            "xfs",
            "--medium",
            "medium.iso",
            "--work",
            str(tmp_path / "out"),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0
    assert "TODO(#4908/#4909)" in proc.stdout


def test_list_stages_prints_all_seven():
    proc = subprocess.run(
        [sys.executable, str(E2E / "run_e2e.py"), "--list-stages"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0
    assert proc.stdout.split() == stages.stage_ids()


def test_ssh_access_comes_from_smbios_credentials_not_from_the_medium():
    """The medium ships no key: the harness passes it as system credentials."""
    import base64

    args = run_e2e.ssh_access_args("ssh-ed25519 AAAAC3Nza e2e\n")
    assert args[0::2] == ["-smbios"] * 3
    decoded = {}
    for value in args[1::2]:
        head, _, body = value.partition("=io.systemd.credential.binary:")
        assert head == "type=11,value"
        name, _, payload = body.partition("=")
        decoded[name] = base64.b64decode(payload).decode()
    assert "ssh-ed25519 AAAAC3Nza e2e" in decoded["tmpfiles.extra"]
    assert "AuthorizedKeysFile /etc/ssh/installer-e2e_authorized_keys" in decoded["tmpfiles.extra"]
    assert "Wants=sshd.service" in decoded["systemd.unit-dropin.multi-user.target"]
    assert decoded["ssh.ephemeral-authorized_keys-all"] == "ssh-ed25519 AAAAC3Nza e2e\n"
    with pytest.raises(run_e2e.DriverError):
        run_e2e.ssh_access_args("a\nb")


def test_firmware_is_two_pflash_drives_not_a_bios_file(tmp_path):
    """`-bios OVMF_CODE_4M.fd` cannot load (run 45557106112)."""
    cmd = run_e2e.build_qemu_cmd(
        "m.iso", "t.qcow2", tmp_path, 2222, "cdrom", "/code.fd", ovmf_vars="/work/vars.fd"
    )
    flat = " ".join(cmd)
    assert "-bios" not in cmd
    assert "if=pflash,format=raw,unit=0,readonly=on,file=/code.fd" in flat
    assert "if=pflash,format=raw,unit=1,file=/work/vars.fd" in flat


def test_a_dead_qemu_fails_the_ssh_wait_at_once():
    class Dead:
        returncode = 1

        def poll(self):
            return 1

    with pytest.raises(DriverError, match="QEMU exited with status 1"):
        run_e2e.wait_ssh(2222, "/nokey", timeout=600, vm=Dead())


def test_only_the_target_disk_without_the_live_karg_is_the_installed_system():
    """`bootc status` also answers in the live session: stage 6 needs proof."""
    live = "BOOT_IMAGE=/x root=UUID=1 ro tunaos.live\n/dev/sr0p2\n"
    assert not run_e2e.is_installed_system(live)
    # No live karg, but the root is the USB medium: still not the target.
    assert not run_e2e.is_installed_system("BOOT_IMAGE=/x root=UUID=1 rw\n/dev/sda2\n")
    assert run_e2e.is_installed_system("BOOT_IMAGE=/x root=UUID=1 rw\n/dev/vda3\n")
    assert run_e2e.is_installed_system("BOOT_IMAGE=/x rd.luks.uuid=2 rw\n/dev/mapper/luks-2\n")
    assert not run_e2e.is_installed_system("")


def test_walk_to_disk_clicks_through_the_pages_before_the_disk_page():
    button = {"name": "Next", "role": "button", "states": ["showing", "sensitive"], "path": "0",
              "ext": [10, 10, 80, 30], "text": ""}
    pages = [
        [dict(button), {"name": "Welcome", "role": "label", "states": ["showing"], "path": "1"}],
        [dict(button), {"name": "Keyboard", "role": "label", "states": ["showing"], "path": "1"}],
        [{"name": "Install Location", "role": "label", "states": ["showing"], "path": "1"}],
    ]
    state = {"at": 0}
    clicks = []

    def dump(_app):
        return pages[min(state["at"], len(pages) - 1)]

    def click(*commands):
        clicks.append(commands)
        state["at"] += 1

    drv = driver_mod.Driver(dump, click, poll_interval=0)
    assert run_e2e.walk_to_disk(drv, "setup", lambda _name: None, timeout=30) == 2


def test_resolve_app_falls_back_from_the_application_id_to_the_program_name():
    def dump(name):
        return [{"name": "x"}] if name == "setup" else []

    assert run_e2e.resolve_app(dump, "org.gnome.Nope", attempts=1, pause=0) == "setup"


def test_a_press_function_replaces_the_pointer_click():
    """Wayland gives no screen coordinates: extents [0, 0, 42, 42] for the
    Next button on the first real run (45594835162)."""
    node = {"name": "Next", "role": "button", "states": ["showing", "sensitive"], "path": "0.3.1",
            "ext": [0, 0, 42, 42], "text": ""}
    pressed, clicked = [], []
    drv = driver_mod.Driver(lambda _a: [node], clicked.append, press=lambda app, n: pressed.append((app, n["path"])))
    drv.click_primary("setup")
    assert pressed == [("setup", "0.3.1")] and clicked == []


def test_press_command_takes_only_a_node_path():
    cmd = tree_dump.ssh_press_command(2222, "/tmp/key", "setup", "0.3.1")
    assert cmd[-1].endswith("python3 - press setup 0.3.1")
    with pytest.raises(ValueError):
        tree_dump.ssh_press_command(2222, "/tmp/key", "setup", "0; reboot")


def test_walk_install_picks_the_disk_row_then_confirms():
    def node(name, role, path):
        return {"name": name, "role": role, "states": ["showing", "sensitive"], "path": path, "text": ""}

    pages = [
        [node("Select a Disk", "label", "0.1"), node("QEMU HARDDISK 64 GB", "list item", "0.2")],
        [node("Select a Disk", "label", "0.1"), node("Use Entire Disk", "button", "0.3")],
        [node("Begin Installation?", "label", "0.1"), node("Cancel", "button", "0.4"),
         node("Erase and Install", "button", "0.5")],
        [node("Installing Albacore", "label", "0.1")],
    ]
    state = {"at": 0}
    pressed = []

    def press(_app, n):
        pressed.append(n["name"])
        state["at"] += 1

    drv = driver_mod.Driver(lambda _a: pages[min(state["at"], 3)], lambda _c: None, poll_interval=0, press=press)
    assert run_e2e.walk_install(drv, "setup", lambda _n: None, timeout=60) == 3
    assert pressed == ["QEMU HARDDISK 64 GB", "Use Entire Disk", "Erase and Install"]


def _node(name, role="label", states=("showing", "sensitive"), path="0.0"):
    return {"name": name, "role": role, "states": list(states), "text": "", "path": path, "ext": None}


def test_the_native_walk_chooses_the_disk_and_fills_the_account():
    """A native frontend: the walk records the disk page and stops at the install."""
    from atspi_match import classify_native
    from driver import Driver

    state = {"page": 0, "disk": False, "text": {}}

    def dump(_app):
        step = ["Welcome", "Target Disk", "User Account", "Confirm Installation", "Installing"]
        nodes = [_node(f"Step {state['page'] + 1} of 5 \u00b7 {step[state['page']]}")]
        if state["page"] == 1:
            states = ["showing", "sensitive"] + (["checked"] if state["disk"] else [])
            nodes.append(_node("QEMU disk /dev/vda", "radio button", states, "0.1"))
        if state["page"] == 2:
            nodes.append(_node("Username", "text", path="0.2"))
        ready = {1: state["disk"], 2: bool(state["text"])}.get(state["page"], True)
        name = "Install" if state["page"] == 3 else "Next"
        nodes.append(_node(name, "push button", ["showing"] + (["sensitive"] if ready else []), "0.9"))
        return nodes

    def press(_app, node):
        if node["role"] == "push button":
            state["page"] += 1

    def act(_app, verb, node, *words):
        if verb == "settext":
            state["text"][node["name"]] = words[0]

    def keys(*_names):
        state["disk"] = True

    driver = Driver(dump, None, poll_interval=0, press=press, classify=classify_native)
    seen = []
    run_e2e.time.sleep, sleep = (lambda _s: None), run_e2e.time.sleep
    try:
        run_e2e.walk_native(driver, "org.tunaos.InstallerKde", lambda _n: None, act, keys, seen.append)
    finally:
        run_e2e.time.sleep = sleep
    assert state["page"] == 4
    assert any("/dev/vda" in n["name"] for n in seen[0])
    assert state["text"] == {"Username": run_e2e.E2E_USER}


def test_a_hidden_step_of_a_qt_tree_does_not_name_the_page():
    from atspi_match import Page, classify_native

    hidden = _node("Installation failed", states=())
    assert classify_native([hidden, _node("Step 2 of 5 \u00b7 Target Disk")]) is Page.DISK
    assert classify_native([_node("Installation failed")]) is Page.FAILURE


def test_the_stamp_of_a_sandboxed_frontend_is_found():
    """Flatpak keeps $XDG_RUNTIME_DIR of the sandbox in .flatpak/APP/xdg-run."""
    assert ".flatpak/*/xdg-run/tuna-installer-ready" in run_e2e.STAMP_LOOKUP
    assert "app/*/tuna-installer-ready" in run_e2e.STAMP_LOOKUP


def test_the_installed_system_boots_without_the_medium(tmp_path):
    """With the medium attached the firmware can start the live system again."""
    cmd = run_e2e.build_qemu_cmd(
        "m.iso", "t.qcow2", tmp_path, 2222, "disk", "/code.fd", serial="serial-usb-installed.log"
    )
    assert "m.iso" not in " ".join(cmd)
    assert any(c.endswith("serial-usb-installed.log") for c in cmd)
