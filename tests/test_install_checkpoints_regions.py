"""Region OCR and artwork-identity corpus for scripts/install-checkpoints.py.

Every case in tests/fixtures/install-checkpoints-v1/regions/cases.json runs the
real script as a subprocess over an evidence directory composed here from the
fixture artwork. As in test_install_checkpoints_corpus.py, only the external
tools are stubbed on PATH: `tesseract` serves the case's transcript for a frame
or for the region crop the script itself wrote, and `magick` measures the
frame's real pixels. Cropping, rendering the expected asset and the
perceptual-hash comparison all run in the script, unpatched.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("yaml", reason="the script reads its contract with PyYAML")
Image = pytest.importorskip("PIL.Image", reason="frames are composed with Pillow")
from PIL import ImageFilter  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install-checkpoints.py"
CORPUS = ROOT / "tests" / "fixtures" / "install-checkpoints-v1" / "regions"
CASES = json.loads((CORPUS / "cases.json").read_text())
FRAME_SIZE = (640, 400)
LOGO_BOX = (0.6, 0.1, 0.25, 0.4)  # contract.yaml's logo region

STUB_MAGICK = """\
import sys
from PIL import Image, ImageStat

argv = sys.argv[1:]
if argv[-1:] == ["info:"] and "-format" in argv:
    with Image.open(argv[0]) as img:
        print(f"{ImageStat.Stat(img.convert('L')).stddev[0] / 255:.6f}")
    sys.exit(0)
sys.exit(1)
"""

STUB_TESSERACT = """\
import json, os, sys

with open({stub!r}) as f:
    text = json.load(f).get(os.path.basename(sys.argv[1]))
if text is None:
    sys.exit(1)
sys.stdout.write(text)
"""


def _load_module():
    spec = importlib.util.spec_from_file_location("install_checkpoints_regions", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compose(path: Path, frame: dict) -> None:
    img = Image.new("RGB", FRAME_SIZE, (90, 90, 90))
    if frame.get("wallpaper"):
        with Image.open(CORPUS / frame["wallpaper"]) as wp:
            img = wp.convert("RGB").resize(FRAME_SIZE)
    if frame.get("logo"):
        x, y, w, h = LOGO_BOX
        box = (round(x * FRAME_SIZE[0]), round(y * FRAME_SIZE[1]),
               round((x + w) * FRAME_SIZE[0]), round((y + h) * FRAME_SIZE[1]))
        with Image.open(CORPUS / frame["logo"]) as logo:
            mark = logo.convert("RGB").resize((box[2] - box[0], box[3] - box[1]))
        if frame.get("blur"):
            mark = mark.filter(ImageFilter.GaussianBlur(2))
        img.paste(mark, box[:2])
    img.save(path)


def stub(bindir: Path, name: str, source: str) -> None:
    tool = bindir / name
    tool.write_text(f"#!{sys.executable}\n{source}")
    tool.chmod(0o755)


def run_script(tmp_path: Path, spec: Path, args: list[str], tools: list[str],
               frames: dict, extra_tools: dict | None = None):
    evidence = tmp_path / "evidence"
    bindir = tmp_path / "bin"
    evidence.mkdir()
    bindir.mkdir()
    transcripts = {}
    for name, frame in frames.items():
        if "same_as" not in frame:
            compose(evidence / f"{name}.png", frame)
        transcripts[f"{name}.png"] = frame.get("ocr", "")
        for rid, text in frame.get("region_ocr", {}).items():
            transcripts[f"{name}.region-{rid}.png"] = text
    for name, frame in frames.items():
        if "same_as" in frame:
            shutil.copyfile(evidence / f"{frame['same_as']}.png", evidence / f"{name}.png")
            transcripts[f"{name}.png"] = frames[frame["same_as"]].get("ocr", "")
    ocr_stub = tmp_path / "ocr-stub.json"
    ocr_stub.write_text(json.dumps(transcripts))
    if "magick" in tools:
        stub(bindir, "magick", STUB_MAGICK)
    if "tesseract" in tools:
        stub(bindir, "tesseract", STUB_TESSERACT.format(stub=str(ocr_stub)))
    for name, target in (extra_tools or {}).items():
        (bindir / name).symlink_to(target)
    env = {k: v for k, v in os.environ.items()
           if k not in ("FLAVOR", "VARIANT", "TUNAOS_CHECKPOINT_NO_GPU")}
    env["PATH"] = str(bindir)  # only the stubs: host tools must not leak in
    summary = tmp_path / "summary.json"
    r = subprocess.run(
        [sys.executable, str(SCRIPT), str(evidence), "--spec", str(spec),
         "--json", str(summary), *args],
        capture_output=True, text=True, env=env, check=False)
    return r.returncode, r.stdout + r.stderr, summary, evidence


def _setup(case: dict) -> dict:
    base = CASES["baseline"]
    frames = dict(base["frames"])
    for name, frame in case.get("frames", {}).items():
        if frame is None:
            frames.pop(name, None)
        else:
            frames[name] = frame
    return {"spec": CORPUS / case.get("spec", base["spec"]),
            "args": case.get("args", base["args"]),
            "tools": case.get("tools", base["tools"]),
            "frames": frames}


@pytest.mark.parametrize("case", CASES["runs"], ids=[c["name"] for c in CASES["runs"]])
def test_region_case(tmp_path, case):
    s = _setup(case)
    rc, log, summary_path, _ = run_script(tmp_path, s["spec"], s["args"], s["tools"],
                                          s["frames"])
    expect = case["expect"]
    assert rc == expect["exit"], log

    summary = json.loads(summary_path.read_text())
    records = {r["id"]: r for r in summary["checkpoints"]}
    got = {cid: [r["outcome"], r["reason"]] for cid, r in records.items()}
    assert got == expect["checkpoints"], log
    got_regions = {cid: {g["id"]: [g["outcome"], g["reason"]] for g in r["regions"]}
                   for cid, r in records.items() if "regions" in r}
    assert got_regions == expect["regions"], log

    lines = log.splitlines()
    for line in expect.get("tap", []):
        assert line in lines, log
    for cid, regions in got_regions.items():
        # Identity that could not be judged is never a pass.
        if any(o != "passed" for o, _ in regions.values()):
            assert records[cid]["outcome"] != "passed", log
        if records[cid]["required"] and records[cid]["outcome"] != "passed":
            assert rc != 0, log


def test_region_crops_are_left_as_evidence(tmp_path):
    s = _setup({})
    rc, log, _, evidence = run_script(tmp_path, s["spec"], s["args"], s["tools"], s["frames"])
    assert rc == 0, log
    for rid in ("name", "logo", "wallpaper"):
        assert (evidence / f"about.region-{rid}.png").is_file()
    assert "Marlin" in (evidence / "about.region-name.ocr.txt").read_text()


SHARED_FRAME_SPEC = """\
schema_version: 1
checkpoints:
  - id: live-desktop
    phase: live
    frames: ["10-ready"]
    keywords: ["this wizard will guide"]
  - id: installed-login
    phase: installed
    frames: ["30-installed", "installed-desktop"]
    keywords: ["password"]
    distinct_from: [live-desktop]
  - id: installed-desktop
    phase: installed
    frames: ["installed-desktop"]
    distinct_from: [installed-login]
"""


def _shared_frames(stale_login: bool) -> dict:
    frames = {"10-ready": CASES["baseline"]["frames"]["10-ready"],
              "installed-desktop": {"wallpaper": "wallpaper-marlin.png", "ocr": "Password"}}
    if stale_login:
        frames["installed-desktop"] = {"same_as": "10-ready"}
    return frames


def test_one_file_listed_by_two_checkpoints_is_not_stale(tmp_path):
    spec = tmp_path / "spec.yaml"
    spec.write_text(SHARED_FRAME_SPEC)
    rc, log, summary, _ = run_script(tmp_path, spec, ["--flavor", "gnome"],
                                     ["magick", "tesseract"], _shared_frames(False))
    outcomes = {r["id"]: r["outcome"] for r in json.loads(summary.read_text())["checkpoints"]}
    assert outcomes == {"live-desktop": "passed", "installed-login": "passed",
                        "installed-desktop": "passed"}, log
    assert rc == 0, log


def test_stale_frame_detected_when_earlier_phase_is_filtered_out(tmp_path):
    spec = tmp_path / "spec.yaml"
    spec.write_text(SHARED_FRAME_SPEC)
    rc, log, summary, _ = run_script(tmp_path, spec,
                                     ["--flavor", "gnome", "--phase", "installed"],
                                     ["magick", "tesseract"], _shared_frames(True))
    got = {r["id"]: [r["outcome"], r["reason"]]
           for r in json.loads(summary.read_text())["checkpoints"]}
    assert got["installed-login"] == ["failed", "frame-stale"], log
    assert "not ok - [installed-login] frame differs from live-desktop" in log.splitlines()


def test_corpus_covers_every_region_outcome():
    seen = {o for case in CASES["runs"] for regions in case["expect"]["regions"].values()
            for o, _ in regions.values()}
    assert seen == {"passed", "failed", "blocked", "not-run"}


def test_fixture_artwork_is_distinguishable():
    """The negative controls only mean something if the swapped artwork is far
    outside the contract's threshold and the right artwork well inside it."""
    mod = _load_module()

    def h(name, box=None):
        with Image.open(CORPUS / name) as img:
            img = img.convert("RGB")
            if box:
                img = img.crop(mod._pixel_box(img.size, box))
            return mod.dhash(img)

    def dist(a, b):
        return bin(a ^ b).count("1")

    strip = [0.0, 0.6, 1.0, 0.4]
    assert dist(h("logo-marlin.png"), h("logo-bonito.png")) > 20
    assert dist(h("logo-marlin.png"), h("other-app.png")) > 20
    assert dist(h("wallpaper-marlin.png", strip), h("wallpaper-bonito.png", strip)) > 20


@pytest.mark.skipif(not shutil.which("rsvg-convert"), reason="rsvg-convert not installed")
def test_svg_asset_renders_and_matches_with_rsvg_convert(tmp_path):
    frames = dict(CASES["baseline"]["frames"])
    rc, log, summary_path, _ = run_script(
        tmp_path, CORPUS / "contract-svg.yaml", ["--flavor", "gnome", "--variant", "marlin"],
        ["magick", "tesseract"], frames,
        extra_tools={"rsvg-convert": shutil.which("rsvg-convert")})
    assert rc == 0, log
    record = json.loads(summary_path.read_text())["checkpoints"][0]
    assert [record["outcome"], record["regions"][0]["outcome"]] == ["passed", "passed"]


def test_region_without_pillow_is_blocked(tmp_path, monkeypatch):
    mod = _load_module()
    frame = tmp_path / "about.png"
    compose(frame, CASES["baseline"]["frames"]["about"])
    monkeypatch.setattr(mod, "_pil_image", lambda: None)
    region = {"id": "logo", "box": list(LOGO_BOX),
              "artwork": {"asset": "x.png", "max_distance": 10}}
    result = mod.judge_region("about", region, [str(frame)], "marlin", enforced=True)
    assert (result["outcome"], result["reason"]) == ("blocked", "pillow-unavailable")


def journey_fixture(tmp_path):
    """Operation-order fixture only: never published-image runtime evidence."""
    mod = _load_module()
    journey = object.__new__(mod.InstalledJourney)
    journey.args = SimpleNamespace(flavor="gnome", variant="yellowfin")
    journey.root = str(tmp_path)
    journey.path = str(tmp_path / "visual-journey.json")
    journey.deadline = mod.time.monotonic() + 10
    journey.user = "tunaose2e"
    journey.assets = mod.journey_assets("yellowfin")
    journey.receipt = {
        "operations": [], "assertions": [], "first_failure": None, "boot_id": "fixture-boot",
        "os_release": {"LOGO": "tunaos"},
        "asset_sha256": {role: journey.digest(ROOT / journey.assets[role])
                         for role in ("mark", "about", "wallpaper", "splash")},
    }
    return mod, journey


def test_plain_install_does_not_require_visual_phase(tmp_path, monkeypatch):
    mod = _load_module()
    spec = {"schema_version": 1, "checkpoints": [
        {"id": "visual-about", "phase": "visual", "required": True, "frames": ["absent"]},
    ]}
    monkeypatch.setattr(mod, "load_spec", lambda _: spec)
    monkeypatch.setattr(mod, "contact_sheet", lambda *args: False)
    monkeypatch.setattr(sys, "argv", ["install-checkpoints.py", str(tmp_path)])
    assert mod.main() == 0
    summary = json.loads((tmp_path / "install-checkpoints-gnome.json").read_text())
    assert summary["checkpoints"] == []
    assert summary["visual_journey"] is None


def test_opted_in_journey_cannot_pass_without_receipt_and_final_capture(tmp_path, monkeypatch):
    mod = _load_module()
    spec = {"schema_version": 1, "checkpoints": [
        {"id": "visual-about", "phase": "visual", "required": True, "frames": ["absent"]},
    ]}
    monkeypatch.setattr(mod, "load_spec", lambda _: spec)
    monkeypatch.setattr(mod, "contact_sheet", lambda *args: False)
    monkeypatch.setattr(sys, "argv", ["install-checkpoints.py", str(tmp_path),
                                    "--visual-journey", "--variant", "yellowfin"])
    assert mod.main() != 0
    summary = json.loads((tmp_path / "install-checkpoints-gnome.json").read_text())
    assert summary["outcome"] == "failed"
    assert summary["checkpoints"][0]["outcome"] == "blocked"
    assert summary["visual_journey"] is None


def test_authentication_timeout_never_captures_secret_surface(tmp_path, monkeypatch):
    _, journey = journey_fixture(tmp_path)
    captures = []
    commands = []

    def observe(command):
        commands.append(command)
        if command == "id -u":
            return "1000"
        return "Class=greeter\nName=gdm\nActive=yes\nDesktop=gnome"

    def await_predicate(predicate):
        assert not predicate()
        raise TimeoutError("fixture authentication deadline")

    monkeypatch.setattr(journey, "observe_state", observe)
    monkeypatch.setattr(journey, "await_predicate", await_predicate)
    monkeypatch.setattr(journey, "capture", lambda *args, **kwargs: captures.append(args[0]))
    assert not journey.session()
    assert captures == []
    assert not any("gnome-control-center " in command for command in commands)
    assert journey.receipt["first_failure"]["id"] == "authenticated-gnome-session"


@pytest.mark.parametrize("wrong_window", [False, True])
def test_actual_about_launch_uses_existing_session_and_owned_application(tmp_path, monkeypatch, wrong_window):
    _, journey = journey_fixture(tmp_path)
    captures, commands = [], []

    def observe(command):
        commands.append(command)
        if command == "id -u":
            return "1000"
        if command.startswith("loginctl"):
            return "Class=user\nType=wayland\nActive=yes\nState=active\nLockedHint=no\nDesktop=gnome\nName=tunaose2e\nUser=1000"
        if command == "cat /proc/sys/kernel/random/boot_id":
            return "fixture-boot"
        if "gsettings get org.gnome.desktop.background" in command:
            return "'file:///usr/share/backgrounds/tunaos/tunaos-default.jpg'"
        if command.startswith("sha256sum /usr/share/backgrounds"):
            return journey.receipt["asset_sha256"]["wallpaper"] + "  wallpaper"
        if command.endswith("gnome-control-center --list"):
            return "system\nbackground\nnetwork"
        if "is-active" in command:
            return "active"
        if "MainPID" in command:
            return "4242"
        if command.startswith("readlink"):
            return "/usr/bin/other-application" if wrong_window else "/usr/bin/gnome-control-center"
        if command.startswith("sha256sum /proc/"):
            return "settings-exe-sha256"
        if command.startswith("sha256sum '/usr/share/icons") or command.startswith("sha256sum '/usr/share/pixmaps"):
            return journey.receipt["asset_sha256"]["about"] + "  tunaos.svg"
        return ""

    monkeypatch.setattr(journey, "observe_state", observe)
    monkeypatch.setattr(journey, "await_predicate", lambda predicate: predicate() or pytest.fail("not ready"))
    monkeypatch.setattr(journey, "monitor_action", lambda _: None)
    monkeypatch.setattr(journey, "capture", lambda label, **kwargs: captures.append(label))
    assert journey.session() is not wrong_window
    assert captures == (["visual-session", "visual-wallpaper"] if wrong_window else
                        ["visual-session", "visual-wallpaper", "visual-about"])
    assert any("gnome-control-center system about" in command for command in commands)
    assert not any("dbus-run-session" in command for command in commands)
    assert any("stop tunaos-visual-about.service" in command for command in commands)


def test_wrong_consumed_wallpaper_never_captures_a_passing_wallpaper(tmp_path, monkeypatch):
    _, journey = journey_fixture(tmp_path)
    captures = []

    def observe(command):
        if command == "id -u":
            return "1000"
        if command.startswith("loginctl"):
            return "Class=user\nActive=yes\nState=active\nLockedHint=no\nDesktop=gnome\nName=tunaose2e\nUser=1000"
        if command == "cat /proc/sys/kernel/random/boot_id":
            return "fixture-boot"
        if "gsettings get org.gnome.desktop.background" in command:
            return "'file:///usr/share/backgrounds/tunaos/another-variant.jpg'"
        if "gnome-control-center --list" in command:
            return ""
        return ""

    monkeypatch.setattr(journey, "observe_state", observe)
    monkeypatch.setattr(journey, "await_predicate", lambda predicate: predicate() or pytest.fail("not ready"))
    monkeypatch.setattr(journey, "capture", lambda label, **kwargs: captures.append(label))
    assert not journey.session()
    assert captures == ["visual-session"]
    assertion = next(row for row in journey.receipt["assertions"]
                     if row["id"] == "fresh-session-wallpaper-consumer")
    assert assertion["outcome"] == "failed"
    assert "noncanonical wallpaper" in assertion["reason"]


def test_observer_stop_failure_withholds_boot_capture_and_credentials(tmp_path, monkeypatch):
    _, journey = journey_fixture(tmp_path)
    captures = []

    def unavailable():
        raise RuntimeError("owned capture child survived")

    monkeypatch.setattr(journey, "pause_observers", unavailable)
    monkeypatch.setattr(journey, "capture", lambda *args, **kwargs: captures.append(args[0]))
    assert not journey.boot()
    assert captures == []
    assert journey.receipt["first_failure"]["id"] == "secret-entry-observers-stopped"


def test_recorder_stop_waits_for_owned_parent_and_capture_child(tmp_path, monkeypatch):
    mod, journey = journey_fixture(tmp_path)
    recorder = tmp_path / "timelapse"
    recorder.mkdir()
    process = subprocess.Popen(
        [sys.executable, "-c",
         "import subprocess,sys,time; "
         "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
         "print(child.pid,flush=True); time.sleep(60)"],
        stdout=subprocess.PIPE, text=True)
    child = int(process.stdout.readline())
    (recorder / ".recorder.pid").write_text(str(process.pid))
    ticks = Path(f"/proc/{process.pid}/stat").read_text().split()[21]
    monkeypatch.setenv("TUNAOS_VISUAL_RECORDER_PID", str(process.pid))
    monkeypatch.setenv("TUNAOS_VISUAL_RECORDER_START_TICKS", ticks)
    try:
        assert journey.pause_observers()["recorder"] == "stopped"
        process.wait(timeout=3)
        child_stat = Path(f"/proc/{child}/stat")
        assert not child_stat.exists() or child_stat.read_text().split()[2] == "Z"
        assert not (recorder / ".recorder.pid").exists()
        assert "not-resumed" in journey.receipt["observers"]
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        try:
            os.kill(child, mod.signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_cleanup_failure_preserves_first_failure_and_final_receipt(tmp_path):
    _, journey = journey_fixture(tmp_path)
    first = {"id": "original-failure", "required": True, "outcome": "failed"}
    journey.receipt["first_failure"] = dict(first)
    summary_path = tmp_path / "install-checkpoints-gnome.json"
    summary_path.write_text(json.dumps({
        "checkpoints": [], "assertions": [], "failures": 0, "outcome": "not-run",
    }))

    def failed_cleanup():
        raise RuntimeError("owned process survived")

    assert not journey.assertion("owned-process-cleanup", failed_cleanup)
    summary = json.loads(summary_path.read_text())
    assert summary["failures"] == 1
    assert summary["outcome"] == "failed"
    assert summary["visual_journey"]["first_failure"] == first
    assert summary["visual_journey"]["assertions"][-1]["outcome"] == "blocked"


@pytest.mark.parametrize("mismatch", ["installed-platform", "index-membership"])
@pytest.mark.parametrize("capture_fails", [False, True])
def test_exact_image_mismatch_survives_later_greeter_success(tmp_path, monkeypatch, mismatch, capture_fails):
    mod, journey = journey_fixture(tmp_path)
    platform = "sha256:" + "a" * 64
    raw = json.dumps({"manifests": [{
        "digest": "sha256:" + "b" * 64,
        "platform": {"os": "linux", "architecture": "amd64"},
    }]}).encode()
    monkeypatch.setenv("TUNAOS_VISUAL_PLATFORM_DIGEST",
                       platform if mismatch == "index-membership" else "sha256:" + "c" * 64)
    monkeypatch.setenv("TUNAOS_VISUAL_INDEX_DIGEST", "sha256:" + mod.hashlib.sha256(raw).hexdigest())
    monkeypatch.setenv("TUNAOS_VISUAL_IMAGE_REPOSITORY", "example.invalid/fixture")
    monkeypatch.setattr(mod.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=raw))

    def observe(command):
        if command == "cat /etc/os-release":
            return 'NAME="Yellowfin"\nVARIANT_ID="yellowfin"\nVERSION_ID="10"'
        if command == "cat /usr/share/tunaos/identity.env":
            return "TUNAOS_VARIANT='yellowfin'"
        if command == "cat /proc/sys/kernel/random/boot_id":
            return "fixture-boot"
        if command == "bootc status --json":
            return json.dumps({"status": {"booted": {"image": {"imageDigest": platform}}}})
        if command.startswith("loginctl"):
            return "Class=greeter\nType=wayland\nName=gdm\nUser=42\nActive=yes"
        if command.endswith('id -u "$name"'):
            return "42"
        if "gsettings get org.gnome.login-screen logo" in command:
            assert "sudo" not in command
            return "'/usr/share/pixmaps/tunaos-lettermark.svg'"
        if command.startswith("sha256sum"):
            return journey.receipt["asset_sha256"]["mark"] + "  canonical-mark"
        if "getent passwd" in command:
            return "Pat Example"
        pytest.fail(f"unexpected fixture operation: {command}")

    captures = []
    guard = tmp_path / ".visual-secret-entry-active"
    guard.touch()

    def capture(label, **kwargs):
        captures.append(label)
        if capture_fails:
            raise RuntimeError("fixture greeter never painted")

    monkeypatch.setattr(journey, "observe_state", observe)
    monkeypatch.setattr(journey, "capture", capture)
    assert journey.pre_auth() == (not capture_fails)
    assert guard.exists() == capture_fails
    assert journey.receipt["user_fullname"] == "Pat Example"
    identity = journey.receipt["assertions"][0]
    assert identity["id"] == "exact-installed-identity"
    assert identity["outcome"] == "failed"
    assert journey.receipt["first_failure"]["id"] == identity["id"]
    assert captures == ["visual-greeter"]
    assert next(row for row in journey.receipt["assertions"]
                if row["id"] == "greeter-consumed-setting")["outcome"] == "passed"


def test_secret_guard_blocks_all_foreground_capture_and_keeps_pre_auth_frame(tmp_path, monkeypatch):
    _, journey = journey_fixture(tmp_path)
    first = tmp_path / "visual-greeter.png"
    Image.new("RGB", (16, 16), "blue").save(first)
    original = first.read_bytes()
    (tmp_path / ".visual-secret-entry-active").touch()
    operations = []
    monkeypatch.setattr(journey, "monitor_action", lambda *args: operations.append(args))
    with pytest.raises(RuntimeError, match="secret-entry capture guard"):
        journey.capture("must-not-capture")
    assert operations == []
    assert first.read_bytes() == original
    assert not (tmp_path / "must-not-capture.png").exists()


@pytest.mark.parametrize("scenario", ["altered-bytes", "missing-hicolor", "missing-pixmaps",
                                     "missing-LOGO", "unsafe-LOGO"])
def test_altered_installed_about_icon_bytes_rejected(tmp_path, monkeypatch, scenario):
    _, journey = journey_fixture(tmp_path)
    captures, commands = [], []
    original = (ROOT / journey.assets["about"]).read_bytes()
    altered = original.replace(b"</svg>", b"<!-- byte-binding regression --></svg>")
    assert altered != original
    # XML comments do not change the rendering tree, unlike the file's digest.
    import xml.etree.ElementTree as ET
    assert ET.tostring(ET.fromstring(original)) == ET.tostring(ET.fromstring(altered))
    installed_icon = tmp_path / "installed-about.svg"
    installed_icon.write_bytes(altered if scenario == "altered-bytes" else original)
    if scenario == "missing-LOGO":
        journey.receipt["os_release"].pop("LOGO")
    elif scenario == "unsafe-LOGO":
        journey.receipt["os_release"]["LOGO"] = "../invalid-icon"

    def observe(command):
        commands.append(command)
        if command == "id -u":
            return "1000"
        if command.startswith("loginctl"):
            return "Class=user\nType=wayland\nActive=yes\nState=active\nLockedHint=no\nDesktop=gnome\nName=tunaose2e\nUser=1000"
        if command == "cat /proc/sys/kernel/random/boot_id":
            return "fixture-boot"
        if "gsettings get org.gnome.desktop.background" in command:
            return "'file:///usr/share/backgrounds/tunaos/tunaos-default.jpg'"
        if command.startswith("sha256sum /usr/share/backgrounds"):
            return journey.receipt["asset_sha256"]["wallpaper"] + "  wallpaper"
        if command.endswith("gnome-control-center --list"):
            return "system\nbackground\nnetwork"
        if "is-active" in command:
            return "active"
        if "MainPID" in command:
            return "4242"
        if command.startswith("readlink"):
            return "/usr/bin/gnome-control-center"
        if command.startswith("sha256sum /proc/"):
            return "settings-sha256"
        if command.startswith("sha256sum '/usr/share/icons") or command.startswith("sha256sum '/usr/share/pixmaps"):
            missing = ((scenario == "missing-hicolor" and "/icons/" in command) or
                       (scenario == "missing-pixmaps" and "/pixmaps/" in command))
            if missing:
                raise RuntimeError("fixture installed canonical icon unavailable")
            return journey.digest(installed_icon) + "  installed-about.svg"
        return ""

    monkeypatch.setattr(journey, "observe_state", observe)
    monkeypatch.setattr(journey, "await_predicate", lambda predicate: predicate() or pytest.fail("not ready"))
    monkeypatch.setattr(journey, "monitor_action", lambda _: None)
    monkeypatch.setattr(journey, "capture", lambda label, **kwargs: captures.append(label))
    assert not journey.session()
    assert "visual-about" not in captures
    about_assertion = next(row for row in journey.receipt["assertions"]
                           if row["id"] == "actual-about-ui")
    if scenario in ("altered-bytes", "unsafe-LOGO"):
        assert about_assertion["outcome"] == "failed"
    else:
        assert about_assertion["outcome"] == "blocked"
    if scenario == "altered-bytes":
        assert "differs from canonical About asset" in about_assertion["reason"]
    if scenario == "unsafe-LOGO":
        assert not any("sha256sum '../" in command for command in commands)


@pytest.mark.parametrize("trace_fd", [False, True])
def test_tracing_refused_on_password_override(tmp_path, trace_fd):
    script_path = ROOT / "scripts" / "iso-e2e.sh"
    trace_path = tmp_path / "bash-trace.log"
    with trace_path.open("w") as trace:
        env = {**os.environ, "TUNAOS_E2E_INSTALL_PASSWORD": "supersecretpassword"}
        if trace_fd:
            env["BASH_XTRACEFD"] = str(trace.fileno())
        res = subprocess.run(
            ["bash", "-x", str(script_path)], env=env,
            pass_fds=(trace.fileno(),) if trace_fd else (),
            capture_output=True, text=True,
        )
    assert res.returncode != 0
    assert "supersecretpassword" not in res.stdout + res.stderr + trace_path.read_text()
    assert "tracing (-x) is forbidden" in res.stderr


def test_luks_failure_retains_secret_guard_and_skips_desktop_failed_screenshot(tmp_path):
    guard = tmp_path / ".visual-secret-entry-active"
    guard.touch()
    # Execute the actual entry point's wrapper, not a copied implementation.
    source = (ROOT / "scripts" / "iso-e2e.sh").read_text()
    body = source.split("\nscreenshot() {\n", 1)[1].split("\n}\n", 1)[0]
    real_wrapper = "screenshot() {\n" + body + "\n}\n"
    script = (
        f'OUTPUT_DIR="{tmp_path}"\n'
        '_raw_screenshot() { echo "CAPTURED" >&2; }\n' +
        real_wrapper + '\nscreenshot "installed-desktop-failed"\n')
    res = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert "CAPTURED" not in res.stderr
    assert "screenshot skipped: secret-entry capture guard is active" in res.stderr
    assert guard.exists()


@pytest.mark.parametrize("missing", ["GECOS", "LOGO"])
def test_missing_observed_identity_blocks_visual_checkpoint(tmp_path, monkeypatch, missing):
    mod = _load_module()
    cid = "visual-greeter" if missing == "GECOS" else "visual-about"
    region = "displayed-user" if missing == "GECOS" else "product-name"
    spec = {"schema_version": 1, "checkpoints": [{
        "id": cid, "phase": "visual", "required": True, "frames": [cid],
        "regions": [{"id": region, "box": [0, 0, 1, 1], "keywords": ["must-be-observed"]}],
    }]}
    osr = {"NAME": "Yellowfin", "VERSION_ID": "10"}
    if missing == "GECOS":
        osr["LOGO"] = "tunaos"
    receipt = {
        "scope": {"variant": "yellowfin", "flavor": "gnome"},
        "os_release": osr, "operations": [], "assertions": [], "asset_sha256": {},
    }
    (tmp_path / "visual-journey.json").write_text(json.dumps(receipt))
    Image.new("RGB", (32, 32), "blue").save(tmp_path / f"{cid}.png")
    monkeypatch.setattr(mod, "load_spec", lambda _: spec)
    monkeypatch.setattr(mod, "contact_sheet", lambda *args: False)
    monkeypatch.setattr(sys, "argv", [
        "install-checkpoints.py", str(tmp_path), "--visual-journey", "--variant", "yellowfin",
    ])
    assert mod.main() != 0
    summary = json.loads((tmp_path / "install-checkpoints-gnome.json").read_text())
    checkpoint = summary["checkpoints"][0]
    assert checkpoint["outcome"] == "blocked"
    assert checkpoint["reason"] == "required-identity-missing"
    assert checkpoint["regions"][0]["outcome"] == "blocked"
