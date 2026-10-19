"""Typed login proof must not turn SSH/readiness/autologin into a GUI pass."""
import importlib.util
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("login_proof", ROOT / "scripts/qualify-fork-login.py")
PROOF = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROOF)
FIXTURES = ROOT / "tests/fixtures/fork-login"
REAL_OCR = pytest.mark.skipif(not shutil.which("tesseract"), reason="real screenshot regression requires Tesseract")


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


@pytest.fixture(params=["yellowfin", "grouper"])
def captured_prompt(request):
    manifest = json.loads((FIXTURES / "provenance.json").read_text())
    sample = manifest["screenshots"][request.param]
    frame = FIXTURES / sample["file"]
    assert hashlib.sha256(frame.read_bytes()).hexdigest() == sample["sha256"]
    return frame, sample


@REAL_OCR
def test_actual_native_prompt_uses_field_geometry_and_cropped_ocr(captured_prompt, tmp_path):
    """Run-5 screenshots failed full-frame OCR despite a visible Password field."""
    frame, sample = captured_prompt
    rows = PROOF.words(frame)
    assert PROOF.find_word(rows, "canary")
    assert not PROOF.find_word(rows, "password")
    receipt = PROOF.password_prompt(frame, rows, tmp_path)
    assert receipt["verified"] is True
    assert receipt["frame_sha256"] == sample["sha256"]
    assert receipt["frame_size"] == [1280, 800]
    assert len(receipt["account_candidates"]) == len(receipt["field_candidates"]) == 1
    assert receipt["field_candidates"][0]["bbox"] == sample["field_bbox"]
    assert receipt["field_ocr"]["crop_bbox"] == sample["crop_bbox"]
    assert receipt["field_ocr"]["psm"] == 7
    assert receipt["field_ocr"]["scale"] == 4
    assert [word["text"] for word in receipt["field_ocr"]["words"]] == ["Password"]
    assert float(receipt["field_ocr"]["words"][0]["conf"]) >= 60
    assert not list(tmp_path.iterdir()), "private crop must be removed after OCR"


@pytest.mark.parametrize("collision", ["substring", "brand-neighbor", "brand-footer", "duplicate", "low-confidence"])
def test_account_anchor_rejects_brand_name_and_ambiguous_labels(captured_prompt, tmp_path, collision):
    frame, sample = captured_prompt
    account = dict(sample["account_word"])
    rows = [account]
    if collision == "substring":
        account["text"] = "canary2"
    elif collision == "brand-neighbor":
        rows.append({**account, "text": "Harbor", "left": int(account["left"]) - 88, "width": 80})
    elif collision == "brand-footer":
        account["top"] = 680
    elif collision == "duplicate":
        rows.append({**account, "top": 350})
    else:
        account["conf"] = 79
    receipt = PROOF.password_prompt(frame, rows, tmp_path)
    assert receipt["verified"] is False
    assert receipt["reason"] == "no unique isolated account label"
    assert "field_ocr" not in receipt


@pytest.mark.parametrize("field_text", [[], [{"text": "canary", "conf": 99}],
                                      [{"text": "NotPassword", "conf": 99}],
                                      [{"text": "Password:", "conf": 99}],
                                      [{"text": "Password", "conf": 59}],
                                      [{"text": "Password", "conf": 99}, {"text": "reset", "conf": 99}]])
def test_field_ocr_has_no_name_substring_or_fuzzy_fallback(captured_prompt, tmp_path, monkeypatch, field_text):
    frame, sample = captured_prompt

    def ocr(path, **kwargs):
        assert kwargs == {"psm": 7, "confidence": 0}
        return field_text

    monkeypatch.setattr(PROOF, "words", ocr)
    receipt = PROOF.password_prompt(frame, [sample["account_word"]], tmp_path)
    assert receipt["verified"] is False
    assert receipt["reason"] == "field interior did not contain exactly Password"


@REAL_OCR
@pytest.mark.parametrize("missing", ["text", "outline"])
def test_visible_account_alone_never_qualifies(captured_prompt, tmp_path, missing):
    frame, sample = captured_prompt
    changed = tmp_path / "negative.png"
    with Image.open(frame) as original:
        image = original.convert("RGB")
        left, top, right, bottom = sample["field_bbox"]
        if missing == "text":
            image.paste(image.getpixel((left + 10, top + 6)), (left + 5, top + 5, right - 5, bottom - 5))
        else:
            interior = image.crop((left + 5, top + 5, right - 5, bottom - 5))
            image.paste(image.getpixel((left - 10, top)), (left - 3, top - 3, right + 3, bottom + 3))
            image.paste(interior, (left + 5, top + 5))
        image.save(changed)
    receipt = PROOF.password_prompt(changed, [sample["account_word"]], tmp_path)
    assert receipt["verified"] is False
    if missing == "outline":
        assert receipt["reason"] == "no unique outlined password field"
        assert "field_ocr" not in receipt
    else:
        assert receipt["reason"] == "field interior did not contain exactly Password"


@REAL_OCR
def test_field_detection_moves_with_the_account(captured_prompt, tmp_path):
    frame, sample = captured_prompt
    shifted = tmp_path / "translated.png"
    with Image.open(frame) as original:
        image = Image.new("RGB", original.size, original.getpixel((0, 0)))
        image.paste(original, (48, -35))
        image.save(shifted)
    account = {**sample["account_word"], "left": int(sample["account_word"]["left"]) + 48,
               "top": int(sample["account_word"]["top"]) - 35}
    receipt = PROOF.password_prompt(shifted, [account], tmp_path)
    assert receipt["verified"] is True
    assert receipt["field_candidates"][0]["bbox"] == [value + delta for value, delta in
                                                       zip(sample["field_bbox"], [48, -35, 48, -35])]


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


@pytest.mark.parametrize("failure", [None, "greeting", "command"])
def test_qmp_releases_single_client_monitor_between_calls(tmp_path, monkeypatch, failure):
    calls = []
    handles = {"sockets": 0, "streams": 0}

    class Stream:
        def __init__(self):
            self.pending = [b'{"QMP": {"version": {}}}\n']
            handles["streams"] += 1

        def write(self, line):
            command = json.loads(line)
            calls.append(command)
            if failure == "command" and command["execute"] == "send-key":
                self.pending.append(b'{"error": {"desc": "do not echo this"}}\n')
            else:
                self.pending.extend([b'{"event": "irrelevant"}\n', b'{"return": {}}\n'])

        def readline(self):
            if failure == "greeting":
                raise TimeoutError("greeting timeout")
            return self.pending.pop(0)

        def close(self):
            handles["streams"] -= 1

    class Socket:
        def __init__(self):
            assert handles["sockets"] == 0, "another client owns the monitor"
            handles["sockets"] += 1

        def settimeout(self, timeout):
            assert timeout == 10

        def connect(self, path):
            assert path == str(tmp_path / "qmp.sock")

        def makefile(self, mode, buffering):
            return Stream()

        def close(self):
            handles["sockets"] -= 1

    monkeypatch.setattr(PROOF.socket, "socket", lambda family: Socket())
    monkeypatch.setattr(PROOF.time, "sleep", lambda seconds: None)
    qmp = PROOF.QMP(tmp_path / "qmp.sock")
    assert handles == {"sockets": 0, "streams": 0}, "screenshot needs the monitor before input"
    if failure:
        with pytest.raises((TimeoutError, RuntimeError)):
            qmp.key("a")
        assert handles == {"sockets": 0, "streams": 0}
        return
    qmp.type("a7z")
    assert handles == {"sockets": 0, "streams": 0}, "screenshot needs the monitor after input"
    qmp.key("ret")
    with pytest.raises(ValueError, match="ASCII"):
        qmp.type("bad!input")
    qmp.close()
    assert handles == {"sockets": 0, "streams": 0}
    assert [c["execute"] for c in calls] == ["qmp_capabilities", "send-key"] * 4
    assert [c["arguments"]["keys"][0]["data"] for c in calls[1::2]] == ["a", "7", "z", "ret"]


@pytest.mark.parametrize("outcome", ["success", "nonzero", "remaining", "timeout", "already-absent"])
def test_vm_cleanup_requires_exit_success_and_resource_absence(tmp_path, monkeypatch, outcome):
    monkeypatch.setattr(PROOF.Path, "home", lambda: tmp_path)
    directory = tmp_path / ".local/share/corral/vms/proof"
    if outcome != "already-absent":
        directory.mkdir(parents=True)

    def execute(command, **kwargs):
        assert command == ["corral", "delete", "proof", "-f"]
        assert kwargs["timeout"] == 150
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(command, 150)
        if directory.exists() and outcome != "remaining":
            directory.rmdir()
        return subprocess.CompletedProcess(command, 2 if outcome in ("nonzero", "already-absent") else 0,
                                           stderr="bounded diagnostic" * 200)

    monkeypatch.setattr(PROOF.subprocess, "run", execute)
    result = PROOF.delete_vm("corral", "proof")
    assert result["passed"] is (outcome in ("success", "already-absent"))
    assert result["already_absent"] is (outcome == "already-absent")
    assert len(result.get("stderr", "")) <= 1500


def test_guest_observer_and_host_harness_compile():
    compile(PROOF.OBSERVE, "guest observer", "exec")
    source = (ROOT / "scripts/qualify-fork-login.py").read_text()
    compile(source, "login harness", "exec")
    assert '"--password"' not in source
    assert '"podman", "push"' not in source
    assert '"production_image_login_qualified": False' in source


@pytest.mark.parametrize("boot_ok", [True, False])
@pytest.mark.parametrize("cleanup_ok", [True, False])
@pytest.mark.parametrize("prompt_ok", [True, False])
@pytest.mark.parametrize("installer_mode", ["skip", "pass", "fail"])
def test_lifecycle_cleans_credentials_and_separates_image_identity(tmp_path, monkeypatch, boot_ok, cleanup_ok, prompt_ok, installer_mode):
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
    source_tags = {"localhost/fork-qualification/yellowfin:gnome-linux-amd64", "localhost/source-alias:keep"}
    original_tags = set(source_tags)
    monkeypatch.setattr(sys, "argv", ["proof", "--image", "localhost/fork-qualification/yellowfin:gnome-linux-amd64",
                                      "--output", str(output), "--wallpaper", str(fixture)])
    if installer_mode != "skip":
        # Exercise opt-in lifecycle/report/cleanup with a fixture helper only.
        # This does not run an installer or qualify a native window.
        root = tmp_path / "fixture-root"
        (root / "scripts").mkdir(parents=True)
        body = 'def qualify(*args):\n    args[-1]["status"] = "passed"\n'
        if installer_mode == "fail":
            body += '    raise ValueError("fixture installer failure")\n'
        (root / "scripts/qualify-fork-installer.py").write_text(body)
        monkeypatch.setattr(PROOF, "ROOT", root)
        sys.argv += ["--installer-artifact", str(tmp_path / "fixture.zip")]
    monkeypatch.setattr(PROOF.os, "geteuid", lambda: 0)
    monkeypatch.setattr(PROOF.shutil, "which", lambda name: None if name == "tailscale" else "/test/" + name)
    monkeypatch.setattr(PROOF.tempfile, "mkdtemp", lambda **kwargs: str(private))
    monkeypatch.setattr(PROOF.signal, "signal", lambda *args: None)
    monkeypatch.setattr(PROOF.Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(PROOF.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(PROOF, "identity", lambda image: {"reference": image, "id":
                        "derived-id" if image.startswith("localhost/corral-vmtest/") else "source-id",
                        "digest": "", "repo_tags": sorted(source_tags)})
    monkeypatch.setattr(PROOF, "observer", lambda access, private: lambda: next(samples))
    monkeypatch.setattr(PROOF, "install_password", lambda access, private, hashed: calls.append(("install-password",)))
    monkeypatch.setattr(PROOF, "words", lambda frame: [{"text": "canary"}, {"text": "Password:"}])
    monkeypatch.setattr(PROOF, "password_prompt", lambda frame, rows, private:
                        {"verified": frame.name == "10-greeter.png" or prompt_ok, "frame_sha256": "fixture-hash"})

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
        if command[:2] == ["podman", "tag"]:
            source_tags.add(command[3])
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
        if command[:2] == ["podman", "untag"]:
            assert len(command) == 4 and command[2] == "source-id"
            assert command[3].startswith("localhost/fork-login-source/")
            source_tags.remove(command[3])
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(PROOF, "run", run)
    monkeypatch.setattr(PROOF.subprocess, "run", execute)
    assert PROOF.main() == (0 if boot_ok and cleanup_ok and prompt_ok and installer_mode != "fail" else 1)
    report = json.loads((output / "login-proof.json").read_text())
    assert report["cleanup"] == ("passed" if cleanup_ok else "failed")
    assert not private.exists()
    assert report["source_image"]["id"] == "source-id"
    assert report["production_image_login_qualified"] is False
    assert removed is cleanup_ok
    assert source_tags == original_tags
    assert set(report["source_image_after_cleanup"]["repo_tags"]) == original_tags
    assert not any(path.name in ("spec.yaml", "id_ed25519", "Containerfile") for path in output.rglob("*"))
    text = (output / "login-proof.json").read_text()
    assert "$6$" not in text and "private-key-fixture" not in text
    if boot_ok and prompt_ok and installer_mode != "skip":
        assert report["installer_ui"] == ("passed" if installer_mode == "pass" else "failed")
    else:
        assert report["installer_ui"] == "not-run"
    if boot_ok:
        assert report["derived_image"]["id"] == "derived-id"
        prompt = json.loads((output / "20-password-prompt.json").read_text())
        assert prompt["verified"] is prompt_ok
    if boot_ok and prompt_ok:
        assert report["typed_login"] == report["wallpaper_render"] == "passed"
        assert len(typed) == 1 and typed[0] not in text
        assert report["password_prompt"]["receipt"] == "20-password-prompt.json"
    else:
        assert report["typed_login"] == "failed" and report["wallpaper_render"] == "not-run"
        assert not typed


def test_source_session_scan_retries_only_confirmed_disappearance():
    import ast
    import re
    from types import SimpleNamespace
    definition = next(n for n in ast.parse(PROOF.OBSERVE).body if isinstance(n, ast.FunctionDef) and n.name == "scan_sessions")
    def scan(results):
        calls = []
        def run(args, **kwargs):
            calls.append(args)
            return next(results)
        namespace = {"subprocess": SimpleNamespace(run=run), "re": re}
        exec(compile(ast.Module(body=[definition], type_ignores=[]), "<session-scan>", "exec"), namespace)
        return namespace["scan_sessions"](), calls
    result = lambda code, text: SimpleNamespace(returncode=code, stdout=text)
    value, calls = scan(iter([result(0, "c1 greeter\n17 canary"), result(1, ""), result(0, "17 canary")]))
    assert value == ([], {"status": "changed", "disappeared": ["c1"]})
    assert calls[-1][1] == "list-sessions"
    with pytest.raises(ValueError, match="could not be read"):
        scan(iter([result(0, "17 canary"), result(1, ""), result(0, "17 canary")]))
    with pytest.raises(ValueError, match="malformed"):
        scan(iter([result(0, "17 canary"), result(0, "Name=canary")]))
    with pytest.raises(ValueError, match="listing failed"):
        scan(iter([result(1, "")]))


def test_changed_scan_cannot_prove_login_or_no_preexisting_session():
    before, after = observations()
    after["session_scan"] = {"status": "changed", "disappeared": ["c1"]}
    assert PROOF.session(after) is None
    with pytest.raises(ValueError, match="scan changed"):
        PROOF.assert_no_login(after)
