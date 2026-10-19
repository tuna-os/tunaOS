#!/usr/bin/env python3
"""Typed GNOME login proof in a disposable, local-only derived canary image.

The source image is never changed or published. Only safe evidence is copied out
of a private temporary workspace; accounts, keys and the derived image are removed.
"""
import argparse
import csv
import hashlib
import io
import importlib.util
import json
import os
from pathlib import Path
import re
from secrets import choice, token_hex
import shutil
import signal
import socket
import string
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
USER = "canary"
WALLPAPER = "file:///usr/share/backgrounds/tunaos/tunaos-default.jpg"

# This runs as root over the disposable VM's loopback-only, ephemeral-key SSH.
# It observes logind and the real user's session bus; it does not create a session.
OBSERVE = r"""
import glob, hashlib, json, os, pwd, subprocess
from pathlib import Path
user = "canary"
def run(args):
    p = subprocess.run(args, text=True, capture_output=True, timeout=15)
    return p.stdout.strip() if p.returncode == 0 else ""
uid = pwd.getpwnam(user).pw_uid
sessions = []
for row in run(["loginctl", "list-sessions", "--no-legend", "--no-pager"]).splitlines():
    sid = row.split()[0]
    properties = run(["loginctl", "show-session", sid, "--no-pager"])
    item = dict(line.split("=", 1) for line in properties.splitlines() if "=" in line)
    sessions.append({key: item.get(key, "") for key in
        ("Id", "User", "Name", "Remote", "Type", "Class", "Active", "State", "Service", "Desktop", "Seat", "Leader", "LockedHint", "TimestampMonotonic")})
shells = []
for proc in Path("/proc").glob("[0-9]*"):
    try:
        if proc.stat().st_uid == uid and (proc / "comm").read_text().strip() == "gnome-shell":
            fields = (proc / "stat").read_text().rsplit(")", 1)[1].split()
            shells.append({"pid": int(proc.name), "start_ticks": fields[19]})
    except (OSError, IndexError):
        pass
settings = {}
if shells:
    for key in ("picture-uri", "picture-uri-dark"):
        settings[key] = run(["runuser", "-u", user, "--", "env",
            "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/%s/bus" % uid,
            "XDG_RUNTIME_DIR=/run/user/%s" % uid,
            "gsettings", "get", "org.gnome.desktop.background", key])
print(json.dumps({"boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
    "uptime": float(Path("/proc/uptime").read_text().split()[0]),
    "uid": uid, "sessions": sessions, "gnome_shell": shells, "wallpaper": settings}))
"""


def run(command, **kwargs):
    return subprocess.run(command, check=True, text=True, capture_output=True, **kwargs).stdout


def identity(image):
    info = json.loads(run(["podman", "image", "inspect", image]))[0]
    return {"reference": image, "id": info["Id"], "digest": info.get("Digest", ""),
            "repo_digests": info.get("RepoDigests", []), "repo_tags": info.get("RepoTags", []) or []}


def admit_image(image):
    if not re.fullmatch(r"localhost/fork-qualification/(yellowfin|grouper):gnome-linux-amd64", image):
        raise ValueError("only the local yellowfin/grouper GNOME qualification canary is admitted")


def session(observation):
    found = [s for s in observation["sessions"] if
             s["Name"] == USER and s["User"] == str(observation["uid"]) and
             s["Class"] == "user" and s["Type"] in ("wayland", "x11") and
             s["Seat"] == "seat0" and s["Remote"] == "no" and s["Active"] == "yes"]
    if len(found) != 1 or found[0]["Service"] != "gdm-password" or found[0]["LockedHint"] != "no":
        return None
    if not observation["gnome_shell"]:
        return None
    return found[0]


def assert_no_login(observation):
    if observation["gnome_shell"] or any(s["Name"] == USER and s["Class"] == "user" and
                                         s["Type"] in ("wayland", "x11") for s in observation["sessions"]):
        raise ValueError("graphical test-user session existed before password input")


def validate_login(before, after):
    assert_no_login(before)
    if before["boot_id"] != after["boot_id"]:
        raise ValueError("guest rebooted during the login proof")
    actual = session(after)
    if not actual:
        raise ValueError("no active, local, unlocked GNOME session authenticated by gdm-password")
    if int(actual["TimestampMonotonic"]) <= int(before["uptime"] * 1_000_000):
        raise ValueError("graphical session predates typed password input")
    return actual


class QMP:
    """Secret keyboard input with no idle monitor connection between calls.

    Corral 388342b opens the same QMP socket for each screenshot. Keeping our
    connection open blocks that client's greeting (native run 39196450923).
    """
    def __init__(self, path):
        self.path = path

    @staticmethod
    def exchange(stream, command, arguments=None):
        stream.write((json.dumps({"execute": command, "arguments": arguments or {}}) + "\n").encode())
        while True:
            response = json.loads(stream.readline())
            if "event" in response:
                continue
            if "error" in response:
                # Never echo a command whose arguments could include a secret.
                raise RuntimeError("QMP command failed: " + command)
            if "return" in response:
                return response["return"]

    def execute(self, command, arguments=None):
        sock = socket.socket(socket.AF_UNIX)
        stream = None
        try:
            sock.settimeout(10)
            sock.connect(str(self.path))
            stream = sock.makefile("rwb", buffering=0)
            if "QMP" not in json.loads(stream.readline()):
                raise ValueError("QMP greeting missing")
            self.exchange(stream, "qmp_capabilities")
            return self.exchange(stream, command, arguments)
        finally:
            # Release both handles even when the greeting/command fails, before
            # Corral's next screenshot, diagnostics, or cleanup operation.
            try:
                if stream is not None:
                    stream.close()
            finally:
                sock.close()

    def key(self, *codes):
        self.execute("send-key", {"keys": [{"type": "qcode", "data": c} for c in codes], "hold-time": 60})
        time.sleep(.15)

    def type(self, text):
        if not re.fullmatch("[a-z0-9]+", text):
            raise ValueError("only lowercase ASCII and digits are admitted for synthetic input")
        for character in text:
            self.key(character)

    def close(self):
        # Each operation already closes its own connection on every path.
        pass


def words(path):
    output = run(["tesseract", str(path), "stdout", "--psm", "11", "tsv"], timeout=30)
    return [row for row in csv.DictReader(io.StringIO(output), delimiter="\t")
            if row.get("text", "").strip() and float(row.get("conf", -1)) >= 30]


def find_word(rows, text):
    matches = [row for row in rows if re.sub(r"[^a-z0-9]", "", row["text"].lower()) == text]
    return matches[0] if len(matches) == 1 else None


def wallpaper_match(frame, reference):
    """Measure the deliberately solid canary wallpaper, never an arbitrary image."""
    from PIL import Image
    with Image.open(reference) as source:
        pixels = list(source.convert("RGB").resize((64, 64)).getdata())
    color = tuple(sorted(p[c] for p in pixels)[len(pixels) // 2] for c in range(3))
    if sum(max(abs(p[c] - color[c]) for c in range(3)) <= 4 for p in pixels) / len(pixels) < .99:
        raise ValueError("wallpaper pixel proof requires the solid qualification fixture")
    with Image.open(frame) as screenshot:
        image = screenshot.convert("RGB")
        w, h = image.size
        pixels = list(image.crop((w // 10, h // 5, w * 9 // 10, h * 9 // 10)).getdata())
    ratio = sum(max(abs(p[c] - color[c]) for c in range(3)) <= 8 for p in pixels) / len(pixels)
    return {"expected_rgb": color, "matching_fraction": ratio, "minimum_fraction": .50,
            "passed": ratio >= .50}


def make_spec(image, name, artifacts, filesystem, ssh_unit):
    if ssh_unit not in ("ssh.service", "sshd.service"):
        raise ValueError("unknown guest SSH unit")
    # Omitting users[].password prevents Corral from enabling SSH password auth
    # or echoing a password. The account is locked in every image/cache layer;
    # only the booted disposable guest receives its short-lived password hash.
    return {"name": name, "bootc": image, "cpus": 4, "memory": "4G", "disk": "40G",
            "filesystem": filesystem, "timeout": "900s", "sshUser": "root", "keep": True,
            "layerEngine": "builtin", "artifacts": str(artifacts),
            "users": [{"name": USER}], "screenshots": {"interval": "5s", "video": False},
            "kargs": ["console=tty0", "console=ttyS0,115200n8", "systemd.journald.forward_to_console=1",
                      "systemd.unit=graphical.target", "systemd.wants=" + ssh_unit, "tunaos.countme=0"],
            "failMarker": "TUNAOS_(DESKTOP|BASE)_CONTRACT_FAIL|Kernel panic|Entering emergency mode"}


def ssh_command(access, private):
    if access.get("host") != "127.0.0.1" or access.get("user") != "root":
        raise ValueError("refusing SSH outside the disposable loopback guest")
    key = Path(access["identityFile"]).resolve()
    if not key.is_relative_to(private.resolve()):
        raise ValueError("SSH key is outside the private temporary run")
    return ["ssh", "-i", str(key), "-p", str(int(access["port"])),
            "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-o", "ConnectTimeout=10",
            "-o", "StrictHostKeyChecking=accept-new", "-o", "UserKnownHostsFile=" + str(private / "known_hosts"),
            "root@127.0.0.1"]


def install_password(access, private, hashed_password):
    if not re.fullmatch(r"\$6\$[./a-zA-Z0-9]+\$[./a-zA-Z0-9]+", hashed_password):
        raise ValueError("invalid ephemeral password hash")
    # The hash is stdin to this disposable guest only, never argv, an image
    # build context, a build-cache layer, a service log, or an uploaded file.
    run(ssh_command(access, private) + ["chpasswd -e && chage -M -1 " + USER],
        input=USER + ":" + hashed_password + "\n", timeout=30)


def observer(access, private):
    command = ssh_command(access, private) + ["python3 -"]
    return lambda: json.loads(run(command, input=OBSERVE, timeout=90))


def delete_vm(corral, name):
    directory = Path.home() / ".local/share/corral/vms" / name
    was_present = directory.exists()
    try:
        # Corral allows 20s for direct QEMU termination, then performs systemctl
        # stop/disable/reload with no shorter internal limit. Cover that sequence
        # and systemd's usual 90s stop timeout with a bounded outer deadline.
        result = subprocess.run([corral, "delete", name, "-f"], capture_output=True, text=True, timeout=150)
        remaining = directory.exists()
        return {"passed": not remaining and (result.returncode == 0 or not was_present),
                "returncode": result.returncode, "timeout_seconds": 150,
                "stderr": (result.stderr or "")[-1500:], "directory_remaining": remaining,
                "already_absent": not was_present}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"passed": False, "error": type(error).__name__, "timeout_seconds": 150,
                "directory_remaining": directory.exists(), "already_absent": not was_present}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wallpaper", type=Path, required=True)
    parser.add_argument("--corral", default="corral")
    parser.add_argument("--installer-artifact", type=Path, help="opt-in frozen installer artifact ZIP; downloaded separately on host")
    args = parser.parse_args()
    admit_image(args.image)
    import yaml
    from PIL import Image
    with Image.open(args.wallpaper) as fixture:
        fixture.verify()
    if os.geteuid() != 0:
        parser.error("run as root, as for the existing Corral boot gate")
    for tool in (args.corral, "podman", "openssl", "ssh", "tesseract"):
        if not shutil.which(tool):
            parser.error("required test tool missing: " + tool)
    # Corral binds to an available tailnet IP by default. This harness permits
    # loopback only and refuses hosts where that default could expose its VM.
    if shutil.which("tailscale"):
        tailscale = subprocess.run(["tailscale", "ip", "-4"], text=True, capture_output=True, timeout=10)
        if tailscale.returncode == 0:
            parser.error("use an isolated runner without a connected Tailscale interface")
    args.output.mkdir(parents=True, exist_ok=False)
    out = args.output.resolve()
    report = {"schema_version": 1, "scope": "disposable derived local canary only",
              "publishing": False, "production_image_login_qualified": False,
              "typed_login": "not-run", "wallpaper_render": "not-run", "cleanup": "not-run",
              "installer_ui": "not-run"}
    name = "fork-login-" + token_hex(6)
    derived = "localhost/corral-vmtest/" + name + ":latest"
    pinned = "localhost/fork-login-source/" + name + ":latest"
    private = Path(tempfile.mkdtemp(prefix="fork-login-private-"))
    qmp = None
    started = False
    pinned_created = False
    def interrupted(signum, frame):
        raise InterruptedError("login proof interrupted; cleaning disposable guest")
    signal.signal(signal.SIGTERM, interrupted)
    try:
        report["source_image"] = identity(args.image)
        run(["podman", "run", "--rm", "--pull=never", "--entrypoint", "sh", args.image,
             "-ec", "command -v getent >/dev/null; if getent passwd " + USER + "; then exit 1; fi"], timeout=60)
        source = report["source_image"]["id"]
        # Corral 388342b treats only localhost/ and containers-storage: as
        # local. Pin this exact image ID under a private, unique localhost tag.
        run(["podman", "tag", source, pinned], timeout=30)
        pinned_created = True
        if identity(pinned)["id"] != source:
            raise ValueError("private source tag does not match the source image ID")
        probe = run(["bash", "-c", 'source "$1/scripts/lib/backend.sh"; probe_image_backend "$2" podman',
                     "bash", str(ROOT), pinned], timeout=60)
        filesystem = "ext4" if "SEALED=1" in probe.splitlines() else "xfs"
        password = "".join(choice(string.ascii_lowercase + string.digits) for _ in range(24))
        hashed = run(["openssl", "passwd", "-6", "-stdin"], input=password + "\n", timeout=10).strip()
        ssh_unit = "ssh.service" if "/grouper:" in args.image else "sshd.service"
        spec_path = private / "spec.yaml"
        spec_path.write_text(yaml.safe_dump(make_spec(pinned, name, private / "corral", filesystem, ssh_unit)))
        spec_path.chmod(0o600)
        report["typed_login"] = "running"
        started = True
        # Corral's raw logs, spec, layer and keypair stay outside upload roots.
        with (private / "corral.log").open("w") as log:
            result = subprocess.run([args.corral, "vmtest", name, "-f", str(spec_path)],
                                    text=True, stdout=log, stderr=subprocess.STDOUT, timeout=2400)
        raw = json.loads((private / "corral/result.json").read_text())
        report["corral_boot"] = {key: raw.get(key) for key in
                                 ("status", "exitCode", "ready", "readyBy", "bootSeconds", "kept")}
        if result.returncode != 0:
            failure = str(raw.get("failure", ""))
            report["corral_failure"] = failure.replace(password, "<redacted>").replace(hashed, "<redacted-hash>")[:1500]
            raise ValueError("derived canary boot failed; see corral_boot and serial.log")
        if not (raw.get("status") == "passed" and raw.get("ready") is True
                and raw.get("readyBy") == "ssh" and raw.get("kept") is True):
            raise ValueError("Corral did not leave the expected SSH-ready guest running")
        report["derived_image"] = identity(derived)
        if report["derived_image"]["id"] == source or not raw["layer"]["derived"] or raw["layer"]["base"] != pinned or identity(pinned)["id"] != source:
            raise ValueError("derived/source image identity was not preserved")
        install_password(raw["ssh"], private, hashed)
        report["test_account"] = {"name": USER, "password_set_in": "disposable booted guest only",
                                  "password_in_source_or_derived_image": False}
        observe = observer(raw["ssh"], private)
        baseline = observe()
        assert_no_login(baseline)
        qmp = QMP(Path.home() / ".local/share/corral/vms" / name / "qmp.sock")

        def screenshot(filename):
            path = out / filename
            run([args.corral, "screenshot", name, "-o", str(path), "--require-paint"], timeout=30)
            return path

        # Drive only visible controls. Never type a secret until the observed
        # GDM screen contains both this account and its Password prompt.
        deadline = time.monotonic() + 180
        selected = False
        while time.monotonic() < deadline:
            try:
                frame = screenshot("10-greeter.png")
            except subprocess.CalledProcessError:
                time.sleep(3)
                continue
            rows = words(frame)
            if find_word(rows, "password") and find_word(rows, USER):
                break
            if not selected and find_word(rows, "username"):
                qmp.type(USER)
                qmp.key("ret")
                selected = True
            elif not selected and find_word(rows, USER):
                # GDM selects its sole account tile with Enter. No virtual
                # tablet is assumed: pinned Corral exposes a PS/2 keyboard.
                qmp.key("ret")
                selected = True
            time.sleep(3)
        else:
            raise ValueError("could not verify the synthetic user's visible GDM Password prompt")
        before = observe()
        assert_no_login(before)
        (out / "before-login.json").write_text(json.dumps(before, indent=2) + "\n")
        screenshot("20-password-prompt.png")
        qmp.type(password)
        qmp.key("ret")
        password = ""
        report["input"] = {"transport": "QMP emulated keyboard", "password_typed": True,
                           "autologin": False, "account": USER}
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            after = observe()
            if session(after):
                validate_login(before, after)
                break
            time.sleep(3)
        else:
            screenshot("login-failed.png")
            raise ValueError("typed password did not produce a gdm-password GNOME desktop session")
        report["typed_login"] = "passed"
        report["authenticated_session"] = validate_login(before, after)
        (out / "after-login.json").write_text(json.dumps(after, indent=2) + "\n")
        qmp.key("esc")
        time.sleep(8)
        screenshot("30-desktop.png")
        final = observe()
        if validate_login(before, final)["Id"] != report["authenticated_session"]["Id"]:
            raise ValueError("desktop screenshot was not paired with the authenticated session")
        report["wallpaper_settings"] = final["wallpaper"]
        expected = "'" + WALLPAPER + "'"
        if any(final["wallpaper"].get(key) != expected for key in ("picture-uri", "picture-uri-dark")):
            raise ValueError("real logged-in user's wallpaper differs from the canary default")
        report["wallpaper_pixels"] = wallpaper_match(out / "30-desktop.png", args.wallpaper)
        report["wallpaper_render"] = "passed" if report["wallpaper_pixels"]["passed"] else "failed"
        if report["wallpaper_render"] != "passed":
            raise ValueError("the actual desktop framebuffer does not show enough canary wallpaper")
        if args.installer_artifact:
            report["installer_ui"] = "running"
            spec = importlib.util.spec_from_file_location("fork_installer", ROOT / "scripts/qualify-fork-installer.py")
            installer = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(installer)
            # Reuse this exact authenticated desktop and cleanup boundary.
            from types import SimpleNamespace
            harness = SimpleNamespace(run=run, ssh_command=ssh_command, validate_login=validate_login, words=words)
            installer.qualify(harness, raw["ssh"], private, args.installer_artifact,
                              out, screenshot, observe, before, report["authenticated_session"]["Id"],
                              report["source_image"]["id"], report.setdefault("installer", {}))
            report["installer_ui"] = "passed"
    except Exception as error:
        # Exception text can include tool argv, so never put password-bearing
        # commands in argv. All input of the synthetic password stays in memory.
        report["error"] = str(error)[:1500]
        if report["typed_login"] == "running":
            report["typed_login"] = "failed"
    finally:
        if report["typed_login"] == "running":
            report["typed_login"] = "failed"
        if report["installer_ui"] == "running":
            report["installer_ui"] = "failed"
            report.setdefault("installer", {})["status"] = "failed"
        errors = []
        if qmp:
            try:
                qmp.close()
            except OSError:
                errors.append("QMP observer close failed")
        serial = Path.home() / ".local/share/corral/vms" / name / "serial.log"
        if not serial.exists():
            serial = private / "corral/serial.log"
        if serial.exists():
            try:
                shutil.copyfile(serial, out / "serial.log")
            except OSError:
                errors.append("serial evidence copy failed")
        if started:
            report["vm_cleanup"] = delete_vm(args.corral, name)
            if not report["vm_cleanup"]["passed"]:
                errors.append("disposable VM deletion failed")
            try:
                exists = subprocess.run(["podman", "image", "exists", derived], capture_output=True, timeout=30)
                if exists.returncode == 0:
                    subprocess.run(["podman", "rmi", "--force", derived], capture_output=True, timeout=60)
                    if subprocess.run(["podman", "image", "exists", derived], capture_output=True, timeout=30).returncode == 0:
                        errors.append("derived image deletion failed")
            except (OSError, subprocess.TimeoutExpired):
                errors.append("derived image deletion failed")
        if pinned_created:
            try:
                # `untag IMAGE` removes ALL its names. Supply the exact extra
                # NAME separately so the original image and every alias survive.
                if subprocess.run(["podman", "untag", report["source_image"]["id"], pinned], capture_output=True, timeout=30).returncode != 0:
                    errors.append("private source tag cleanup failed")
                retained = identity(args.image)
                report["source_image_after_cleanup"] = retained
                if retained["id"] != report["source_image"]["id"]:
                    errors.append("source image tag changed during the proof")
                if not set(report["source_image"].get("repo_tags", [])).issubset(retained.get("repo_tags", [])):
                    errors.append("source image aliases changed during cleanup")
            except (OSError, subprocess.SubprocessError):
                errors.append("source image identity verification failed")
        # Only this run's mkdtemp directory, never a supplied or resolved path.
        try:
            shutil.rmtree(private)
        except OSError:
            errors.append("ephemeral key artifact cleanup failed")
        report["cleanup"] = "failed" if errors else "passed"
        if errors:
            report["cleanup_errors"] = errors
        for frame in out.glob("*.png"):
            report.setdefault("screenshots", {})[frame.name] = hashlib.sha256(frame.read_bytes()).hexdigest()
        (out / "login-proof.json").write_text(json.dumps(report, indent=2) + "\n")
    required = ["typed_login", "wallpaper_render", "cleanup"]
    if args.installer_artifact:
        required.append("installer_ui")
    print(json.dumps({key: report[key] for key in required}))
    return 0 if all(report[key] == "passed" for key in required) else 1


if __name__ == "__main__":
    raise SystemExit(main())
