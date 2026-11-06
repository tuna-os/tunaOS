"""Fixture corpus for the schema_version 1 screen-checkpoint contract.

Every case in tests/fixtures/install-checkpoints-v1/cases.json runs the real
scripts/install-checkpoints.py as a subprocess over an evidence directory
built here. Pillow draws the frames; the two tools the script shells out to
are replaced on PATH by stubs — `tesseract` prints the case's transcript (or
exits non-zero, as a timed-out run does) and `magick` measures the frame's
grayscale standard deviation from its real pixels. Nothing inside the script
is patched, so each case exercises the production path from frame lookup to
outcome, TAP and exit code, without needing tesseract or ImageMagick on the
host.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("yaml", reason="the script reads its contract with PyYAML")
Image = pytest.importorskip("PIL.Image", reason="frames are drawn with Pillow")

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install-checkpoints.py"
CORPUS = ROOT / "tests" / "fixtures" / "install-checkpoints-v1"
CASES = json.loads((CORPUS / "cases.json").read_text())
OUTCOMES = {"passed", "failed", "blocked", "not-run", "unsupported"}
# Fields the summary carried before outcomes existed; consumers may read them.
LEGACY_RECORD_FIELDS = {"id", "phase", "required", "frames", "matched", "forbidden", "rendered"}

# `magick <frame> -colorspace Gray -format %[fx:standard_deviation] info:` is
# the only ImageMagick call whose result the verdict depends on; the dark-UI
# conversion and the contact sheet fail here, which the script already treats
# as "no extra pass" and "no sheet". The frames are pure grayscale, so
# Pillow's L conversion and ImageMagick's Gray colorspace agree on them.
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
    entry = json.load(f).get(os.path.basename(sys.argv[1]))
if entry is None:
    sys.exit(1)
if entry.get("ocr_exit"):
    sys.exit(entry["ocr_exit"])
sys.stdout.write(entry["ocr"])
"""


def _load_module():
    spec = importlib.util.spec_from_file_location("install_checkpoints_corpus", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def draw(path: Path, pixels: str) -> None:
    if pixels == "content":
        img = Image.new("L", (320, 200), 0)
        img.paste(255, (0, 0, 160, 200))  # stddev 0.5
    elif pixels == "blank":
        img = Image.new("L", (320, 200), 0)  # stddev 0
    elif pixels == "dim":
        # Nearly uniform, not uniform: stddev ~0.005, under the 0.02 floor.
        img = Image.new("L", (320, 200), 20)
        img.paste(40, (0, 0, 16, 16))
    else:
        raise ValueError(f"unknown pixels kind {pixels!r}")
    img.save(path)


def stub(bindir: Path, name: str, source: str) -> None:
    tool = bindir / name
    tool.write_text(f"#!{sys.executable}\n{source}")
    tool.chmod(0o755)


def run_script(tmp_path: Path, spec: Path, args: list[str], tools: list[str],
               frames: dict) -> tuple[int, str, Path, Path]:
    evidence = tmp_path / "evidence"
    bindir = tmp_path / "bin"
    evidence.mkdir()
    bindir.mkdir()
    ocr_stub = tmp_path / "ocr-stub.json"
    ocr_stub.write_text(json.dumps({f"{name}.png": frame for name, frame in frames.items()}))
    for name, frame in frames.items():
        draw(evidence / f"{name}.png", frame["pixels"])
    if "magick" in tools:
        stub(bindir, "magick", STUB_MAGICK)
    if "tesseract" in tools:
        stub(bindir, "tesseract", STUB_TESSERACT.format(stub=str(ocr_stub)))
    env = {k: v for k, v in os.environ.items()
           if k not in ("FLAVOR", "VARIANT", "TUNAOS_CHECKPOINT_NO_GPU")}
    env["PATH"] = str(bindir)  # only the stubs: a host tesseract must not leak in
    summary = tmp_path / "summary.json"
    r = subprocess.run(
        [sys.executable, str(SCRIPT), str(evidence), "--spec", str(spec),
         "--json", str(summary), *args],
        capture_output=True, text=True, env=env, check=False)
    return r.returncode, r.stdout + r.stderr, summary, evidence


def _run_case(case: dict) -> dict:
    base = CASES["baseline"]
    frames = dict(base["frames"])
    for name, frame in case.get("frames", {}).items():
        if frame is None:
            frames.pop(name, None)
        else:
            frames[name] = frame
    return {
        "spec": CORPUS / case.get("spec", base["spec"]),
        "args": case.get("args", base["args"]),
        "tools": case.get("tools", base["tools"]),
        "frames": frames,
    }


@pytest.mark.parametrize("case", CASES["runs"], ids=[c["name"] for c in CASES["runs"]])
def test_run_case(tmp_path, case):
    setup = _run_case(case)
    rc, log, summary_path, _ = run_script(tmp_path, setup["spec"], setup["args"],
                                          setup["tools"], setup["frames"])
    expect = case["expect"]
    assert rc == expect["exit"], log

    summary = json.loads(summary_path.read_text())
    got = {r["id"]: [r["outcome"], r["reason"]] for r in summary["checkpoints"]}
    assert got == expect["checkpoints"], log
    assert summary["spec_schema_version"] == 1

    lines = log.splitlines()
    for line in expect.get("tap", []):
        assert line in lines, log
    for record in summary["checkpoints"]:
        assert LEGACY_RECORD_FIELDS <= set(record), record
        assert record["outcome"] in OUTCOMES, record
        assert f"  # [{record['id']}] outcome: {record['outcome']} ({record['reason']})" in lines
        # The invariant the outcomes exist for: a required checkpoint that was
        # not judged "passed" can never leave the run exiting as a pass.
        if record["required"] and record["outcome"] != "passed" \
                and record["outcome"] != "unsupported":
            assert rc != 0, log
    # TAP plan still closes the stream.
    assert f"1..{len(summary['assertions'])}" in lines


@pytest.mark.parametrize("case", CASES["contracts"], ids=[c["name"] for c in CASES["contracts"]])
def test_contract_case(tmp_path, case):
    spec = CORPUS / case["spec"]
    frames = CASES["baseline"]["frames"]
    rc, log, summary, _ = run_script(tmp_path, spec, ["--flavor", "kde"],
                                     ["magick", "tesseract"], frames)
    assert rc == 78, log
    lines = log.splitlines()
    assert len(lines) == 1, log
    prefix = f"Bail out! invalid checkpoint contract {spec}: "
    assert lines[0].startswith(prefix), log
    assert lines[0].removeprefix(prefix).strip(), "a bailout must explain the refusal"
    assert not summary.exists(), "a refused contract must not leave a verdict behind"


@pytest.mark.parametrize("path", [
    ROOT / "tests" / "install-pipeline-screens.yaml",
    CORPUS / "contract.yaml",
    CORPUS / "forbid-only-required.yaml",
    CORPUS / "regions" / "contract.yaml",
    CORPUS / "regions" / "contract-svg.yaml",
], ids=["shipped-contract", "corpus-contract", "forbid-only-contract",
        "regions-contract", "regions-svg-contract"])
def test_valid_contracts_load(path):
    doc = _load_module().load_spec(str(path))
    assert doc["schema_version"] == 1


def test_corpus_exercises_every_outcome():
    seen = {outcome for case in CASES["runs"]
            for outcome, _reason in case["expect"]["checkpoints"].values()}
    assert seen == OUTCOMES
