#!/usr/bin/env python3
"""End-to-end run of one installer medium cell (tunaOS#4910).

Builds nothing: CI builds the medium per cell first by calling
installer-medium/build-medium.sh. This script boots the exact bytes twice
(CD-ROM with `media=cdrom`, and USB disk), runs the 7 stages with
screenshots, and writes JSON evidence. Offline by default (SLIRP
restrict=on proves the install needs no network, tunaOS#4903).

Usage:
    run_e2e.py --cell tromso:kde --medium OUT.ISO --work DIR [--dry-run]
    run_e2e.py --list-stages

--dry-run prints every step and touches nothing: no QEMU, no network, no
disk. Unit tests and local runs use it; CI runs the real boots.
"""

from __future__ import annotations

import argparse
import base64
import collections
import contextlib
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import ocr_fallback
from atspi_match import RECOVERY_KEY_RE, qualify
from driver import Driver, DriverError
from qmp_input import click_at
from stages import EL10_REBOOT_TODO, plan_for_cell, stage_ids
from tree_dump import (
    GUEST_DUMP_SOURCE,
    parse_tree,
    ssh_dump_command,
    ssh_node_command,
    ssh_press_command,
    summarize,
)

SCREEN_W, SCREEN_H = 1280, 800
SSH_TIMEOUT = 600
STAMP_TIMEOUT = 300
PAGE_TIMEOUT = 600


def build_netdev(ssh_port, offline=True):
    """SLIRP netdev value; restrict=on keeps the SSH forward, drops egress."""
    restrict = ",restrict=on" if offline else ""
    return f"user,id=net0{restrict},hostfwd=tcp:127.0.0.1:{ssh_port}-:22"


def kvm_args(kvm=True):
    """Hardware accel when /dev/kvm allows it, TCG fallback otherwise.

    kvm=False (--no-kvm) forces TCG even where /dev/kvm exists."""
    node = Path("/dev/kvm")
    # The CPU model matters: EL10 userspace needs x86-64-v3, and QEMU's
    # default model (qemu64) is x86-64-v1, so an EL10 cell cannot start init
    # on it. `host` passes the runner's CPU through; `max` is the TCG
    # equivalent.
    if kvm and node.exists() and os.access(node, os.R_OK | os.W_OK):
        return ["-accel", "kvm", "-cpu", "host"]
    return ["-accel", "tcg", "-cpu", "max"]


def firmware_args(ovmf_code, ovmf_vars=None):
    """OVMF as two pflash drives: the code read-only, the variables writable.

    `-bios OVMF_CODE_4M.fd` does not start: the file is the code half of a
    split build ("qemu: could not load PC BIOS", run 45557106112). The
    variable store is a per-lane copy, so the boot entry that the install
    writes is still there after the reboot into the installed system.
    """
    out = ["-drive", f"if=pflash,format=raw,unit=0,readonly=on,file={ovmf_code}"]
    if ovmf_vars:
        out += ["-drive", f"if=pflash,format=raw,unit=1,file={ovmf_vars}"]
    return out


def build_qemu_cmd(
    medium,
    target_disk,
    work,
    ssh_port,
    boot,
    ovmf_code,
    offline=True,
    tpm_sock=None,
    virgl=False,
    kvm=True,
    extra=(),
    ovmf_vars=None,
    serial=None,
):
    """QEMU command booting the medium bytes as CD-ROM or as a USB disk."""
    work = Path(work)
    cmd = [
        "qemu-system-x86_64",
        "-machine",
        "q35",
        # cosmic-comp is killed for memory in 4 GiB (installer-smoke.yml, run
        # 31216208138); the live root is a tmpfs overlay on top of that.
        "-m",
        "8192",
        "-smp",
        "4",
        *kvm_args(kvm),
        *firmware_args(ovmf_code, ovmf_vars),
        # q35 has no USB controller of its own: without one QEMU stops with
        # "No 'usb-bus' bus found for device 'usb-tablet'".
        "-device",
        "qemu-xhci,id=xhci",
        "-device",
        "usb-tablet",
        "-netdev",
        build_netdev(ssh_port, offline),
        "-device",
        "virtio-net-pci,netdev=net0",
        "-drive",
        f"file={target_disk},format=qcow2,if=none,id=target",
        "-device",
        "virtio-blk-pci,drive=target,serial=TARGET",
        "-serial",
        f"file:{work}/{serial or f'serial-{boot}.log'}",
        "-qmp",
        f"unix:{work}/qmp.sock,server=on,wait=off",
    ]
    if boot == "cdrom":
        cmd += ["-cdrom", str(medium)]
    elif boot == "usb":
        cmd += [
            "-drive",
            f"file={medium},format=raw,if=none,id=usb,readonly=on",
            "-device",
            "usb-storage,drive=usb,serial=MEDIUM",
        ]
    elif boot != "disk":
        raise ValueError(f"boot must be cdrom, usb or disk, got {boot!r}")
    if tpm_sock:
        cmd += [
            "-chardev",
            f"socket,id=chrtpm,path={tpm_sock}",
            "-tpmdev",
            "emulator,id=tpm0,chardev=chrtpm",
            "-device",
            "tpm-crb,tpmdev=tpm0",
        ]
    if virgl:
        # QEMU 8.2 screendump has no console surface for a GL scanout ("no
        # surface", karnataka pod, medium run 45822993049). egl-headless still
        # copies each frame into that surface for the VNC server, so the
        # screenshots come from a VNC socket (Qmp.screendump).
        cmd += ["-display", "egl-headless,gl=on", "-device", "virtio-vga-gl"]
        cmd += ["-vnc", f"unix:{work}/vnc.sock"]
    else:
        cmd += ["-display", "none", "-vga", "virtio"]
    cmd.extend(extra)
    return cmd


class Qmp:
    """Minimal QMP client: one connection per call batch."""

    def __init__(self, sock):
        self.sock = Path(sock)

    def run(self, *commands):
        """Send QMP commands; return replies. Raises DriverError on error."""
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(15)
            try:
                s.connect(str(self.sock))
            except OSError as exc:
                raise DriverError(f"QMP connect failed: {exc}") from exc
            stream = s.makefile("rwb", buffering=0)

            def reply():
                while True:
                    line = stream.readline()
                    if not line:
                        raise DriverError("QMP connection closed")
                    msg = json.loads(line)
                    if "return" in msg or "error" in msg:
                        return msg

            # The greeting is {"QMP": ...}: it has no "return" key, so it is
            # read as a line. reply() waited for one and timed out on every
            # call (measured with a real QEMU, 2026-11-25).
            if not stream.readline():
                raise DriverError("QMP connection closed before the greeting")
            stream.write(b'{"execute": "qmp_capabilities"}\n')
            reply()
            out = []
            for cmd in commands:
                stream.write(json.dumps(cmd).encode() + b"\n")
                result = reply()
                if "error" in result:
                    raise DriverError(f"QMP {cmd['execute']}: {result['error']}")
                out.append(result)
            return out

    def screendump(self, ppm_path):
        """Save the guest screen to a PPM file.

        A GL scanout (--virgl) has no surface for QMP: the VNC socket next to
        the QMP socket gives the same frame."""
        try:
            self.run(
                {"execute": "screendump", "arguments": {"filename": str(ppm_path), "format": "ppm"}}
            )
        except DriverError as exc:
            vnc = self.sock.with_name("vnc.sock")
            if "no surface" not in str(exc) or not vnc.exists():
                raise
            vnc_screendump(vnc, ppm_path)

    def send_keys(self, *keys):
        """Press QMP keys one at a time (OCR fallback path, no AT-SPI)."""
        for key in keys:
            self.run(
                {
                    "execute": "send-key",
                    "arguments": {
                        "keys": [{"type": "qcode", "data": key}],
                        "hold-time": 50,
                    },
                }
            )
            time.sleep(0.4)

    def type_line(self, text):
        """Type one line of ASCII (QMP qcodes, shift where needed) and press Return."""
        for ch in text:
            if ch in QCODES:
                qcodes = QCODES[ch]
            elif ch.isascii() and (ch.islower() or ch.isdigit()):
                qcodes = (ch,)
            elif ch.isascii() and ch.isupper():
                qcodes = ("shift", ch.lower())
            else:
                raise DriverError(f"no QMP key for {ch!r}")
            self.run(
                {
                    "execute": "send-key",
                    "arguments": {
                        "keys": [{"type": "qcode", "data": q} for q in qcodes],
                        "hold-time": 30,
                    },
                }
            )
            time.sleep(0.08)
        self.send_keys("ret")


# QMP qcodes of the ASCII characters that are not a plain lowercase letter or digit.
QCODES = {
    " ": ("spc",),
    "/": ("slash",),
    ".": ("dot",),
    "-": ("minus",),
    "_": ("shift", "minus"),
    "=": ("equal",),
    ";": ("semicolon",),
    "|": ("shift", "backslash"),
    ">": ("shift", "dot"),
    "&": ("shift", "7"),
    "*": ("shift", "8"),
    ":": ("shift", "semicolon"),
}


def _recv_exact(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise DriverError("VNC: the server closed the connection")
        data += chunk
    return bytes(data)


def vnc_screendump(sock_path, ppm_path, timeout=30):
    """One full frame from QEMU's VNC server (RFB 3.8, no auth, raw) as PPM."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(str(sock_path))
        if not _recv_exact(s, 12).startswith(b"RFB 003."):
            raise DriverError("VNC: no RFB server")
        s.sendall(b"RFB 003.008\n")
        types = _recv_exact(s, _recv_exact(s, 1)[0])
        if 1 not in types:
            raise DriverError(f"VNC: no 'None' security type in {list(types)}")
        s.sendall(b"\x01")
        if _recv_exact(s, 4) != b"\0\0\0\0":
            raise DriverError("VNC: security handshake failed")
        s.sendall(b"\x01")  # ClientInit: shared
        init = _recv_exact(s, 24)
        width, height = int.from_bytes(init[0:2], "big"), int.from_bytes(init[2:4], "big")
        _recv_exact(s, int.from_bytes(init[20:24], "big"))  # desktop name
        # 32 bpp, depth 24, little endian, true colour, 8 bits each: B G R X.
        pixel = bytes([32, 24, 0, 1, 0, 255, 0, 255, 0, 255, 16, 8, 0, 0, 0, 0])
        s.sendall(b"\x00\0\0\0" + pixel)
        s.sendall(b"\x02\0\x00\x01" + (0).to_bytes(4, "big", signed=True))  # raw only
        s.sendall(b"\x03\x00" + b"\0\0\0\0" + width.to_bytes(2, "big") + height.to_bytes(2, "big"))
        frame = bytearray(width * height * 4)
        while True:
            kind = _recv_exact(s, 1)[0]
            if kind == 2:  # Bell
                continue
            if kind == 3:  # ServerCutText
                head = _recv_exact(s, 7)
                _recv_exact(s, int.from_bytes(head[3:7], "big"))
                continue
            if kind != 0:
                raise DriverError(f"VNC: unexpected message type {kind}")
            count = int.from_bytes(_recv_exact(s, 3)[1:3], "big")
            for _ in range(count):
                rect = _recv_exact(s, 12)
                x, y, w, h = (int.from_bytes(rect[i : i + 2], "big") for i in (0, 2, 4, 6))
                if int.from_bytes(rect[8:12], "big", signed=True) != 0:
                    raise DriverError("VNC: the server sent an encoding other than raw")
                data = _recv_exact(s, w * h * 4)
                for row in range(h):
                    if y + row >= height:
                        break
                    start = ((y + row) * width + x) * 4
                    end = start + min(w, width - x) * 4
                    frame[start:end] = data[row * w * 4 : row * w * 4 + (end - start)]
            break
    rgb = bytearray(width * height * 3)
    rgb[0::3] = frame[2::4]
    rgb[1::3] = frame[1::4]
    rgb[2::3] = frame[0::4]
    Path(ppm_path).write_bytes(b"P6\n%d %d\n255\n" % (width, height) + bytes(rgb))


def to_png(ppm, png):
    """Convert a QMP screendump PPM to PNG; keep the PPM when no tool fits."""
    ppm = Path(ppm)
    png = Path(png)
    for tool, args in (("ffmpeg", ["-y", "-loglevel", "error", "-i"]), ("convert", [])):
        if shutil.which(tool):
            try:
                subprocess.run([tool, *args, str(ppm), str(png)], check=True, timeout=120)
                ppm.unlink(missing_ok=True)
                return png
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                continue
    return ppm


# QEMU qcodes for the characters of a shell line typed on the guest console.
QCODE = {" ": "spc", "-": "minus", ".": "dot", "/": "slash", "=": "equal", ",": "comma"}


def qcodes(line):
    """The QEMU qcodes that type `line` on a US keyboard, then Enter."""
    out = []
    for ch in line:
        if ch.isascii() and (ch.islower() or ch.isdigit()):
            out.append(ch)
        elif ch in QCODE:
            out.append(QCODE[ch])
        else:
            raise ValueError(f"no qcode for {ch!r}")
    return [*out, "ret"]


# A live boot that stops in the initrd shows only "Failed to start
# initrd-switch-root.service" (gurnard:pantheon CD lane, run 45826234346): the
# medium's kernel command line sends nothing to the serial port. In dracut's
# emergency shell the harness types these lines and takes a picture of each.
EMERGENCY_LINES = (
    "systemctl status initrd-switch-root.service -l --no-pager",
    "journalctl -b -p 4 -n 45 --no-pager -o short-monotonic",
    # Where the root is: the command line, the loop devices of the disc, the
    # block devices, then what /sysroot holds and which unit should have filled it.
    "cat /proc/cmdline",
    "losetup -a",
    "lsblk -o name,fstype,size,mountpoint",
    "ls /sysroot /sysroot/usr",
    "journalctl -b --no-pager -o short-monotonic -u bootc-root-setup.service -u sysroot.mount -u medium-sr0 -n 30",
)


def at_emergency_shell(qmp, shots, boot):
    """True when the screen shows dracut's emergency mode.

    A guest that runs a live desktop but never answers SSH (brussels:xfce run
    45910882687) must not get these keys: they went into the installer's
    language search box.
    """
    ppm = shots / f"{boot}-0-boot-probe.ppm"
    try:
        qmp.screendump(ppm)
        text = ocr_fallback.ocr_text(to_png(ppm, ppm.with_suffix(".png")))
    except DriverError as exc:
        print(f"emergency probe: {exc}", file=sys.stderr)
        return False
    return "emergency" in text or "maintenance" in text


def emergency_status(qmp, shots, boot):
    """Enter dracut's emergency shell and photograph the cause of the failed boot.

    Returns False, having typed nothing, when the screen is not the emergency shell.
    """
    if not at_emergency_shell(qmp, shots, boot):
        return False
    qmp.send_keys("ret")
    time.sleep(3)
    for n, line in enumerate(EMERGENCY_LINES, 1):
        for key in qcodes("clear") + qcodes(line):
            qmp.send_keys(key)
        time.sleep(4)
        ppm = shots / f"{boot}-0-boot-failed-{n}.ppm"
        qmp.screendump(ppm)
        to_png(ppm, ppm.with_suffix(".png"))
    return True


def ssh_access_args(public_key):
    """QEMU arguments that give the harness SSH access, with no change to the medium.

    The medium ships no key and its images ship sshd disabled, so the first
    real run could not reach the guest ("guest sshd never answered"). systemd
    reads system credentials from SMBIOS type 11 strings in a VM:
    `tmpfiles.extra` writes one key file that sshd reads for every account,
    and `systemd.unit-dropin.multi-user.target` (systemd 256) starts sshd.
    On systemd 255 (Ubuntu 24.04) that credential does nothing; there the
    medium's medium-e2e-ssh.service starts sshd when the
    `ssh.ephemeral-authorized_keys-all` credential is present.
    The same VM boots the installed system later, so stages 5 to 7 get the
    same access. The medium bytes stay the bytes under test.
    """
    key = public_key.strip()
    if not key or "\n" in key:
        raise DriverError("the SSH public key must be one line")
    tmpfiles = (
        f"f+ /etc/ssh/installer-e2e_authorized_keys 0644 root root - {key}\n"
        "f+ /etc/ssh/sshd_config.d/00-installer-e2e.conf 0600 root root - "
        "AuthorizedKeysFile /etc/ssh/installer-e2e_authorized_keys .ssh/authorized_keys\n"
        # sshd keeps the FIRST value of an option. Brussels (freedesktop-sdk)
        # sets `AuthorizedKeysFile .ssh/authorized_keys` in sshd_config BEFORE
        # its `Include /etc/ssh/sshd_config.d/*.conf`, so the line above never
        # wins there ("Permission denied (publickey...)", brussels:xfce run
        # 45918942685). The main file sets no AuthorizedKeysCommand, and these
        # drop-ins sort before 20-systemd-userdb.conf, so this one is taken.
        "f+ /etc/ssh/sshd_config.d/02-installer-e2e.conf 0600 root root - "
        "AuthorizedKeysCommand /usr/bin/cat /etc/ssh/installer-e2e_authorized_keys\n"
        "f+ /etc/ssh/sshd_config.d/03-installer-e2e.conf 0600 root root - AuthorizedKeysCommandUser root\n"
    )
    # Debian and Ubuntu name the unit ssh.service; a missing unit is no error.
    dropin = "[Unit]\nWants=sshd.service ssh.service\n"
    out = []
    for name, text in (
        # The credential that Utah's harness uses: systemd 256 lets sshd
        # accept this key for every account, with no file in /etc. The two
        # below cover an image whose sshd has no userdb drop-in.
        ("ssh.ephemeral-authorized_keys-all", key + "\n"),
        ("tmpfiles.extra", tmpfiles),
        ("systemd.unit-dropin.multi-user.target", dropin),
    ):
        value = base64.b64encode(text.encode()).decode()
        out += ["-smbios", f"type=11,value=io.systemd.credential.binary:{name}={value}"]
    return out


def ssh_base(ssh_port, key_path, user="liveuser"):
    """Base SSH argv to the guest (BatchMode: never prompt in CI)."""
    return [
        "ssh",
        "-p",
        str(ssh_port),
        "-i",
        str(key_path),
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        f"{user}@127.0.0.1",
    ]


def ssh_run(ssh_port, key_path, *remote, user="liveuser", timeout=120):
    """Run one command in the guest; return (rc, stdout)."""
    proc = subprocess.run(
        [*ssh_base(ssh_port, key_path, user), "--", *remote],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return proc.returncode, proc.stdout


def wait_ssh(ssh_port, key_path, timeout=SSH_TIMEOUT, vm=None, progress=None):
    """Wait until the guest sshd answers. Raises DriverError on timeout.

    A QEMU that has exited cannot answer: say so at once, not after the
    whole timeout."""
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        if vm is not None and vm.poll() is not None:
            raise DriverError(f"QEMU exited with status {vm.returncode} before sshd answered")
        if progress is not None:
            progress()
        try:
            proc = subprocess.run(
                [*ssh_base(ssh_port, key_path), "--", "true"],
                capture_output=True, text=True, timeout=30, check=False,
            )
        except subprocess.TimeoutExpired:
            last = "ssh did not end in 30 s"
            continue
        if proc.returncode == 0:
            return
        last = proc.stderr.strip()[-300:]
        time.sleep(5)
    # The live account can be missing while root answers: say why.
    try:
        rc, state = ssh_run(
            ssh_port,
            key_path,
            "id liveuser; systemctl status --no-pager medium-live-setup display-manager | tail -60; "
            "systemctl --failed --no-legend; journalctl -b -p warning --no-pager | tail -60",
            user="root",
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        rc, state = 1, "no answer for root either"
    raise DriverError(f"guest sshd never answered; ssh: {last}; root: {rc}: {state[-6000:]}")


def start_swtpm(work, name):
    """Start a software TPM2 with state under work; return its socket path."""
    if not shutil.which("swtpm"):
        raise DriverError("--tpm needs swtpm on PATH")
    state = Path(work) / "swtpm-state"
    state.mkdir(parents=True, exist_ok=True)
    sock = Path(work) / f"{name}-swtpm.sock"
    sock.unlink(missing_ok=True)
    log = Path(work) / f"{name}-swtpm.log"
    with log.open("w") as stream:
        proc = subprocess.Popen(
            [
                "swtpm",
                "socket",
                "--tpm2",
                "--tpmstate",
                f"dir={state}",
                "--ctrl",
                f"type=unixio,path={sock}",
            ],
            stdout=stream,
            stderr=subprocess.STDOUT,
        )
    for _ in range(50):
        if sock.exists() or proc.poll() is not None:
            break
        time.sleep(0.2)
    if not sock.exists():
        raise DriverError(f"swtpm never created its socket (exit {proc.poll()})")
    return proc, str(sock)


def bootc_digest(status_json):
    """Booted image digest from `bootc status --format=json` output."""
    try:
        status = json.loads(status_json)
    except json.JSONDecodeError as exc:
        raise DriverError(f"bootc status is not JSON: {exc}") from exc
    # BootcHost has status.booted; a list of deployments is the older shape.
    booted = (status.get("status") or {}).get("booted")
    if booted is not None and booted.get("image"):
        booted = booted["image"]
    if booted is None:
        deployments = status.get("status", {}).get("deployments", [])
        booted = next((d for d in deployments if d.get("booted")), None)
        if booted is None:
            booted = deployments[0] if deployments else None
    if booted is None:
        raise DriverError("bootc status lists no deployments")
    digest = booted.get("digest") or booted.get("imageDigest") or ""
    if not digest:
        raise DriverError("booted deployment carries no digest")
    return digest


def run_cell(args):
    """Boot both media, run the 7 stages, write evidence. Returns exit code."""
    work = Path(args.work)
    shots = work / "screenshots"
    evidence = work / "evidence"
    if args.dry_run:
        print(f"e2e {args.cell}: medium {args.medium} work {args.work}")
        print(f"build: installer-medium/build-medium.sh {args.cell} {args.medium}")
        for boot in ["cdrom", "usb"] if args.boot == "both" else [args.boot]:
            net = "offline=1" if args.offline else "offline=0"
            frontend = "ocr-fallback" if args.no_atspi else "atspi"
            display = "virgl" if args.virgl else "vga"
            print(
                f"boot {boot}: qemu OVMF swtpm={'on' if args.tpm else 'off'} {net} input={frontend} display={display}"
            )
            for stage in plan_for_cell({"filesystem": args.filesystem}):
                print(f"  stage {stage['id']}: {stage['title']}")
                for check in stage["checks"]:
                    print(f"    check: {check}")
            print(f"  screenshots: {shots}/{boot}-*.png")
        print(
            f"publish: chunk-publish.py {args.cell} {args.medium} "
            f"(by digest, after all stages pass)"
        )
        print("sign: cosign sign --keyless (workflow identity), attach receipt")
        print(
            f"lifecycle: baseline={args.baseline or 'unset'} candidate={args.candidate or 'unset'}"
        )
        return 0
        # Real run below. Needs KVM/QEMU/OVMF/swtpm: CI only, never local.
    work.mkdir(parents=True, exist_ok=True)
    shots.mkdir(parents=True, exist_ok=True)
    evidence.mkdir(parents=True, exist_ok=True)
    results = {"cell": args.cell, "boot": {}, "offline": bool(args.offline)}
    boots = ["cdrom", "usb"] if args.boot == "both" else [args.boot]
    for boot in boots:
        # Every lane runs: the CD-ROM and USB paths fail for different
        # reasons, and one run must show both.
        results["boot"][boot] = run_boot(args, boot, shots, evidence)
    (evidence / "results.json").write_text(json.dumps(results, indent=2))
    return 0 if all(v == 0 for v in results["boot"].values()) else 1


def run_boot(args, boot, shots, evidence):
    """One boot lane (cdrom or usb) through the 7 stages. Returns exit code."""
    work = Path(args.work)
    disk = work / f"target-{boot}.qcow2"
    if not disk.exists():
        # Larger than the medium: the installer copies the medium to the
        # target, and gnome-setup shows "No Usable Disks Detected" for a
        # 20 GB target under a 24 GB medium (run 45606046787). The file is
        # sparse.
        subprocess.run(
            ["qemu-img", "create", "-f", "qcow2", str(disk), args.target_size], check=True
        )
    swtpm_proc, tpm_sock = (None, None)
    vm = None
    try:
        if args.tpm:
            swtpm_proc, tpm_sock = start_swtpm(work, boot)
        vars_copy = work / f"ovmf-vars-{boot}.fd"
        shutil.copyfile(args.ovmf_vars, vars_copy)

        def start(source, log):
            cmd = build_qemu_cmd(
                args.medium,
                disk,
                work,
                args.ssh_port,
                source,
                args.ovmf_code,
                # Only the install must do without a network: `bootc switch`
                # fetches the candidate.
                offline=args.offline and source != "disk",
                tpm_sock=tpm_sock,
                virgl=args.virgl,
                kvm=args.kvm,
                extra=ssh_access_args(Path(f"{args.ssh_key}.pub").read_text()),
                ovmf_vars=vars_copy,
                serial=log,
            )
            return subprocess.Popen(cmd)

        def restart_from_disk():
            """The same machine with the medium taken out: firmware variables, TPM and disk stay."""
            nonlocal vm, swtpm_proc, tpm_sock
            stop(vm, graceful=180)
            if args.tpm:
                stop(swtpm_proc)
                swtpm_proc, tpm_sock = start_swtpm(work, boot)
            vm = start("disk", f"serial-{boot}-installed.log")

        vm = start(boot, f"serial-{boot}.log")
        time.sleep(10)
        # One screenshot a minute while the guest boots: the firmware, the
        # boot menu and a kernel that stops are visible on the screen only.
        seen = {"at": 0.0, "n": 0}

        def boot_progress():
            if time.monotonic() - seen["at"] < 60:
                return
            seen["at"] = time.monotonic()
            seen["n"] += 1
            try:
                ppm = shots / f"{boot}-0-boot-{seen['n']:02d}.ppm"
                Qmp(work / "qmp.sock").screendump(ppm)
                to_png(ppm, ppm.with_suffix(".png"))
            except (DriverError, OSError) as exc:
                print(f"boot screenshot: {exc}", file=sys.stderr)

        wait_ssh(args.ssh_port, args.ssh_key, vm=vm, progress=boot_progress)
        return run_stages(args, boot, shots, evidence, restart_from_disk)
    except (DriverError, subprocess.CalledProcessError, OSError) as exc:
        print(f"boot {boot} failed: {exc}", file=sys.stderr)
        # The screen is the only evidence of a boot that SSH never reached.
        try:
            ppm = shots / f"{boot}-0-boot-failed.ppm"
            Qmp(work / "qmp.sock").screendump(ppm)
            to_png(ppm, ppm.with_suffix(".png"))
            if vm is not None and vm.poll() is None:
                emergency_status(Qmp(work / "qmp.sock"), shots, boot)
        except (DriverError, OSError) as shot_exc:
            print(f"screenshot of the failed boot: {shot_exc}", file=sys.stderr)
        error = failed_boot_error(exc, work / f"serial-{boot}.log")
        return finish(evidence, boot, [{"id": "live-boot", "status": "fail", "error": error}], 1)
    finally:
        stop(vm)
        stop(swtpm_proc)


SERIAL_TAIL_LINES = 80
SERIAL_TAIL_CHARS = 12000
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def failed_boot_error(exc, serial_log):
    """The error of a boot that never reached stage 1, with what the guest said last.

    A guest that SSH never reached still writes to the serial port when the
    live entry has a console (the `live_kargs` input: console=ttyS0 and the
    journal forwarded to it). The last lines of that log are the first look
    at the cause, so the next owner does not need a diagnosis run
    (albacore:kde run 45931354890). No log, or an empty one (an entry with
    no console), changes nothing."""
    try:
        text = Path(serial_log).read_text(errors="replace")
    except OSError:
        return str(exc)
    lines = ANSI_RE.sub("", text).replace("\r", "").splitlines()
    lines = [line for line in lines if line.strip()][-SERIAL_TAIL_LINES:]
    if not lines:
        return str(exc)
    tail = "\n".join(lines)[-SERIAL_TAIL_CHARS:]
    return f"{exc}\n--- last {len(lines)} lines of {Path(serial_log).name} ---\n{tail}"


def stop(proc, graceful=0):
    """End a child process; with graceful, wait that long for it to end by itself."""
    if proc is None:
        return
    try:
        if graceful:
            proc.wait(timeout=graceful)
            return
    except subprocess.TimeoutExpired:
        pass
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=30)


def run_stages(args, boot, shots, evidence, restart_from_disk):
    """Stages 1-7 against the running VM. Returns exit code."""

    qmp = Qmp(Path(args.work) / "qmp.sock")
    stage_results = []
    # The screen reader choice of the first page (tunaOS#5012): its own field,
    # never a stage verdict.
    a11y = {"status": "not run"}

    def shot(name):
        ppm = shots / f"{boot}-{name}.ppm"
        try:
            qmp.screendump(ppm)
        except DriverError as exc:
            print(f"screenshot {name} failed: {exc}", file=sys.stderr)
            return None
        return to_png(ppm, ppm.with_suffix(".png"))

    typed_at = [0.0]

    def unlock():
        """A no-TPM install asks for the disk passphrase at every boot."""
        if args.tpm or time.monotonic() - typed_at[0] < 45:
            return
        if type_disk_passphrase(qmp, shots / f"{boot}-unlock-probe.ppm"):
            typed_at[0] = time.monotonic()
            shot(f"unlock-typed-{int(typed_at[0]) % 100000}")

    # sshd answers before the session starts: wait for the stamp.
    deadline = time.monotonic() + STAMP_TIMEOUT
    while True:
        rc, stamp = ssh_run(
            args.ssh_port, args.ssh_key, STAMP_LOOKUP, timeout=60
        )
        if rc == 0 or time.monotonic() > deadline:
            break
        time.sleep(10)
    app = "installer"
    if rc == 0:
        for line in stamp.splitlines():
            if line.startswith("app_id="):
                app = line.split("=", 1)[1].strip() or app
    # Stage 1: live boot. SSH answered, so the medium booted; the stage
    # passes only when the frontend also wrote its readiness stamp.
    live = shot("1-live-boot")
    if rc != 0:
        _, session = ssh_run(
            args.ssh_port,
            args.ssh_key,
            "stat -c '%a %U:%G %n' / /etc /etc/ssh; loginctl list-sessions --no-legend; systemctl --failed --no-legend; "
            "systemctl is-active display-manager medium-live-setup; "
            # Why the frontend did not start: its autostart entry, the Flatpak
            # store, and what the session logged about it.
            "cat /usr/lib/medium-live/desktop; ls /etc/xdg/autostart | grep -i installer; "
            "flatpak list --system --columns=application 2>&1 | head -20; "
            "pgrep -af 'medium-live-installer|bwrap|tuna-installer'; "
            "find $XDG_RUNTIME_DIR -name 'tuna-installer-ready' 2>/dev/null; "
            # A session that runs no XDG autostart starts the launcher as a
            # user unit (Tuna Desktop, tunaOS#5028): did it run, and did the
            # user manager know the display.
            "systemctl --user --no-pager status 'medium-live-installer*' 2>&1 | head -20; "
            "systemctl --user show-environment 2>&1 | grep -E '^(WAYLAND_DISPLAY|DISPLAY|XDG_SESSION_TYPE|XDG_CURRENT_DESKTOP)='; "
            "journalctl --user -b --no-pager 2>&1 | grep -iE 'installer|flatpak|medium-live' | tail -40; "
            # And what the system itself logged: a session that never started
            # leaves its reason here, not in the user journal.
            "sudo -n journalctl -b -p warning --no-pager 2>&1 | tail -40",
            timeout=120,
        )
        stage_results.append(
            {
                "id": "live-boot",
                "status": "fail",
                "error": "no readiness stamp below $XDG_RUNTIME_DIR",
                "guest": session,
            }
        )
        return finish(evidence, boot, stage_results, a11y=a11y, code=1)
    # A stamp with nothing on the screen is no live boot: niri answers frame
    # callbacks with no renderer (runs 45637943733 and 45651256265, black).
    # COSMIC stamps before its window maps, so the check waits.
    for _ in range(6):
        if live is not None and not blank(live):
            break
        time.sleep(10)
        live = shot("1-live-boot")
    else:
        stage_results.append(
            {
                "id": "live-boot",
                "status": "fail",
                "error": "readiness stamp, but the screen shows no desktop (one color or only console text)",
                "app": app,
                "guest": daemon_state(args),
            }
        )
        return finish(evidence, boot, stage_results, a11y=a11y, code=1)
    live_record = {"id": "live-boot", "status": "pass", "app": app}
    # What the live session knows about language and keyboard (tunaOS#5064):
    # recorded before and after the pages, never a verdict.
    live_record["locale-at-start"] = locale_state(args, "liveuser")
    stage_results.append(live_record)
    # Stages 2-4: installer pages, install, unlock. AT-SPI matchers by
    # default; QEMU keys plus OCR where the toolkit has no AT-SPI.
    if args.no_atspi:
        code = middle_stages_ocr(args, shot, qmp, stage_results, app, a11y)
    else:
        code = middle_stages_atspi(args, shot, qmp, stage_results, app, a11y)
    live_record["locale-at-end"] = locale_state(args, "liveuser")
    if code != 0:
        return finish(evidence, boot, stage_results, a11y=a11y, code=code)
    # Leave the live session and take the medium out, as a user does. With the
    # medium still attached the firmware can start it again.
    try:
        ssh_run(args.ssh_port, args.ssh_key, "sudo systemctl poweroff", timeout=30)
    except (subprocess.TimeoutExpired, OSError):
        pass
    restart_from_disk()
    installed, proof = wait_installed_system(args, shot, unlock=unlock)
    if installed:
        proof = f"{proof}\n--- locale handoff on the installed system\n{locale_state(args, 'root')}"
    shot("5-first-boot-setup")
    if not installed:
        capture_emergency_shell(qmp, shot)
        stage_results.append(
            {
                "id": "first-boot-setup",
                "status": "fail",
                "error": "the VM did not boot the installed system",
                "guest": proof,
            }
        )
        return finish(evidence, boot, stage_results, a11y=a11y, code=1)
    # A native frontend made the account in the install: log in as it. On a
    # GNOME or Pantheon cell the first-boot app makes the account.
    if app.startswith(NATIVE_APP_PREFIX):
        time.sleep(40)
        png = shot("5-greeter")
        try:
            pick_greeter_user(shot, qmp, png)
            qmp.send_keys(*E2E_PASSWORD, "ret")
        except DriverError as exc:
            print(f"login: {exc}", file=sys.stderr)
        time.sleep(60)
        png, dark = settled_shot(shot, "5-login")
        _, sessions = ssh_run(
            args.ssh_port, args.ssh_key, "loginctl list-sessions --no-legend; id tester", user="root"
        )
        seated = any("seat0" in line and E2E_USER in line for line in sessions.splitlines())
        result = {
            "id": "first-boot-setup",
            "status": "pass" if seated and not dark else ("fail" if dark else "unverified"),
            "note": "login with the account that the install made",
            "guest": f"{proof}\n{sessions}",
        }
        if dark:
            result["error"] = f"{Path(png).name if png else '5-login'}: the screen is blank after the login"
            result["blank-diagnosis"] = desktop_diagnosis(args)
        stage_results.append(result)
    else:
        done, log, login = drive_initial_setup(args, shot, lambda *k: qmp.send_keys(*k))
        if done and login:
            # elementary: the greeter shows the new account after "Finish Setup".
            time.sleep(20)
            shot("5-greeter")
            try:
                qmp.send_keys(*E2E_PASSWORD, "ret")
            except DriverError as exc:
                log.append(f"login: {exc}")
        time.sleep(60)
        _, dark = settled_shot(shot, "5-session")
        _, sessions = ssh_run(
            args.ssh_port, args.ssh_key, "loginctl list-sessions --no-legend; id tester", user="root"
        )
        seated = any("seat0" in line and E2E_USER in line for line in sessions.splitlines())
        result = {
            "id": "first-boot-setup",
            "status": "fail" if dark else ("pass" if done and seated else "unverified"),
            "steps": log,
            "note": EL10_REBOOT_TODO if args.filesystem == "xfs" else "",
            "guest": f"{proof}\n{sessions}",
        }
        if dark:
            result["error"] = "5-session: the screen is blank"
            result["blank-diagnosis"] = desktop_diagnosis(args)
        stage_results.append(result)
    # Stage 6: desktop plus bootc status.
    def root(command, timeout=120):
        try:
            return ssh_run(args.ssh_port, args.ssh_key, command, user="root", timeout=timeout)
        except subprocess.TimeoutExpired:
            return 1, "no answer"

    rc, out = root("bootc status --format=json")
    if rc != 0:
        stage_results.append(
            {"id": "desktop-status", "status": "fail", "error": "bootc status failed", "guest": out}
        )
        return finish(evidence, boot, stage_results, a11y=a11y, code=1)
    try:
        digest = bootc_digest(out)
    except DriverError as exc:
        stage_results.append({"id": "desktop-status", "status": "fail", "error": str(exc)})
        return finish(evidence, boot, stage_results, a11y=a11y, code=1)
    _, system = root(
        "getenforce; systemctl is-active graphical.target display-manager; "
        "loginctl list-sessions --no-legend; systemctl --failed --no-legend; "
        "lsblk -o NAME,SIZE,TYPE,FSTYPE,PARTLABEL,MOUNTPOINTS; cat /etc/crypttab"
    )
    png, dark = settled_shot(shot, "6-desktop-status")
    key_opens = recovery_key_opens_the_disk(args)
    unlock_verdict(stage_results, key_opens, getattr(args, "recovery_key_source", None))
    # The desktop of a user is up when a session of class `user` is on a seat.
    # A greeter alone is the first-boot setup or a login that nobody drove.
    desktop = any(
        "seat0" in line and "greeter" not in line and " gdm" not in line
        for line in system.splitlines()
    )
    result = {
        "id": "desktop-status",
        # A session record is no desktop when the picture is one colour
        # (albacore:kde run 46083819054: tester on seat0, screen black).
        "status": "fail" if dark else ("pass" if desktop else "unverified"),
        "recovery-key-opens-the-disk": key_opens,
        "bootc-status": "pass",
        "user-session": desktop,
        "booted": digest,
        # The medium installs the live layer of the cell image, so the
        # booted digest is not the digest of the published image.
        "published": args.baseline,
        "guest": system,
        "installed-system": proof,
    }
    if dark:
        result["error"] = "6-desktop-status: the screen is blank"
        result["blank-diagnosis"] = desktop_diagnosis(args)
    stage_results.append(result)
    if a11y.get("pressed"):
        _, seen = root(A11Y_READ, timeout=180)
        a11y.update(a11y_result(seen))
    # Stage 7: bootc switch plus rollback (Utah phase rules).
    if not args.candidate:
        stage_results.append(
            {"id": "switch-rollback", "status": "todo", "note": "no --candidate digest given"}
        )
        return finish(evidence, boot, stage_results, a11y=a11y, code=0)
    record = {"id": "switch-rollback", "status": "fail", "baseline": digest}
    stage_results.append(record)
    try:
        image = json.loads(out)["spec"]["image"]["image"]
        repo = image.split("@")[0]
        if ":" in repo.rsplit("/", 1)[-1]:
            repo = repo.rsplit(":", 1)[0]
        target = f"{repo}@{args.candidate}"
        record["candidate"] = target

        def reboot_to(want):
            _, before = root("cat /proc/sys/kernel/random/boot_id")
            root("systemctl reboot", timeout=30)
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                time.sleep(10)
                unlock()
                code, now = root("cat /proc/sys/kernel/random/boot_id", timeout=30)
                if code == 0 and now.strip() and now != before:
                    break
            else:
                raise DriverError("the VM did not come back after the reboot")
            now_status = root("bootc status --format=json")[1]
            got = bootc_digest(now_status)
            # The candidate is the digest of an image index; imageDigest is
            # the manifest of this architecture. The booted reference names
            # the index (run 45669552583).
            booted = (json.loads(now_status).get("status") or {}).get("booted") or {}
            ref = ((booted.get("image") or {}).get("image") or {}).get("image", "")
            record.setdefault("booted", []).append({"digest": got, "image": ref})
            if got != want and not ref.endswith("@" + want):
                raise DriverError(f"booted {got} ({ref}), expected {want}")

        rc, log = root(f"bootc switch {target} 2>&1 | tail -20; exit ${{PIPESTATUS[0]}}", timeout=2400)
        if rc != 0:
            raise DriverError(f"bootc switch failed: {log[-1500:]}")
        reboot_to(args.candidate)
        if settled_shot(shot, "7-switch")[1]:
            raise DriverError("7-switch: the screen of the candidate is blank")
        rc, log = root("bootc rollback 2>&1", timeout=300)
        if rc != 0:
            raise DriverError(f"bootc rollback failed: {log[-1500:]}")
        reboot_to(digest)
        if settled_shot(shot, "7-switch-rollback")[1]:
            raise DriverError("7-switch-rollback: the screen of the baseline is blank")
        record["status"] = "pass"
    except (DriverError, KeyError, ValueError) as exc:
        record["error"] = str(exc)
        shot("7-failed")
        return finish(evidence, boot, stage_results, a11y=a11y, code=1)
    return finish(evidence, boot, stage_results, a11y=a11y, code=0)


# Language and keyboard as the guest holds them: the files the install copies
# (systemd-firstboot --copy-locale/--copy-keymap), what localed reports, and the
# environment of the app that shows the pages (gnome-setup on the live medium,
# the first-boot app on the installed system). tunaOS#5064.
LOCALE_STATE = (
    "echo '--- cmdline'; tr ' ' '\\n' </proc/cmdline | grep -E '^locale\\.|^vconsole\\.'; "
    "for f in /etc/locale.conf /etc/vconsole.conf "
    "/etc/gnome-initial-setup/vendor.conf /usr/share/gnome-initial-setup/vendor.conf; do "
    'echo "--- $f"; cat "$f" 2>&1; done; '
    "echo '--- localectl'; localectl status 2>&1; "
    "echo '--- app environment'; "
    "for p in $(pgrep -f '^(/[^ ]*/)?(gnome-setup|gnome-initial-setup|io\\.elementary\\.initial-setup)( |$)'); do "
    "ps -o pid=,user=,args= -p $p | cut -c1-120; "
    "tr '\\0' '\\n' </proc/$p/environ 2>/dev/null | grep -E '^(LANG|LANGUAGE|LC_[A-Z]+)='; done; "
    "echo '--- session manager'; systemctl --user show-environment 2>&1 | grep -E '^(LANG|LC_[A-Z]+)='; true"
)


def locale_state(args, user):
    """The guest's language and keyboard state as text; never raises."""
    try:
        _, out = ssh_run(args.ssh_port, args.ssh_key, LOCALE_STATE, user=user, timeout=60)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return f"no answer: {exc}"
    return out


# The stamp of a sandboxed frontend is not in $XDG_RUNTIME_DIR of the host:
# flatpak binds $XDG_RUNTIME_DIR of the sandbox to .flatpak/APP/xdg-run, and an
# older one to app/APP (installer-smoke.yml and e2e-installer-gui-checks.sh
# read the same three places). bonito:kde run 45601458778 failed stage 1 for it.
STAMP_LOOKUP = (
    "sh -c 'cat $XDG_RUNTIME_DIR/tuna-installer-ready "
    "$XDG_RUNTIME_DIR/.flatpak/*/xdg-run/tuna-installer-ready "
    "$XDG_RUNTIME_DIR/app/*/tuna-installer-ready 2>/dev/null | grep .'"
)
# Qt and libcosmic build the accessibility tree only when the session says an
# assistive client runs.
ENABLE_A11Y = (
    "DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus busctl --user set-property "
    "org.a11y.Bus /org/a11y/bus org.a11y.Status IsEnabled b true"
)

INSTALLED_PROBE = "cat /proc/cmdline; findmnt -no SOURCE /sysroot || findmnt -no SOURCE /"

# Stage 6 tries the recovery key on the installed LUKS volume. cryptsetup
# open tries LUKS2 tokens before the key file, and the systemd-tpm2 token
# opens the volume on the booted PCRs, so a token check would read "the key
# opens the disk" whatever the key is. --disable-external-tokens stops the
# plugin tokens (systemd-tpm2) but not cryptsetup's built-in token types
# (luks2-keyring), so --token-type names a type no volume has: only the
# keyslots are tried, as in fishermand's finalize check (fisherman#544).
RECOVERY_KEY_CHECK = (
    "cryptsetup open --test-passphrase --disable-external-tokens "
    "--token-type=fisherman-keyslots-only --key-file=- "
    "$(lsblk -nrpo NAME,FSTYPE | awk '$2==\"crypto_LUKS\"{print $1; exit}')"
)


def recovery_key_opens_the_disk(args):
    """True, False, or None when no key was read: does a key read from the screen open the disk?

    OCR can leave a few letters in doubt (t, f and l at 11 pixels), so it
    hands over every reading and the disk says which one is the key. Never
    logged: a key goes over stdin, and only the exit status comes back."""
    candidates = getattr(args, "recovery_key_candidates", None) or (
        [args.recovery_key] if getattr(args, "recovery_key", None) else []
    )
    if not candidates:
        return None
    for candidate in candidates:
        proc = subprocess.run(
            [*ssh_base(args.ssh_port, args.ssh_key, "root"), RECOVERY_KEY_CHECK],
            input=candidate, capture_output=True, text=True, timeout=120, check=False,
        )
        if proc.returncode == 0:
            return True
    return False


def is_installed_system(probe_output):
    """True when the probe output is from the installed disk, not the live medium.

    The live boot has `tunaos.live` on the kernel command line. The target is
    the only virtio disk (/dev/vd*) or its LUKS mapping; the medium is a
    CD-ROM or a USB disk.
    """
    lines = probe_output.strip().splitlines()
    if len(lines) < 2 or "tunaos.live" in lines[0].split():
        return False
    return lines[-1].startswith(("/dev/vd", "/dev/mapper/", "/dev/dm-"))


# A disk that the TPM does not unlock asks for its passphrase on every boot
# (bonito:xfce run 45836677572 stopped at "Please enter passphrase for disk
# root"). The harness reads the boot screen and types the passphrase that the
# install page took.
DISK_PROMPT_WORDS = ("passphrase", "unlock disk")


def type_disk_passphrase(qmp, ppm):
    """Type the disk passphrase when the screen asks for it; True when typed."""
    try:
        qmp.screendump(ppm)
        text = ocr_fallback.ocr_text(to_png(ppm, ppm.with_suffix(".png")))
    except DriverError as exc:
        print(f"disk prompt: {exc}", file=sys.stderr)
        return False
    if not any(word in text for word in DISK_PROMPT_WORDS):
        return False
    qmp.send_keys(*E2E_PASSWORD, "ret")
    return True


# What an installed boot that stops in the dracut emergency shell must say. The
# installed kernel command line has no console, so the shell's output goes to
# the serial port (serial-<boot>-installed.log) by redirecting the shell itself.
EMERGENCY_COMMANDS = (
    "exec >/dev/ttyS0 2>&1",
    "echo emergency-capture-begin",
    "cat /proc/cmdline",
    "tail -n 120 /run/initramfs/rdsosreport.txt",
    "ls -l /dev/disk/by-uuid /dev/mapper",
    "blkid",
    "ls /usr/lib/x86_64-linux-gnu/cryptsetup /usr/lib/cryptsetup",
    "ls /dev/tpm0 /dev/tpmrm0",
    "journalctl -b --no-pager -p warning | tail -n 80",
    "echo emergency-capture-end",
)


def capture_emergency_shell(qmp, shot):
    """Open the dracut emergency shell and print the failing unit's story to serial.

    Blind keystrokes: harmless on any other screen. Never raises."""
    try:
        qmp.send_keys("ret")
        time.sleep(4)
        for line in EMERGENCY_COMMANDS:
            qmp.type_line(line)
            time.sleep(2)
        time.sleep(10)
    except (DriverError, OSError) as exc:
        print(f"emergency capture: {exc}", file=sys.stderr)
    shot("5-emergency-shell")


def wait_installed_system(args, shot=lambda _name: None, timeout=900, unlock=lambda: None):
    """Wait for SSH on the installed system. Returns (ok, last probe output)."""
    deadline = time.monotonic() + timeout
    out, count, next_shot = "", 0, time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            rc, out = ssh_run(args.ssh_port, args.ssh_key, INSTALLED_PROBE, user="root", timeout=30)
        except subprocess.TimeoutExpired:
            rc = 1
        if rc == 0 and is_installed_system(out):
            return True, out.strip()
        unlock()
        if time.monotonic() > next_shot:
            count += 1
            shot(f"5-boot-{count:02d}")
            next_shot = time.monotonic() + 60
        time.sleep(10)
    return False, out.strip()


def log_snapshot(driver):
    """Actionable AT-SPI lines to the CI log; timeouts save the full JSON."""
    for line in summarize(driver.last_nodes):
        print(f"atspi: {line}", file=sys.stderr)


APP_FALLBACKS = ("setup", "installer")
# "Install Now" is the choice on the try-or-install page of gnome-setup: the
# walk of run 45599811536 passed the language and keyboard pages and then
# found no button it knew there ("Try Albacore", "Install Now", "Back").
WALK_NAMES = (
    "Next",
    "Continue",
    "Install Now",
    "Install",
    "Install to Disk",
    "Accept",
    "Agree",
    "Start",
)


def resolve_app(dump, app, attempts=30, pause=5.0):
    """The app substring that has an AT-SPI tree: the stamp's id, then fallbacks."""
    candidates = [app, app.rsplit(".", 1)[-1], *APP_FALLBACKS]
    for _ in range(attempts):
        for candidate in candidates:
            if dump(candidate):
                return candidate
        time.sleep(pause)
    raise_from = ", ".join(repr(c) for c in candidates)
    print(f"atspi: no application tree for any of {raise_from}", file=sys.stderr)
    return app


def walk_to_disk(driver, app, shot, max_pages=12, timeout=PAGE_TIMEOUT):
    """Click the primary action of each page until the disk page shows."""
    from atspi_match import Page

    deadline = time.monotonic() + timeout
    clicks = 0
    while time.monotonic() < deadline:
        page = driver.poll(app)
        if page is Page.FAILURE:
            raise DriverError(f"installer failed before the disk page: {driver.last_nodes!r}")
        if page is Page.DISK:
            return clicks
        if page is Page.WAIT and not driver.last_nodes:
            time.sleep(driver.poll_interval)
            continue
        if clicks >= max_pages:
            break
        try:
            node = driver.click_primary(app, names=WALK_NAMES)
        except DriverError:
            time.sleep(driver.poll_interval)
            continue
        clicks += 1
        # The click lands where AT-SPI says the node is; the log line and the
        # screenshot show whether that is where the button is on the screen.
        print(
            f"walk: click {clicks} on {node.get('role')} {node.get('name')!r} at {node.get('ext')}",
            file=sys.stderr,
        )
        shot(f"2-page-{clicks:02d}")
        time.sleep(3)
    raise DriverError(
        f"no disk page after {clicks} clicks; last page: "
        f"{[n.get('name') for n in driver.last_nodes if n.get('name')][:40]!r}"
    )


def photograph_progress(page, shot):
    """One picture of the install page when a walk ends on it.

    The page shows only while the copy runs and the stage 3 wait after the
    walk looks for the next page, so no other picture of a run has it
    (bonito:kde run 45836370728). A walk that ends on the key page or the
    done page (a fast copy) has no progress page to take."""
    from atspi_match import Page

    if page is Page.PROGRESS:
        shot("3-progress")


# The buttons of the disk pages of gnome-setup at the pinned commit
# (src/page/installer/disk/*.rs, *.blp), the most final one first. A
# mnemonic underscore is not in the accessible name.
INSTALL_NAMES = (
    "Erase and Install",
    "Install",
    "Start Installation",
    "Use Entire Disk",
    "Next",
    "Continue",
)
ROW_ROLES = ("list item", "table row", "row")


def walk_install(driver, app, shot, act, keys, max_steps=20, timeout=PAGE_TIMEOUT):
    """From the disk page to the running install: choose the disk, confirm.

    Each step presses the first known button; with none, it presses the
    first disk row. The VM has one disk the installer accepts, the target.
    """
    from atspi_match import TARGET_RE, Page, text_of

    deadline = time.monotonic() + timeout
    steps = 0
    while time.monotonic() < deadline:
        page = driver.poll(app)
        if page is Page.FAILURE:
            raise DriverError(f"installer failed before the install: {driver.last_nodes!r}")
        if page in (Page.PROGRESS, Page.RECOVERY_KEY, Page.COMPLETE):
            photograph_progress(page, shot)
            return steps
        if steps >= max_steps:
            break
        node = None
        try:
            node = driver.click_primary(app, names=INSTALL_NAMES)
        except DriverError:
            rows = [
                n
                for n in driver.last_nodes
                if n.get("role") in ROW_ROLES
                and TARGET_RE.search(text_of(n))
                and {"showing", "sensitive"} <= set(n.get("states", []))
            ]
            if rows:
                # A GTK list row has no accessible action (run 45611066032):
                # it takes the keyboard focus and Return.
                node = rows[0]
                focused = "focused" in node.get("states", []) or act(app, "focus", node)
                keys("ret" if focused else "tab")
        if node is None:
            time.sleep(driver.poll_interval)
            continue
        steps += 1
        print(f"install: step {steps} on {node.get('role')} {node.get('name')!r}", file=sys.stderr)
        shot(f"3-step-{steps:02d}")
        time.sleep(3)
    raise DriverError(
        f"the install did not start after {steps} steps; last page: "
        f"{[n.get('name') for n in driver.last_nodes if n.get('name')][:40]!r}"
    )


# A desktop has gradients and anti-aliased text: hundreds of colors. A kernel
# console is text in one or two colors on black. Fewer colors than this is no desktop.
DESKTOP_MIN_COLORS = 16
# A screen where this share of the pixels is one color has nothing on it but a line or two.
BLANK_SHARE = 0.995


def settled_shot(shot, name, tries=6, pause=20):
    """A picture of a screen that has settled: (png, blank).

    A picture taken while the system still boots is black for a while
    (bonito:kde run 45836370728, usb-7-switch-rollback.png), so a blank
    picture is taken again, up to `tries` times. A screen that stays one
    colour is blank: stages 5-7 fail on it, whatever the records say
    (albacore:kde run 46083819054)."""
    png = None
    for attempt in range(tries):
        png = shot(name)
        if png is not None and not blank(png):
            return png, False
        if attempt + 1 < tries:
            time.sleep(pause)
    return png, True


# What the guest says about its display when the picture is blank: the
# DRM devices, the seat of each session, the kernel DRM lines, then what the
# compositor and the shell of the user session logged. Unit start and stop
# lines are left out: in albacore:kde run 46087879404 they filled the record
# and pushed the kwin_wayland lines out of it.
DESKTOP_DIAG = (
    "echo '--- cmdline'; cat /proc/cmdline; echo '--- dri'; ls -l /dev/dri; "
    "echo '--- sessions'; loginctl list-sessions --no-legend | while read -r s _; do "
    "loginctl show-session \"$s\" -p Name -p Type -p Class -p State -p VTNr -p Seat; done; "
    "echo '--- kernel'; journalctl -b -k --no-pager -o short-monotonic | "
    "grep -iE 'drm|virtio.?gpu|bochs|segfault' | head -30; "
    "echo '--- desktop'; journalctl -b --no-pager -o short-monotonic | "
    "grep -E 'kwin_wayland|plasmashell|kwin_|ksplash|startplasma|gnome-shell|cosmic-comp|niri' | "
    "grep -vE 'systemd\\[[0-9]+\\]: (Start|Stopp|Finish|Reach)' | head -150; "
    # What the compositor of the seat's user session says about its outputs:
    # in albacore:kde run 46100963160 the session started after the login
    # screen's kwin had gone and the screen stayed black all the same.
    "u=$(loginctl list-sessions --no-legend | awk '$4==\"seat0\" && $3!=\"plasmalogin\" {print $3; exit}'); "
    "if [ -n \"$u\" ]; then id=$(id -u \"$u\"); "
    "run() { runuser -u \"$u\" -- env XDG_RUNTIME_DIR=/run/user/$id "
    "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$id/bus WAYLAND_DISPLAY=wayland-0 \"$@\" 2>&1; }; "
    "echo '--- kscreen'; command -v kscreen-doctor >/dev/null && run kscreen-doctor -o | head -40; "
    "echo '--- kwin'; run busctl --user call org.kde.KWin /KWin org.kde.KWin supportInformation | "
    "sed 's/\\\\n/\\n/g' | grep -iE -A2 'output|compositing|openglis|renderer|backend|screen' | head -80; "
    "echo '--- user config'; ls -la \"$(getent passwd \"$u\" | cut -d: -f6)/.config\" 2>/dev/null | "
    "grep -iE 'kwin|kscreen|powerdevil'; fi"
)


def desktop_diagnosis(args):
    try:
        _, out = ssh_run(args.ssh_port, args.ssh_key, DESKTOP_DIAG, user="root", timeout=120)
    except subprocess.TimeoutExpired:
        return "no answer"
    return out[:20000]


def blank(png):
    """True when the screenshot shows no desktop: one color, or only console text.

    Run 46008379629 (bonito:niri, hosted) passed stage 1 on a picture of one
    kernel console line on black ("tun: Universal TUN/TAP device driver"):
    the old check wanted every pixel the same. Now the picture is blank when
    one color covers 99.5% of it (a line or two of text), or when it has fewer
    than 16 distinct colors (a whole screen of console text)."""
    try:
        rgb = ocr_fallback.raw_rgb(png)
    except (OSError, subprocess.SubprocessError):
        return False
    pixels = len(rgb) // 3
    if pixels == 0:
        return False
    colors = collections.Counter(zip(rgb[0::3], rgb[1::3], rgb[2::3]))
    return len(colors) < DESKTOP_MIN_COLORS or colors.most_common(1)[0][1] >= BLANK_SHARE * pixels


def daemon_state(args):
    """The installer daemon and the disks, for the record of a stage."""
    try:
        _, out = ssh_run(
            args.ssh_port,
            args.ssh_key,
            "sudo journalctl -b --no-pager -u fishermand -u polkit 2>&1 | tail -60; "
            "systemctl is-active fishermand.service; "
            "getenforce; ls -dZ / /usr /etc /var /usr/lib64 /usr/lib64/libaudit.so.1; "
            "sudo dmesg | grep -E 'avc: +denied' | tail -25; "
            # The finish step of gnome-setup is a unit; it waits for its job.
            "sudo systemctl --no-pager list-jobs; "
            "sudo systemctl --no-pager status 'medium-install-post@*' 2>&1 | head -30; "
            "sudo journalctl -b --no-pager -n 40 -o short-monotonic; "
            "lsblk -o NAME,SIZE,TYPE,FSTYPE,PARTLABEL,MOUNTPOINTS; "
            # The frontend: does it run, did it crash, what did it say.
            "pgrep -af 'tuna-installer|gnome-setup' | cut -c1-200; coredumpctl --no-pager list 2>&1 | tail -5; "
            "journalctl --user -b --no-pager 2>&1 | "
            "grep -iE 'niri|medium-live|tuna-installer|org.tunaos|gnome-setup|panic|wgpu|vulkan|EGL' | grep -v '#[0-9]' | tail -40",
            timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return f"no answer: {exc}"
    return out[-9000:]


LIVE_MARKER = "/var/tmp/installer-e2e-live-marker"


def marker_first(args):
    """Write the file that a btrfs install must keep, before the install starts."""
    if args.filesystem == "btrfs":
        ssh_run(args.ssh_port, args.ssh_key, f"test -f {LIVE_MARKER} || echo live > {LIVE_MARKER}")


NATIVE_APP_PREFIX = "org.tunaos.Installer"
NATIVE_NAMES = ("Install now", "Erase and Install", "Install", "Get started", "Next", "Continue")
ENTRY_ROLES = ("text", "entry", "password text")
# Values for the account page and the passphrase page. The VM is thrown away;
# the same password lets stage 5 and stage 6 log in.
E2E_USER, E2E_PASSWORD = "tester", "tunae2epassword25"


def entry_value(node):
    """What the walk types into an entry, by its accessible name; None to leave it."""
    name = (node.get("name") or "").lower()
    if "password" in name or "passphrase" in name or node.get("role") == "password text":
        return E2E_PASSWORD
    if "user" in name and "name" in name:
        return E2E_USER
    return None


def key_press(driver, app, keys, name, role, tries=10):
    """Tab to the node and press Space. False when it never has the focus."""
    for _ in range(tries):
        node = qualify(driver.dump(app), name, role=role)
        if node is None:
            return False
        if "focused" in node.get("states", []):
            keys("spc")
            return True
        keys("tab")
        time.sleep(0.5)
    return False


# The first-boot account app: gnome-initial-setup (GNOME), or
# io.elementary.initial-setup, which io.elementary.greeter runs as the
# greeter user on its X11 display when the system has no user (Pantheon).
# "initial-setup" names both on the AT-SPI desktop.
GIS = "initial-setup"
GIS_PROCESS = r"(^|/)(gnome-initial-setup|io\.elementary\.initial-setup)( |$)"
# "Start Setup" is the Welcome page of gnome-initial-setup 49 (Fedora 43, Tuna
# Desktop): bonito:tuna run 45996411588 stopped there, six "no button" steps.
GIS_NAMES = ("Start Setup", "Next", "Continue", "Accept", "Skip", "Set Up Later", "Done", "Select")
# The button that ends the setup: GNOME starts the session itself; elementary
# goes back to the greeter, where the new account logs in.
GIS_LAST = {"Start Using": False, "Finish Setup": True}


def initial_setup_command(args, verb, *words):
    """SSH command that runs the guest script in the session of the first-boot app.

    The bus and display come from the environment of the app: the greeter
    session of LightDM has no fixed bus path."""
    tail = " ".join(shlex.quote(w) for w in (verb, GIS, *words))
    return [
        *ssh_base(args.ssh_port, args.ssh_key, "root"),
        f"p=$(pgrep -o -f {shlex.quote(GIS_PROCESS)}); [ -n \"$p\" ] || exit 9; "
        'u=$(ps -o user:64= -p "$p" | tr -d " "); d=/run/user/$(id -u "$u"); '
        "e=$(tr '\\0' '\\n' < /proc/$p/environ | "
        "grep -E '^(DBUS_SESSION_BUS_ADDRESS|AT_SPI_BUS_ADDRESS|DISPLAY|XAUTHORITY|WAYLAND_DISPLAY|XDG_RUNTIME_DIR)='); "
        'runuser -u "$u" -- env XDG_RUNTIME_DIR=$d DBUS_SESSION_BUS_ADDRESS=unix:path=$d/bus $e '
        f"python3 - {tail}",
    ]


def setup_entry_value(node, label):
    """What stage 5 types into an entry: by its name, else by the label before it."""
    name = (node.get("name") or label or "").lower()
    if "full name" in name:
        return "Tester"
    return entry_value({**node, "name": name})


def setup_row(nodes):
    """The list row to select when "Select" is off: English first, else the first row."""
    rows = [n for n in nodes if n.get("role") == "list item"]
    return next((n for n in rows if (n.get("name") or "").startswith("English")), rows[0] if rows else None)


def drive_initial_setup(args, shot, keys, max_steps=25, timeout=600):
    """First boot: make the account in the first-boot app.

    Returns (done, log, login): login is True when the app ends at the
    greeter and the new account must log in."""
    from atspi_match import PRESS_ROLES, is_sensitive, is_showing

    def guest(verb, *words):
        with GUEST_DUMP_SOURCE.open() as script:
            return subprocess.run(
                initial_setup_command(args, verb, *words),
                stdin=script, capture_output=True, text=True, timeout=60, check=False,
            )

    log, filled, rows = [], {}, {}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and len(log) < max_steps:
        try:
            proc = guest("dump")
            nodes = [n for n in parse_tree(proc.stdout) if is_showing(n)]
        except (ValueError, TypeError, subprocess.TimeoutExpired):
            time.sleep(5)
            continue
        buttons = [n for n in nodes if n.get("role") in PRESS_ROLES and is_sensitive(n)]
        for want, login in GIS_LAST.items():
            last = next((n for n in buttons if (n["name"] or "").startswith(want)), None)
            if last is not None:
                shot("5-setup-last")
                guest("press", last["path"])
                log.append(f"pressed {last['name']!r}")
                return True, log, login
        wrote, label = False, ""
        for node in nodes:
            if node.get("role") == "label":
                label = node.get("name") or node.get("text") or ""
            if node.get("role") not in ENTRY_ROLES or not is_sensitive(node) or node.get("text"):
                continue
            value = setup_entry_value(node, label)
            key = (node["path"], (node.get("name") or label).lower())
            if value is None or filled.get(key, 0) >= 3:
                continue
            filled[key] = filled.get(key, 0) + 1
            guest("settext", node["path"], value)
            wrote = True
        if wrote:
            time.sleep(2)
            continue
        # elementary keeps "Select" off until a row of its list is chosen:
        # select the row, then the keyboard (Return on the focused row).
        held = any(n.get("role") in PRESS_ROLES and n["name"] == "Select" and not is_sensitive(n) for n in nodes)
        row = setup_row(nodes) if held else None
        if row is not None:
            turn = rows[row["path"]] = rows.get(row["path"], 0) + 1
            if turn % 2:
                guest("select", row["path"])
            else:
                guest("focus", row["path"])
                with contextlib.suppress(DriverError):
                    keys("ret")
            log.append(f"chose row {row['name']!r}")
            time.sleep(2)
            continue
        node = next((n for want in GIS_NAMES for n in buttons if n["name"] == want), None)
        if node is None:
            log.append(f"no button: {[n['name'] for n in nodes if n['name']][:25]!r}")
            time.sleep(5)
            continue
        guest("press", node["path"])
        log.append(f"pressed {node['name']!r}")
        shot(f"5-setup-{len(log):02d}")
        time.sleep(4)
    return False, log, False


def walk_native(driver, app, shot, act, keys, record, max_steps=60, timeout=PAGE_TIMEOUT, a11y=None):
    """From the first page of a native frontend to the running install.

    Each step fills the entries of the page, presses the forward button, or
    chooses the first disk. `record(nodes)` gets the tree of the disk page:
    stage 2 is that page with the target disk on it. On the first page it
    ticks the "Screen reader" check box when there is one (XFCE,
    installer#491) and records it in `a11y`.
    """
    from atspi_match import PRESS_ROLES, TARGET_RE, Page, is_sensitive, is_showing, text_of

    deadline = time.monotonic() + timeout
    steps, filled, tried = 0, {}, {}
    while time.monotonic() < deadline and steps < max_steps:
        page = driver.poll(app)
        nodes = [n for n in driver.last_nodes if is_showing(n)]
        if page is Page.FAILURE:
            raise DriverError(f"installer failed: {[n.get('name') for n in nodes if n.get('name')][:40]!r}")
        if page in (Page.PROGRESS, Page.RECOVERY_KEY, Page.COMPLETE):
            photograph_progress(page, shot)
            return steps
        if page is Page.DISK:
            record(nodes)
        if a11y is not None and steps == 0 and "pressed" not in a11y:
            box = screen_reader_box(nodes)
            if box is not None:
                # Already ticked (the live session had it on): leave it.
                if "checked" not in box.get("states", []):
                    act(app, "focus", box)
                    keys("spc")
                time.sleep(1)
                driver.poll(app)
                after = screen_reader_box([n for n in driver.last_nodes if is_showing(n)])
                ticked = after is not None and "checked" in after.get("states", [])
                a11y.update({"pressed": True, "status": "pressed", "live-checked": ticked})
                shot("2-native-a11y")
                continue
        wrote = False
        forward = {name.lower() for name in NATIVE_NAMES}
        ready = any(
            n.get("role") in PRESS_ROLES
            and (n.get("name") or "").strip().lower() in forward
            and is_sensitive(n)
            for n in nodes
        )
        for node in nodes:
            value = entry_value(node) if node.get("role") in ENTRY_ROLES else None
            # Qt puts the text of a password entry in its name (run 45647965089).
            if value in (None, node.get("name")) or not is_sensitive(node) or node.get("text"):
                continue
            # The text is read again on the next turn: an entry that stays
            # empty gets the keyboard.
            key = (node.get("path"), node.get("name"))
            filled[key] = filled.get(key, 0) + 1
            if filled[key] == 1:
                act(app, "settext", node, value)
                wrote = True
            elif filled[key] <= 3 and not ready:
                # A password entry can read as empty when it is not: the
                # keyboard is for a page that does not let the user go on.
                act(app, "focus", node)
                keys(*value)
        if wrote:
            # Read the page again: the forward button follows the entries.
            continue
        radios = [
            n
            for n in nodes
            if n.get("role") in ("radio button", "list item") and TARGET_RE.search(text_of(n))
        ]
        if page is Page.DISK and not radios:
            radios = disk_radio_by_label(nodes)
        chosen = any("checked" in n.get("states", []) for n in radios)
        if page is Page.DISK and radios and not chosen:
            # The press action first, then the keyboard: Qt sends no toggled()
            # signal for an accessible action, and the model reads that signal.
            turn = tried[page] = tried.get(page, 0) + 1
            if turn % 2:
                driver.press(app, radios[0])
            else:
                act(app, "focus", radios[0])
                keys("spc")
            node = radios[0]
        else:
            node = next(
                (
                    n
                    for name in NATIVE_NAMES
                    for n in nodes
                    if n.get("role") in PRESS_ROLES
                    and (n.get("name") or "").strip().lower() == name.lower()
                    and is_sensitive(n)
                ),
                None,
            )
            if node is not None:
                driver.press(app, node)
        if node is None:
            time.sleep(driver.poll_interval)
            continue
        steps += 1
        if a11y is not None and "pressed" not in a11y:
            # The first page had no screen reader control: "not run".
            a11y["pressed"] = False
        print(f"native: step {steps} on {node.get('role')} {node.get('name')!r}", file=sys.stderr)
        shot(f"2-native-{steps:02d}")
        time.sleep(3)
    raise DriverError(
        f"the install did not start after {steps} steps; last page: "
        f"{[n.get('name') for n in driver.last_nodes if n.get('name')][:60]!r}"
    )


def middle_stages_atspi(args, shot, qmp, stage_results, app, a11y=None):
    """Stages 2-4 through AT-SPI matchers. Returns 0, else 1 with fail staged."""
    from atspi_match import Page, classify_native, classify_page, lists_target

    def dump(app_name):
        cmd = ssh_dump_command(args.ssh_port, args.ssh_key, app_name)
        with GUEST_DUMP_SOURCE.open() as script:
            proc = subprocess.run(
                cmd, stdin=script, capture_output=True, text=True, timeout=60, check=False
            )
        try:
            return parse_tree(proc.stdout)
        except (ValueError, TypeError) as exc:
            # No tree yet (no session bus, no typelib) reads as an empty
            # screen; the reason goes to the log, and the poll loop times out.
            print(f"atspi dump: {exc}; stderr: {proc.stderr.strip()[-300:]}", file=sys.stderr)
            return []

    def press(app_name, node):
        cmd = ssh_press_command(args.ssh_port, args.ssh_key, app_name, node["path"])
        with GUEST_DUMP_SOURCE.open() as script:
            proc = subprocess.run(
                cmd, stdin=script, capture_output=True, text=True, timeout=60, check=False
            )
        if proc.returncode != 0:
            raise DriverError(f"press {node.get('name')!r}: {proc.stderr.strip()[-200:]}")

    def act(app_name, verb, node, *words):
        cmd = ssh_node_command(
            args.ssh_port, args.ssh_key, app_name, verb, node["path"], *words
        )
        with GUEST_DUMP_SOURCE.open() as script:
            proc = subprocess.run(
                cmd, stdin=script, capture_output=True, text=True, timeout=60, check=False
            )
        if proc.returncode != 0:
            print(f"{verb} {node.get('name')!r}: {proc.stderr.strip()[-200:]}", file=sys.stderr)
        return proc.returncode == 0

    native = app.startswith(NATIVE_APP_PREFIX)
    rc, _ = ssh_run(args.ssh_port, args.ssh_key, ENABLE_A11Y)
    if rc != 0:
        print("atspi: could not set org.a11y.Status IsEnabled", file=sys.stderr)

    # Buttons are pressed through the AT-SPI action interface in the guest.
    # A pointer click cannot work here: the session is Wayland, and the first
    # real run got the extents [0, 0, 42, 42] for the Next button
    # (run 45594835162). click_node gives a list of QMP commands and Qmp.run
    # takes them as arguments; the pointer path stays for a session that
    # reports screen coordinates.
    driver = Driver(
        dump,
        lambda commands: qmp.run(*commands),
        shot,
        width=SCREEN_W,
        height=SCREEN_H,
        press=press,
        classify=classify_native if native else classify_page,
    )
    # The stamp names the application id (org.gnome.Setup); the AT-SPI name
    # of the same process can be its program name. Take the first candidate
    # that has a tree.
    app = resolve_app(dump, app)
    # Stage 2: installer pages through the driver. The wizard shows other
    # pages before the disk page (language, keyboard, try or install):
    # walk_to_disk clicks through them.
    disk_page = {}

    def record(nodes):
        # The disk list fills after the page shows: keep the last reading.
        if not disk_page.get("target"):
            disk_page["names"] = [n["name"] for n in nodes if n.get("name")][:60]
            disk_page["target"] = lists_target(nodes)
            shot("2-installer-pages")

    def pages_status():
        return "pass" if disk_page.get("target") else "unverified"

    try:
        if native:
            # The walk of a native frontend runs to the install; stage 2 is
            # the disk page that it passes on the way.
            marker_first(args)
            walk_native(driver, app, shot, act, qmp.send_keys, record, a11y=a11y)
        else:
            walk_to_disk(driver, app, shot)
            for _ in range(15):
                driver.poll(app)
                record(driver.last_nodes)
                if disk_page.get("target"):
                    break
                time.sleep(driver.poll_interval)
    except DriverError as exc:
        log_snapshot(driver)
        shot("2-stopped")
        if disk_page:
            stage_results.append({"id": "installer-pages", "status": pages_status(), **disk_page})
            stage_results.append(
                {"id": "install", "status": "fail", "error": str(exc), "guest": daemon_state(args)}
            )
        else:
            stage_results.append(
                {
                    "id": "installer-pages",
                    "status": "fail",
                    "error": str(exc),
                    "guest": daemon_state(args),
                }
            )
        return 1
    if not disk_page:
        stage_results.append(
            {"id": "installer-pages", "status": "fail", "error": "the walk saw no disk page"}
        )
        return 1
    stage_results.append({"id": "installer-pages", "status": pages_status(), **disk_page})
    # Stage 3: install, with the btrfs live-file assert on btrfs cells.
    marker = LIVE_MARKER
    marker_first(args)
    try:
        if not native:
            walk_install(driver, app, shot, act, qmp.send_keys)
        # The copy runs; the next page is the recovery key or the done page.
        driver.wait_for(app, {Page.RECOVERY_KEY, Page.COMPLETE}, timeout=900)
    except DriverError as exc:
        log_snapshot(driver)
        stage_results.append(
            {"id": "install", "status": "fail", "error": str(exc), "guest": daemon_state(args)}
        )
        return 1
    shot("3-install")
    checks = {"status": "pass", "daemon": daemon_state(args)}
    if args.filesystem == "btrfs":
        rc, _ = ssh_run(args.ssh_port, args.ssh_key, f"test -f {marker}")
        # The session is still the live one here, so the file says nothing
        # about the installed system: fishermand decides `reboot` for every
        # target until the migrate handoff exists (tunaOS#4908).
        checks["live-file-survives"] = "unverified" if rc == 0 else "fail"
    stage_results.append({"id": "install", **checks})
    # Stage 4: TPM unlock or recovery key by shape (never logged).
    shot("4-unlock")
    key = driver.recovery_key_value(app)
    # Leave the recovery key page as a user does (the check box, then Done),
    # and wait for the done page: a reboot before it could cut the
    # post-install step short. A failure here is in the stage record.
    done_page = False
    try:
        if driver.poll(app) is Page.RECOVERY_KEY:
            # gnome-setup, then the native frontends. A GTK check box has no
            # accessible action on EL10 (run 45651057509): it takes Space.
            for name in ("I backed up my recovery key", "I have saved my recovery key"):
                try:
                    driver.click_named(app, name, role="check box")
                    break
                except DriverError:
                    if key_press(driver, app, qmp.send_keys, name, "check box"):
                        break
            time.sleep(2)
            driver.click_primary(app, names=("Done", "Next", "Continue"))
            time.sleep(5)
            shot("4-after-key")
        driver.wait_for(app, Page.COMPLETE, timeout=900)
        done_page = True
        shot("4-done")
    except DriverError as exc:
        print(f"unlock: the done page did not show: {str(exc)[:1500]}", file=sys.stderr)
    # The recovery key on screen is the only thing this stage reads. Whether
    # the TPM unlocks the disk shows at the next boot, in stage 6.
    stage_results.append(
        {
            "id": "unlock",
            # A key that the installer shows and does not save unlocks nothing
            # (bonito:kde run 45671929202): the page after it must show. Stage
            # 6 tries the key on the disk.
            "status": "pass" if key is not None and done_page else "fail",
            "recovery-key-present": key is not None,
            "done-page": done_page,
            "tpm": bool(args.tpm),
        }
    )
    # The page shows the key in a label, maybe with more words around it.
    match = RECOVERY_KEY_RE.search(key or "")
    args.recovery_key = match.group(0) if match else None
    args.recovery_key_source = "atspi" if args.recovery_key else None
    return 0


# The first page has a screen reader control: COSMIC a "Turn on" button
# (tuna-os/installer#481, OCR walk), XFCE a "Screen reader" check box
# (installer#491, AT-SPI walk). The choice reaches the installed system through
# ConfigureTarget (tuna-os/fisherman#539): /etc/tunaos/accessibility.conf, and
# an autostart script that sets the GSettings key at the first login. The
# script runs after the login, so the read waits up to about 60 s.
#
# The read takes DCONF_PROFILE from the user manager: COSMIC's start-cosmic
# exports DCONF_PROFILE=cosmic (user-db:cosmic first) and imports it there, so
# the script's write lands in ~/.config/dconf/cosmic. A gsettings without it
# reads ~/.config/dconf/user and gets the default false (run 45826150571).
# cosmic-initial-setup turns the at-spi status on by itself, so the key alone
# does not prove the carry: the script's done marker must be there too
# (${XDG_STATE_HOME:-$HOME/.local/state}/tunaos/first-login-accessibility.done,
# fisherman#539 accessibilityScript; the session sets no XDG_STATE_HOME).
A11Y_READ = (
    # $env splits into the two assignments on purpose.
    f"uid=$(id -u {E2E_USER}); home=$(getent passwd {E2E_USER} | cut -d: -f6); "
    'env="env DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$uid/bus XDG_RUNTIME_DIR=/run/user/$uid"; '
    "v=; p=; for _ in $(seq 1 12); do "
    f"p=$(runuser -u {E2E_USER} -- $env systemctl --user show-environment 2>/dev/null "
    "| sed -n 's/^DCONF_PROFILE=//p'); "
    f"v=$(runuser -u {E2E_USER} -- $env ${{p:+DCONF_PROFILE=$p}} gsettings get "
    "org.gnome.desktop.a11y.applications screen-reader-enabled 2>&1); "
    '[ "$v" = true ] && break; sleep 5; done; echo "gsettings=$v"; echo "dconf-profile=$p"; '
    'if [ -e "$home/.local/state/tunaos/first-login-accessibility.done" ]; '
    'then echo "first-login-done=yes"; else echo "first-login-done=no"; fi; '
    f'echo "atspi=$(runuser -u {E2E_USER} -- $env busctl --user get-property '
    'org.a11y.Bus /org/a11y/bus org.a11y.Status ScreenReaderEnabled 2>&1)"; '
    "cat /etc/tunaos/accessibility.conf 2>&1"
)


def a11y_result(output):
    """Read A11Y_READ's output: pass only when the key, the script's done
    marker and the record are all on."""
    lines = [ln.strip() for ln in output.splitlines()]

    def field(name):
        return next((ln.split("=", 1)[1] for ln in lines if ln.startswith(name + "=")), "")

    key = field("gsettings")
    done = field("first-login-done") == "yes"
    conf = "ScreenReader=yes" in lines
    return {
        "status": "pass" if key == "true" and done and conf else "fail",
        "gsettings": key,
        "dconf-profile": field("dconf-profile"),
        "first-login-done": done,
        "accessibility-conf": conf,
        "guest": output[-800:],
    }


def screen_reader_box(nodes):
    """The unticked or ticked "Screen reader" check box of a page, or None."""
    return next(
        (
            n
            for n in nodes
            if n.get("role") == "check box"
            and (n.get("name") or "").strip().lower() == "screen reader"
        ),
        None,
    )


def press_screen_reader(found, qmp, a11y, shot):
    """Press "Turn on" of the screen reader row when the page shows it.

    Records a11y["pressed"]; a page without the button leaves the result
    "not run". Returns the picture taken after the press, or None.
    """
    at = ocr_fallback.label_at(found, "Turn", "on")
    if at is None:
        a11y["pressed"] = False
        return None
    qmp.run(*click_at(at[1] + 20, at[0], SCREEN_W, SCREEN_H))
    time.sleep(3)
    png = shot()
    after = ocr_fallback.page_text(ocr_fallback.words(png)) if png is not None else ""
    a11y.update({"pressed": True, "status": "pressed", "live-button-off": "turn off" in after})
    return png


def disk_radio_by_label(nodes):
    """The radio of the target disk when its name is the model, not the path.

    fisherman#537 names a virtio disk "Virtual disk"; the KDE radio takes that
    name and "/dev/vda • 64 GiB • VirtIO" is a label of its own, so no radio
    matched TARGET_RE (bonito:kde run 45742289429). Take the radio whose tree
    path shares the longest prefix with the label that names the target, and
    only when exactly one radio is that close. A Kirigami FormRadioDelegate
    holds an unnamed RadioButton indicator under the delegate radio, so both
    tie (bonito:kde run 45756690146): a radio inside another tied radio is
    part of the same row and drops out."""
    from atspi_match import TARGET_RE, text_of

    labels = [n for n in nodes if n.get("role") not in ("radio button", "list item") and TARGET_RE.search(text_of(n))]
    radios = [n for n in nodes if n.get("role") == "radio button"]
    if not labels or not radios:
        return []
    if len(radios) == 1:
        return radios

    def common(a, b):
        a, b = str(a or ""), str(b or "")
        n = 0
        for x, y in zip(a.split("."), b.split(".")):
            if x != y:
                break
            n += 1
        return n

    best = [(max(common(r.get("path"), l.get("path")) for l in labels), i) for i, r in enumerate(radios)]
    top = max(b for b, _ in best)
    near = [radios[i] for b, i in best if b == top]

    def inside(r, o):
        rp, op = str(r.get("path") or ""), str(o.get("path") or "")
        return r is not o and op != "" and rp.startswith(op + ".")

    near = [r for r in near if not any(inside(r, o) for o in near)]
    return near if len(near) == 1 else []


def pick_greeter_user(shot, qmp, png):
    """Choose the installed account on a greeter that opens on "Select user..." (DMS, niri).

    The DMS greeter of bonito:niri shows a user drop-down and no password
    entry until a user is chosen (karnataka pod, usb-5-greeter.png of medium
    run 45828155977). Other greeters take the password as they are.
    """
    if png is None or not ocr_fallback.ocr_available():
        return
    at = ocr_fallback.label_at(ocr_fallback.words(png), "Select", "user...")
    if at is None:
        return
    qmp.run(*click_at(at[1] + 40, at[0], SCREEN_W, SCREEN_H))
    time.sleep(3)
    menu = shot("5-greeter-users")
    if menu is None:
        return
    user = next((w for w in ocr_fallback.words(menu) if w[0] == E2E_USER), None)
    if user is None:
        return
    qmp.run(*click_at(user[1] + user[3] // 2, user[2] + user[4] // 2, SCREEN_W, SCREEN_H))
    time.sleep(3)
    shot("5-greeter-user")


def tpm_row(found):
    """The center of the "TPM" choice when the encryption page is in passphrase mode, or None.

    The niri frontend opens its encryption page on "Passphrase" with the
    entries showing ("Enter passphrase"), even with a TPM (karnataka pod,
    medium run 45828155977). The rows are "Passphrase", "TPM" and
    "TPM + passphrase": the TPM row is the "TPM" word with no "+" beside it.
    """
    if "enter passphrase" not in ocr_fallback.page_text(found):
        return None
    for word in found:
        if word[0] == "TPM" and not any(o[0] == "+" and abs(o[2] - word[2]) <= 8 for o in found):
            return word[1] + word[3] // 2, word[2] + word[4] // 2
    return None


def walk_ocr(shot, qmp, disk_page, max_steps=40, timeout=PAGE_TIMEOUT, tpm=False, a11y=None):
    """From the first page of a frontend with no AT-SPI tree to the running install.

    Read the words, act on the page that the header names, then press the
    accent button. The controls of a form row are right of its label: the
    radio button above the center of the forward button, an entry left of it
    (COSMIC, docs/screenshots of the frontend). With a TPM the encryption page
    takes the TPM choice and no passphrase.
    """
    deadline = time.monotonic() + timeout
    button, steps, typed, last, scrolls = None, 0, set(), "", 0
    tpm_chosen = False
    while time.monotonic() < deadline and steps < max_steps:
        png = shot(f"2-ocr-{steps:02d}")
        if png is None:
            time.sleep(5)
            continue
        found = ocr_fallback.words(png)
        text = ocr_fallback.page_text(found)
        last = ocr_fallback.step_name(found)
        if "installation failed" in text or "no disks found" in text:
            raise DriverError(f"the frontend reports a failure: {text[:400]}")
        if last.startswith(("installing", "recovery", "handoff", "done", "finished")):
            return steps
        button = (
            ocr_fallback.accent_button(ocr_fallback.raw_rgb(png), SCREEN_W, SCREEN_H) or button
        )
        if button is None:
            time.sleep(5)
            continue
        # The header line also holds the window title: "welcome bonito"
        # (run 45819747629 never pressed "Turn on").
        if a11y is not None and last.startswith("welcome") and "pressed" not in a11y:
            after = f"2-ocr-{steps:02d}-a11y"
            png = press_screen_reader(found, qmp, a11y, lambda name=after: shot(name)) or png
        if "disk" in last and "encryption" not in last:
            # OCR read "/dev/vda" as "/devi/vda" (run 45652764616).
            row = next((w for w in found if re.search(r"/dev\w?/vda", w[0])), None)
            disk_page["text"] = text[:600]
            if row is not None:
                disk_page["target"] = True
                qmp.run(*click_at(button[0], row[2] - 4, SCREEN_W, SCREEN_H))
                time.sleep(2)
                png = shot(f"2-ocr-{steps:02d}-disk") or png
        if tpm and not tpm_chosen and "encryption" in last:
            at = tpm_row(found)
            if at is not None:
                tpm_chosen = True
                qmp.run(*click_at(*at, SCREEN_W, SCREEN_H))
                time.sleep(2)
                png = shot(f"2-ocr-{steps:02d}-tpm") or png
        rgb = None
        for label, value in (
            (("Username",), E2E_USER),
            (("Password",), E2E_PASSWORD),
            (("Confirm", "password"), E2E_PASSWORD),
            # niri's account page (run 45828155977, usb-2-ocr-06.png).
            (("Password", "again"), E2E_PASSWORD),
            (("Passphrase",), E2E_PASSWORD),
            (("Confirm", "passphrase"), E2E_PASSWORD),
        ):
            if tpm_chosen and "encryption" in last:
                # "Passphrase" is now the label of a radio row, not an entry.
                break
            at = ocr_fallback.label_at(found, *label)
            if at is None or (last, label) in typed:
                continue
            typed.add((last, label))
            # The entry right of the label, found by its color; else left of
            # the forward button (COSMIC).
            if rgb is None:
                try:
                    rgb = ocr_fallback.raw_rgb(png)
                except (OSError, subprocess.SubprocessError):
                    rgb = b""
            x = ocr_fallback.entry_x(rgb, SCREEN_W, at[0], at[1], button[0] - 40) if rgb else None
            qmp.run(*click_at(x if x is not None else button[0] - 108, at[0], SCREEN_W, SCREEN_H))
            time.sleep(1)
            qmp.send_keys(*value)
            png = shot(f"2-ocr-{steps:02d}-{label[-1].lower()}") or png
        if last.startswith("account") and (last, ("Confirm", "password")) not in typed and scrolls < 8:
            # The form is longer than the window: the next fields are below.
            scrolls += 1
            qmp.run(*click_at(SCREEN_W // 2, 420, SCREEN_W, SCREEN_H)[:1])
            for _ in range(3):
                for down in (True, False):
                    event = {"type": "btn", "data": {"button": "wheel-down", "down": down}}
                    qmp.run({"execute": "input-send-event", "arguments": {"events": [event]}})
            time.sleep(2)
            continue
        button = (
            ocr_fallback.accent_button(ocr_fallback.raw_rgb(png), SCREEN_W, SCREEN_H) or button
        )
        steps += 1
        print(f"ocr: step {steps} page {last!r} press at {button}", file=sys.stderr)
        qmp.run(*click_at(*button, SCREEN_W, SCREEN_H))
        time.sleep(4)
    raise DriverError(f"the install did not start after {steps} steps; last page {last!r}")


def middle_stages_ocr(args, shot, qmp, stage_results, app, a11y=None):
    """Stages 2-4 without AT-SPI: QEMU keys plus tesseract OCR (niri, cosmic)."""
    if not ocr_fallback.ocr_available():
        stage_results.append(
            {
                "id": "installer-pages",
                "status": "fail",
                "error": "tesseract missing for OCR fallback",
            }
        )
        return 1
    # Stages 2 and 3 to the running install: the pointer on what OCR reads.
    marker_first(args)
    disk_page = {}
    try:
        steps = walk_ocr(shot, qmp, disk_page, tpm=bool(args.tpm), a11y=a11y)
    except DriverError as exc:
        status = "pass" if disk_page.get("target") else "fail"
        stage_results.append(
            {"id": "installer-pages", "status": status, "input": "ocr-fallback", **disk_page}
        )
        stage_results.append(
            {"id": "install", "status": "fail", "error": str(exc), "guest": daemon_state(args)}
        )
        return 1
    stage_results.append(
        {
            "id": "installer-pages",
            "status": "pass" if disk_page.get("target") else "unverified",
            "input": "ocr-fallback",
            "steps": steps,
            **disk_page,
        }
    )
    # Stage 3: watch the header of the frontend until the copy ends.
    deadline = time.monotonic() + 1800
    page = ""
    while time.monotonic() < deadline:
        png = shot("3-install-poll")
        found = ocr_fallback.words(png) if png is not None else []
        text = ocr_fallback.page_text(found)
        if "installation failed" in text or "installation did not" in text:
            stage_results.append(
                {
                    "id": "install",
                    "status": "fail",
                    "error": "OCR read an install failure",
                    "ocr": text[:600],
                    "guest": daemon_state(args),
                }
            )
            return 1
        page = ocr_fallback.step_name(found)
        # The last pages of COSMIC have no step counter.
        if page.startswith(("recovery", "handoff", "done", "finished")) or any(
            end in text for end in ("recovery key", " is installed", "restart now")
        ):
            break
        time.sleep(10)
    else:
        stage_results.append(
            {
                "id": "install",
                "status": "fail",
                "error": f"OCR never read the end of the install; last page {page!r}",
                "guest": daemon_state(args),
            }
        )
        return 1
    shot("3-install")
    stage_results.append(
        {
            "id": "install",
            "status": "pass",
            "input": "ocr-fallback",
            "page": page,
            "daemon": daemon_state(args),
        }
    )
    # Stage 4: recovery key by shape from OCR words (never logged). OCR can
    # read one letter wrong: eight groups with most of their letters will do.
    png = shot("4-unlock")
    found = ocr_fallback.words(png) if png is not None else []
    seen = ocr_fallback.shows_recovery_key(found)
    # The keys go only to stage 6, which tries them on the disk; never logged.
    args.recovery_key_candidates = ocr_fallback.recovery_key_candidates(png, found) if png else []
    args.recovery_key = args.recovery_key_candidates[0] if args.recovery_key_candidates else None
    args.recovery_key_source = "ocr" if args.recovery_key else None
    done = False
    # Leave the page as a user does: the box, then the accent button.
    at = ocr_fallback.label_at(found, "saved", "my")
    if at is not None:
        qmp.run(*click_at(at[1] + 20, at[0], SCREEN_W, SCREEN_H))
        time.sleep(2)
        png = shot("4-ticked")
        button = png and ocr_fallback.accent_button(
            ocr_fallback.raw_rgb(png), SCREEN_W, SCREEN_H
        )
        if button:
            qmp.run(*click_at(*button, SCREEN_W, SCREEN_H))
            time.sleep(20)
        png = shot("4-after-key")
        after = ocr_fallback.page_text(ocr_fallback.words(png)) if png is not None else ""
        done = "could not" not in after and any(
            end in after for end in ("handoff", "is installed", "restart", "switch to the installed")
        )
    stage_results.append(
        {
            "id": "unlock",
            "status": "pass" if seen and done else "fail",
            "recovery-key-present": seen,
            # How many keys the readings left (the disk picks, in stage 6).
            "recovery-key-readings": len(args.recovery_key_candidates),
            "done-page": done,
            "tpm": bool(args.tpm),
            "input": "ocr-fallback",
        }
    )
    return 0


def unlock_verdict(stage_results, key_opens, source):
    """Stage 4 passes only when the recovery key also opens the disk without the TPM.

    DESKTOP-STANDARD C.4. Stage 6 runs `cryptsetup open --test-passphrase`
    with the key on the installed system and the result lands here. A key
    that OCR read and that does not open the disk is "unverified": OCR can
    read one letter wrong. A key from the AT-SPI tree that does not open the
    disk is a fail."""
    record = next((r for r in stage_results if r.get("id") == "unlock"), None)
    if record is None:
        return
    record["recovery-key-opens-the-disk"] = key_opens
    record["recovery-key-source"] = source
    if record.get("status") != "pass":
        return
    if key_opens is None:
        record["status"] = "unverified"
        record["note"] = "the key was not read, so nobody tried it without the TPM"
    elif not key_opens:
        record["status"] = "unverified" if source == "ocr" else "fail"
        record["note"] = "the recovery key did not open the disk"


def finish(evidence, boot, stage_results, code, a11y=None):
    """Write per-boot evidence JSON (chunked path mirrors iso-builder CI).

    Publishing needs a zero exit, so a run with a stage that nobody verified
    is not a success.
    """
    # A run that stops before stage 6 never tried the key without the TPM.
    unlock = next((r for r in stage_results if r.get("id") == "unlock"), None)
    if unlock is not None and "recovery-key-opens-the-disk" not in unlock:
        unlock_verdict(stage_results, None, None)
    if code == 0 and any(s.get("status") != "pass" for s in stage_results):
        code = 3
    path = Path(evidence) / f"{boot}-stages.json"
    record = {"boot": boot, "stages": stage_results, "code": code}
    # What the medium carries, so a record says which code it proves.
    if os.environ.get("E2E_FISHERMAN_REF"):
        record["fisherman_ref"] = os.environ["E2E_FISHERMAN_REF"]
    if a11y is not None:
        # Its own field: it never changes a stage verdict or the exit code.
        record["a11y"] = a11y
    text = json.dumps(record, indent=2)
    # A failure record holds the names of the page, and one page shows the key.
    path.write_text(RECOVERY_KEY_RE.sub("<recovery key>", text))
    return code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cell", default="tromso:kde")
    parser.add_argument("--medium", default="medium.iso")
    parser.add_argument("--work", default="e2e-out")
    parser.add_argument("--filesystem", choices=("xfs", "btrfs", "ext4"), default="btrfs")
    parser.add_argument("--boot", choices=("cdrom", "usb", "both"), default="both")
    parser.add_argument("--ssh-port", type=int, default=2222)
    parser.add_argument("--ssh-key", default="id_ed25519")
    parser.add_argument("--ovmf-code", default="/usr/share/OVMF/OVMF_CODE_4M.fd")
    parser.add_argument("--ovmf-vars", default="/usr/share/OVMF/OVMF_VARS_4M.fd")
    parser.add_argument("--target-size", default="64G", help="size of the install target disk")
    parser.add_argument("--candidate", default="", help="digest for the bootc switch stage")
    parser.add_argument("--baseline", default="", help="expected booted digest before the switch")
    parser.add_argument("--tpm", dest="tpm", action="store_true", default=True)
    parser.add_argument("--no-tpm", dest="tpm", action="store_false")
    parser.add_argument("--offline", dest="offline", action="store_true", default=True)
    parser.add_argument("--online", dest="offline", action="store_false")
    parser.add_argument("--atspi", dest="no_atspi", action="store_false", default=False)
    parser.add_argument("--no-atspi", dest="no_atspi", action="store_true")
    parser.add_argument("--virgl", dest="virgl", action="store_true", default=False)
    parser.add_argument("--no-virgl", dest="virgl", action="store_false")
    parser.add_argument("--kvm", dest="kvm", action="store_true", default=True)
    parser.add_argument("--no-kvm", dest="kvm", action="store_false", help="force TCG emulation")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--list-stages", action="store_true")
    args = parser.parse_args(argv)
    if args.list_stages:
        print("\n".join(stage_ids()))
        return 0
    if args.dry_run:
        return run_cell(args)
    if os.geteuid() == 0:
        print("run as a normal user (QEMU/KVM need no root)", file=sys.stderr)
        return 2
    return run_cell(args)


if __name__ == "__main__":
    sys.exit(main())
