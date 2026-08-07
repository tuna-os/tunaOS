#!/usr/bin/env python3
"""Fake QEMU serial+monitor sockets to drive luks-first-boot.py locally."""
import os, socket, sys, threading, time

sdir, mode = sys.argv[1], sys.argv[2]
os.makedirs(sdir, exist_ok=True)
ser_p, mon_p = f"{sdir}/ser.sock", f"{sdir}/mon.sock"
for p in (ser_p, mon_p):
    if os.path.exists(p):
        os.unlink(p)


def listen(path):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(path)
    s.listen(1)
    return s


ser_l, mon_l = listen(ser_p), listen(mon_p)
threading.Thread(target=lambda: mon_l.accept(), daemon=True).start()
c, _ = ser_l.accept()
c.sendall(b"Please enter passphrase for disk root:\n")
time.sleep(1)
c.recv(4096)  # the injected passphrase
c.sendall(b"[    5.0] Reached target Multi-User System\nlocalhost login:\n")
if mode in ("ok", "fail"):
    # Emit a large burst first, so a sliding-window scan would lose the marker.
    time.sleep(2)
    c.sendall(b"[    6.0] noise line padding the buffer\n" * 400)
    time.sleep(1)
    c.sendall(
        b"[   12.8] verify-desktop-experience[1286]: TUNAOS_DESKTOP_CONTRACT_"
        + (b"OK desktop=gnome experience=x\n" if mode == "ok" else b"FAIL desktop=gnome\n")
    )
    c.sendall(b"[   13.0] more noise after the marker\n" * 400)
time.sleep(400)
