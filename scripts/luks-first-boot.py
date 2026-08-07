#!/usr/bin/env python3
"""Drive the FIRST boot of a LUKS-installed system over the QEMU serial.

With first-boot TPM2 enrollment (fisherman#48), the first installed boot
still needs a key at the cryptsetup prompt — the TPM token isn't enrolled
yet. This connects to the QEMU serial unix socket, injects the known test
passphrase when prompted, waits for the first-boot enrollment oneshot to
run (login reached + a grace period), then powers the guest off via the
monitor socket. The SECOND boot (driven by iso-e2e.sh) then proves TPM
auto-unlock: no passphrase prompt.

Usage: luks-first-boot.py <serial.sock> <monitor.sock> <passphrase> [timeout]
Exit 0 on success (passphrase accepted + userspace reached), non-zero else.
"""
import re
import socket
import sys
import time

serial_path, monitor_path, passphrase = sys.argv[1], sys.argv[2], sys.argv[3]
timeout = int(sys.argv[4]) if len(sys.argv) > 4 else 900


def connect(path, tries=60):
    for _ in range(tries):
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(path)
            s.settimeout(5)
            return s
        except OSError:
            time.sleep(1)
    raise SystemExit(f"could not connect to {path}")


ser = connect(serial_path)
buf = b""
deadline = time.time() + timeout
sent = False
reached_login = False
login_at = None

# How long past login to keep draining the serial waiting for the desktop
# contract marker. 0 disables the wait entirely (the historic behaviour).
#
# The LUKS passphrase gate used to power the guest off 60s after login, which
# proves the disk unlocked and userspace came up -- and nothing at all about
# whether a desktop session followed. On yellowfin:gnome that is the whole
# difference between "encrypted install boots" and "lands on a usable
# desktop": tunaos-desktop-contract.service is WantedBy=graphical.target and
# Requires=display-manager.service, so its marker is the first evidence that
# the DM actually started on the INSTALLED system rather than the live ISO.
#
# Bounded, and it costs nothing on a healthy image -- the contract fired at
# 12.8s of uptime in the live environment. An image whose DM never starts
# pays the full window once, and that is exactly the case worth waiting for.
contract_wait = int(sys.argv[5]) if len(sys.argv) > 5 else 0
CONTRACT_RE = re.compile(r"TUNAOS_DESKTOP_CONTRACT_(OK|FAIL)")
contract_result = None

while time.time() < deadline:
    try:
        d = ser.recv(4096)
        if d:
            buf += d
            sys.stdout.buffer.write(d)
            sys.stdout.flush()
    except socket.timeout:
        pass

    text = buf[-4000:].decode("utf-8", "replace")

    if not sent and "passphrase for disk root" in text.lower():
        print("\n>>> injecting LUKS passphrase", flush=True)
        ser.sendall(passphrase.encode() + b"\n")
        sent = True
        time.sleep(2)

    if not reached_login and ("login:" in text or "Reached target" in text and "Multi-User" in text):
        reached_login = True
        login_at = time.time()
        print("\n>>> userspace reached; letting first-boot enrollment run", flush=True)

    # Scan the WHOLE buffer, not the 4000-byte window above: the contract
    # marker is a single line emitted once, and at 10s-ish poll granularity a
    # burst of systemd output can push it out of the window between reads.
    if contract_result is None:
        m = CONTRACT_RE.search(buf.decode("utf-8", "replace"))
        if m:
            contract_result = m.group(1).lower()
            print(f"\n>>> desktop contract marker seen: {contract_result}", flush=True)

    # Give the multi-user first-boot oneshot time to enroll, then power off.
    if reached_login and login_at and time.time() - login_at > 60:
        # Enrollment window is done. Keep draining only if we were asked to
        # wait for the contract and it has not arrived yet.
        if contract_wait <= 0 or contract_result is not None:
            break
        if time.time() - login_at > 60 + contract_wait:
            print(
                f"\n!!! no desktop contract marker within {contract_wait}s of login",
                flush=True,
            )
            break

if not sent:
    print("\n!!! passphrase prompt never appeared", flush=True)
    sys.exit(2)
if not reached_login:
    print("\n!!! first boot never reached userspace after unlock", flush=True)
    sys.exit(3)

# Graceful power off so swtpm state + LUKS metadata flush cleanly.
try:
    mon = connect(monitor_path, tries=5)
    mon.sendall(b"system_powerdown\n")
    time.sleep(8)
except Exception as e:
    print(f"powerdown note: {e}", flush=True)
print("\n>>> first boot complete (passphrase accepted, enrollment window elapsed)", flush=True)
# A single machine-readable line for iso-e2e.sh to harvest. "absent" is
# deliberately distinct from "fail": fail means the contract ran and the
# desktop was wrong; absent means nothing ever emitted a marker, which is
# usually the DM not starting -- a different fault at a different layer.
print(
    f"LUKS_FIRST_BOOT_DESKTOP_CONTRACT={contract_result or 'absent'}",
    flush=True,
)
sys.exit(0)
