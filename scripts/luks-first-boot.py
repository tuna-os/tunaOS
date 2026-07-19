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

    # Give the multi-user first-boot oneshot time to enroll, then power off.
    if reached_login and login_at and time.time() - login_at > 60:
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
sys.exit(0)
