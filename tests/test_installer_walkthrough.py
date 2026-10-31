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
# The output is the LAST argument, not $2: installer-walkthrough.py's OCR
# fallback calls `magick in.png -negate out.png`, and treating $2 as the
# destination wrote a file literally named "-negate" into the repo root while
# leaving the negated pass untested. Whatever operators sit in between, the
# stub copies the input to the final path.
out=""
for a in "$@"; do out="$a"; done
if [ -n "$out" ] && [ "$out" != "$1" ]; then
  cp "$1" "$out" 2>/dev/null || printf 'P3\n1 1\n255\n0 0 0\n' > "$out"
fi
exit 0
"""

TESSERACT_STUB = r"""#!/bin/bash
# Fake tesseract. The image filename encodes the frame number
# (walkthrough-<flavor>-NN.png); the OCR text for that frame comes from the
# TESS_NN environment variable.
# A negated copy is <frame>.neg.png. It answers from TESSNEG_NN instead, so
# a test can make the negated pass the only readable one -- which is the
# whole point of that fallback existing.
name=$(basename "$1")
pfx="TESS"
case "$name" in
  *.neg.png) name=${name%.neg.png}; pfx="TESSNEG";;
esac
nn=$(printf '%s' "$name" | sed -n 's/.*-\([0-9][0-9]\)\.png$/\1/p')
var="${pfx}_${nn}"
printf '%s' "${!var}"
"""


class FakeQEMUMonitor:
    """Answers sendkey/screendump over a unix socket like QEMU's HMP."""

    def __init__(self, sock_path, outdir, power_off_after_sendkeys=None,
                 power_off_after_frame=None):
        # Emulates a guest that powers off once that many sendkey commands
        # have been served: QEMU exits and its monitor socket disappears.
        self.power_off_after_sendkeys = power_off_after_sendkeys
        self.power_off_after_frame = power_off_after_frame
        self.sock_path = sock_path
        self.outdir = outdir
        # Recorded so tests can assert the ORDER keys are sent, not just that
        # the run finished. The overview-dismissal fix is entirely about
        # sending 'esc' BEFORE anything else.
        self.commands = []
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
                self.commands.append(cmd)
                if cmd.startswith("screendump "):
                    ppm = cmd.split(None, 1)[1]
                    with open(ppm, "w") as f:
                        f.write(PPM)
                conn.sendall(b"\r\n(qemu) ")
                frame_exit = (cmd.startswith("screendump ") and
                              self.power_off_after_frame is not None and
                              Path(cmd.split(None, 1)[1]).stem.endswith(
                                  f"-{self.power_off_after_frame:02d}"))
                if (frame_exit or (self.power_off_after_sendkeys is not None and
                        sum(c.startswith("sendkey ") for c in self.commands)
                        >= self.power_off_after_sendkeys)):
                    self._srv.close()
                    os.unlink(self.sock_path)
                    return
                try:
                    conn.shutdown(socket.SHUT_WR)
                except OSError:
                    pass
            except Exception:
                pass
            finally:
                conn.close()


def run_walkthrough(tess, magick_ae=5000, magick_stddev=0.5, steps="2",
                    flavor="de", strict=False, timeout=120, tess_neg=None,
                    spec=None, power_off_after_sendkeys=None,
                    power_off_after_frame=None, install_timeout=30, mode=None):
    """Run the script against the fake monitor + stubs.

    *tess* maps frame number (str) -> OCR text. *tess_neg* is the same for the
    negated copy the OCR fallback makes, so a test can give the plain pass
    noise and the negated pass words. Returns (proc, summary_json).
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

        mon = FakeQEMUMonitor(sock, str(outdir), power_off_after_sendkeys,
                              power_off_after_frame)
        mon.start()

        env = dict(os.environ)
        env["PATH"] = str(fakebin) + os.pathsep + env.get("PATH", "")
        env["MAGICK_AE"] = str(magick_ae)
        env["MAGICK_STDDEV"] = str(magick_stddev)
        # The settle waits exist for a real guest to redraw; the fake monitor
        # has written the frame before it answers, so they only cost time.
        env["TBOX_WALKTHROUGH_WAIT_SCALE"] = "0"
        env["TUNAOS_WALKTHROUGH_INSTALL_TIMEOUT"] = str(install_timeout)
        env["TUNAOS_WALKTHROUGH_LUKS_PASS"] = "tunaos-e2e-luks"
        for k, v in tess.items():
            env[f"TESS_{k}"] = v
        for k, v in (tess_neg or {}).items():
            env[f"TESSNEG_{k}"] = v

        cmd = [sys.executable, str(SCRIPT), sock, str(outdir), steps, flavor]
        if strict:
            cmd.append("--strict")
        if spec is not None:
            cmd.append(f"--spec={spec}")
        if mode is not None:
            cmd.append(f"--mode={mode}")
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env,
                              timeout=timeout)

        summary = None
        summary_path = outdir / f"walkthrough-{flavor}.json"
        if summary_path.exists():
            summary = json.loads(summary_path.read_text())
        run_walkthrough.last_commands = list(mon.commands)
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


class TestLeavesTheShellOverview:
    """Run 32450214451's gnome leg: a mapped, correctly stamped installer
    window, 9 frames, 2 visual states, zero page advances.

    The frames showed why -- the session sat in GNOME's Activities overview
    with the installer as a thumbnail behind the "Type to search" entry, so
    every key went to the shell. The focus-widening loop then walked onto the
    thumbnail's CLOSE button, which is worse than useless: one more Return
    would have closed the installer.
    """

    def test_escape_is_sent_before_any_advance_key(self):
        """Escape must come first, or the overview eats the whole run."""
        run_walkthrough({"0": "Welcome", "1": "Welcome"}, steps="2")
        keys = [c.split(None, 1)[1] for c in run_walkthrough.last_commands
                if c.startswith("sendkey ")]
        assert keys, "no keys were sent at all"
        assert keys[0] == "esc", (
            f"first key sent was {keys[0]!r}, not 'esc' -- an overview would "
            f"swallow it and every key after it (full order: {keys})"
        )

    def test_escape_precedes_the_first_activation(self):
        run_walkthrough({"0": "Welcome"}, steps="2")
        keys = [c.split(None, 1)[1] for c in run_walkthrough.last_commands
                if c.startswith("sendkey ")]
        assert "ret" in keys, f"no activation key was sent: {keys}"
        assert keys.index("esc") < keys.index("ret")

    def test_a_dismissed_overlay_is_reported(self):
        """High pixel-diff stub => the screen changed when esc was pressed."""
        proc, summary = run_walkthrough(
            {"0": "Welcome", "1": "Disk", "2": "Disk"},
            magick_ae=5000, steps="2")
        assert "shell overlay was covering the installer" in proc.stdout, (
            f"the dismissal was not reported:\n{proc.stdout}"
        )
        entry = _find_tap(summary, "frontmost at session start")
        assert entry is not None, "no frontmost assertion in the summary"
        assert entry["ok"] is False

    def test_no_overlay_is_reported_when_escape_changes_nothing(self):
        """magick_ae=0 => esc changed no pixels => nothing was covering it."""
        proc, summary = run_walkthrough(
            {"0": "Welcome", "1": "Welcome", "2": "Welcome"},
            magick_ae=0, steps="2")
        assert "shell overlay was covering the installer" not in proc.stdout
        entry = _find_tap(summary, "frontmost at session start")
        assert entry is not None
        assert entry["ok"] is True

    def test_the_overlay_finding_does_not_fail_the_run_on_its_own(self):
        """Reported, not enforced -- the wizard behind it has never been
        exercised on gnome, so failing here would swap one unknown for
        another. It must still be in the record."""
        _, summary = run_walkthrough(
            {"0": "Welcome", "1": "Disk", "2": "Disk"},
            magick_ae=5000, steps="2")
        entry = _find_tap(summary, "frontmost at session start")
        assert entry["enforced"] is False


def _find_tap(summary, needle):
    if not summary:
        return None
    for entry in summary.get("tap", []):
        if needle in entry.get("desc", ""):
            return entry
    return None


class TestVmPowersOffMidWalk:
    """Run 40309516730: the gnome leg's focus sweep powered the VM off at
    step 10 and the harness died on FileNotFoundError with no verdict/JSON."""

    def test_vm_exit_is_an_enforced_failure_with_summary(self):
        # 1 'esc' (overview probe) + step 1 'ret' + step 2 'ret' -> gone.
        proc, summary = run_walkthrough(
            {"00": "Welcome", "01": "Disk"}, steps="4",
            power_off_after_sendkeys=3)
        assert "Traceback" not in proc.stderr, proc.stderr
        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert summary is not None
        assert summary["vm_gone_step"] == 2
        entry = _find_tap(summary, "VM stayed up")
        assert entry == {"ok": False, "desc": "de: VM stayed up for the whole "
                         "walkthrough", "enforced": True}

    def test_vm_that_stays_up_passes_the_check(self):
        proc, summary = run_walkthrough(
            {"00": "Welcome", "01": "Disk", "02": "Disk"})
        assert summary["vm_gone_step"] is None
        assert _find_tap(summary, "VM stayed up")["ok"] is True


class TestBackendObservation:
    def test_welcome_prose_about_installing_does_not_start_polling(self):
        proc, summary = run_walkthrough(
            {"00": "This wizard will guide you through installing Yellowfin",
             "01": "Choose the disk where the system will be installed.",
             "02": "Choose the disk where the system will be installed."})
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert summary["screens"]["disk"] is True
        assert [c for c in run_walkthrough.last_commands
                if c.startswith("sendkey ")] == [
                    "sendkey esc", "sendkey ret", "sendkey ret"]

    def test_initial_progress_receives_no_escape_or_activation(self):
        proc, summary = run_walkthrough(
            {"00": "Installation progress", "01": "Installation complete"},
            steps="1", power_off_after_sendkeys=1)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert summary["frames"] == 2
        assert not any(c.startswith("sendkey ")
                       for c in run_walkthrough.last_commands)

    def test_delayed_completion_never_receives_another_activation(self):
        proc, summary = run_walkthrough(
            {"00": "Welcome to TunaOS installer",
             "01": "Installation progress: writing image",
             "02": "Installing packages",
             "03": "Finalizing system",
             "04": "Installation complete. Remove the installation media"},
            steps="1", power_off_after_sendkeys=3)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert summary["frames"] == 5
        assert summary["screens"]["done"] is True
        assert summary["vm_gone_step"] is None
        assert [c for c in run_walkthrough.last_commands
                if c.startswith("sendkey ")] == ["sendkey esc", "sendkey ret"]
        assert run_walkthrough.last_commands[-1].endswith("-04.ppm")

    def test_missing_completion_is_not_inferred_from_progress(self):
        proc, summary = run_walkthrough(
            {"00": "Welcome", "01": "Installation progress"},
            steps="1", install_timeout=0)
        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert summary["screens"]["done"] is False
        assert any(not t["ok"] and t["enforced"] and
                   "installation completed in time" in t["desc"]
                   for t in summary["tap"])

    def test_guest_exit_during_observation_remains_a_failure(self):
        proc, summary = run_walkthrough(
            {"00": "Welcome", "01": "Installation progress",
             "02": "Installing packages"},
            steps="1", power_off_after_frame=2)
        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert summary["vm_gone_step"] == 3
        assert summary["screens"]["done"] is False
        assert [c for c in run_walkthrough.last_commands
                if c.startswith("sendkey ")] == ["sendkey esc", "sendkey ret"]

    def test_backend_failure_is_captured_without_more_input(self):
        proc, summary = run_walkthrough(
            {"00": "Welcome", "01": "Installation progress",
             "02": "Installation failed: disk write error"}, steps="1")
        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert summary["frames"] == 3
        assert summary["screens"]["done"] is False
        assert any(not t["ok"] and t["enforced"] and
                   "installation succeeded" in t["desc"]
                   for t in summary["tap"])
        assert [c for c in run_walkthrough.last_commands
                if c.startswith("sendkey ")] == ["sendkey esc", "sendkey ret"]

    @pytest.mark.parametrize("mode", ["plain", "luks"])
    def test_explicit_mode_configures_and_completes_in_order(self, mode):
        proc, summary = run_walkthrough(
            {"00": "Welcome",
             "01": "Choose the disk where the system will be installed",
             "02": "Disk encryption: passphrase",
             "03": "Confirm installation",
             "04": "Please wait",
             "05": "Installation progress: writing image",
             "06": "Installing packages",
             "07": "Finalizing system",
             "08": "Installation complete"},
            steps="4", mode=mode)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert summary["mode"] == mode
        for sid in ("welcome", "disk", "encryption", "summary", "install", "done"):
            assert summary["screens"][sid] is True
            assert any(t["ok"] and t["enforced"] and
                       t["desc"] == f"de: strict {mode}: reached '{sid}' screen"
                       for t in summary["tap"])
        commands = run_walkthrough.last_commands
        progress = next(i for i, c in enumerate(commands)
                        if c.startswith("screendump ") and c.endswith("-05.ppm"))
        before_submit = next(i for i, c in enumerate(commands)
                             if c.startswith("screendump ") and c.endswith("-04.ppm"))
        assert [c for c in commands[before_submit + 1:progress]
                if c.startswith("sendkey ")] == ["sendkey ret"]
        assert not any(c.startswith("sendkey ") for c in commands[progress + 1:])
        keys = [c for c in commands if c.startswith("sendkey ")]
        if mode == "luks":
            assert "luks mode: typed test passphrase" in proc.stdout
            assert keys.count("sendkey down") == 1
            assert keys.count("sendkey minus") == 4
        else:
            assert "sendkey down" not in keys
        assert commands[-1].endswith("-08.ppm")

    def test_luks_progress_cannot_waive_encryption_or_required_screens(self):
        proc, summary = run_walkthrough(
            {"00": "Welcome", "01": "Installation progress",
             "02": "Installation complete"}, steps="1", mode="luks")
        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert summary["screens"]["done"] is True
        for fragment in ("encryption screen was configured",
                         "strict luks: reached 'disk'",
                         "strict luks: reached 'encryption'",
                         "strict luks: reached 'summary'"):
            assert any(not t["ok"] and t["enforced"] and fragment in t["desc"]
                       for t in summary["tap"])

    def test_completion_out_of_order_does_not_waive_required_sequence(self):
        proc, summary = run_walkthrough(
            {"00": "Welcome", "01": "Confirm installation",
             "02": "Choose the disk where the system will be installed",
             "03": "Disk encryption: passphrase",
             "04": "Installation progress",
             "05": "Installation complete"}, steps="4", mode="plain")
        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert summary["screens"]["done"] is True
        assert any(not t["ok"] and t["enforced"] and
                   "strict plain: 'summary' screen in order" in t["desc"]
                   for t in summary["tap"])

    @pytest.mark.parametrize("text,expected", [
        ("Installation complete", 1),  # One terminal frame is not a walkthrough.
        ("Installation failed: disk write error", 1),
    ])
    def test_initial_terminal_backend_screen_receives_no_input(self, text, expected):
        proc, summary = run_walkthrough({"00": text}, steps="1")
        assert proc.returncode == expected, proc.stdout + proc.stderr
        assert summary["frames"] == 1
        assert not any(c.startswith("sendkey ")
                       for c in run_walkthrough.last_commands)
