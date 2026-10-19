"""Typed login proof must not turn SSH/readiness/autologin into a GUI pass."""
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("login_proof", ROOT / "scripts/qualify-fork-login.py")
PROOF = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROOF)


def observations():
    before = {"boot_id": "boot-a", "uptime": 100.0, "uid": 1000, "sessions": [], "gnome_shell": []}
    active = {"Id": "3", "Name": "canary", "User": "1000", "Class": "user", "Type": "wayland",
              "Seat": "seat0", "Remote": "no", "Active": "yes", "Service": "gdm-password",
              "LockedHint": "no", "TimestampMonotonic": "105000000"}
    after = {**before, "uptime": 110.0, "sessions": [active], "gnome_shell": [{"pid": 123, "start_ticks": 10400}]}
    return before, after


def test_only_local_canary_images_admitted():
    PROOF.admit_image("localhost/fork-qualification/yellowfin:gnome-linux-amd64")
    PROOF.admit_image("localhost/fork-qualification/grouper:gnome-linux-amd64")
    for bad in ("ghcr.io/tuna-os/yellowfin:gnome", "localhost/fork-qualification/marlin:gnome-linux-amd64",
                "localhost/fork-qualification/yellowfin:kde-linux-amd64", "localhost/other:latest"):
        with pytest.raises(ValueError, match="local"):
            PROOF.admit_image(bad)


def test_new_gdm_password_session_is_required():
    before, after = observations()
    assert PROOF.validate_login(before, after)["Id"] == "3"
    assert PROOF.session(before) is None
    with pytest.raises(ValueError, match="before password"):
        PROOF.validate_login(after, after)


@pytest.mark.parametrize("key,value", [("Service", "gdm-autologin"), ("Service", "sshd"),
                                      ("Type", "tty"), ("Class", "greeter"), ("Seat", ""),
                                      ("Remote", "yes"), ("Active", "no"), ("Name", "root"),
                                      ("LockedHint", "yes"), ("User", "0")])
def test_non_password_or_non_graphical_session_rejected(key, value):
    before, after = observations()
    after["sessions"][0][key] = value
    with pytest.raises(ValueError, match="gdm-password"):
        PROOF.validate_login(before, after)


def test_old_session_reboot_or_missing_gnome_shell_rejected():
    before, after = observations()
    after["sessions"][0]["TimestampMonotonic"] = "99000000"
    with pytest.raises(ValueError, match="predates"):
        PROOF.validate_login(before, after)
    before, after = observations()
    after["boot_id"] = "boot-b"
    with pytest.raises(ValueError, match="rebooted"):
        PROOF.validate_login(before, after)
    before, after = observations()
    after["gnome_shell"] = []
    with pytest.raises(ValueError, match="GNOME"):
        PROOF.validate_login(before, after)


def test_corral_spec_does_not_enable_password_ssh_or_autologin(tmp_path):
    spec = PROOF.make_spec("localhost/private-source:latest", "proof", tmp_path, "ext4", "sshd.service")
    assert spec["users"] == [{"name": "canary"}]
    assert "rootPassword" not in spec and "packages" not in spec and "extraRun" not in spec
    assert spec["sshUser"] == "root" and spec["keep"] is True
    assert "systemd.wants=sshd.service" in spec["kargs"]
    assert "provision" not in spec
    assert all(word not in json.dumps(spec) for word in ("AutomaticLogin", "TimedLogin", "pam.d", "sudo", "PasswordAuthentication"))
    with pytest.raises(ValueError, match="SSH unit"):
        PROOF.make_spec("localhost/x", "proof", tmp_path, "ext4", "other.service")


def test_password_hash_sent_to_disposable_guest_stdin_only(tmp_path, monkeypatch):
    calls = []
    access = {"host": "127.0.0.1", "user": "root", "port": 2222, "identityFile": str(tmp_path / "key")}
    monkeypatch.setattr(PROOF, "run", lambda args, **kwargs: calls.append((args, kwargs)) or "")
    hashed = "$6$abc$def"
    PROOF.install_password(access, tmp_path, hashed)
    assert calls[0][1]["input"] == "canary:" + hashed + "\n"
    assert hashed not in str(calls[0][0])
    assert "chpasswd -e" in calls[0][0][-1]
    with pytest.raises(ValueError, match="hash"):
        PROOF.install_password(access, tmp_path, "plaintext")


def test_observer_only_uses_ephemeral_loopback_key(tmp_path, monkeypatch):
    key = tmp_path / "key"
    access = {"host": "127.0.0.1", "user": "root", "port": 2222, "identityFile": str(key)}
    calls = []
    monkeypatch.setattr(PROOF, "run", lambda args, **kwargs: calls.append((args, kwargs)) or "{}")
    assert PROOF.observer(access, tmp_path)() == {}
    assert "IdentitiesOnly=yes" in calls[0][0]
    assert "StrictHostKeyChecking=accept-new" in calls[0][0]
    assert calls[0][1]["input"] == PROOF.OBSERVE
    for changed in ({"host": "192.0.2.1"}, {"user": "realuser"}, {"identityFile": "/real/key"}):
        with pytest.raises(ValueError):
            PROOF.observer({**access, **changed}, tmp_path)


def test_ocr_matching_requires_exact_unambiguous_visible_words():
    assert PROOF.find_word([{"text": "Password:"}], "password")
    assert PROOF.find_word([{"text": "canary"}], "canary")
    assert not PROOF.find_word([{"text": "canary"}, {"text": "canary"}], "canary")
    assert not PROOF.find_word([{"text": "canary2"}], "canary")


def test_pixels_require_actual_solid_canary_color(tmp_path):
    reference = tmp_path / "reference.jpg"
    screen = tmp_path / "desktop.png"
    Image.new("RGB", (128, 128), "#12394b").save(reference)
    Image.new("RGB", (1280, 800), "#12394b").save(screen)
    assert PROOF.wallpaper_match(screen, reference)["passed"] is True
    Image.new("RGB", (1280, 800), "#555555").save(screen)
    assert PROOF.wallpaper_match(screen, reference)["passed"] is False
    image = Image.new("RGB", (128, 128), "#12394b")
    image.paste("red", (0, 0, 64, 128))
    image.save(reference)
    with pytest.raises(ValueError, match="solid"):
        PROOF.wallpaper_match(screen, reference)


def test_qmp_emits_real_keyboard_events_without_command_line(tmp_path, monkeypatch):
    calls = []

    class Stream:
        pending = [b'{"QMP": {"version": {}}}\n']

        def write(self, line):
            calls.append(json.loads(line))
            self.pending.extend([b'{"event": "irrelevant"}\n', b'{"return": {}}\n'])

        def readline(self):
            return self.pending.pop(0)

        def close(self):
            pass

    class Socket:
        def settimeout(self, timeout):
            assert timeout == 10

        def connect(self, path):
            assert path == str(tmp_path / "qmp.sock")

        def makefile(self, mode, buffering):
            return Stream()

        def close(self):
            pass

    monkeypatch.setattr(PROOF.socket, "socket", lambda family: Socket())
    monkeypatch.setattr(PROOF.time, "sleep", lambda seconds: None)
    qmp = PROOF.QMP(tmp_path / "qmp.sock")
    qmp.type("a7z")
    qmp.key("ret")
    with pytest.raises(ValueError, match="ASCII"):
        qmp.type("bad!input")
    qmp.close()
    assert calls[0]["execute"] == "qmp_capabilities"
    assert all(c["execute"] == "send-key" for c in calls[1:])
    assert [c["arguments"]["keys"][0]["data"] for c in calls[1:]] == ["a", "7", "z", "ret"]


def test_guest_observer_and_host_harness_compile():
    compile(PROOF.OBSERVE, "guest observer", "exec")
    source = (ROOT / "scripts/qualify-fork-login.py").read_text()
    compile(source, "login harness", "exec")
    assert '"--password"' not in source
    assert '"podman", "push"' not in source
    assert '"production_image_login_qualified": False' in source


@pytest.mark.parametrize("boot_ok", [True, False])
@pytest.mark.parametrize("cleanup_ok", [True, False])
def test_lifecycle_cleans_credentials_and_separates_image_identity(tmp_path, monkeypatch, boot_ok, cleanup_ok):
    """A mocked lifecycle checks report/cleanup contracts; it is not a VM pass."""
    import sys
    import yaml
    private = tmp_path / "private"
    private.mkdir()
    output = tmp_path / "output"
    fixture = tmp_path / "wallpaper.jpg"
    Image.new("RGB", (128, 128), "#12394b").save(fixture)
    before, after = observations()
    after["wallpaper"] = {key: "'" + PROOF.WALLPAPER + "'" for key in ("picture-uri", "picture-uri-dark")}
    samples = iter([before, before, after, after])
    calls = []
    typed = []
    removed = False
    monkeypatch.setattr(sys, "argv", ["proof", "--image", "localhost/fork-qualification/yellowfin:gnome-linux-amd64",
                                      "--output", str(output), "--wallpaper", str(fixture)])
    monkeypatch.setattr(PROOF.os, "geteuid", lambda: 0)
    monkeypatch.setattr(PROOF.shutil, "which", lambda name: None if name == "tailscale" else "/test/" + name)
    monkeypatch.setattr(PROOF.tempfile, "mkdtemp", lambda **kwargs: str(private))
    monkeypatch.setattr(PROOF.signal, "signal", lambda *args: None)
    monkeypatch.setattr(PROOF.Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(PROOF.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(PROOF, "identity", lambda image: {"reference": image, "id":
                        "derived-id" if image.startswith("localhost/corral-vmtest/") else "source-id", "digest": ""})
    monkeypatch.setattr(PROOF, "observer", lambda access, private: lambda: next(samples))
    monkeypatch.setattr(PROOF, "install_password", lambda access, private, hashed: calls.append(("install-password",)))
    monkeypatch.setattr(PROOF, "words", lambda frame: [{"text": "canary"}, {"text": "Password:"}])

    class QMP:
        def __init__(self, path):
            pass

        def type(self, text):
            typed.append(text)

        def key(self, *keys):
            calls.append(keys)

        def close(self):
            calls.append(("qmp-close",))

    monkeypatch.setattr(PROOF, "QMP", QMP)

    def run(command, **kwargs):
        calls.append(command)
        if command[:3] == ["openssl", "passwd", "-6"]:
            assert kwargs["input"].endswith("\n")
            return "$6$random$hash"
        if command[0] == "bash":
            return "SEALED=1\n"
        if command[:2] == ["corral", "screenshot"]:
            Image.new("RGB", (1280, 800), "#12394b").save(command[command.index("-o") + 1])
        return ""

    def execute(command, **kwargs):
        nonlocal removed
        calls.append(command)
        if command[:2] == ["corral", "vmtest"]:
            spec = yaml.safe_load(Path(command[-1]).read_text())
            root = Path(spec["artifacts"])
            root.mkdir()
            (root / "result.json").write_text(json.dumps({
                "status": "passed" if boot_ok else "failed", "exitCode": 0 if boot_ok else 6,
                "ready": boot_ok, "readyBy": "ssh", "kept": True,
                "layer": {"derived": True, "base": spec["bootc"]}, "ssh": {},
                "failure": "" if boot_ok else "fixture failure $6$random$hash"}))
            (root / "serial.log").write_text("disposable fixture boot\n")
            (root / "ssh").mkdir()
            (root / "ssh/id_ed25519").write_text("private-key-fixture")
            return subprocess.CompletedProcess(command, 0 if boot_ok else 6)
        if command[:3] == ["podman", "image", "exists"]:
            return subprocess.CompletedProcess(command, 1 if removed else 0)
        if command[:2] == ["podman", "rmi"]:
            removed = cleanup_ok
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(PROOF, "run", run)
    monkeypatch.setattr(PROOF.subprocess, "run", execute)
    assert PROOF.main() == (0 if boot_ok and cleanup_ok else 1)
    report = json.loads((output / "login-proof.json").read_text())
    assert report["cleanup"] == ("passed" if cleanup_ok else "failed")
    assert not private.exists()
    assert report["source_image"]["id"] == "source-id"
    assert report["production_image_login_qualified"] is False
    assert removed is cleanup_ok
    assert not any(path.name in ("spec.yaml", "id_ed25519", "Containerfile") for path in output.rglob("*"))
    text = (output / "login-proof.json").read_text()
    assert "$6$" not in text and "private-key-fixture" not in text
    if boot_ok:
        assert report["derived_image"]["id"] == "derived-id"
        assert report["typed_login"] == report["wallpaper_render"] == "passed"
        assert len(typed) == 1 and typed[0] not in text
    else:
        assert report["typed_login"] == "failed" and report["wallpaper_render"] == "not-run"
        assert not typed
