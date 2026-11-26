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
        cmd += ["-display", "egl-headless,gl=on", "-device", "virtio-vga-gl"]
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
        """Save the guest screen to a PPM file."""
        self.run(
            {"execute": "screendump", "arguments": {"filename": str(ppm_path), "format": "ppm"}}
        )

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


def ssh_access_args(public_key):
    """QEMU arguments that give the harness SSH access, with no change to the medium.

    The medium ships no key and its images ship sshd disabled, so the first
    real run could not reach the guest ("guest sshd never answered"). systemd
    reads system credentials from SMBIOS type 11 strings in a VM:
    `tmpfiles.extra` writes one key file that sshd reads for every account,
    and `systemd.unit-dropin.multi-user.target` (systemd 256) starts sshd.
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
        # bonito:niri refuses each key: "bad ownership or modes for directory
        # /etc" (run 45627175940). The session record has the modes of /etc.
        "f+ /etc/ssh/sshd_config.d/01-installer-e2e.conf 0600 root root - StrictModes no\n"
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
        except (DriverError, OSError) as shot_exc:
            print(f"screenshot of the failed boot: {shot_exc}", file=sys.stderr)
        return finish(evidence, boot, [{"id": "live-boot", "status": "fail", "error": str(exc)}], 1)
    finally:
        stop(vm)
        stop(swtpm_proc)


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

    def shot(name):
        ppm = shots / f"{boot}-{name}.ppm"
        try:
            qmp.screendump(ppm)
        except DriverError as exc:
            print(f"screenshot {name} failed: {exc}", file=sys.stderr)
            return None
        return to_png(ppm, ppm.with_suffix(".png"))

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
            "journalctl --user -b --no-pager 2>&1 | grep -iE 'installer|flatpak|medium-live' | tail -40",
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
        return finish(evidence, boot, stage_results, 1)
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
                "error": "readiness stamp, but the screen is one color",
                "app": app,
                "guest": daemon_state(args),
            }
        )
        return finish(evidence, boot, stage_results, 1)
    stage_results.append({"id": "live-boot", "status": "pass", "app": app})
    # Stages 2-4: installer pages, install, unlock. AT-SPI matchers by
    # default; QEMU keys plus OCR where the toolkit has no AT-SPI.
    if args.no_atspi:
        code = middle_stages_ocr(args, shot, qmp, stage_results, app)
    else:
        code = middle_stages_atspi(args, shot, qmp, stage_results, app)
    if code != 0:
        return finish(evidence, boot, stage_results, code)
    # Leave the live session and take the medium out, as a user does. With the
    # medium still attached the firmware can start it again.
    try:
        ssh_run(args.ssh_port, args.ssh_key, "sudo systemctl poweroff", timeout=30)
    except (subprocess.TimeoutExpired, OSError):
        pass
    restart_from_disk()
    installed, proof = wait_installed_system(args, shot)
    shot("5-first-boot-setup")
    if not installed:
        stage_results.append(
            {
                "id": "first-boot-setup",
                "status": "fail",
                "error": "the VM did not boot the installed system",
                "guest": proof,
            }
        )
        return finish(evidence, boot, stage_results, 1)
    # A native frontend made the account in the install: log in as it. On a
    # GNOME cell the first boot makes the account, and nothing drives that yet.
    if app.startswith(NATIVE_APP_PREFIX):
        time.sleep(40)
        shot("5-greeter")
        try:
            qmp.send_keys(*E2E_PASSWORD, "ret")
        except DriverError as exc:
            print(f"login: {exc}", file=sys.stderr)
        time.sleep(60)
        shot("5-login")
        _, sessions = ssh_run(
            args.ssh_port, args.ssh_key, "loginctl list-sessions --no-legend; id tester", user="root"
        )
        seated = any("seat0" in line and E2E_USER in line for line in sessions.splitlines())
        stage_results.append(
            {
                "id": "first-boot-setup",
                "status": "pass" if seated else "unverified",
                "note": "login with the account that the install made",
                "guest": f"{proof}\n{sessions}",
            }
        )
    else:
        done, log = drive_initial_setup(args, shot)
        time.sleep(60)
        shot("5-session")
        _, sessions = ssh_run(
            args.ssh_port, args.ssh_key, "loginctl list-sessions --no-legend; id tester", user="root"
        )
        seated = any("seat0" in line and E2E_USER in line for line in sessions.splitlines())
        stage_results.append(
            {
                "id": "first-boot-setup",
                "status": "pass" if done and seated else "unverified",
                "steps": log,
                "note": EL10_REBOOT_TODO if args.filesystem == "xfs" else "",
                "guest": f"{proof}\n{sessions}",
            }
        )
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
        return finish(evidence, boot, stage_results, 1)
    try:
        digest = bootc_digest(out)
    except DriverError as exc:
        stage_results.append({"id": "desktop-status", "status": "fail", "error": str(exc)})
        return finish(evidence, boot, stage_results, 1)
    _, system = root(
        "getenforce; systemctl is-active graphical.target display-manager; "
        "loginctl list-sessions --no-legend; systemctl --failed --no-legend; "
        "lsblk -o NAME,SIZE,TYPE,FSTYPE,PARTLABEL,MOUNTPOINTS; cat /etc/crypttab"
    )
    shot("6-desktop-status")
    key_opens = None
    if getattr(args, "recovery_key", None):
        # Never logged: the key goes over stdin, and only the exit status back.
        proc = subprocess.run(
            [
                *ssh_base(args.ssh_port, args.ssh_key, "root"),
                "cryptsetup open --test-passphrase --key-file=- "
                "$(lsblk -nrpo NAME,FSTYPE | awk '$2==\"crypto_LUKS\"{print $1; exit}')",
            ],
            input=args.recovery_key, capture_output=True, text=True, timeout=120, check=False,
        )
        key_opens = proc.returncode == 0
    unlock_verdict(stage_results, key_opens, getattr(args, "recovery_key_source", None))
    # The desktop of a user is up when a session of class `user` is on a seat.
    # A greeter alone is the first-boot setup or a login that nobody drove.
    desktop = any(
        "seat0" in line and "greeter" not in line and " gdm" not in line
        for line in system.splitlines()
    )
    stage_results.append(
        {
            "id": "desktop-status",
            "status": "pass" if desktop else "unverified",
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
    )
    # Stage 7: bootc switch plus rollback (Utah phase rules).
    if not args.candidate:
        stage_results.append(
            {"id": "switch-rollback", "status": "todo", "note": "no --candidate digest given"}
        )
        return finish(evidence, boot, stage_results, 0)
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
        shot("7-switch")
        rc, log = root("bootc rollback 2>&1", timeout=300)
        if rc != 0:
            raise DriverError(f"bootc rollback failed: {log[-1500:]}")
        reboot_to(digest)
        shot("7-switch-rollback")
        record["status"] = "pass"
    except (DriverError, KeyError, ValueError) as exc:
        record["error"] = str(exc)
        shot("7-failed")
        return finish(evidence, boot, stage_results, 1)
    return finish(evidence, boot, stage_results, 0)


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


def wait_installed_system(args, shot=lambda _name: None, timeout=900):
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


def blank(png):
    """True when each pixel of the screenshot has the same color."""
    try:
        rgb = ocr_fallback.raw_rgb(png)
    except (OSError, subprocess.SubprocessError):
        return False
    return len(rgb) >= 3 and rgb == rgb[:3] * (len(rgb) // 3)


def daemon_state(args):
    """The installer daemon and the disks, for the record of a stage."""
    try:
        _, out = ssh_run(
            args.ssh_port,
            args.ssh_key,
            "sudo journalctl -b --no-pager -u fishermand -u polkit 2>&1 | tail -60; "
            "systemctl is-active fishermand.service; "
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


GIS = "gnome-initial-setup"
GIS_NAMES = ("Next", "Continue", "Accept", "Skip", "Set Up Later", "Done")


def initial_setup_command(args, verb, *words):
    """SSH command that runs the guest script in the session of gnome-initial-setup."""
    tail = " ".join(shlex.quote(w) for w in (verb, GIS, *words))
    return [
        *ssh_base(args.ssh_port, args.ssh_key, "root"),
        f"u=$(ps -o user:64= -C {GIS} | head -n 1); [ -n \"$u\" ] || exit 9; "
        'd=/run/user/$(id -u "$u"); '
        'runuser -u "$u" -- env XDG_RUNTIME_DIR=$d DBUS_SESSION_BUS_ADDRESS=unix:path=$d/bus '
        f"python3 - {tail}",
    ]


def drive_initial_setup(args, shot, max_steps=25, timeout=600):
    """GNOME first boot: make the account in gnome-initial-setup. Returns (done, log)."""
    from atspi_match import PRESS_ROLES, is_sensitive, is_showing

    def guest(verb, *words):
        with GUEST_DUMP_SOURCE.open() as script:
            return subprocess.run(
                initial_setup_command(args, verb, *words),
                stdin=script, capture_output=True, text=True, timeout=60, check=False,
            )

    log, filled = [], {}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and len(log) < max_steps:
        try:
            proc = guest("dump")
            nodes = [n for n in parse_tree(proc.stdout) if is_showing(n)]
        except (ValueError, TypeError, subprocess.TimeoutExpired):
            time.sleep(5)
            continue
        buttons = [n for n in nodes if n.get("role") in PRESS_ROLES and is_sensitive(n)]
        last = next((n for n in buttons if (n["name"] or "").startswith("Start Using")), None)
        if last is not None:
            shot("5-setup-last")
            guest("press", last["path"])
            return True, log
        wrote = False
        for node in nodes:
            if node.get("role") not in ENTRY_ROLES or not is_sensitive(node) or node.get("text"):
                continue
            name = (node.get("name") or "").lower()
            value = "Tester" if "full name" in name else entry_value(node)
            key = (node["path"], name)
            if value is None or filled.get(key, 0) >= 3:
                continue
            filled[key] = filled.get(key, 0) + 1
            guest("settext", node["path"], value)
            wrote = True
        if wrote:
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
    return False, log


def walk_native(driver, app, shot, act, keys, record, max_steps=60, timeout=PAGE_TIMEOUT):
    """From the first page of a native frontend to the running install.

    Each step fills the entries of the page, presses the forward button, or
    chooses the first disk. `record(nodes)` gets the tree of the disk page:
    stage 2 is that page with the target disk on it.
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
            return steps
        if page is Page.DISK:
            record(nodes)
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
        print(f"native: step {steps} on {node.get('role')} {node.get('name')!r}", file=sys.stderr)
        shot(f"2-native-{steps:02d}")
        time.sleep(3)
    raise DriverError(
        f"the install did not start after {steps} steps; last page: "
        f"{[n.get('name') for n in driver.last_nodes if n.get('name')][:60]!r}"
    )


def middle_stages_atspi(args, shot, qmp, stage_results, app):
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
            walk_native(driver, app, shot, act, qmp.send_keys, record)
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


def walk_ocr(shot, qmp, disk_page, max_steps=40, timeout=PAGE_TIMEOUT):
    """From the first page of a frontend with no AT-SPI tree to the running install.

    Read the words, act on the page that the header names, then press the
    accent button. The controls of a form row are right of its label: the
    radio button above the center of the forward button, an entry left of it
    (COSMIC, docs/screenshots of the frontend).
    """
    deadline = time.monotonic() + timeout
    button, steps, typed, last, scrolls = None, 0, set(), "", 0
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
        if "disk" in last and "encryption" not in last:
            # OCR read "/dev/vda" as "/devi/vda" (run 45652764616).
            row = next((w for w in found if re.search(r"/dev\w?/vda", w[0])), None)
            disk_page["text"] = text[:600]
            if row is not None:
                disk_page["target"] = True
                qmp.run(*click_at(button[0], row[2] - 4, SCREEN_W, SCREEN_H))
                time.sleep(2)
                png = shot(f"2-ocr-{steps:02d}-disk") or png
        for label, value in (
            (("Username",), E2E_USER),
            (("Password",), E2E_PASSWORD),
            (("Confirm", "password"), E2E_PASSWORD),
            (("Passphrase",), E2E_PASSWORD),
            (("Confirm", "passphrase"), E2E_PASSWORD),
        ):
            at = ocr_fallback.label_at(found, *label)
            if at is None or (last, label) in typed:
                continue
            typed.add((last, label))
            qmp.run(*click_at(button[0] - 108, at[0], SCREEN_W, SCREEN_H))
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


def middle_stages_ocr(args, shot, qmp, stage_results, app):
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
        steps = walk_ocr(shot, qmp, disk_page)
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
    # The key goes only to stage 6, which tries it on the disk; never logged.
    args.recovery_key = ocr_fallback.recovery_key_text(found)
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


def finish(evidence, boot, stage_results, code):
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
    text = json.dumps({"boot": boot, "stages": stage_results, "code": code}, indent=2)
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
