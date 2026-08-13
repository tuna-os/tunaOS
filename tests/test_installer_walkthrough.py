#!/usr/bin/env python3
"""
Unit/integration tests for scripts/installer-walkthrough.py

The walkthrough harness drives the five installer frontends over the QEMU
monitor and decides, from pixel diffs + OCR, whether the installer rendered,
advanced, and reached each expected screen. Its decision logic (activation
escalation ret→spc, tab-widening, modal escape, per-visual-state positional
screen matching) has been tuned against many real failing runs and had 0%
coverage.

These tests run the script as a subprocess against a fake QEMU monitor
(unix socket that answers sendkey/screendump) and stub `magick` / `tesseract`
executables on PATH, so every frame's stddev, pixel-diff and OCR text are
deterministic. No QEMU, no ImageMagick, no real frontends needed.

Run with:

    python3 -m pytest tests/test_installer_walkthrough.py -v
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "installer-walkthrough.py"
PPM = "P3\n1 1\n255\n255 255 255\n"

MAGICK_STUB = r"""#!/bin/bash
# Fake ImageMagick. Serves the three call shapes installer-walkthrough.py uses:
#   magick compare -metric AE -fuzz 5% a b null:   -> MAGICK_AE to stderr
#   magick in.png ... %[fx:standard_deviation] ... -> MAGICK_STDDEV to stdout
#   magick in out                                 -> copy/convert (any bytes ok)
if [ "$1" = "compare" ]; then
  echo "${MAGICK_AE:-0}" >&2
  exit 0
fi
for a in "$@"; do
  if [ "$a" = "%[fx:standard_deviation]" ]; then
    echo "${MAGICK_STDDEV:-0.5}"
    exit 0
  fi
done
if [ -n "${2:-}" ]; then
  cp "$1" "$2" 2>/dev/null || printf 'P3\n1 1\n255\n0 0 0\n' > "$2"
fi
exit 0
"""

TESSERACT_STUB = r"""#!/bin/bash
# Fake tesseract. The image filename encodes the frame number
# (walkthrough-<flavor>-NN.png); the OCR text for that frame comes from the
# TESS_NN environment variable.
name=$(basename "$1")
nn=$(printf '%s' "$name" | sed -n 's/.*-\([0-9][0-9]\)\.png$/\1/p')
var="TESS_${nn}"
printf '%s' "${!var}"
"""


class FakeQEMUMonitor:
    """Answers sendkey/screendump over a unix socket like QEMU's HMP."""

    def __init__(self, sock_path, outdir):
        self.sock_path = sock_path
        self.outdir = outdir
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._srv.bind(sock_path)
        self._srv.listen(8)
        self.thread = threading.Thread(target=self._serve, daemon=True)

    def start(self):
        self.thread.start()

    def _serve(self):
        while True:
            try:
                conn, _ = self._srv.accept()
            except OSError:
                return
            try:
                conn.settimeout(2)
                conn.sendall(b"(qemu) ")
                data = b""
                while b"\n" not in data:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                cmd = data.decode("utf-8", "replace").strip()
                if cmd.startswith("screendump "):
                    ppm = cmd.split(None, 1)[1]
                    with open(ppm, "w") as f:
                        f.write(PPM)
                conn.sendall(b"\r\n(qemu) ")
                try:
                    conn.shutdown(socket.SHUT_WR)
                except OSError:
                    pass
            except Exception:
                pass
            finally:
                conn.close()


def run_walkthrough(tess, magick_ae=5000, magick_stddev=0.5, steps="2",
                    flavor="de", strict=False, timeout=120):
    """Run the script against the fake monitor + stubs.

    *tess* maps frame number (str) -> OCR text. Returns (proc, summary_json).
    """
    tmp = Path(tempfile.mkdtemp(prefix="walkthrough-test-"))
    try:
        outdir = tmp / "out"
        outdir.mkdir()
        sock = str(tmp / "monitor.sock")
        fakebin = tmp / "bin"
        fakebin.mkdir()
        (fakebin / "magick").write_text(MAGICK_STUB)
        (fakebin / "tesseract").write_text(TESSERACT_STUB)
        (fakebin / "magick").chmod(0o755)
        (fakebin / "tesseract").chmod(0o755)

        mon = FakeQEMUMonitor(sock, str(outdir))
        mon.start()

        env = dict(os.environ)
        env["PATH"] = str(fakebin) + os.pathsep + env.get("PATH", "")
        env["MAGICK_AE"] = str(magick_ae)
        env["MAGICK_STDDEV"] = str(magick_stddev)
        for k, v in tess.items():
            env[f"TESS_{k}"] = v

        cmd = [sys.executable, str(SCRIPT), sock, str(outdir), steps, flavor]
        if strict:
            cmd.append("--strict")
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env,
                              timeout=timeout)

        summary = None
        summary_path = outdir / f"walkthrough-{flavor}.json"
        if summary_path.exists():
            summary = json.loads(summary_path.read_text())
        return proc, summary
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── Scenarios ────────────────────────────────────────────────────────────────

class TestRendersAdvancesScreens:
    def test_happy_path_reaches_welcome_and_disk(self):
        proc, summary = run_walkthrough(
            {"00": "Welcome to TunaOS installer. Get Started",
             "01": "Choose the disk where the system will be installed.",
             "02": "Choose the disk where the system will be installed."},
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert summary["frames"] == 3
        assert summary["rendered_frames"] == 3
        assert summary["advanced_transitions"] == 2
        assert summary["visual_states"] == 3
        assert summary["screens"]["welcome"] is True
        assert summary["screens"]["disk"] is True
        assert "ok - de: reached 'welcome' screen" in proc.stdout
        assert "ok - de: reached 'disk' screen" in proc.stdout

    def test_prose_on_welcome_does_not_credit_later_screens(self):
        # The positional fix: welcome prose that mentions disk keywords must
        # NOT credit the disk screen, because the installer never advanced to
        # a state that shows it (frames 1,2 are still the welcome screen).
        proc, summary = run_walkthrough(
            {"00": "Welcome to TunaOS installer. You will choose the disk "
                   "where the system will be installed. Get Started",
             "01": "Welcome to TunaOS installer. Get Started",
             "02": "Welcome to TunaOS installer. Get Started"},
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert summary["screens"]["welcome"] is True
        assert summary["screens"]["disk"] is False
        assert "not ok - de: reached 'disk' screen" in proc.stdout

    def test_no_advance_escalates_activation_and_groups_one_state(self):
        # AE=0: nothing on screen ever changes. The harness must escalate
        # ret -> spc, keep a single visual state, and only credit screens
        # visible on state 0 (welcome).
        proc, summary = run_walkthrough(
            {"00": "Welcome to TunaOS installer. Get Started",
             "01": "Welcome to TunaOS installer. Get Started",
             "02": "Welcome to TunaOS installer. Get Started"},
            magick_ae=0,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert summary["advanced_transitions"] == 0
        assert summary["visual_states"] == 1
        assert summary["activation_key"] == "spc"
        assert summary["screens"]["welcome"] is True
        assert summary["screens"]["disk"] is False

    def test_blank_frames_fail_render_check_in_strict_mode(self):
        proc, summary = run_walkthrough(
            {"00": "", "01": "", "02": ""},
            magick_stddev=0.0,
            strict=True,
        )
        assert proc.returncode == 1
        assert "not ok - de: screen is not blank" in proc.stdout
        assert summary["rendered_frames"] == 0
        assert summary["strict"] is True

    def test_blank_frames_pass_in_non_strict_mode(self):
        proc, summary = run_walkthrough(
            {"00": "", "01": "", "02": ""},
            magick_stddev=0.0,
        )
        assert proc.returncode == 0
        assert summary["rendered_frames"] == 0
        # Non-strict: the blank check reports but does not fail the run.
        assert "not ok - de: screen is not blank" in proc.stdout

    def test_nothing_matched_prints_diagnosis(self):
        # Renders + advances, but OCR never matches any screen keyword: the
        # harness must print the no-window diagnosis instead of six silent
        # "screen not reached" lines.
        proc, summary = run_walkthrough(
            {"00": "clock ticking 12:00", "01": "clock ticking 12:01",
             "02": "clock ticking 12:02"},
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "DIAGNOSIS" in proc.stdout
        assert "no installer screen was ever detected" in proc.stdout
        assert summary["screens"]["welcome"] is False


class TestTapContract:
    def test_tap_summary_lines(self):
        proc, _ = run_walkthrough(
            {"00": "Welcome to TunaOS installer. Get Started",
             "01": "Welcome to TunaOS installer. Get Started",
             "02": "Welcome to TunaOS installer. Get Started"},
        )
        # Non-strict run with only the welcome screen reached: other screens
        # report as not-ok TAP lines but do not fail the run (exit 0).
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "# Results:" in proc.stdout
        assert "screens reached: welcome" in proc.stdout
