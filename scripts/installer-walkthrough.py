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


def shot(idx, label):
    ppm = os.path.abspath(f"{outdir}/walkthrough-{flavor}-{idx:02d}.ppm")
    png = ppm[:-4] + ".png"
    hmp(f"screendump {ppm}")
    time.sleep(1.5)
    if os.path.exists(ppm):
        subprocess.run(["convert", ppm, png], check=False)
        os.remove(ppm)
        print(f"captured step {idx}: {label} -> {png}", flush=True)
        return png
    print(f"!!! no screendump at step {idx} ({label})", flush=True)
    return None


def send_keys(*keys):
    for k in keys:
        hmp(f"sendkey {k}")
        time.sleep(0.4)


def stddev(png):
    """Grayscale standard deviation — 0 means a flat (blank) image."""
    r = subprocess.run(
        ["convert", png, "-colorspace", "Gray", "-format",
         "%[fx:standard_deviation]", "info:"],
        capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def changed_pixels(a, b):
    """Pixels differing between two frames (ImageMagick absolute-error metric)."""
    r = subprocess.run(["compare", "-metric", "AE", "-fuzz", "5%", a, b, "null:"],
                       capture_output=True, text=True)
    m = re.search(r"(\d+)", (r.stderr or "").strip())
    return int(m.group(1)) if m else 0


def ocr(png):
    if not shutil.which("tesseract"):
        return None
    r = subprocess.run(["tesseract", png, "stdout", "--psm", "6"],
                       capture_output=True, text=True)
    return (r.stdout or "").lower()


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
p = shot(0, "initial screen")
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
activation = "ret"
switched = False
for i in range(1, steps + 1):
    send_keys("tab", "tab", activation)
    time.sleep(3)
    p = shot(i, f"after advance {i}")
    if p:
        prev = frames[-1] if frames else None
        frames.append(p)
        if (prev and not switched
                and changed_pixels(prev, p) <= DIFF_PIXELS
                and activation == "ret"):
            activation = "spc"
            switched = True
            print("  # 'ret' did not advance the installer — "
                  "escalating to 'spc' (space) for the remaining steps",
                  flush=True)

print(f"\n# walkthrough verification ({flavor}) — {len(frames)} frames, "
      f"strict={strict}\n", flush=True)

tap(len(frames) >= 2, f"{flavor}: captured at least 2 frames",
    f"got {len(frames)}")

# ── 1. RENDERS ───────────────────────────────────────────────────────────
# Non-strict for Smithay-on-GPU-less: blank there is expected, not a defect.
rendered = 0
for f in frames:
    sd = stddev(f)
    if sd > BLANK_STDDEV:
        rendered += 1
tap(rendered > 0, f"{flavor}: installer renders actual content",
    f"{rendered}/{len(frames)} frames above stddev {BLANK_STDDEV} "
    f"(blank everywhere usually means no GL — niri/xfwl4 need virgl)",
    enforced=strict)
note(f"{rendered}/{len(frames)} frames above stddev {BLANK_STDDEV}")

# ── 2. ADVANCES ──────────────────────────────────────────────────────────
advanced = sum(1 for a, b in zip(frames, frames[1:])
               if changed_pixels(a, b) > DIFF_PIXELS)
tap(advanced > 0, f"{flavor}: installer advances between screens",
    f"{advanced}/{max(len(frames) - 1, 0)} transitions changed >{DIFF_PIXELS}px "
    f"(0 means it never left the first screen — stuck, modal, or crashed)",
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
}
with open(os.path.join(outdir, f"walkthrough-{flavor}.json"), "w") as f:
    json.dump(summary, f, indent=2)

print(f"\n# Results: {sum(1 for t in _tap if t['ok'])} passed, "
      f"{sum(1 for t in _tap if not t['ok'])} failed, {len(_tap)} total", flush=True)
print(f"# screens reached: "
      f"{', '.join(k for k, v in reached.items() if v) or '(none detected)'}", flush=True)
sys.exit(1 if _fails else 0)
