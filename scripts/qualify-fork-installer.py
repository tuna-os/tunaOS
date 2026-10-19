#!/usr/bin/env python3
"""Frozen installer artifact and visible-wizard proof for disposable GNOME guests.

The download command is host-only. The login harness imports qualify() only
when --installer-artifact is supplied. This never drives the Install action.
"""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

REPOSITORY = "tuna-os/bootc-installer"
RUN_ID = 39191155314
ARTIFACT_ID = 12160008700
SOURCE_HEAD = "c037f9b71a651bc42027db0cab21fe5cca72261f"
TESTED_MERGE = "eebc9fa608875f5f5ad33a187e64245711908d34"
ZIP_SHA256 = "49f0185d567dc94604d583785fc00aeb7ed2275b4a0e7dda2b6f728eb93075d6"
APP = "org.bootcinstaller.Installer"
BUNDLE_NAME = APP + ".flatpak"
API = "https://api.github.com/repos/" + REPOSITORY
LIMIT = 128 * 1024 * 1024
BRANDING = "/etc/bootc-installer/branding.json"
LOGO = "/usr/share/pixmaps/tunaos.svg"


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_metadata(artifact, run):
    expected = {"id": ARTIFACT_ID, "name": BUNDLE_NAME, "expired": False,
                "digest": "sha256:" + ZIP_SHA256}
    if any(artifact.get(k) != v for k, v in expected.items()):
        raise ValueError("artifact metadata differs from the frozen installer artifact")
    source = artifact.get("workflow_run", {})
    if source.get("id") != RUN_ID or source.get("head_sha") != SOURCE_HEAD:
        raise ValueError("artifact run/head provenance differs from the frozen installer")
    if (run.get("id") != RUN_ID or run.get("head_sha") != SOURCE_HEAD
            or run.get("repository", {}).get("full_name") != REPOSITORY
            or run.get("event") != "pull_request"):
        raise ValueError("workflow run source provenance differs from the frozen installer")
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        raise ValueError("frozen artifact workflow run has not completed successfully")
    return {"repository": REPOSITORY, "run_id": RUN_ID, "artifact_id": ARTIFACT_ID,
            "artifact_name": BUNDLE_NAME, "source_head": SOURCE_HEAD,
            "recorded_tested_merge": TESTED_MERGE, "api_verified_source_head": SOURCE_HEAD,
            "archive_sha256": ZIP_SHA256,
            "run_status": run.get("status"), "run_conclusion": run.get("conclusion")}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def api_request(path, token):
    # Never put the token in argv, a URL, a file, the guest, or an error message.
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        return urllib.request.build_opener(NoRedirect()).open(
            urllib.request.Request(API + path, headers=headers), timeout=60)
    except urllib.error.HTTPError as error:
        if error.code == 302 and path.endswith("/zip"):
            return error
        raise RuntimeError(f"GitHub artifact API denied or failed: HTTP {error.code} at {path}") from None
    except urllib.error.URLError:
        raise RuntimeError("GitHub artifact API transport failed") from None


def public_archive_url(url):
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname or ""
    if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443)
            or not (host.endswith(".blob.core.windows.net") or host.endswith(".githubusercontent.com"))):
        raise ValueError("artifact redirect is not an admitted HTTPS GitHub artifact storage endpoint")
    return url


class ArchiveRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        public_archive_url(new_url)
        return super().redirect_request(request, fp, code, message, headers, new_url)


def unpack(archive, directory):
    if Path(archive).stat().st_size > LIMIT or sha256(archive) != ZIP_SHA256:
        raise ValueError("installer artifact ZIP checksum does not match the frozen artifact")
    with zipfile.ZipFile(archive) as zipped:
        members = zipped.infolist()
        if len(members) != 1:
            raise ValueError("installer artifact must contain exactly its Flatpak bundle")
        member = members[0]
        mode = member.external_attr >> 16
        if (member.filename != BUNDLE_NAME or member.is_dir() or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                or member.flag_bits & 1 or not 0 < member.file_size <= LIMIT):
            raise ValueError("unsafe or unexpected member in installer artifact ZIP")
        destination = Path(directory) / BUNDLE_NAME
        with zipped.open(member) as source, destination.open("xb") as output:
            shutil.copyfileobj(source, output)
    return destination, {"archive_sha256": ZIP_SHA256, "bundle_sha256": sha256(destination),
                         "bundle_bytes": destination.stat().st_size}


def download(output):
    output.mkdir(parents=True, exist_ok=False)
    token = os.environ.get("GITHUB_TOKEN", "")
    with api_request("/actions/artifacts/" + str(ARTIFACT_ID), token) as response:
        artifact = json.loads(response.read(1024 * 1024))
    with api_request("/actions/runs/" + str(RUN_ID), token) as response:
        workflow = json.loads(response.read(1024 * 1024))
    receipt = validate_metadata(artifact, workflow)
    with api_request("/actions/artifacts/" + str(ARTIFACT_ID) + "/zip", token) as response:
        if response.code != 302:
            raise ValueError("GitHub artifact API did not return its expected archive redirect")
        url = public_archive_url(response.headers.get("Location", ""))
    token = ""
    archive = output / "installer-artifact.zip"
    try:
        # Separate request/opener: Authorization is never forwarded to storage.
        with urllib.request.build_opener(ArchiveRedirect()).open(url, timeout=60) as response, archive.open("xb") as stream:
            count = 0
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                if count > LIMIT:
                    raise ValueError("installer artifact exceeds the bounded download size")
                stream.write(chunk)
    except urllib.error.URLError:
        raise RuntimeError("GitHub artifact storage download failed") from None
    _, checksums = unpack(archive, output)
    receipt.update(checksums)
    (output / "artifact-provenance.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


# Run only through the login harness's admitted ephemeral loopback SSH.
# Session environment is allowlisted from the observed GNOME user manager, not invented
# or imported from the host's token-bearing environment.
GUEST_COMMON = r'''
import configparser, hashlib, json, os, pwd, stat, subprocess, time
from pathlib import Path
APP = "org.bootcinstaller.Installer"
user = pwd.getpwnam("canary")
uid = user.pw_uid
runtime = Path("/run/user") / str(uid)
def run(args, timeout=30):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError("guest command failed (" + args[0] + "): " + result.stderr[-3000:])
    return result.stdout.strip()
def user_env():
    shells = []
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            if proc.stat().st_uid == uid and (proc / "comm").read_text().strip() == "gnome-shell":
                shells.append(proc)
        except OSError:
            continue
    if len(shells) != 1:
        raise ValueError("expected one real canary gnome-shell")
    # GNOME exports its display to the user manager after starting. The
    # compositor process's initial /proc/environ need not contain its socket.
    manager = run(["runuser", "-u", "canary", "--", "env", "-i",
                   "PATH=/usr/bin:/bin", "XDG_RUNTIME_DIR=" + str(runtime),
                   "DBUS_SESSION_BUS_ADDRESS=unix:path=" + str(runtime / "bus"),
                   "systemctl", "--user", "show-environment"])
    inherited = dict(item.split("=", 1) for item in manager.splitlines() if "=" in item)
    env = {"HOME": user.pw_dir, "USER": user.pw_name, "LOGNAME": user.pw_name,
           "PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8",
           "XDG_RUNTIME_DIR": str(runtime), "DBUS_SESSION_BUS_ADDRESS": "unix:path=" + str(runtime / "bus")}
    for key in ("WAYLAND_DISPLAY", "DISPLAY", "XAUTHORITY", "XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP"):
        if key in inherited:
            env[key] = inherited[key]
    display = env.get("WAYLAND_DISPLAY", "")
    if not display or "/" in display or not stat.S_ISSOCK((runtime / display).stat().st_mode):
        raise ValueError("real logged-in Wayland socket is not available")
    return ["runuser", "-u", "canary", "--", "env", "-i"] + [k + "=" + v for k, v in env.items()]
def instances():
    found = []
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            if proc.stat().st_uid != uid:
                continue
            command = (proc / "cmdline").read_bytes().split(b"\0")
            if b"/app/bin/bootc-installer" not in command:
                continue
            info = configparser.ConfigParser(interpolation=None)
            info.read_string((proc / "root/.flatpak-info").read_text())
            if info["Application"]["name"] == APP:
                found.append({"pid": int(proc.name), "uid": uid, "application": APP,
                              "app_commit": info["Instance"].get("app-commit", ""),
                              "runtime_commit": info["Instance"].get("runtime-commit", "")})
        except (OSError, KeyError, configparser.Error):
            continue
    return found
'''

GUEST_INSTALL = GUEST_COMMON + r'''
expected = __BUNDLE_SHA__
bundle = Path("/var/tmp/fork-installer.flatpak")
with bundle.open("rb") as stream:
    if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
        raise ValueError("guest bundle checksum differs from the verified artifact")
run(["flatpak", "remote-add", "--system", "--if-not-exists", "flathub", "https://flathub.org/repo/flathub.flatpakrepo"], 120)
run(["flatpak", "install", "--system", "--noninteractive", "-y", "flathub", "org.gnome.Platform//50"], 1200)
run(["flatpak", "install", "--system", "--noninteractive", "--reinstall", "-y", str(bundle)], 600)
commit = run(["flatpak", "info", "--system", "--show-commit", APP])
runtime_ref = run(["flatpak", "info", "--system", "--show-runtime", APP])
metadata = run(["flatpak", "info", "--system", "--show-metadata", APP])
if runtime_ref != "org.gnome.Platform/x86_64/50":
    raise ValueError("unexpected installer runtime")
info = configparser.ConfigParser(interpolation=None)
info.read_string(metadata)
if info["Application"].get("command") != "bootc-installer":
    raise ValueError("artifact has an unexpected normal entrypoint")
print(json.dumps({"app_commit": commit, "runtime": runtime_ref, "bundle_sha256": expected,
                  "entrypoint": "bootc-installer", "installation": "system in disposable guest"}))
'''

GUEST_LAUNCH = GUEST_COMMON + r'''
if instances():
    raise ValueError("installer was already running before normal launch")
paths = [runtime / "tuna-installer-ready", runtime / "app" / APP / "tuna-installer-ready"]
if any(p.exists() for p in paths):
    raise ValueError("installer readiness stamp predates normal launch")
command = user_env() + ["flatpak", "run", "--system", APP]
started = time.time()
with open("/var/tmp/fork-installer.log", "w") as log:
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                               stderr=subprocess.STDOUT, start_new_session=True)
print(json.dumps({"started_at": started, "launcher_pid": process.pid, "uid": uid,
                  "application": APP, "normal_entrypoint": True, "command_override": False}))
'''

GUEST_OBSERVE = GUEST_COMMON + r'''
stamps = []
for path in (runtime / "tuna-installer-ready", runtime / "app" / APP / "tuna-installer-ready"):
    if path.exists():
        data = dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)
        stamps.append({"fields": data, "uid": path.stat().st_uid})
print(json.dumps({"instances": instances(), "stamps": stamps}))
'''


def validate_window(observation, launched, installed):
    processes = [p for p in observation["instances"] if p["uid"] == launched["uid"]
                 and p["application"] == APP and p["app_commit"] == installed["app_commit"]]
    stamps = [s for s in observation["stamps"] if s["uid"] == launched["uid"]
              and s["fields"].get("app_id") == APP and s["fields"].get("window") == "BootcWindow"
              and s["fields"].get("signal") == "gtk-map"
              and float(s["fields"].get("mapped_at", "0")) >= launched["started_at"] - .001]
    return bool(processes and stamps)


def logo_reference(svg, png):
    """Read only the self-contained PNG wrapper generated by our canary builder."""
    from PIL import Image
    matches = re.findall(r'data:image/png;base64,([A-Za-z0-9+/=]+)', svg)
    if len(matches) != 1:
        raise ValueError("source image logo is not the expected self-contained raster SVG")
    data = base64.b64decode(matches[0], validate=True)
    with Image.open(io.BytesIO(data)) as image:
        if image.size != (128, 128):
            raise ValueError("source logo is not the 128-pixel qualification fixture")
        pixels = image.convert("RGB")
        if pixels.getextrema() != ((235, 235), (146, 146), (45, 45)):
            raise ValueError("source logo is not the exact qualification fixture")
        pixels.save(png)
    return hashlib.sha256(svg.encode()).hexdigest()


def visible_branding(frame, reference, rows):
    """Pair the welcome heading with a reference-matched square above it.

    This is deliberately specific to the solid 128px qualification logo. Color
    alone, unrelated orange rectangles, and an app title without welcome copy
    cannot earn a pass. Different logos need a different pixel matcher.
    """
    from PIL import Image, ImageChops
    lines = {}
    for row in rows:
        key = tuple(row.get(k, "") for k in ("page_num", "block_num", "par_num", "line_num"))
        lines.setdefault(key, []).append(row)
    heading = []
    install = []
    for line in lines.values():
        normalized = " ".join(re.sub(r"[^a-z0-9]", "", r["text"].lower()) for r in line)
        if normalized == "welcome to harbor canary":
            heading.append(line)
        if normalized == "install harbor canary":
            install.append(line)
    if len(heading) != 1 or len(install) != 1:
        return {"passed": False, "reason": "unique welcome heading and install row are not both visible"}
    line = heading[0]
    left = min(int(r["left"]) for r in line)
    right = max(int(r["left"]) + int(r["width"]) for r in line)
    top = min(int(r["top"]) for r in line)
    center = (left + right) / 2
    with Image.open(reference) as source, Image.open(frame) as screenshot:
        reference_image = source.convert("RGB")
        image = screenshot.convert("RGB")
        expected = reference_image.getpixel((64, 64))
        candidates = []
        # Bound the component search to the heading's column and immediately
        # above it, where the real 128px BootcPageHeader logo is laid out.
        x0, x1 = max(0, int(center - 180)), min(image.width, int(center + 180))
        y0, y1 = max(0, top - 360), max(0, top - 5)
        pixels = image.load()
        remaining = {(x, y) for y in range(y0, y1) for x in range(x0, x1)
                     if max(abs(pixels[x, y][c] - expected[c]) for c in range(3)) <= 8}
        while remaining:
            seed = remaining.pop()
            component, todo = [seed], [seed]
            while todo:
                x, y = todo.pop()
                for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if neighbor in remaining:
                        remaining.remove(neighbor)
                        component.append(neighbor)
                        todo.append(neighbor)
            if len(component) < 64 * 64:
                continue
            xs, ys = zip(*component)
            box = min(xs), min(ys), max(xs) + 1, max(ys) + 1
            w, h = box[2] - box[0], box[3] - box[1]
            if not (64 <= w <= 256 and 64 <= h <= 256 and abs(w - h) <= 3
                    and abs((box[0] + box[2]) / 2 - center) <= 12 and 5 <= top - box[3] <= 100):
                continue
            actual = image.crop(box).resize(reference_image.size)
            diff = ImageChops.difference(actual, reference_image)
            matching = sum(max(p) <= 8 for p in diff.getdata()) / (128 * 128)
            if matching >= .98:
                candidates.append({"bounds": box, "reference_matching_fraction": matching})
    return {"passed": len(candidates) == 1, "welcome_heading": "Welcome to Harbor Canary",
            "install_row": "Install Harbor Canary", "logo_matches": candidates,
            "reference_sha256": sha256(reference), "minimum_reference_matching_fraction": .98}


def qualify(harness, access, private, archive, out, screenshot, observe, before, session_id, source_image, report):
    report.update({"status": "running", "installer_committed_install": "not-run",
                   "installed_target_identity": "not-run", "production_installer_qualified": False})
    bundle, checksums = unpack(archive, private)
    report["artifact"] = {"repository": REPOSITORY, "run_id": RUN_ID, "artifact_id": ARTIFACT_ID,
                          "source_head": SOURCE_HEAD, "recorded_tested_merge": TESTED_MERGE,
                          "provenance_basis": "frozen artifact binding by pinned ZIP digest; checkout merge not reverified", **checksums}
    ssh = harness.ssh_command(access, private)

    def guest(source, timeout=90):
        try:
            return json.loads(harness.run(ssh + ["python3 -"], input=source, timeout=timeout))
        except subprocess.CalledProcessError as error:
            # Guest-only diagnostics: no host token or synthetic login secret
            # is present in these observer/install scripts or their arguments.
            report["guest_error"] = (error.stderr or "")[-6000:]
            raise

    # Capture the deployed image's own identity assets. No branding override or
    # mock recipe is supplied to the app, and the source files are never edited.
    branding = json.loads(harness.run(ssh + ["cat " + BRANDING], timeout=30))
    if branding.get("name") != "Harbor Canary" or branding.get("logo") != LOGO:
        raise ValueError("guest branding does not match the built canary identity")
    svg = harness.run(ssh + ["cat " + LOGO], timeout=30)
    source_branding = json.loads(harness.run(["podman", "run", "--rm", "--pull=never", "--entrypoint", "cat",
                                             source_image, BRANDING], timeout=60))
    source_svg = harness.run(["podman", "run", "--rm", "--pull=never", "--entrypoint", "cat",
                              source_image, LOGO], timeout=60)
    if branding != source_branding or svg != source_svg:
        raise ValueError("guest identity assets differ from the pinned source image")
    reference = out / "installer-logo-reference.png"
    report["source_image_id"] = source_image
    report["guest_logo_sha256"] = logo_reference(svg, reference)
    report["source_logo_sha256"] = hashlib.sha256(source_svg.encode()).hexdigest()
    # SSH stdin transports bytes; the host's environment/token never enters VM.
    with bundle.open("rb") as stream:
        subprocess.run(ssh + ["umask 077; cat > /var/tmp/fork-installer.flatpak"],
                       stdin=stream, capture_output=True, check=True, timeout=180)
    report["installed_bundle"] = guest(GUEST_INSTALL.replace("__BUNDLE_SHA__", repr(checksums["bundle_sha256"])), 2100)
    report["launch"] = guest(GUEST_LAUNCH)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        current = observe()
        if harness.validate_login(before, current)["Id"] != session_id:
            raise ValueError("installer proof lost the authenticated desktop session")
        observed = guest(GUEST_OBSERVE)
        frame = screenshot("40-installer-welcome.png")
        pixels = visible_branding(frame, reference, harness.words(frame))
        report["observed_window"] = observed
        report["visible_branding"] = pixels
        if validate_window(observed, report["launch"], report["installed_bundle"]) and pixels["passed"]:
            report["status"] = "passed"
            return
        time.sleep(3)
    report["guest_application_log"] = harness.run(ssh + ["tail -c 12000 /var/tmp/fork-installer.log"], timeout=30)
    raise ValueError("normal installer did not show a mapped GNOME wizard with the built fork name and reference logo")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = download(args.download_output)
    except Exception as error:
        parser.exit(1, str(error) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
