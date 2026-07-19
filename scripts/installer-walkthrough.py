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
    if diagnostic:
        print(f"  # {diagnostic}", flush=True)
    _tap.append({"ok": bool(ok), "desc": desc, "enforced": enforced})
    if not ok and enforced:
        _fails += 1


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
# resulting screen. Tab reaches Next/Continue in GTK/Qt layouts; Return fires it.
for i in range(1, steps + 1):
    send_keys("tab", "tab", "ret")
    time.sleep(3)
    p = shot(i, f"after advance {i}")
    if p:
        frames.append(p)

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

# ── 2. ADVANCES ──────────────────────────────────────────────────────────
advanced = sum(1 for a, b in zip(frames, frames[1:])
               if changed_pixels(a, b) > DIFF_PIXELS)
tap(advanced > 0, f"{flavor}: installer advances between screens",
    f"{advanced}/{max(len(frames) - 1, 0)} transitions changed >{DIFF_PIXELS}px "
    f"(0 means it never left the first screen — stuck, modal, or crashed)",
    enforced=strict)

# ── 3. SCREENS (feature parity) ──────────────────────────────────────────
spec = load_spec(spec_path)
text = ""
have_ocr = shutil.which("tesseract") is not None
if have_ocr:
    for f in frames:
        text += (ocr(f) or "") + "\n"
else:
    print("  # tesseract not installed — screen detection skipped", flush=True)

reached = {}
for sc in spec:
    hit = any(k.lower() in text for k in sc.get("keywords", [])) if have_ocr else None
    reached[sc["id"]] = hit
    if have_ocr:
        tap(bool(hit),
            f"{flavor}: reached '{sc['id']}' screen ({sc.get('title', '')})",
            "not found in any frame's text",
            enforced=strict and sc.get("required", False))

# ── Result for the parity matrix ─────────────────────────────────────────
summary = {
    "flavor": flavor,
    "frames": len(frames),
    "rendered_frames": rendered,
    "advanced_transitions": advanced,
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
