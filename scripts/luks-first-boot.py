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

TUNAOS_LUKS_GRUB_APPEND="<kargs>" types <kargs> onto the kernel line in GRUB's
entry editor for THIS boot only; the installed disk is not modified. Exit 5
when that edit cannot be made.
"""
import os
import re
import socket
import sys
import time

serial_path, monitor_path, passphrase = sys.argv[1], sys.argv[2], sys.argv[3]
timeout = int(sys.argv[4]) if len(sys.argv) > 4 else 900
diagnostic_observe = os.environ.get("TUNAOS_INSTALLED_BOOT_DIAGNOSTIC") == "1"


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

# Dracut's emergency shell announces itself and then waits forever; the boot
# will never reach userspace, and the ONLY diagnosis — rdsosreport.txt — lives
# inside the guest and dies with it. guppy:xfce hit exactly this (run
# 31182709691): "Failed to start Switch Root", emergency shell, and an
# artifact that proves the failure happened while containing nothing about
# why. The console is interactive at that prompt, so harvest the report
# instead of timing out around it: press Enter for the maintenance shell,
# cat the report and the journal tail to the serial (which tee already
# captures into installed-serial.log), then bail with the existing exit 3.
emergency_seen = False


def harvest_emergency(ser):
    if diagnostic_observe:
        print("DIAGNOSTIC_EMERGENCY_OBSERVED", flush=True)
        return
    print("\n>>> emergency shell detected; harvesting rdsosreport", flush=True)
    ser.sendall(b"\n")
    time.sleep(3)
    ser.sendall(b"cat /run/initramfs/rdsosreport.txt 2>/dev/null || true\n")
    time.sleep(5)
    ser.sendall(b"journalctl -b --no-pager -n 120 2>/dev/null || true\n")
    # Drain whatever the guest prints for a bounded window.
    drain_until = time.time() + 30
    while time.time() < drain_until:
        try:
            d = ser.recv(4096)
            if d:
                sys.stdout.buffer.write(d)
                sys.stdout.flush()
        except socket.timeout:
            # Expected: the guest is simply quiet right now. Keep polling until
            # drain_until rather than cutting the harvest short.
            pass


# A GUI install from published media boots with `rhgb quiet` and no serial
# console, so the cryptsetup prompt goes to Plymouth and never reaches the
# serial this script reads. Run 40074592548 sat for 15 minutes at a framebuffer
# that showed one kernel line. The strict harness cannot add kargs at install
# time without changing what it qualifies, so it asks for them per boot.
# GRUB's menu is mirrored to the serial by OVMF, OVMF forwards serial input to
# GRUB's EFI console, and GRUB maps control bytes from a serial terminal to
# Ctrl-<key>.
grub_append = os.environ.get("TUNAOS_LUKS_GRUB_APPEND", "").strip()
if diagnostic_observe and grub_append:
    sys.exit(5)
grub_edited = not grub_append
ANSI_RE = re.compile(r"\x1b\[[0-9;:?=]*[A-Za-z]")
# blscfg (Fedora/CentOS grub2) generates every BLS menu entry as exactly
# these commands, in this order, before `linux`; the editor opens on line 0.
BLS_PREAMBLE = ("load_video", "set gfxpayload=keep", "insmod gzio")


def edit_grub_entry(ser, extra):
    print(f"\n>>> GRUB menu seen; appending for this boot only: {extra}", flush=True)
    ser.sendall(b"e")
    screen = b""
    until = time.time() + 30
    while time.time() < until:
        try:
            d = ser.recv(4096)
        except socket.timeout:
            d = b""
        if d:
            screen += d
            sys.stdout.buffer.write(d)
            sys.stdout.flush()
        plain = ANSI_RE.sub("\n", screen.decode("utf-8", "replace"))
        # The menu never shows command text, so a linux and an initrd line
        # mean the editor is open and drawn through the end of the entry.
        if re.search(r"(?m)^\s*linux\s[\s\S]*\binitrd\s", plain):
            break
    plain = ANSI_RE.sub("\n", screen.decode("utf-8", "replace"))
    linux = re.search(r"(?m)^\s*linux\s", plain)
    if not linux:
        print("\n!!! GRUB entry editor did not open with a linux line", flush=True)
        return False
    head = plain[: linux.start()]
    positions = [head.find(cmd) for cmd in BLS_PREAMBLE]
    if -1 in positions or positions != sorted(positions) or "setparams" in head:
        print("\n!!! GRUB entry is not the blscfg layout; refusing to guess the linux line", flush=True)
        return False
    ser.sendall(b"\x0e" * len(BLS_PREAMBLE))  # Ctrl-N: down to the linux line
    time.sleep(0.5)
    ser.sendall(b"\x05")  # Ctrl-E: end of the (wrapped) logical line
    time.sleep(0.5)
    ser.sendall(b" " + extra.encode())
    time.sleep(1)
    ser.sendall(b"\x18")  # Ctrl-X: boot the edited entry
    print("\n>>> GRUB entry edited; booting", flush=True)
    return True


while time.time() < deadline:
    try:
        d = ser.recv(4096)
        if d:
            buf += d
            if diagnostic_observe:
                buf = buf[-1024*1024:]
            else:
                sys.stdout.buffer.write(d)
                sys.stdout.flush()
    except socket.timeout:
        pass

    text = buf[-4000:].decode("utf-8", "replace")

    if not grub_edited and "press enter to boot the selected os" in text.lower():
        if not edit_grub_entry(ser, grub_append):
            sys.exit(5)
        grub_edited = True
        continue

    if not sent and "passphrase for disk root" in text.lower():
        if diagnostic_observe:
            print("DIAGNOSTIC_PROMPT_OBSERVED_NO_UNLOCK", flush=True)
            sys.exit(77)
        print("\n>>> injecting LUKS passphrase", flush=True)
        ser.sendall(passphrase.encode() + b"\n")
        sent = True
        time.sleep(2)

    if not reached_login and ("login:" in text or "Reached target" in text and "Multi-User" in text):
        reached_login = True
        login_at = time.time()
        print("\n>>> userspace reached; letting first-boot enrollment run", flush=True)

    # Initramfs gave up: userspace will never come. Capture the diagnosis the
    # emergency shell offers, then stop burning the timeout — the exit path
    # below reports "never reached userspace" exactly as before.
    if not emergency_seen and not reached_login and "Entering emergency mode" in text:
        emergency_seen = True
        harvest_emergency(ser)
        break

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
#
# Unless the caller still has work to do inside this guest. iso-e2e.sh
# photographs the installed desktop on THIS boot (a powerdown sent here raced
# that capture and left a black frame, tunaOS#979), and its greeter-login phase
# logs in over SSH and sendkey. So iso-e2e.sh always sets
# TUNAOS_LUKS_NO_POWEROFF=1 and powers the guest down itself afterwards.
if os.environ.get("TUNAOS_LUKS_NO_POWEROFF") == "1":
    print("\n>>> leaving the guest running for the caller's session phase",
          flush=True)
    print(
        f"LUKS_FIRST_BOOT_DESKTOP_CONTRACT={contract_result or 'absent'}",
        flush=True,
    )
    sys.exit(0)

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
