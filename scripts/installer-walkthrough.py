#!/usr/bin/env python3
"""Capture AND VERIFY an installer click-through walkthrough via the QEMU monitor.

Drives the running installer with hardware-level key events (HMP `sendkey`)
and captures each screen with `screendump` — compositor-agnostic (KDE/COSMIC/
Niri/XFCE all work), no ydotool/Wayland tooling needed in the guest.

Capturing frames is not evidence on its own, so this also asserts (TAP output):

  1. RENDERS   — each frame has real content (grayscale stddev above a floor),
                 catching a blank/crashed window that a screenshot alone hides.
  2. ADVANCES  — consecutive frames differ, proving the installer actually
                 steps forward instead of sitting on one screen (or a modal
                 error dialog) while we happily collect identical PNGs.
  3. SCREENS   — OCR each frame and match it against tests/installer-screens.yaml
                 so we know WHICH screens this frontend reached. Because the
                 five frontends are independent forks, this is the only check
                 that catches feature drift between them.

Writes <outdir>/walkthrough-<flavor>.json summarising the screens reached, which
feeds the per-frontend parity matrix in docs/INSTALLER-FRONTENDS.md.

Rendering caveat: Smithay compositors (niri, xfwl4) need virgl to render at all,
so on a GPU-less runner their frames are legitimately blank. Pass --strict only
where rendering is expected (kde/cosmic/gnome in CI, everything on an iGPU host).

Usage:
  installer-walkthrough.py <monitor.sock> <outdir> [steps] [flavor] [--strict] [--spec FILE]
Exit: 0 if all enforced checks pass (non-strict never fails on render/advance).
"""
import glob
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time

args = [a for a in sys.argv[1:] if not a.startswith("--")]
flags = [a for a in sys.argv[1:] if a.startswith("--")]
mon_path = args[0]
outdir = args[1]
steps = int(args[2]) if len(args) > 2 else 8
flavor = args[3] if len(args) > 3 else "de"
strict = "--strict" in flags
spec_path = next((f.split("=", 1)[1] for f in flags if f.startswith("--spec=")),
                 os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "..", "tests", "installer-screens.yaml"))
# QEMU's screendump answers "Error: no surface" the moment a Wayland compositor
# scans out through virgl — which is every session this harness exists to
# photograph on a GPU host. So on the one path where cosmic, niri and xfwl4
# actually render, screendump captures nothing at all. The VNC *client* path
# still works; iso-e2e.sh has done it this way since #844.
vnc_sock = next((f.split("=", 1)[1] for f in flags if f.startswith("--vnc=")),
                os.path.join(outdir, "vnc.sock"))
vnc_port = int(os.environ.get("TBOX_WALKTHROUGH_VNC_PORT", "5998"))
os.makedirs(outdir, exist_ok=True)

BLANK_STDDEV = 0.02   # same floor iso-e2e.sh uses for "screen looks blank"
DIFF_PIXELS = 500     # pixels that must change for a frame to count as "advanced"

_tap = []
_fails = 0


def tap(ok, desc, diagnostic="", enforced=True):
    """Record a TAP assertion. Non-enforced ones report but never fail."""
    global _fails
    print(f"{'ok' if ok else 'not ok'} - {desc}", flush=True)
    # Only explain failures. Printing the diagnostic unconditionally produced
    # self-contradicting output like "ok - reached 'welcome' screen" followed
    # by "# not found in any frame's text", which made a passing run read as a
    # failing one.
    if diagnostic and not ok:
        print(f"  # {diagnostic}", flush=True)
    _tap.append({"ok": bool(ok), "desc": desc, "enforced": enforced})
    if not ok and enforced:
        _fails += 1


def note(msg):
    """Print a neutral TAP comment that is true regardless of pass/fail."""
    print(f"  # {msg}", flush=True)


def hmp(cmd):
    """Send one HMP command over the monitor socket, return the reply."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(mon_path)
    s.settimeout(5)
    time.sleep(0.2)
    try:
        s.recv(65536)  # drain banner
    except socket.timeout:
        pass
    s.sendall(cmd.encode() + b"\n")
    time.sleep(0.4)
    out = b""
    try:
        while True:
            d = s.recv(65536)
            if not d:
                break
            out += d
    except socket.timeout:
        pass
    s.close()
    return out.decode("utf-8", "replace")


def vnc_capture(png):
    """Capture via the VNC client. Returns True if a non-empty PNG landed.

    vncdo speaks TCP, so bridge the unix socket for the moment of capture —
    the same trick iso-e2e.sh's screenshot() uses. Silent-and-false when the
    socket or tooling is absent, so the screendump path can still run.
    """
    if not (os.path.exists(vnc_sock)
            and shutil.which("vncdo") and shutil.which("socat")):
        return False
    bridge = subprocess.Popen(
        ["socat", f"TCP-LISTEN:{vnc_port},reuseaddr,fork",
         f"UNIX-CONNECT:{vnc_sock}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1)
        subprocess.run(["vncdo", "-s", f"127.0.0.1::{vnc_port}", "capture", png],
                       check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    finally:
        bridge.terminate()
        try:
            bridge.wait(timeout=5)
        except Exception:
            bridge.kill()
    return os.path.exists(png) and os.path.getsize(png) > 0


# ImageMagick command resolution, done once at import time.
#
# The screendump path, stddev() and changed_pixels() all used to hardcode
# `convert` / `compare` directly. On ImageMagick 7 those are subcommands of
# `magick`, not standalone binaries, so a bare `convert` raises
# FileNotFoundError out of subprocess.run and crashes the harness — exactly
# what happened in run 31168173594 for the PPM converter.  The same defect
# is still present in stddev() and changed_pixels(), which were never given
# the same resolution logic.
#
# Resolve once at module scope so every call site uses the same version.
def _resolve_im_convert():
    """Return the ImageMagick command prefix for convert-style operations.

    IM7: ["magick"]   — `magick input.png ...`
    IM6: ["convert"]  — `convert input.png ...`
    Returns None if neither is available."""
    if shutil.which("magick"):
        return ["magick"]
    if shutil.which("convert"):
        return ["convert"]
    return None


def _resolve_im_compare():
    """Return the ImageMagick command prefix for compare-style operations.

    IM7: ["magick", "compare"]  — `magick compare -metric AE ...`
    IM6: ["compare"]            — `compare -metric AE ...`
    Returns None if neither is available."""
    if shutil.which("magick"):
        return ["magick", "compare"]
    if shutil.which("compare"):
        return ["compare"]
    return None


def _resolve_ppm_converter():
    """Return a callable(ppm, png) that converts a PPM to PNG."""
    if _im_convert is not None:
        return lambda ppm, png, im=_im_convert: subprocess.run(
            im + [ppm, png], check=False)
    if shutil.which("pnmtopng"):
        def _pnmtopng(ppm, png):
            with open(png, "wb") as out:
                subprocess.run(["pnmtopng", ppm], stdout=out, check=False)
        return _pnmtopng
    return None


_im_convert = _resolve_im_convert()
_im_compare = _resolve_im_compare()
_ppm_to_png = _resolve_ppm_converter()
if _im_convert is None:
    note("no ImageMagick found (magick / convert) — screendump frames cannot "
         "be saved; install imagemagick")
elif _ppm_to_png is None:
    note("no PPM converter found (magick / convert / pnmtopng) — screendump "
         "frames cannot be saved; install imagemagick or netpbm")


def shot(idx, label):
    png = os.path.abspath(f"{outdir}/walkthrough-{flavor}-{idx:02d}.png")

    # VNC first: on the virgl path it is the only thing that works, and on the
    # non-GL path there is no vnc.sock so this costs one os.path.exists().
    if vnc_capture(png):
        print(f"captured step {idx}: {label} -> {png} (vnc)", flush=True)
        return png

    ppm = png[:-4] + ".ppm"
    hmp(f"screendump {ppm}")
    time.sleep(1.5)
    if os.path.exists(ppm):
        if _ppm_to_png is not None:
            _ppm_to_png(ppm, png)
        os.remove(ppm)
        print(f"captured step {idx}: {label} -> {png} (screendump)", flush=True)
        return png

    # Say which path failed and why. A silently missing frame here used to be
    # indistinguishable from a blank one, and blank-vs-absent is the difference
    # between "the compositor did not start" and "we cannot photograph it".
    print(f"!!! no capture at step {idx} ({label}): screendump found no surface "
          f"and no usable VNC at {vnc_sock}. On the virgl path start QEMU with "
          f"-vnc unix:<sock> and install vncdotool.", flush=True)
    return None


def send_keys(*keys):
    for k in keys:
        hmp(f"sendkey {k}")
        time.sleep(0.4)


def stddev(png):
    """Grayscale standard deviation — 0 means a flat (blank) image."""
    if _im_convert is None:
        return 0.0
    r = subprocess.run(
        _im_convert + [png, "-colorspace", "Gray", "-format",
                       "%[fx:standard_deviation]", "info:"],
        capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except (ValueError, FileNotFoundError):
        return 0.0


def changed_pixels(a, b):
    """Pixels differing between two frames (ImageMagick absolute-error metric)."""
    if _im_compare is None:
        return 0
    r = subprocess.run(_im_compare + ["-metric", "AE", "-fuzz", "5%", a, b, "null:"],
                       capture_output=True, text=True)
    m = re.search(r"(\d+)", (r.stderr or "").strip())
    return int(m.group(1)) if m else 0


# How the OCR pass is chosen, and why there is more than one.
#
# kde run 32735883406 read this off four distinct visual states:
#
#     state 0: 1 ft
#     state 1: hm
#     state 2: i]
#     state 3: lm
#
# Nine frames above the blank threshold, four distinct states, and a readiness
# stamp from the same guest saying `signal=frame-swapped page=welcome` -- the
# wizard was on screen and tesseract got two characters of noise off it. The
# spec keywords were never the problem; the pixels never became words.
#
# `--psm 6` is "assume a single uniform block of text". A desktop screenshot is
# not that: it is a window of sparse headings and buttons on a background, and
# psm 6 will happily return line noise rather than fail. Nothing downstream can
# tell that apart from a screen with no text on it, which is how "no installer
# screen was ever detected" survived as a diagnosis.
#
# So: score the result, and if it is not words, try the other readings before
# giving up --
#   * --psm 11 (sparse text), the segmentation a desktop actually needs;
#   * the same two against a negated copy, because tesseract wants dark ink on
#     light paper and a dark-themed frontend is the exact inverse. gnome's
#     Adwaita default is light and gnome is the flavor that has always scored;
#     that asymmetry is worth ruling in or out rather than assuming.
#
# The winning variant is recorded and reported. If plain psm 6 keeps winning,
# this costs one extra process on frames that were unreadable anyway; if a
# negated pass starts winning, that IS the finding.
MIN_WORD_CHARS = 8

def _text_score(text):
    """Alphabetic characters in words of 3+ letters.

    Deliberately not len(text): "1 ft\nhm\ni]" is 9 characters and zero
    words, and treating it as content is what made an unreadable screen look
    like a vocabulary mismatch."""
    return sum(len(w) for w in re.findall(r"[a-z]{3,}", text.lower()))


def readable(text):
    """Whether OCR output is words rather than noise."""
    return _text_score(text or "") >= MIN_WORD_CHARS


_ocr_variant = {}
# {frame: {pass_name: score}} -- every reading, not only the winner. The first
# version recorded the winner alone, and reported "best pass per frame: psm6"
# on kde run 32747410944 where in fact ALL FOUR passes scored zero. `>` is
# strictly greater, so a four-way tie leaves psm6 holding the title it started
# with, and the printed hint then read that as evidence FOR psm6 -- an
# argument from a tie. The scores say what the winner cannot.
_ocr_scores = {}


def _tesseract(png, psm):
    r = subprocess.run(["tesseract", png, "stdout", "--psm", psm],
                       capture_output=True, text=True)
    return (r.stdout or "").lower()


def ocr(png):
    if not shutil.which("tesseract"):
        return None

    best, best_name = _tesseract(png, "6"), "psm6"
    _ocr_scores[png] = {"psm6": _text_score(best)}
    if readable(best):
        _ocr_variant[png] = best_name
        return best

    candidates = [(_tesseract(png, "11"), "psm11")]

    # A negated copy, for a light-on-dark frontend. Skipped rather than
    # failed if ImageMagick is missing -- this is a fallback, not a
    # dependency.
    if _im_convert is not None:
        neg = png + ".neg.png"
        try:
            subprocess.run(_im_convert + [png, "-negate", neg],
                           check=False, capture_output=True)
            if os.path.exists(neg):
                candidates.append((_tesseract(neg, "6"), "psm6-negated"))
                candidates.append((_tesseract(neg, "11"), "psm11-negated"))
        finally:
            if os.path.exists(neg):
                os.unlink(neg)

    for text, name in candidates:
        _ocr_scores[png][name] = _text_score(text)
        if _text_score(text) > _text_score(best):
            best, best_name = text, name

    _ocr_variant[png] = best_name
    return best


def png_geometry(path):
    """(width, height) from the PNG IHDR, or None.

    Read here rather than shelled out to `identify`: a frame too small for its
    glyphs to survive is one of the readings of an unreadable screen, and it
    would be absurd to spawn a process to learn it."""
    try:
        with open(path, "rb") as f:
            head = f.read(24)
        if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
            return None
        return (int.from_bytes(head[16:20], "big"),
                int.from_bytes(head[20:24], "big"))
    except OSError:
        return None


def load_spec(path):
    """Minimal parser for the screens spec (avoids a hard PyYAML dependency)."""
    try:
        import yaml  # noqa
        with open(path) as f:
            return yaml.safe_load(f).get("screens", [])
    except Exception:
        pass
    screens, cur = [], None
    try:
        with open(path) as f:
            for line in f:
                s = line.strip()
                if s.startswith("- id:"):
                    cur = {"id": s.split(":", 1)[1].strip(), "required": False,
                           "keywords": [], "title": ""}
                    screens.append(cur)
                elif cur and s.startswith("title:"):
                    cur["title"] = s.split(":", 1)[1].strip()
                elif cur and s.startswith("required:"):
                    cur["required"] = s.split(":", 1)[1].strip() == "true"
                elif cur and s.startswith("keywords:"):
                    cur["keywords"] = re.findall(r'"([^"]+)"', s)
    except FileNotFoundError:
        pass
    return screens


# ── Capture ──────────────────────────────────────────────────────────────
time.sleep(5)  # let the installer settle on its first screen
frames = []

# Leave the shell overview before driving a single key.
#
# Run 32450214451's gnome leg reached this point with a mapped, correctly
# stamped installer window and still produced 9 frames, 2 visual states and
# zero page advances. The frames say why: the session was sitting in GNOME's
# ACTIVITIES OVERVIEW, with the installer rendered as a window thumbnail
# behind the "Type to search" entry. Every key went to the shell, not the
# app — the widen-the-focus-sweep loop then walked focus onto the
# thumbnail's CLOSE button and the dash icon, which is worse than useless:
# one more Return would have closed the installer.
#
# Escape is the right key and the only safe one here. In GNOME it closes the
# overview and does nothing when the overview is already down, so it costs a
# single keystroke on the four flavors that never had this problem. Super
# would TOGGLE — opening the overview on any session that was fine.
#
# Whether it was needed is itself a finding, so it is measured rather than
# assumed: capture before, press, capture after, and compare. A frontend
# that boots behind its own compositor's shell is a real defect in the live
# session, and quietly dismissing it would hide exactly the inconsistency
# this workflow exists to catch.
overlay_dismissed = False
_pre = shot(0, "initial screen")
if _pre:
    _probe = _pre[:-4] + "-preesc.png"
    shutil.copyfile(_pre, _probe)
    send_keys("esc")
    time.sleep(2)
    _post = shot(0, "initial screen (after leaving any shell overview)")
    if _post and changed_pixels(_probe, _post) > DIFF_PIXELS:
        overlay_dismissed = True
        note("a shell overlay was covering the installer at session start; "
             "'esc' dismissed it")
    try:
        os.remove(_probe)
    except OSError:
        pass
    p = _post or _pre
else:
    p = _pre
if p:
    frames.append(p)

# Walk forward: nudge focus to the primary action and advance, capturing the
# resulting screen. Tab reaches Next/Continue in GTK/Qt layouts.
#
# Activation is escalated rather than assumed. Run 29675493401 sent
# "tab tab ret" eight times against the KDE frontend and never left the
# welcome screen: the captured frames show a focus ring appearing on "Get
# Started", so Tab was landing but Return was not firing the button. Space
# activates a focused button in both GTK and Qt, so fall back to it when a
# step produces no visual change — and report which key worked, because
# "Return does not activate the primary action" is itself a UX finding worth
# seeing rather than silently working around.
# The tab count is escalated too. A fixed two tabs cannot work across pages
# with different widget counts: run 29681255102 advanced welcome -> disk with
# 'spc', then stalled for seven steps on Select Target Disk, where focus starts
# in the disk list and Continue is several widgets away — space just re-toggled
# the list selection. Each step with no visual change adds a tab, so focus
# sweeps outward until it lands on the primary action, and resets once a page
# advances.
activation = "ret"
switched = False
# Start at 0: try the DEFAULT ACTION before tabbing anywhere.
#
# This used to start at 2, so the harness never once pressed Enter on the
# focused widget — it always tabbed twice first. On a wizard whose primary
# action has focus that skips straight past it, and on GNOME's welcome screen
# tab order is install -> bluetooth -> recovery -> poweroff -> credits, so
# sweeping outward walks toward Credits and away from Install. Run
# 31183217981 opened the Credits modal and never left the welcome screen.
#
# Costs one step when the app sets no default focus — the existing widen loop
# picks up from 1 exactly as before — and saves the run when it does.
tabs = 0
MAX_TABS = 8
# Set once the escape hatch below has been spent; cleared by any real
# advance so a long run can escape more than one modal.
escaped = False
for i in range(1, steps + 1):
    send_keys(*(["tab"] * tabs), activation)
    time.sleep(3)
    p = shot(i, f"after advance {i}")
    if p:
        prev = frames[-1] if frames else None
        frames.append(p)
        moved = bool(prev) and changed_pixels(prev, p) > DIFF_PIXELS
        if moved:
            tabs = 0          # new page: try its default action first, again
            escaped = False   # re-arm the modal escape for the next stall
        elif prev:
            if not switched and activation == "ret":
                activation = "spc"
                switched = True
                print("  # 'ret' did not advance the installer — "
                      "escalating to 'spc' (space) for the remaining steps",
                      flush=True)
            elif tabs < MAX_TABS:
                tabs += 1
                print(f"  # no change — widening focus search to {tabs} tabs",
                      flush=True)
            elif not escaped:
                # A modal swallows the whole sweep. Starting the tab count at
                # 0 (above) stops the harness WALKING into GNOME's Credits
                # dialog, but nothing stops a dialog that opens for any other
                # reason — and once inside, every escalation is spent on the
                # modal's own widgets while the wizard behind it never moves.
                #
                # Run 31216208138's gnome leg is the shape: frame 02 is the
                # Credits modal, frame 03 is byte-identical to it, and the
                # remaining five steps produced no new screen. The harness
                # reported "6/8 transitions changed >500px" — opening and
                # scrolling a dialog counts as movement — so the stall was
                # invisible in every metric except the pictures.
                #
                # Escape is the one key that means "close this" in both GTK
                # and Qt, and it does nothing to a wizard page that has no
                # dialog open, so it is safe to spend a step on. Once only
                # per stall: re-armed by the next real advance, so a run
                # cannot sit in an Escape loop.
                escaped = True
                tabs = 0
                print("  # focus sweep exhausted — sending 'esc' in case a "
                      "modal (Credits, About, a file chooser) is on top",
                      flush=True)
                send_keys("esc")
                time.sleep(2)
            elif os.path.exists(vnc_sock) and shutil.which("vncdo") and shutil.which("socat"):
                # Fallback to mouse click on primary button location via VNC if keyboard navigation stalls
                # Primary action buttons ("Get Started", "Next", "Continue") sit near bottom right / center bottom
                print("  # keyboard navigation exhausted — attempting VNC mouse click on primary action button", flush=True)
                bridge = subprocess.Popen(
                    ["socat", f"TCP-LISTEN:{vnc_port},reuseaddr,fork", f"UNIX-CONNECT:{vnc_sock}"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    time.sleep(1)
                    # Click center-right / bottom-right region (x=700, y=550 for 1024x768 framebuffer)
                    subprocess.run(["vncdo", "-s", f"127.0.0.1::{vnc_port}", "move", "700", "550", "click", "1"],
                                   check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                finally:
                    bridge.terminate()
                    try:
                        bridge.wait(timeout=5)
                    except Exception:
                        bridge.kill()

print(f"\n# walkthrough verification ({flavor}) — {len(frames)} frames, "
      f"strict={strict}\n", flush=True)

# Reported, not enforced -- for now. The wizard behind it has never been
# exercised on gnome, so failing here would replace one unknown with
# another. It is a genuine live-session defect and belongs in the record
# while that sequencing plays out; see tuna-os/tunaOS#1941.
tap(not overlay_dismissed,
    f"{flavor}: installer is frontmost at session start",
    "a shell overlay (GNOME Activities overview or equivalent) was covering "
    "the installer and had to be dismissed with 'esc' before the walkthrough "
    "could drive it -- a user booting this ISO sees the same thing",
    enforced=False)

tap(len(frames) >= 2, f"{flavor}: captured at least 2 frames",
    f"got {len(frames)}")

# ── 1. RENDERS ───────────────────────────────────────────────────────────
# Non-strict for Smithay-on-GPU-less: blank there is expected, not a defect.
rendered = 0
for f in frames:
    sd = stddev(f)
    if sd > BLANK_STDDEV:
        rendered += 1
# NOT "the installer renders": this measures the whole framebuffer, so a
# booted desktop with no installer window at all passes it. cosmic did exactly
# that (run 29684495194) — 9/9 frames "rendered" while every frame was the bare
# COSMIC desktop, clock ticking, no window. Named for what it actually checks.
tap(rendered > 0, f"{flavor}: screen is not blank",
    f"{rendered}/{len(frames)} frames above stddev {BLANK_STDDEV} "
    f"(blank everywhere: check the serial log for an OOM kill FIRST — "
    f"a compositor the kernel keeps killing looks exactly like a GL failure)",
    enforced=strict)
note(f"{rendered}/{len(frames)} frames above stddev {BLANK_STDDEV} "
     f"(whole screen, not the installer window)")

# ── 2. ADVANCES ──────────────────────────────────────────────────────────
advanced = sum(1 for a, b in zip(frames, frames[1:])
               if changed_pixels(a, b) > DIFF_PIXELS)
# NOT "the installer advances": like the render check above, this measures the
# whole framebuffer, so anything that animates satisfies it. kde did exactly
# that (run 29914643652) — 8/8 transitions and 9 "distinct visual states" while
# every frame was the SDDM greeter's password prompt and the only thing moving
# was its clock. Named for what it actually checks; the screens section below
# is what decides whether the installer was ever on screen.
tap(advanced > 0, f"{flavor}: screen changes between steps",
    f"{advanced}/{max(len(frames) - 1, 0)} transitions changed >{DIFF_PIXELS}px "
    f"(0 means nothing on screen responded at all — stuck, modal, or crashed; "
    f">0 is not by itself evidence the installer moved — a clock will do it)",
    enforced=strict)
note(f"{advanced}/{max(len(frames) - 1, 0)} transitions changed >{DIFF_PIXELS}px"
     + (f"; primary action activated with '{activation}'" if advanced else ""))

# ── 3. SCREENS (feature parity) ──────────────────────────────────────────
# OCR is matched PER FRAME, and a frame only counts for a screen if the
# installer actually moved there.
#
# The previous version concatenated every frame's text and asked whether a
# keyword appeared anywhere. That reports screens the installer never showed:
# TunaOS's welcome page reads "You'll select a target disk, configure
# filesystem and encryption options, and the installer will do the rest",
# which alone matched the 'disk', 'encryption' AND 'install' keyword lists. Run
# 29675493401 duly recorded three screens as reached while every frame was the
# welcome screen — a parity matrix full of screens nobody has seen.
#
# Prose describing a screen is indistinguishable from that screen's heading in
# raw OCR, so the fix is positional rather than lexical: group the frames into
# distinct visual states, and refuse to credit any screen beyond the first to
# state 0. If the installer never advanced there is exactly one state, and the
# only screen that can honestly be claimed is the one it opened on.
spec = load_spec(spec_path)
have_ocr = shutil.which("tesseract") is not None

# Group frames into distinct visual states (consecutive near-identical frames
# are the same screen). state_of[i] is the state index of frame i.
state_of, state = [], 0
for i, f in enumerate(frames):
    if i > 0 and changed_pixels(frames[i - 1], f) > DIFF_PIXELS:
        state += 1
    state_of.append(state)
n_states = (state_of[-1] + 1) if state_of else 0

frame_text = []
if have_ocr:
    frame_text = [(ocr(f) or "") for f in frames]
else:
    note("tesseract not installed — screen detection skipped")

note(f"{n_states} distinct visual state(s) across {len(frames)} frames")
if n_states <= 1 and have_ocr:
    note("installer never advanced, so only its opening screen can be "
         "credited — later screens are reported unverified, not absent")

reached = {}
for idx, sc in enumerate(spec):
    if not have_ocr:
        reached[sc["id"]] = None
        continue
    kws = [k.lower() for k in sc.get("keywords", [])]
    hit_states = {state_of[i] for i, t in enumerate(frame_text)
                  if any(k in t for k in kws)}
    # Screens after the first must be seen on a state the installer actually
    # advanced to; a match confined to state 0 is prose on the opening screen.
    if idx > 0:
        hit_states.discard(0)
    hit = bool(hit_states)
    reached[sc["id"]] = hit
    where = (f"seen on visual state(s) {sorted(hit_states)}" if hit
             else "not found on any state the installer advanced to")
    tap(hit,
        f"{flavor}: reached '{sc['id']}' screen ({sc.get('title', '')})",
        where,
        enforced=strict and sc.get("required", False))
    if hit:
        note(where)

# ── No-window diagnosis ──────────────────────────────────────────────────
# If the screen is not blank yet no screen ever matched, the installer was
# never photographed, whatever the pixels did. Say so, rather than leaving six
# identical "screen not reached" lines for someone to interpret.
#
# This used to also require n_states <= 1, which silently disabled it in the
# case that needed it most: kde's greeter clock produced 9 states, so the
# diagnosis never printed and the run read as "advanced 8 times, found
# nothing". Movement is not evidence of an installer, so it is not a reason to
# withhold the diagnosis.
if have_ocr and not any(reached.values()) and rendered > 0:
    _moved = "nothing responded to input" if n_states <= 1 else (
        f"the screen changed {n_states - 1}x, but no change was an installer "
        f"screen (a greeter clock or desktop animation looks identical here)")
    # Deliberately lists the causes instead of naming a favourite.
    #
    # It used to end "most likely a login greeter or the bare desktop, with no
    # installer window mapped". On run 31171184497 that was wrong on every
    # count: the session was a fully drawn GNOME desktop, and the reason no
    # installer screen appeared is that the gnome live adapter never launched
    # one — it had no autostart entry at all, while kde, cosmic and xfce did.
    # A confident wrong guess is worse than no guess: it sent the investigation
    # looking for a greeter, then for a GTK renderer bug, before anyone read
    # the five desktop adapters and saw the asymmetry.
    #
    # "process is running" is also weaker evidence than it sounds. That gate
    # lives in installer-smoke.yml and does not run here, so on this harness it
    # is an assumption, not a check.
    print(f"  # DIAGNOSIS: {flavor} — no installer screen was ever detected "
          f"and {_moved}. Causes, in the order they are worth checking:\n"
          f"  #   1. the installer was never LAUNCHED — check that "
          f"live-iso/common/src/desktop-{flavor}.sh arranges an autostart "
          f"entry, a systemd user unit or a spawn-at-startup line\n"
          f"  #   2. it launched and exited — check the user journal\n"
          f"  #   3. the COMPOSITOR is being OOM-killed — grep the serial log "
          f"for 'Out of memory: Killed process'. This is what a 4G guest does "
          f"to cosmic-comp, and every frame is black, which reads as a GL "
          f"failure and is not one\n"
          f"  #   4. its window is mapped but not drawing (no GL path)\n"
          f"  #   5. the frames are a greeter, so the session never started\n"
          f"  # These look identical in the numbers and completely different in "
          f"the PNGs. Look at the captured frames first — an empty desktop with "
          f"the app merely pinned to a dock or launcher is case 1, not a UI bug.",
          flush=True)

# ── What the OCR actually read ───────────────────────────────────────────
# The five causes above share an assumption that is false often enough to cost
# whole rounds: that a screen which matched nothing was not the installer.
# There is a sixth cause, and on kde it is the true one --
#
#     the installer WAS on screen, and no keyword in the spec describes what
#     it says.
#
# kde run 32718219267 reported "no installer screen was ever detected" while
# the readiness stamp written by that same process, in that same guest, read
#
#     window=ApplicationWindow signal=frame-swapped page=welcome
#
# A frame had been swapped and the app was on its welcome page. Six red lines
# and a diagnosis pointing at autostart, OOM-kills and missing GL paths, for a
# frontend that was working.
#
# I then "corrected" that to say the wizard draws the step name "Welcome"
# above the page (Wizard.qml:46,185) and so the word WAS on screen. The
# published capture shows it is not: the welcome step reads "Install
# Yellowfin", then the wizard prose, then "Next". Reading the QML told me what
# should render; the picture told me what did.
#
# Which is the argument for this block. Two rounds went into explaining a
# screen nobody had looked at, and both explanations came from source code.
# Printing what the OCR read is cheaper than either.
#
# Printing the text settles it without downloading an artifact: text present
# and unmatched is a spec gap, text absent everywhere is a rendering or OCR
# failure, and those want opposite fixes.
#
# Gated on a MISSING REQUIRED SCREEN rather than on "nothing matched at all",
# because the partial case is the one this run will produce next: with the
# welcome keyword fixed, kde is expected to credit welcome and still miss the
# later screens, and that is exactly when someone needs to see the words on
# the page. Silent on a fully green leg; printed on every leg that fails.
_missing_required = [sc["id"] for sc in spec
                     if sc.get("required", False) and not reached.get(sc["id"])]
if have_ocr and _missing_required:
    _seen = {}
    for _i, _t in enumerate(frame_text):
        _seen.setdefault(state_of[_i], "")
        if not _seen[state_of[_i]]:
            _seen[state_of[_i]] = " ".join(_t.split())
    print("  # what the OCR actually read, per visual state "
          f"(missing required: {', '.join(_missing_required)}):", flush=True)
    for _s in sorted(_seen):
        print(f"  #   state {_s}: {_seen[_s] or '(no text)'}"[:220], flush=True)

    # The first version of this block asked `if any(_seen.values())` and, on
    # kde run 32735883406, printed "1 ft / hm / i] / lm" under a heading
    # inviting the reader to fix the keyword list. Nine non-blank frames of
    # line noise are not a vocabulary problem, and a truthiness test cannot
    # say so. Score it instead.
    if any(readable(t) for t in _seen.values()):
        print("  # Those are words, so this is cause 6: the spec's keywords do "
              "not describe this frontend's screens. Fix "
              "tests/installer-screens.yaml against the frontend's source "
              "strings -- not the frontend against the spec.", flush=True)
    else:
        _geo = png_geometry(frames[0]) if frames else None
        _w, _h = _geo or ("?", "?")
        # Best score each pass reached on ANY frame. Reporting the winner
        # alone cannot distinguish "psm6 read the most" from "nothing read
        # anything and psm6 kept the tie", and those are different findings.
        _totals = {}
        for _scores in _ocr_scores.values():
            for _name, _score in _scores.items():
                _totals[_name] = max(_totals.get(_name, 0), _score)
        _table = ", ".join(f"{_n}={_v}" for _n, _v in sorted(_totals.items()))
        print("  # Those are NOT words. Every OCR reading came back as noise, "
              "so this is not a keyword gap -- the pixels never became text.\n"
              f"  # Frame geometry {_w}x{_h}. Best word-score any frame reached, "
              f"per pass: {_table or 'none'} (readable needs "
              f"{MIN_WORD_CHARS}).\n"
              "  # A *-negated pass scoring HIGHER means the frontend draws "
              "light text on a dark ground and tesseract wants the inverse. "
              "All passes at or near zero means no segmentation helped, and "
              "the next question is the frame itself, not the spec -- pull the "
              "published capture and look at it before changing anything.",
              flush=True)

# ── Result for the parity matrix ─────────────────────────────────────────
summary = {
    "flavor": flavor,
    "frames": len(frames),
    "rendered_frames": rendered,
    "advanced_transitions": advanced,
    # How many genuinely different screens were seen. 1 means the installer
    # never advanced, which caps how much the "screens" map below can claim.
    "visual_states": n_states,
    "activation_key": activation,
    "ocr": have_ocr,
    "screens": reached,
    "strict": strict,
    "failures": _fails,
    # The assertions themselves, not just how many failed. A bare count says
    # "5 failed" and leaves every consumer -- the scoreboard, a reviewer, a
    # test -- to re-parse stdout to learn WHICH, and whether each was
    # enforced or advisory.
    "tap": _tap,
}
with open(os.path.join(outdir, f"walkthrough-{flavor}.json"), "w") as f:
    json.dump(summary, f, indent=2)

print(f"\n# Results: {sum(1 for t in _tap if t['ok'])} passed, "
      f"{sum(1 for t in _tap if not t['ok'])} failed, {len(_tap)} total", flush=True)
print(f"# screens reached: "
      f"{', '.join(k for k, v in reached.items() if v) or '(none detected)'}", flush=True)
sys.exit(1 if _fails else 0)
