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
