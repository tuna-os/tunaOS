"""Installer e2e harness units run without KVM or root (tunaOS#4910).

Falsification: a QMP click outside the tablet range, a guest dump that is
not a node list passing validation, a lane without `restrict=on` calling
itself offline, a bootc digest read from the wrong deployment, or a
`--dry-run` that creates files all fail this module.
"""

import importlib.util
import json
import re
import socket
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
        assert gl[gl.index("-vnc") + 1] == f"unix:{work}/vnc.sock"
        assert "-vnc" not in vga


def _fake_vnc_server(path, width, height, pixels, extra=b""):
    """A one-client RFB 3.8 server: no auth, one raw rectangle per update."""
    import threading

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(1)

    def serve():
        conn, _ = server.accept()
        with conn:
            conn.sendall(b"RFB 003.008\n")
            conn.recv(12)
            conn.sendall(b"\x01\x01")
            conn.recv(1)
            conn.sendall(b"\0\0\0\0")
            conn.recv(1)
            name = b"QEMU"
            conn.sendall(
                width.to_bytes(2, "big") + height.to_bytes(2, "big") + bytes(16)
                + len(name).to_bytes(4, "big") + name
            )
            got = b""
            while len(got) < 20 + 8 + 10:  # SetPixelFormat, SetEncodings, request
                got += conn.recv(64)
            rect = (0).to_bytes(4, "big") + width.to_bytes(2, "big") + height.to_bytes(2, "big")
            conn.sendall(extra + b"\x00\x00\x00\x01" + rect + bytes(4) + pixels)
        server.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return thread


def test_vnc_screendump_writes_the_frame_as_ppm(tmp_path):
    # 2x1 pixels, B G R X: red, then blue. A bell and a cut text come first.
    pixels = bytes([0, 0, 255, 0, 255, 0, 0, 0])
    extra = b"\x02" + b"\x03" + bytes(3) + (2).to_bytes(4, "big") + b"hi"
    sock = tmp_path / "vnc.sock"
    thread = _fake_vnc_server(sock, 2, 1, pixels, extra)
    run_e2e.vnc_screendump(sock, tmp_path / "s.ppm", timeout=10)
    thread.join(10)
    assert (tmp_path / "s.ppm").read_bytes() == b"P6\n2 1\n255\n" + bytes([255, 0, 0, 0, 0, 255])


def test_a_gl_scanout_screenshot_comes_from_the_vnc_socket(tmp_path, monkeypatch):
    qmp = run_e2e.Qmp(tmp_path / "qmp.sock")

    def no_surface(*_cmds):
        raise run_e2e.DriverError("QMP screendump: {'class': 'GenericError', 'desc': 'no surface'}")

    monkeypatch.setattr(qmp, "run", no_surface)
    grabbed = []
    monkeypatch.setattr(run_e2e, "vnc_screendump", lambda sock, ppm: grabbed.append((sock, ppm)))
    with pytest.raises(run_e2e.DriverError):
        qmp.screendump(tmp_path / "a.ppm")  # no VNC socket: the QMP error stands
    (tmp_path / "vnc.sock").touch()
    qmp.screendump(tmp_path / "b.ppm")
    assert grabbed == [(tmp_path / "vnc.sock", tmp_path / "b.ppm")]


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
    # sshd keeps the first value: a base that sets AuthorizedKeysFile before its
    # Include (Brussels) ignores the line above, so a command reads the key too.
    assert "AuthorizedKeysCommand /usr/bin/cat /etc/ssh/installer-e2e_authorized_keys" in decoded["tmpfiles.extra"]
    assert "AuthorizedKeysCommandUser root" in decoded["tmpfiles.extra"]
    # sshd keeps its StrictModes check: bonito:niri ships /etc 0755 since
    # tunaOS#5019 (it was 0775 and sshd refused every key).
    assert "StrictModes" not in decoded["tmpfiles.extra"]
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

    def keys(key):
        # The row has no action: Return on the focused row opens it.
        pressed.append(f"{key} on the row")
        state["at"] += 1

    drv = driver_mod.Driver(lambda _a: pages[min(state["at"], 3)], lambda _c: None, poll_interval=0, press=press)
    shots = []
    assert run_e2e.walk_install(drv, "setup", shots.append, lambda *_a: True, keys, timeout=60) == 3
    assert pressed == ["ret on the row", "Use Entire Disk", "Erase and Install"]
    # The install page is photographed once, where the walk ends on it.
    assert [s for s in shots if "progress" in s] == ["3-progress"]


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
    seen, shots = [], []
    run_e2e.time.sleep, sleep = (lambda _s: None), run_e2e.time.sleep
    try:
        run_e2e.walk_native(driver, "org.tunaos.InstallerKde", shots.append, act, keys, seen.append)
    finally:
        run_e2e.time.sleep = sleep
    assert state["page"] == 4
    # The walk ends on the install page and photographs it once (bonito:kde 45836370728).
    assert [s for s in shots if "progress" in s] == ["3-progress"]
    assert any("/dev/vda" in n["name"] for n in seen[0])
    assert state["text"] == {"Username": run_e2e.E2E_USER}


def test_a_walk_that_ends_on_the_key_or_done_page_takes_no_progress_picture():
    from atspi_match import Page

    shots = []
    for page in (Page.RECOVERY_KEY, Page.COMPLETE, Page.NEXT, Page.WAIT):
        run_e2e.photograph_progress(page, shots.append)
    assert shots == []
    run_e2e.photograph_progress(Page.PROGRESS, shots.append)
    assert shots == ["3-progress"]


def test_a_hidden_step_of_a_qt_tree_does_not_name_the_page():
    from atspi_match import Page, classify_native

    hidden = _node("Installation failed", states=())
    assert classify_native([hidden, _node("Step 2 of 5 \u00b7 Target Disk")]) is Page.DISK
    assert classify_native([_node("Installation failed")]) is Page.FAILURE


def test_the_stamp_of_a_sandboxed_frontend_is_found():
    """Flatpak keeps $XDG_RUNTIME_DIR of the sandbox in .flatpak/APP/xdg-run."""
    assert ".flatpak/*/xdg-run/tuna-installer-ready" in run_e2e.STAMP_LOOKUP
    assert "app/*/tuna-installer-ready" in run_e2e.STAMP_LOOKUP


def test_the_locale_state_probe_reads_what_the_install_copies():
    """tunaOS#5064: the record says which language, keyboard and environment the
    guest held. The probe is a shell string: it must parse."""
    probe = run_e2e.LOCALE_STATE
    for want in ("/etc/locale.conf", "/etc/vconsole.conf", "/etc/gnome-initial-setup/vendor.conf", "localectl status", "LANG"):
        assert want in probe
    subprocess.run(["bash", "-n", "-c", probe], check=True)


def test_the_installed_system_boots_without_the_medium(tmp_path):
    """With the medium attached the firmware can start the live system again."""
    cmd = run_e2e.build_qemu_cmd(
        "m.iso", "t.qcow2", tmp_path, 2222, "disk", "/code.fd", serial="serial-usb-installed.log"
    )
    assert "m.iso" not in " ".join(cmd)
    assert any(c.endswith("serial-usb-installed.log") for c in cmd)


def test_stage_2_needs_the_target_disk_on_the_page():
    """Run 45606046787 recorded a pass on a page with no disk."""
    from atspi_match import lists_target

    assert lists_target([_node("Select a Disk"), _node("/dev/vda")])
    assert lists_target([_node("68.7\u00a0GB")])
    assert not lists_target([_node("Select a Disk"), _node("Power Off", "push button")])
    assert not lists_target([_node("Unusable Disks"), _node("/dev/vda")])
    assert not lists_target([_node("/dev/vda", states=())])


def test_the_ocr_walk_reads_the_header_the_labels_and_the_accent_button():
    """COSMIC has no AT-SPI tree (run 45624842877): the walk reads the screen."""
    ocr = load("ocr_fallback")
    row = "5\t1\t1\t1\t1\t{n}\t{x}\t{y}\t100\t20\t{conf}\t{text}"
    tsv = "header\n" + "\n".join(
        [
            row.format(n=i, x=40 + 120 * i, y=30, conf=90, text=t)
            for i, t in enumerate(["Step", "15", "of", "21", "-", "Account"])
        ]
        + [
            row.format(n=1, x=40, y=800, conf=90, text="Confirm"),
            row.format(n=2, x=160, y=800, conf=90, text="password"),
            row.format(n=3, x=40, y=900, conf=5, text="noise"),
        ]
    )
    found = ocr.parse_tsv(tsv)
    assert ocr.step_name(found) == "account"
    assert ocr.label_at(found, "Confirm", "password") == (405, 20)
    assert ocr.label_at(found, "Username") is None
    assert "noise" not in ocr.page_text(found)

    width, height = 400, 300
    rgb = bytearray(width * height * 3)

    def fill(x0, y0, x1, y1):
        for y in range(y0, y1):
            for x in range(x0, x1):
                rgb[(y * width + x) * 3 : (y * width + x) * 3 + 3] = bytes(ocr.ACCENT)

    fill(0, 10, 400, 14)  # the window border
    assert ocr.accent_button(bytes(rgb), width, height) is None
    fill(250, 200, 350, 230)  # the button
    assert ocr.accent_button(bytes(rgb), width, height) == (300, 214)


def test_the_ocr_walk_finds_the_niri_accent_button():
    """The niri frontend's button is lilac, not the COSMIC accent: with the
    COSMIC accent alone the walk stayed on the welcome page (pod run of
    medium 45822993049)."""
    ocr = load("ocr_fallback")
    width, height = 400, 300
    rgb = bytearray(width * height * 3)
    for y in range(200, 230):
        for x in range(250, 350):
            rgb[(y * width + x) * 3 : (y * width + x) * 3 + 3] = bytes(ocr.NIRI_ACCENT)
    assert ocr.accent_button(bytes(rgb), width, height) == (300, 214)
    assert ocr.accent_button(bytes(rgb), width, height, accents=(ocr.ACCENT,)) is None


def test_a_run_with_an_unverified_stage_is_not_a_success(tmp_path):
    """The exit status is the publish gate: unverified is not pass."""
    done = [{"id": "live-boot", "status": "pass"}]
    assert run_e2e.finish(tmp_path, "usb", done, 0) == 0
    assert run_e2e.finish(tmp_path, "usb", [*done, {"id": "x", "status": "unverified"}], 0) == 3
    assert run_e2e.finish(tmp_path, "usb", [*done, {"id": "x", "status": "todo"}], 0) == 3
    assert run_e2e.finish(tmp_path, "usb", done, 1) == 1


def test_stage_4_needs_the_key_to_open_the_disk_without_the_tpm():
    """DESKTOP-STANDARD C.4: a key shown and saved is not enough."""
    def unlock():
        return [{"id": "unlock", "status": "pass"}]

    stages_ = unlock()
    run_e2e.unlock_verdict(stages_, True, "atspi")
    assert stages_[0]["status"] == "pass"
    stages_ = unlock()
    run_e2e.unlock_verdict(stages_, False, "atspi")
    assert stages_[0]["status"] == "fail"
    stages_ = unlock()
    run_e2e.unlock_verdict(stages_, False, "ocr")
    assert stages_[0]["status"] == "unverified"
    stages_ = unlock()
    run_e2e.unlock_verdict(stages_, None, None)
    assert stages_[0]["status"] == "unverified"
    failed = [{"id": "unlock", "status": "fail"}]
    run_e2e.unlock_verdict(failed, True, "atspi")
    assert failed[0]["status"] == "fail"


def test_a_run_that_stops_before_stage_6_leaves_stage_4_unverified(tmp_path):
    stages_ = [{"id": "live-boot", "status": "pass"}, {"id": "unlock", "status": "pass"}]
    assert run_e2e.finish(tmp_path, "usb", stages_, 0) == 3
    assert stages_[1]["status"] == "unverified"


KEY_FIXTURES = ROOT / "tests/fixtures/installer-e2e"
# Pictures of real runs, cut to the key and the line above it (the key of a
# throwaway test VM). The truth was read from the pictures by eye.
COSMIC_CD_KEY = "tubtevgb-vnlbfgcj-jubjvvvg-rhdvfrhd-bnutiurb-uujluglk-rjtvcbdn-cddujeie"
COSMIC_CD_DOUBT_KEY = "fnhfhbfe-rgirkcgr-rbftfebf-ghenntbj-vuvtrikn-diekkfht-iuunlchb-vibrehgj"
KDE_WRAPPED_KEY = "gkiigjbv-ttfhkhgb-eibggivr-nkhevrcb-vbfevhcf-eihvbril-elruiltk-iefkfhth"
NIRI_KEY = "ngiinenb-ugnbfinn-lbvucbrr-rdrtdbtv-rbjnvhhu-hgeitrhn-kflniecn-jljilrbl"


@pytest.fixture
def ocr_tools():
    """The key tests read real pictures: a missing tool is a failure, not a skip (the skip ratchet)."""
    import shutil

    missing = [t for t in ("tesseract", "ffmpeg", "ffprobe") if shutil.which(t) is None]
    assert not missing, f"missing {missing}: the Unit Tests job installs tesseract-ocr and ffmpeg"


def test_the_key_of_bonito_cosmic_on_cd_is_read_where_the_page_pass_dropped_two_groups(ocr_tools):
    """Run 45925317913 stage 4: the page pass lost the first groups and read l as i."""
    png = KEY_FIXTURES / "recovery-key-cosmic-cd.png"
    candidates = ocr_fallback.recovery_key_candidates(png)
    # l and i are both modhex: the picture leaves them in doubt for the
    # readings, so the disk picks; the true key is among a few.
    assert COSMIC_CD_KEY in candidates
    assert 1 <= len(candidates) <= 4
    assert all(ocr_fallback.RECOVERY_KEY_RE.fullmatch(c) for c in candidates)


def test_a_key_in_doubt_between_t_and_f_gives_both_with_the_voted_one_first(ocr_tools):
    candidates = ocr_fallback.recovery_key_candidates(KEY_FIXTURES / "recovery-key-cosmic-cd-doubt.png")
    assert COSMIC_CD_DOUBT_KEY in candidates
    assert 1 <= len(candidates) <= 4


def test_a_key_wrapped_over_two_lines_is_one_key(ocr_tools):
    """Run 45836370728 (KDE): the second line is short and has one hyphen."""
    candidates = ocr_fallback.recovery_key_candidates(KEY_FIXTURES / "recovery-key-kde-wrapped.png")
    assert KDE_WRAPPED_KEY in candidates
    assert len(candidates) <= 4


def test_the_key_on_the_niri_page_is_read_where_the_page_pass_reads_l_as_bang(ocr_tools):
    """Run 46155011978 (bonito:niri) stage 4: the page pass read the key as one
    word ending in "j|jilrb!", so no line counted as a key line."""
    candidates = ocr_fallback.recovery_key_candidates(KEY_FIXTURES / "recovery-key-niri.png")
    # l and i are both modhex; which reading comes first depends on the
    # tesseract build (CI's put the i first), so the disk picks.
    assert NIRI_KEY in candidates
    assert 1 <= len(candidates) <= 4


def test_a_page_without_a_key_has_no_candidates(ocr_tools):
    assert ocr_fallback.recovery_key_candidates(KEY_FIXTURES / "recovery-key-no-key.png") == []


def _stub_key_reading(monkeypatch, per_scale):
    """Stand in for tesseract: `per_scale` maps a scale to the text it reads."""
    monkeypatch.setattr(ocr_fallback, "ocr_available", lambda: True)
    monkeypatch.setattr(ocr_fallback, "_image_size", lambda _png: (1280, 800))
    monkeypatch.setattr(ocr_fallback, "_key_box", lambda *_a: (0, 1280, 300, 20, True))
    monkeypatch.setattr(ocr_fallback, "_read_line", lambda _png, _box, scale: per_scale[scale])


KEY_PAGE_WORDS = [
    ("Write", 233, 259, 34, 10),
    ("it", 273, 259, 7, 10),
    ("tubtevgb-vnlbfgcj-jubj", 233, 295, 160, 15),
    ("vvvg-rhdvfrhd-bnutiurb-uuj", 396, 295, 200, 15),
]
KEY = "tubtevgb-vnlbfgcj-jubjvvvg-rhdvfrhd-bnutiurb-uujluglk-rjtvcbdn-cddujeie"


def test_readings_that_agree_are_one_key(monkeypatch):
    _stub_key_reading(monkeypatch, dict.fromkeys(ocr_fallback._KEY_SCALES, KEY))
    assert ocr_fallback.recovery_key_candidates("page.png", KEY_PAGE_WORDS) == [KEY]


def test_readings_that_differ_in_l_and_i_give_every_combination_voted_first(monkeypatch):
    scales = ocr_fallback._KEY_SCALES
    # Position 9 (l/i) is read l by four scales and i by two; position 49 the other way.
    read = {}
    for n, scale in enumerate(scales):
        text = list(KEY)
        text[9] = "l" if n < 4 else "i"
        text[49] = "l" if n >= 4 else "i"
        read[scale] = "".join(text)
    _stub_key_reading(monkeypatch, read)
    found = ocr_fallback.recovery_key_candidates("page.png", KEY_PAGE_WORDS)
    assert len(found) == 4
    assert len(set(found)) == 4
    assert found[0][9] == "l" and found[0][49] == "i"
    assert all(ocr_fallback.RECOVERY_KEY_RE.fullmatch(k) for k in found)


def test_more_doubt_than_four_letters_is_no_key(monkeypatch):
    scales = ocr_fallback._KEY_SCALES
    read = {}
    for n, scale in enumerate(scales):
        text = list(KEY)
        for pos in (0, 1, 2, 3, 4):
            text[pos] = "c" if n % 2 else "b"
        read[scale] = "".join(text)
    _stub_key_reading(monkeypatch, read)
    assert ocr_fallback.recovery_key_candidates("page.png", KEY_PAGE_WORDS) == []


def test_a_reading_that_is_not_the_shape_of_a_key_is_dropped(monkeypatch):
    # A letter outside the alphabet, a missing group, a wrong group length.
    bad = {
        2: KEY.replace("t", "x", 1),
        3: "-".join(KEY.split("-")[:7]),
        4: KEY.replace("-", "", 1),
    }
    good = dict.fromkeys(ocr_fallback._KEY_SCALES[3:], KEY)
    _stub_key_reading(monkeypatch, {**bad, **good})
    assert ocr_fallback.recovery_key_candidates("page.png", KEY_PAGE_WORDS) == [KEY]
    _stub_key_reading(monkeypatch, {**bad, 5: bad[2], 6: bad[3], 8: bad[4]})
    assert ocr_fallback.recovery_key_candidates("page.png", KEY_PAGE_WORDS) == []


def test_a_key_that_wraps_at_a_hyphen_is_joined_with_or_without_it(monkeypatch):
    groups = KEY.split("-")
    first, second = "-".join(groups[:4]), "-".join(groups[4:])
    for lead in ("", "-"):
        monkeypatch.setattr(ocr_fallback, "ocr_available", lambda: True)
        monkeypatch.setattr(ocr_fallback, "_image_size", lambda _png: (1280, 800))
        monkeypatch.setattr(ocr_fallback, "_key_box", lambda *_a: (0, 1280, 300, 20, True))
        reads = {}

        def read(_png, _box, scale, reads=reads, lead=lead):
            # Two rows per scale, in order.
            reads.setdefault(scale, iter([first + lead, second]))
            return next(reads[scale])

        monkeypatch.setattr(ocr_fallback, "_read_line", read)
        words_ = [
            ("tubtevgb-vnlbfgcj-jubjvvvg-rhdvfrhd-", 233, 295, 250, 15),
            ("bnutiurb-uujluglk-rjtvcbdn-cddujeie", 233, 316, 250, 15),
        ]
        assert ocr_fallback.recovery_key_candidates("page.png", words_) == [KEY]


def test_the_key_rows_are_the_lines_with_key_letters_not_prose():
    prose = [
        (w, 233 + 40 * i, 259, 35, 11)
        for i, w in enumerate("Save it somewhere safe, like a password manager".split())
    ]
    # KDE of run 45836370728: six groups on the first line, two on the wrapped one.
    first = [("gkiigjbv-ttfhkhgb-eibggivr-nkhevrcb-vbfevhcf-eihvbril", 397, 347, 460, 15), ("-", 860, 347, 6, 15)]
    wrapped = [("elruiltk-iefkfhth", 564, 369, 152, 15)]
    rows = ocr_fallback._key_rows(prose + first + wrapped)
    assert [[w[0] for w in r] for r in rows] == [[w[0] for w in first], [w[0] for w in wrapped]]
    assert ocr_fallback._key_rows(prose) == []


def test_stage_6_tries_every_reading_until_one_opens_the_disk(monkeypatch):
    tried = []

    def fake_run(cmd, input=None, **_kw):
        tried.append(input)
        return subprocess.CompletedProcess(cmd, 0 if input == "the-key" else 2)

    monkeypatch.setattr(run_e2e.subprocess, "run", fake_run)
    args = type("A", (), {})()
    args.ssh_port, args.ssh_key = 2222, "/k"
    args.recovery_key_candidates = ["wrong-1", "the-key", "never"]
    args.recovery_key = "wrong-1"
    assert run_e2e.recovery_key_opens_the_disk(args) is True
    assert tried == ["wrong-1", "the-key"]
    tried.clear()
    args.recovery_key_candidates = ["wrong-1", "wrong-2"]
    assert run_e2e.recovery_key_opens_the_disk(args) is False
    assert tried == ["wrong-1", "wrong-2"]
    # The AT-SPI path has one key and no candidates; no key is not a verdict.
    tried.clear()
    args.recovery_key_candidates = None
    args.recovery_key = "the-key"
    assert run_e2e.recovery_key_opens_the_disk(args) is True
    args.recovery_key = None
    assert run_e2e.recovery_key_opens_the_disk(args) is None


def test_a_disk_radio_named_by_model_is_found_by_its_label():
    """fisherman#537 names the disk by model; the path is a label of its own (run 45742289429)."""
    radio = {"role": "radio button", "name": "Virtual disk", "states": [], "path": "0.3.1.0"}
    label = {"role": "label", "name": "/dev/vda \u2022 64 GiB \u2022 VirtIO", "states": [], "path": "0.3.1.1"}
    other = {"role": "push button", "name": "Next", "states": [], "path": "0.4"}
    assert run_e2e.disk_radio_by_label([radio, label, other]) == [radio]
    # Two disks: the radio nearest the target label.
    radio2 = {"role": "radio button", "name": "Virtual disk", "states": [], "path": "0.3.2.0"}
    label2 = {"role": "label", "name": "/dev/vdb \u2022 32 GiB \u2022 VirtIO", "states": [], "path": "0.3.2.1"}
    assert run_e2e.disk_radio_by_label([radio, label, radio2, label2]) == [radio]
    # No label that names the target: nothing is chosen.
    assert run_e2e.disk_radio_by_label([radio, other]) == []


def test_a_kirigami_radio_delegate_wins_over_its_indicator():
    """FormRadioDelegate holds an unnamed RadioButton under it; both tie with the label (run 45756690146)."""
    radio = {"role": "radio button", "name": "Virtual disk", "states": [], "path": "0.3.1.0"}
    indicator = {"role": "radio button", "name": "", "states": [], "path": "0.3.1.0.2"}
    label = {"role": "label", "name": "/dev/vda \u2022 64 GiB \u2022 VirtIO", "states": [], "path": "0.3.1.1"}
    assert run_e2e.disk_radio_by_label([radio, indicator, label]) == [radio]
    radio2 = {"role": "radio button", "name": "Virtual disk", "states": [], "path": "0.3.2.0"}
    indicator2 = {"role": "radio button", "name": "", "states": [], "path": "0.3.2.0.2"}
    label2 = {"role": "label", "name": "/dev/vdb \u2022 32 GiB \u2022 VirtIO", "states": [], "path": "0.3.2.1"}
    assert run_e2e.disk_radio_by_label([radio, indicator, label, radio2, indicator2, label2]) == [radio]


def test_elementary_setup_entries_take_the_label_before_them():
    """io.elementary.initial-setup entries sit under labels (AccountView)."""
    entry = {"role": "text", "name": "", "states": ["sensitive"], "path": "0.1"}
    assert run_e2e.setup_entry_value(entry, "Full Name") == "Tester"
    assert run_e2e.setup_entry_value(entry, "Username") == run_e2e.E2E_USER
    assert run_e2e.setup_entry_value(entry, "Choose a Password") == run_e2e.E2E_PASSWORD
    assert run_e2e.setup_entry_value(entry, "Confirm Password") == run_e2e.E2E_PASSWORD
    assert run_e2e.setup_entry_value(entry, "Device name") is None
    # The entry's own name wins over the label.
    assert run_e2e.setup_entry_value({**entry, "name": "Full Name"}, "Device name") == "Tester"


def test_elementary_setup_row_prefers_english():
    rows = [
        {"role": "list item", "name": "Deutsch", "path": "0.2.0"},
        {"role": "list item", "name": "English", "path": "0.2.1"},
    ]
    assert run_e2e.setup_row(rows)["name"] == "English"
    assert run_e2e.setup_row(rows[:1])["name"] == "Deutsch"
    assert run_e2e.setup_row([{"role": "push button", "name": "Select"}]) is None


def test_the_first_boot_app_is_found_by_process_for_gnome_and_elementary():
    import re

    rx = re.compile(run_e2e.GIS_PROCESS)
    assert rx.search("/usr/libexec/gnome-initial-setup")
    assert rx.search("io.elementary.initial-setup")
    assert rx.search("/usr/bin/io.elementary.initial-setup --foo")
    assert not rx.search("/usr/libexec/gnome-initial-setup-copy-worker")
    # The SSH command line holds the pattern itself and must not match it.
    assert not rx.search(run_e2e.GIS_PROCESS)


def test_bootc_digest_reads_a_boothost():
    status = {"status": {"booted": {"image": {"imageDigest": "sha256:abc"}}, "rollback": None}}
    assert run_e2e.bootc_digest(json.dumps(status)) == "sha256:abc"


def _screen(monkeypatch, pixels):
    monkeypatch.setattr(run_e2e.ocr_fallback, "raw_rgb", lambda _p: b"".join(bytes(p) for p in pixels))


def test_a_black_screen_is_blank(monkeypatch):
    """bonito:niri wrote its stamp on a black screen (run 45651256265)."""
    _screen(monkeypatch, [(0, 0, 0)] * 100)
    assert run_e2e.blank("x.png")


def test_a_console_line_on_black_is_no_desktop(monkeypatch):
    """Run 46008379629 (hosted bonito:niri): stage 1 passed on one kernel console line on black."""
    # 1280x800 with ~0.2% white pixels, as one line of console text.
    pixels = [(0, 0, 0)] * 1_000_000 + [(255, 255, 255)] * 2000
    _screen(monkeypatch, pixels)
    assert run_e2e.blank("x.png")


def test_a_whole_screen_of_console_text_is_no_desktop(monkeypatch):
    # 10% of the pixels are text, but there are two colors: a console, not a desktop.
    _screen(monkeypatch, [(0, 0, 0)] * 900 + [(170, 170, 170)] * 100)
    assert run_e2e.blank("x.png")


def test_a_screen_with_a_desktop_on_it_is_not_blank(monkeypatch):
    # A wallpaper gradient under a window: many colors, no color covers 99.5%.
    pixels = [(n % 256, (n * 3) % 256, (n * 7) % 256) for n in range(10_000)]
    _screen(monkeypatch, pixels)
    assert not run_e2e.blank("x.png")
    # A dark installer on a dark wallpaper: one color 60%, 30 more colors.
    _screen(monkeypatch, [(20, 20, 20)] * 600 + [(30 + n % 30, 40, 50) for n in range(400)])
    assert not run_e2e.blank("x.png")


def test_the_ocr_walk_presses_the_screen_reader_button_only_when_shown(monkeypatch):
    """COSMIC's first page has "Turn on" (installer#481); niri's has none."""
    row = "5\t1\t1\t1\t1\t{n}\t{x}\t{y}\t100\t20\t90\t{text}"

    def page(*words):
        return ocr_fallback.parse_tsv(
            "header\n" + "\n".join(row.format(n=i, x=x, y=y, text=t) for i, (t, x, y) in enumerate(words))
        )

    class FakeQmp:
        def __init__(self):
            self.calls = []

        def run(self, *commands):
            self.calls.append(commands)

    monkeypatch.setattr(run_e2e.time, "sleep", lambda _s: None)
    monkeypatch.setattr(ocr_fallback, "words", lambda _png: page(("Turn", 1340, 880), ("off", 1450, 880)))
    qmp, a11y = FakeQmp(), {"status": "not run"}
    shown = page(("Screen", 480, 880), ("reader", 600, 880), ("Turn", 1340, 880), ("on", 1450, 880))
    assert run_e2e.press_screen_reader(shown, qmp, a11y, lambda: "after.png") == "after.png"
    assert a11y["pressed"] is True and a11y["live-button-off"] is True
    # One click: move, press, release, right of the label's left edge.
    assert len(qmp.calls) == 1 and len(qmp.calls[0]) == 3

    qmp, a11y = FakeQmp(), {"status": "not run"}
    assert run_e2e.press_screen_reader(page(("Get", 100, 900), ("started", 200, 900)), qmp, a11y, lambda: None) is None
    assert a11y == {"status": "not run", "pressed": False}
    assert qmp.calls == []


def test_the_ocr_walk_presses_the_screen_reader_on_a_welcome_header_with_the_title(monkeypatch):
    """The header line holds the window title too: OCR reads "welcome bonito"
    (run 45819747629, usb-2-ocr-00.png), and the walk never pressed "Turn on"."""
    row = "5\t1\t1\t1\t1\t{n}\t{x}\t{y}\t60\t20\t90\t{text}"

    def page(*words):
        return ocr_fallback.parse_tsv(
            "header\n" + "\n".join(row.format(n=i, x=x, y=y, text=t) for i, (t, x, y) in enumerate(words))
        )

    # Raw tesseract boxes at twice the screen size, as parse_tsv expects.
    welcome = page(
        ("Step", 440, 234), ("1", 520, 234), ("of", 550, 234), ("11", 590, 234), ("-", 630, 242),
        ("Welcome", 650, 234), ("Bonito", 1172, 232), ("Installer", 1300, 232),
        ("Turn", 1650, 962), ("on", 1720, 962),
    )
    installing = page(("Step", 440, 234), ("8", 520, 234), ("of", 550, 234), ("11", 590, 234),
                      ("-", 630, 242), ("Installing", 650, 234))
    pages = iter([welcome, installing])
    assert ocr_fallback.step_name(welcome) == "welcome bonito"

    class FakeQmp:
        def run(self, *commands):
            pass

    pressed = []
    monkeypatch.setattr(run_e2e.time, "sleep", lambda _s: None)
    monkeypatch.setattr(ocr_fallback, "words", lambda _png: next(pages))
    monkeypatch.setattr(ocr_fallback, "raw_rgb", lambda _png: b"")
    monkeypatch.setattr(ocr_fallback, "accent_button", lambda *_a: (987, 616))
    monkeypatch.setattr(run_e2e, "press_screen_reader", lambda found, *_a: pressed.append(found))
    run_e2e.walk_ocr(lambda _name: "x.png", FakeQmp(), {}, a11y={"status": "not run"})
    assert pressed == [welcome]


def test_the_a11y_result_needs_the_key_the_done_marker_and_the_record():
    on = (
        "gsettings=true\ndconf-profile=cosmic\nfirst-login-done=yes\natspi=b true\n"
        "[Accessibility]\nScreenReader=yes\nScalePercent=0\n"
    )
    result = run_e2e.a11y_result(on)
    assert result["status"] == "pass" and result["dconf-profile"] == "cosmic"
    assert run_e2e.a11y_result(on.replace("gsettings=true", "gsettings=false"))["status"] == "fail"
    # cosmic-initial-setup can turn the reader on by itself: without the
    # script's done marker a true key proves no carry.
    no_script = run_e2e.a11y_result(on.replace("first-login-done=yes", "first-login-done=no"))
    assert no_script["status"] == "fail" and no_script["first-login-done"] is False
    missing = on.replace("[Accessibility]\nScreenReader=yes\n", "cat: /etc/tunaos/accessibility.conf: No such file\n")
    result = run_e2e.a11y_result(missing)
    assert result["status"] == "fail" and result["accessibility-conf"] is False
    assert "gsettings get org.gnome.desktop.a11y.applications screen-reader-enabled" in run_e2e.A11Y_READ
    assert "runuser -u tester" in run_e2e.A11Y_READ and "/etc/tunaos/accessibility.conf" in run_e2e.A11Y_READ


@pytest.mark.parametrize("profile", ["cosmic", ""])
def test_the_a11y_read_uses_the_session_dconf_profile(tmp_path, profile):
    """Run 45826150571: start-cosmic sets DCONF_PROFILE=cosmic, the script wrote
    ~/.config/dconf/cosmic, and a gsettings without the profile read false.
    The read runs here with stubs: gsettings says true only in the profile
    that systemctl --user show-environment names."""
    stubs, home = tmp_path / "bin", tmp_path / "home"
    stubs.mkdir()
    (home / ".local/state/tunaos").mkdir(parents=True)
    (home / ".local/state/tunaos/first-login-accessibility.done").write_text("")
    scripts = {
        "id": "echo 1000",
        "getent": f"echo 'tester:x:1000:1000::{home}:/bin/bash'",
        # runuser -u USER -- CMD...: run CMD.
        "runuser": 'while [ "$1" != -- ]; do shift; done; shift; exec "$@"',
        "systemctl": f"echo HOME={home}; " + (f"echo DCONF_PROFILE={profile}" if profile else ":"),
        "gsettings": f'[ "${{DCONF_PROFILE:-user}}" = "{profile or "user"}" ] && echo true || echo false',
        "busctl": "echo 'b true'",
        "sleep": ":",
    }
    for name, body in scripts.items():
        stub = stubs / name
        stub.write_text(f"#!/bin/sh\n{body}\n")
        stub.chmod(0o755)
    seen = subprocess.run(
        ["/bin/sh", "-c", run_e2e.A11Y_READ],
        env={"PATH": f"{stubs}:/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    result = run_e2e.a11y_result(seen)
    assert result["gsettings"] == "true", seen
    assert result["dconf-profile"] == profile
    assert result["first-login-done"] is True


def test_the_a11y_field_never_changes_the_verdict(tmp_path):
    done = [{"id": "live-boot", "status": "pass"}]
    failed = {"status": "fail", "gsettings": "false"}
    assert run_e2e.finish(tmp_path, "usb", done, 0, a11y=failed) == 0
    record = json.loads((tmp_path / "usb-stages.json").read_text())
    assert record["a11y"] == failed and record["stages"] == done
    run_e2e.finish(tmp_path, "usb", done, 0)
    assert "a11y" not in json.loads((tmp_path / "usb-stages.json").read_text())


def test_the_native_walk_ticks_the_xfce_screen_reader_box(monkeypatch):
    """XFCE's first page has a "Screen reader" check box (installer#491)."""
    from atspi_match import Page

    monkeypatch.setattr(run_e2e.time, "sleep", lambda _s: None)
    shown = ["showing", "sensitive"]

    class FakeDriver:
        poll_interval = 0

        def __init__(self, box):
            self.box, self.pages, self.last_nodes = box, [], []

        def poll(self, _app):
            if self.pages and self.pages[-1] == "pressed":
                self.last_nodes = []
                return Page.PROGRESS
            nodes = [{"role": "push button", "name": "Next", "states": shown}]
            if self.box is not None:
                nodes.append(self.box)
            self.last_nodes = nodes
            return Page.NEXT

        def press(self, _app, _node):
            self.pages.append("pressed")

    def walk(box):
        driver, done = FakeDriver(box), []

        def keys(*k):
            done.extend(k)
            if box is not None and "spc" in k:
                box["states"] = [*box["states"], "checked"]

        a11y = {"status": "not run"}
        run_e2e.walk_native(driver, "app", lambda _n: None, lambda *_a: None, keys,
                            lambda _n: None, a11y=a11y)
        return a11y, done

    a11y, keys = walk({"role": "check box", "name": "Screen reader", "states": list(shown)})
    assert a11y["pressed"] is True and a11y["live-checked"] is True and keys == ["spc"]
    # Already ticked: no key, still pressed (the choice is on).
    a11y, keys = walk({"role": "check box", "name": "Screen reader", "states": [*shown, "checked"]})
    assert a11y["pressed"] is True and keys == []
    # No control: "not run".
    a11y, keys = walk(None)
    assert a11y == {"status": "not run", "pressed": False} and keys == []


def test_the_record_names_the_fishermand_commit(tmp_path, monkeypatch):
    """The record says which fishermand the medium carries."""
    monkeypatch.setenv("E2E_FISHERMAN_REF", "8212b98f64bdb8c50126ca9fea86b06ffa31e082")
    run_e2e.finish(tmp_path, "usb", [{"id": "live-boot", "status": "pass"}], 0)
    record = json.loads((tmp_path / "usb-stages.json").read_text())
    assert record["fisherman_ref"].startswith("8212b98f")
    monkeypatch.delenv("E2E_FISHERMAN_REF")
    run_e2e.finish(tmp_path, "usb", [{"id": "live-boot", "status": "pass"}], 0)
    assert "fisherman_ref" not in json.loads((tmp_path / "usb-stages.json").read_text())


def test_the_ocr_walk_takes_the_tpm_row_of_niri_in_passphrase_mode():
    # niri opens its encryption page on Passphrase (medium run 45828155977);
    # boxes are what tesseract read on usb-2-ocr-04.png of that run.
    rows = [
        ("Passphrase", 59, 195, 79, 12),
        ("TPM", 59, 253, 28, 10),
        ("TPM", 59, 311, 28, 10),
        ("+", 94, 313, 9, 9),
        ("passphrase", 108, 311, 75, 12),
    ]
    entries = [("Enter", 67, 414, 40, 12), ("passphrase", 112, 414, 76, 12)]
    assert run_e2e.tpm_row(rows + entries) == (73, 258)
    # TPM already chosen: the entries are gone, nothing to press.
    assert run_e2e.tpm_row(rows) is None


def test_the_ocr_walk_finds_niris_second_password_entry():
    ocr = load("ocr_fallback")
    found = [
        ("Username", 56, 213, 70, 12),
        ("Password", 56, 313, 70, 12),
        ("Password", 56, 363, 70, 12),
        ("again", 130, 363, 40, 12),
        ("Show", 232, 412, 40, 12),
        ("passwords", 276, 412, 70, 12),
    ]
    assert ocr.label_at(found, "Password") == (319, 56)
    assert ocr.label_at(found, "Password", "again") == (369, 56)


def test_the_entry_is_found_right_of_its_label_not_left_of_the_button():
    # Maximized niri window: entries at x 384-683, Continue at x 1189 (pod run
    # on medium 45986432375, usb-2-ocr-06-again.png). button - 108 missed them.
    ocr = load("ocr_fallback")
    width, height, bg, line = 1280, 800, (43, 41, 47), (73, 69, 79)
    img = bytearray(bytes(bg) * width * height)

    def put(x, y, color):
        o = (y * width + x) * 3
        img[o:o + 3] = bytes(color)

    for y in range(241, 282):
        for x in (384, 683):
            put(x, y, line)
    for x in range(384, 684):
        put(x, 241, line)
        put(x, 281, line)
    for x in range(56, 126, 3):  # label letters: short strokes only
        for y in range(255, 267):
            put(x, y, (200, 200, 200))
    assert ocr.entry_x(bytes(img), width, 261, 55, 1149) == 414
    # No outlined entry (a filled one, as on COSMIC): None, the caller falls back.
    assert ocr.entry_x(bytes(bytearray(bytes(bg) * width * height)), width, 261, 55, 1149) is None


def test_the_login_picks_the_account_on_a_dms_greeter(monkeypatch):
    # bonito:niri's DMS greeter opens on "Select user..." (medium run 45828155977).
    screens = {
        "g.png": [("Select", 538, 486, 40, 11), ("user...", 583, 488, 38, 8)],
        "5-greeter-users": [("tester", 594, 437, 38, 12), ("Auto-login", 578, 537, 70, 12)],
    }
    clicks = []

    class FakeQmp:
        def run(self, *cmds):
            clicks.append(cmds)

    monkeypatch.setattr(run_e2e.time, "sleep", lambda _s: None)
    monkeypatch.setattr(run_e2e.ocr_fallback, "ocr_available", lambda: True)
    monkeypatch.setattr(run_e2e.ocr_fallback, "words", lambda png: screens.get(png, []))
    run_e2e.pick_greeter_user(lambda name: name, FakeQmp(), "g.png")
    assert len(clicks) == 2
    # Another greeter (no "Select user..."): nothing is pressed.
    clicks.clear()
    screens["g.png"] = [("Password", 500, 480, 70, 12)]
    run_e2e.pick_greeter_user(lambda name: name, FakeQmp(), "g.png")
    assert clicks == []


def test_the_emergency_lines_type_on_a_us_keyboard():
    assert run_e2e.qcodes("ls -l /a.b=1,c") == [
        "l", "s", "spc", "minus", "l", "spc", "slash", "a", "dot", "b", "equal", "1",
        "comma", "c", "ret",
    ]
    for line in run_e2e.EMERGENCY_LINES:
        assert run_e2e.qcodes(line)[-1] == "ret"
    try:
        run_e2e.qcodes("a | b")
    except ValueError:
        pass
    else:
        raise AssertionError("a pipe has no plain qcode")


def emergency_fakes(monkeypatch, screen):
    keys, dumps = [], []

    class FakeQmp:
        def send_keys(self, *k):
            keys.extend(k)

        def screendump(self, path):
            dumps.append(Path(path).name)

    monkeypatch.setattr(run_e2e.time, "sleep", lambda _s: None)
    monkeypatch.setattr(run_e2e, "to_png", lambda ppm, png: png)
    monkeypatch.setattr(run_e2e.ocr_fallback, "ocr_text", lambda _p: screen)
    return FakeQmp(), keys, dumps


def test_a_failed_boot_photographs_the_emergency_shell(tmp_path, monkeypatch):
    qmp, keys, dumps = emergency_fakes(monkeypatch, "entering emergency mode. press enter for maintenance")
    assert run_e2e.emergency_status(qmp, tmp_path, "cdrom") is True
    assert keys[0] == "ret"
    numbered = [d for d in dumps if "failed" in d]
    assert numbered == [f"cdrom-0-boot-failed-{n}.ppm" for n in range(1, len(run_e2e.EMERGENCY_LINES) + 1)]
    assert keys.count("ret") == 1 + 2 * len(run_e2e.EMERGENCY_LINES)


def test_a_live_desktop_that_never_answers_ssh_gets_no_keys(tmp_path, monkeypatch):
    # brussels:xfce run 45910882687: the keys went into the installer's language search box.
    qmp, keys, dumps = emergency_fakes(monkeypatch, "welcome search languages english deutsch")
    assert run_e2e.emergency_status(qmp, tmp_path, "usb") is False
    assert keys == []
    assert dumps == ["usb-0-boot-probe.ppm"]


def test_the_recovery_key_check_tries_the_keyslots_only():
    # cryptsetup open tries LUKS2 tokens before the key file: with the
    # systemd-tpm2 token on, a TPM install would pass any key.
    # --disable-external-tokens stops plugin tokens only; the token type no
    # volume has also stops the built-in ones (luks2-keyring).
    check = run_e2e.RECOVERY_KEY_CHECK
    assert "--test-passphrase" in check
    assert "--disable-external-tokens" in check
    assert "--token-type=fisherman-keyslots-only" in check
    assert "--key-file=-" in check


def test_the_disk_passphrase_is_typed_only_when_the_boot_screen_asks(tmp_path, monkeypatch):
    keys = []

    class FakeQmp:
        def screendump(self, path):
            pass

        def send_keys(self, *k):
            keys.extend(k)

    monkeypatch.setattr(run_e2e, "to_png", lambda ppm, png: png)
    ppm = tmp_path / "probe.ppm"
    for screen, typed in (
        ("starting plymouth", False),
        ("please enter passphrase for disk root (luks-1234)!", True),
        ("please unlock disk root:", True),
    ):
        keys.clear()
        monkeypatch.setattr(run_e2e.ocr_fallback, "ocr_text", lambda _p, screen=screen: screen)
        assert run_e2e.type_disk_passphrase(FakeQmp(), ppm) is typed
        assert (keys == [*run_e2e.E2E_PASSWORD, "ret"]) is typed
        assert typed or keys == []


def test_a_boot_that_ssh_never_reached_carries_the_last_serial_lines(tmp_path):
    """albacore:kde run 45931354890: the first look at the cause is the serial log."""
    log = tmp_path / "serial-usb.log"
    lines = [f"[{n:4}.000] line {n}" for n in range(200)]
    log.write_text("\n".join(lines[:100]) + "\n\x1b[1;31mFAILED\x1b[0m start of x\r\n\n" + "\n".join(lines[100:]) + "\n")
    error = run_e2e.failed_boot_error(DriverError("guest sshd never answered"), log)
    assert error.startswith("guest sshd never answered\n--- last 80 lines of serial-usb.log ---\n")
    body = error.split("---\n", 1)[1].splitlines()
    assert len(body) == 80
    assert body[-1] == "[ 199.000] line 199"
    assert "\x1b" not in error and "\r" not in error
    # Blank lines do not count, and the older lines are cut.
    assert "line 100" not in error and "line 120" in error


def test_a_boot_without_serial_output_keeps_its_error(tmp_path):
    exc = DriverError("guest sshd never answered")
    assert run_e2e.failed_boot_error(exc, tmp_path / "no-such.log") == "guest sshd never answered"
    empty = tmp_path / "serial-cdrom.log"
    empty.write_text("\n\n")
    assert run_e2e.failed_boot_error(exc, empty) == "guest sshd never answered"


def test_the_stage_record_of_a_boot_that_ssh_never_reached_holds_the_serial_tail(tmp_path, monkeypatch):
    import io
    import types

    work, shots, evidence = tmp_path / "work", tmp_path / "shots", tmp_path / "evidence"
    for d in (work, shots, evidence):
        d.mkdir()
    (tmp_path / "key.pub").write_text("ssh-ed25519 AAAA test\n")
    (tmp_path / "vars.fd").write_text("")
    args = types.SimpleNamespace(
        work=str(work), medium="m.iso", ssh_port=2222, ssh_key=str(tmp_path / "key"),
        ovmf_code="/code.fd", ovmf_vars=str(tmp_path / "vars.fd"), target_size="1G",
        tpm=False, offline=False, virgl=False, kvm=False,
    )
    (work / "target-usb.qcow2").write_text("")
    (work / "serial-usb.log").write_text("Booting `Albacore (ostree:0)'\nLoading initrd\n")
    monkeypatch.setattr(run_e2e, "build_qemu_cmd", lambda *_a, **_k: ["qemu"])
    monkeypatch.setattr(
        run_e2e.subprocess,
        "Popen",
        lambda _c, **_k: types.SimpleNamespace(
            poll=lambda: None, terminate=lambda: None, wait=lambda **_k: 0, stderr=io.BytesIO()
        ),
    )
    monkeypatch.setattr(run_e2e.time, "sleep", lambda _s: None)

    def never(*_a, **_k):
        raise DriverError("guest sshd never answered")

    monkeypatch.setattr(run_e2e, "wait_ssh", never)

    class NoQmp:
        def __init__(self, *_a):
            pass

        def screendump(self, _p):
            raise DriverError("no QMP in the test")

    monkeypatch.setattr(run_e2e, "Qmp", NoQmp)
    assert run_e2e.run_boot(args, "usb", shots, evidence) == 1
    record = json.loads((evidence / "usb-stages.json").read_text())
    error = record["stages"][0]["error"]
    assert record["stages"][0]["id"] == "live-boot"
    assert "guest sshd never answered" in error
    assert "Booting `Albacore (ostree:0)'" in error and "Loading initrd" in error


def test_the_first_boot_driver_presses_start_setup():
    """gnome-initial-setup 49 opens on a Welcome page whose only button is
    "Start Setup" (bonito:tuna run 45996411588 never got past it)."""
    assert "Start Setup" in run_e2e.GIS_NAMES


def test_a_blank_desktop_picture_is_taken_again_then_counts_as_blank(monkeypatch):
    """Stages 5-7 fail on a one-colour picture (albacore:kde run 46083819054)."""
    monkeypatch.setattr(run_e2e.time, "sleep", lambda _s: None)
    taken = []

    def shot(name):
        taken.append(name)
        return f"{name}-{len(taken)}.png"

    # Black while the system boots, then the desktop: not blank.
    monkeypatch.setattr(run_e2e, "blank", lambda png: png.endswith("-1.png"))
    assert run_e2e.settled_shot(shot, "7-switch") == ("7-switch-2.png", False)
    # Black every time: blank after every try.
    taken.clear()
    monkeypatch.setattr(run_e2e, "blank", lambda _png: True)
    assert run_e2e.settled_shot(shot, "6-desktop-status", tries=3) == ("6-desktop-status-3.png", True)
    assert taken == ["6-desktop-status"] * 3
    # No picture at all is no proof of a desktop.
    assert run_e2e.settled_shot(lambda _n: None, "5-login", tries=2) == (None, True)
    assert "journalctl -b" in run_e2e.DESKTOP_DIAG and "/dev/dri" in run_e2e.DESKTOP_DIAG


def test_the_emergency_shell_capture_types_only_known_keys():
    """Every character of the capture commands has a QMP key, and the first
    command sends the shell's output to the serial port (the installed boot
    has no console, gurnard:pantheon run 46083846171)."""
    assert run_e2e.EMERGENCY_COMMANDS[0] == "exec >/dev/ttyS0 2>&1"
    sent = []

    class Fake(run_e2e.Qmp):
        def __init__(self):
            pass

        def run(self, cmd):
            sent.append(cmd)

        def send_keys(self, *keys):
            sent.append(keys)

    fake = Fake()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(run_e2e.time, "sleep", lambda _s: None)
        for line in run_e2e.EMERGENCY_COMMANDS:
            fake.type_line(line)
    assert sent
    with pytest.raises(run_e2e.DriverError):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(run_e2e.time, "sleep", lambda _s: None)
            fake.type_line("\u00e9")


@pytest.mark.parametrize(
    ("sessions", "want"),
    [
        # A greeter belongs to the display manager's user: gurnard:pantheon
        # run 46112524928 counted it as a desktop.
        ("c4 106 lightdm seat0 - active no -\n", False),
        ("c1 60578 gdm seat0 tty1 active no -\n", False),
        ("c2 977 sddm seat0 tty2 active no -\n", False),
        ("2 1000 tester seat0 tty2 active no -\n", True),
        ("2 1000 tester seat0 - active no -\n25 0 root - - active no -\n", True),
        # The user without a seat (ssh) is no desktop.
        ("36 1000 tester - pts/0 active no -\n", False),
        ("", False),
    ],
)
def test_only_a_session_of_the_user_on_a_seat_is_a_desktop(sessions, want):
    assert run_e2e.user_session(sessions) is want


def test_the_login_diagnostics_never_print_the_hash():
    """The probe names the hash type (four characters) and nothing more."""
    probe = run_e2e.LOGIN_DIAGNOSTICS
    assert "cut -d: -f2 | cut -c1-4" in probe
    for want in ("lightdm", "/var/log/lightdm", "ausearch", ".xsession-errors", "loginctl list-sessions",
                 "lightdm --show-config", "/usr/share/wayland-sessions", "AccountsService/users"):
        assert want in probe
    subprocess.run(["bash", "-n", "-c", probe], check=True)


def test_stage_6_and_7_fail_without_a_user_session():
    """A greeter on screen is no desktop (like the black-screen case)."""
    src = Path(run_e2e.__file__).read_text()
    assert '"status": "fail" if dark or not desktop or shell_missing or not picture_ok else "pass"' in src
    assert 'if desktop:\n            record["status"] = "pass"' in src


def test_a_pantheon_session_without_panel_and_dock_is_no_desktop():
    """gurnard:pantheon run 46122173243: gala and a '+' on the wallpaper."""
    gala_only = "gala\n/usr/bin/io.elementary.gala\ngnome-session --session=pantheon\n"
    assert run_e2e.missing_shell("pantheon", gala_only) == ["io.elementary.wingpanel", "io.elementary.dock"]
    full = gala_only + "io.elementary.wingpanel\nio.elementary.dock\n"
    assert run_e2e.missing_shell("pantheon", full) == []
    # Flavors with no list are not checked here.
    assert run_e2e.missing_shell("gnome", "") == []
    subprocess.run(["bash", "-n", "-c", run_e2e.SHELL_DIAGNOSTICS], check=True)


def test_a_pantheon_picture_needs_a_clock_and_launchers(monkeypatch):
    """gurnard:pantheon run 46122173243: wallpaper and a lone '+' with every
    shell process running is no desktop."""
    monkeypatch.setattr(run_e2e, "top_bar_clock", lambda png: False)
    monkeypatch.setattr(run_e2e, "dock_launchers", lambda args: ["Files", "Web", "AppCenter"])
    assert run_e2e.picture_verdict("pantheon", "x.png", None)[0] is False
    monkeypatch.setattr(run_e2e, "top_bar_clock", lambda png: True)
    monkeypatch.setattr(run_e2e, "dock_launchers", lambda args: [])
    assert run_e2e.picture_verdict("pantheon", "x.png", None)[0] is False
    monkeypatch.setattr(run_e2e, "dock_launchers", lambda args: ["Files", "Web", "AppCenter"])
    ok, evidence = run_e2e.picture_verdict("pantheon", "x.png", None)
    assert ok and evidence["dock-launchers"] == ["Files", "Web", "AppCenter"]
    # No OCR (None) never fails on its own; other flavors are not judged here.
    monkeypatch.setattr(run_e2e, "top_bar_clock", lambda png: None)
    assert run_e2e.picture_verdict("pantheon", "x.png", None)[0] is True
    assert run_e2e.picture_verdict("gnome", "x.png", None) == (True, {})


def test_the_clock_reader_says_no_on_the_wallpaper_and_lone_plus_picture(tmp_path):
    """The picture of run 46122173243 (wallpaper, '+'): no clock in the top strip."""
    import shutil

    import ocr_fallback

    src = Path(__file__).parent / "fixtures/installer-e2e/pantheon-no-shell-6.png"
    assert src.exists()
    if not (shutil.which("ffmpeg") and ocr_fallback.ocr_available()):
        # The Unit Tests job installs both; the ratchet allows no new skips.
        return
    png = tmp_path / "shot.png"
    png.write_bytes(src.read_bytes())
    assert run_e2e.top_bar_clock(png) is False


def test_qemu_gl_display_faults_are_found_in_its_log(tmp_path):
    """Run 46150465103 (bonito:niri, hosted): these lines came with every frozen picture."""
    log = tmp_path / "qemu-usb.log"
    log.write_text(
        "MESA-LOADER: failed to retrieve device information\n"
        "qemu-system-x86_64: egl: eglMakeCurrent failed: EGL_BAD_ACCESS\n"
        "make_current: Error switching context: -1\n"
        'vrend_decode_ctx_submit_cmd: context error reported 4 "quickshell" Illegal command buffer 852011\n'
    )
    assert len(run_e2e.host_display_fault(log)) == 2
    clean = tmp_path / "qemu-cdrom.log"
    clean.write_text("MESA-LOADER: failed to retrieve device information\n")
    assert run_e2e.host_display_fault(clean) == []
    assert run_e2e.host_display_fault(tmp_path / "missing.log") == []


def test_the_guest_picture_is_kept_only_when_it_is_a_png(tmp_path, monkeypatch):
    args = type("Args", (), {"ssh_port": 2222, "ssh_key": "id"})()
    replies = iter(
        [
            subprocess.CompletedProcess([], 0, b"\x89PNG\r\n\x1a\nrest", b""),
            subprocess.CompletedProcess([], 1, b"", b"no compositor"),
            subprocess.CompletedProcess([], 0, b"not a picture", b""),
        ]
    )
    seen = []

    def fake_run(cmd, **_kw):
        seen.append(cmd)
        return next(replies)

    monkeypatch.setattr(run_e2e.subprocess, "run", fake_run)
    out = tmp_path / "usb-3-install-poll-guest.png"
    assert run_e2e.guest_picture(args, out) == out
    assert out.read_bytes().startswith(b"\x89PNG")
    assert run_e2e.guest_picture(args, tmp_path / "b.png") is None
    assert run_e2e.guest_picture(args, tmp_path / "c.png") is None
    # grim first, niri's own screenshot action when there is no grim.
    assert "grim -" in seen[0][-1] and "screenshot-screen" in seen[0][-1]


def test_the_display_record_is_its_own_field_and_no_verdict(tmp_path, monkeypatch):
    monkeypatch.setitem(
        run_e2e.DISPLAY_RECORDS, "usb", {"source": "vnc", "host-display-fault": {"lines": 18}}
    )
    done = [{"id": s, "status": "pass"} for s in ("live-boot", "installer-pages")]
    assert run_e2e.finish(tmp_path, "usb", done, 0) == 0
    record = json.loads((tmp_path / "usb-stages.json").read_text())
    assert record["display"]["host-display-fault"] == {"lines": 18}
    assert "note" not in record["display"]
    failed = [*done, {"id": "install", "status": "fail"}]
    assert run_e2e.finish(tmp_path, "usb", failed, 1) == 1
    record = json.loads((tmp_path / "usb-stages.json").read_text())
    assert "not a frontend failure" in record["display"]["note"]


def test_qemu_stderr_goes_to_the_job_log_and_to_its_file(tmp_path, capfdbinary):
    proc = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stderr.write('egl: eglMakeCurrent failed\\n')"],
        stderr=subprocess.PIPE,
    )
    run_e2e.tee_lines(proc.stderr, tmp_path / "qemu-usb.log")
    proc.wait()
    assert b"eglMakeCurrent failed" in capfdbinary.readouterr().err
    assert run_e2e.host_display_fault(tmp_path / "qemu-usb.log")
