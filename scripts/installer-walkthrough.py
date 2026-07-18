#!/usr/bin/env python3
"""Capture an installer click-through walkthrough via the QEMU monitor.

Drives the running installer with hardware-level key events (HMP
`sendkey`) and captures each screen with `screendump` — compositor-
agnostic (KDE/COSMIC/Niri all work), no ydotool/Wayland tooling in the
guest. Produces a numbered sequence of PNGs for the docs walkthrough.

It does NOT try to complete a real install; it steps forward through the
installer's screens (Tab to reach the primary action, Return to advance)
and screenshots each, which is what a walkthrough needs. On a desktop
image in a throwaway CI VM, letting it proceed is harmless anyway.

Usage: installer-walkthrough.py <monitor.sock> <outdir> [steps] [flavor]
"""
import os
import socket
import subprocess
import sys
import time

mon_path = sys.argv[1]
outdir = sys.argv[2]
steps = int(sys.argv[3]) if len(sys.argv) > 3 else 8
flavor = sys.argv[4] if len(sys.argv) > 4 else "de"
os.makedirs(outdir, exist_ok=True)


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
        # root-owned when qemu runs under sudo; best-effort chown handled by caller
        print(f"captured step {idx}: {label} -> {png}", flush=True)
        return png
    print(f"!!! no screendump at step {idx} ({label})", flush=True)
    return None


def send_keys(*keys):
    for k in keys:
        hmp(f"sendkey {k}")
        time.sleep(0.4)


# Let the installer settle on its first screen.
time.sleep(5)
shot(0, "initial screen")

# Walk forward. Each iteration: nudge focus to the primary action and
# advance, then capture the resulting screen. Tab reaches the Next/Continue
# button in GTK/Qt installers; Return activates it. A few Tabs covers
# layouts where Next isn't the first focusable control.
for i in range(1, steps + 1):
    send_keys("tab", "tab", "ret")
    time.sleep(3)
    shot(i, f"after advance {i}")

print("walkthrough capture complete", flush=True)
