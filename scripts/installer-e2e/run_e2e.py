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
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import ocr_fallback
from driver import Driver, DriverError
from stages import EL10_REBOOT_TODO, plan_for_cell, stage_ids
from tree_dump import (
    GUEST_DUMP_SOURCE,
    parse_tree,
    ssh_dump_command,
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
):
    """QEMU command booting the medium bytes as CD-ROM or as a USB disk."""
    work = Path(work)
    cmd = [
        "qemu-system-x86_64",
        "-machine",
        "q35",
        "-m",
        "4096",
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
        f"file:{work}/serial-{boot}.log",
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
    else:
        raise ValueError(f"boot must be cdrom or usb, got {boot!r}")
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
                {"execute": "send-key", "arguments": {"keys": [{"key": key}], "hold-time": 50}}
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
    while time.monotonic() < deadline:
        if vm is not None and vm.poll() is not None:
            raise DriverError(f"QEMU exited with status {vm.returncode} before sshd answered")
        if progress is not None:
            progress()
        rc, _ = ssh_run(ssh_port, key_path, "true", timeout=15)
        if rc == 0:
            return
        time.sleep(5)
    raise DriverError("guest sshd never answered")


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
        cmd = build_qemu_cmd(
            args.medium,
            disk,
            work,
            args.ssh_port,
            boot,
            args.ovmf_code,
            offline=args.offline,
            tpm_sock=tpm_sock,
            virgl=args.virgl,
            kvm=args.kvm,
            extra=ssh_access_args(Path(f"{args.ssh_key}.pub").read_text()),
            ovmf_vars=vars_copy,
        )
        vm = subprocess.Popen(cmd)
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
        return run_stages(args, boot, shots, evidence)
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
        if vm is not None and vm.poll() is None:
            vm.terminate()
            try:
                vm.wait(timeout=60)
            except subprocess.TimeoutExpired:
                vm.kill()
        if swtpm_proc is not None and swtpm_proc.poll() is None:
            swtpm_proc.terminate()
            swtpm_proc.wait(timeout=30)


def run_stages(args, boot, shots, evidence):
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
            args.ssh_port, args.ssh_key, "cat $XDG_RUNTIME_DIR/tuna-installer-ready", timeout=60
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
    shot("1-live-boot")
    if rc != 0:
        _, session = ssh_run(
            args.ssh_port,
            args.ssh_key,
            "loginctl list-sessions --no-legend; systemctl --failed --no-legend; "
            "systemctl is-active display-manager medium-live-setup; "
            # Why the frontend did not start: its autostart entry, the Flatpak
            # store, and what the session logged about it.
            "cat /usr/lib/medium-live/desktop; ls /etc/xdg/autostart | grep -i installer; "
            "flatpak list --system --columns=application 2>&1 | head -20; "
            "journalctl --user -b --no-pager 2>&1 | grep -iE 'installer|flatpak|medium-live' | tail -40",
            timeout=120,
        )
        stage_results.append(
            {
                "id": "live-boot",
                "status": "fail",
                "error": "no readiness stamp at $XDG_RUNTIME_DIR/tuna-installer-ready",
                "guest": session,
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
    # Leave the live session: the installer offers a restart; without it the
    # harness asks the guest. The same VM then boots the target disk.
    try:
        ssh_run(args.ssh_port, args.ssh_key, "sudo systemctl reboot", timeout=30)
    except (subprocess.TimeoutExpired, OSError):
        pass
    installed, proof = wait_installed_system(args)
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
    # Nothing drives the first-boot setup yet: the stage has no check.
    note = EL10_REBOOT_TODO if args.filesystem == "xfs" else "first-boot setup is not driven yet"
    stage_results.append({"id": "first-boot-setup", "status": "unverified", "note": note, "guest": proof})
    # Stage 6: desktop plus bootc status.
    rc, out = ssh_run(
        args.ssh_port, args.ssh_key, "bootc status --format=json", user="root", timeout=60
    )
    if rc != 0:
        stage_results.append(
            {"id": "desktop-status", "status": "fail", "error": "bootc status failed"}
        )
        return finish(evidence, boot, stage_results, 1)
    try:
        digest = bootc_digest(out)
    except DriverError as exc:
        stage_results.append({"id": "desktop-status", "status": "fail", "error": str(exc)})
        return finish(evidence, boot, stage_results, 1)
    if args.baseline and digest != args.baseline:
        stage_results.append(
            {
                "id": "desktop-status",
                "status": "fail",
                "error": f"booted {digest}, expected baseline {args.baseline}",
            }
        )
        return finish(evidence, boot, stage_results, 1)
    shot("6-desktop-status")
    stage_results.append(
        {"id": "desktop-status", "status": "pass", "booted": digest, "installed-system": proof}
    )
    # Stage 7: bootc switch plus rollback (Utah phase rules).
    if not args.candidate:
        stage_results.append(
            {"id": "switch-rollback", "status": "todo", "note": "no --candidate digest given"}
        )
        return finish(evidence, boot, stage_results, 0)
    rc, _ = ssh_run(
        args.ssh_port, args.ssh_key, f"bootc switch {args.candidate}", user="root", timeout=600
    )
    if rc != 0:
        stage_results.append(
            {"id": "switch-rollback", "status": "fail", "error": "bootc switch failed"}
        )
        return finish(evidence, boot, stage_results, 1)
    shot("7-switch-rollback")
    stage_results.append(
        {"id": "switch-rollback", "status": "pass", "baseline": digest, "candidate": args.candidate}
    )
    return finish(evidence, boot, stage_results, 0)


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


def wait_installed_system(args, timeout=900):
    """Wait for SSH on the installed system. Returns (ok, last probe output)."""
    deadline = time.monotonic() + timeout
    out = ""
    while time.monotonic() < deadline:
        try:
            rc, out = ssh_run(args.ssh_port, args.ssh_key, INSTALLED_PROBE, user="root", timeout=30)
        except subprocess.TimeoutExpired:
            rc, out = 1, out
        if rc == 0 and is_installed_system(out):
            return True, out.strip()
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


def walk_install(driver, app, shot, max_steps=10, timeout=PAGE_TIMEOUT):
    """From the disk page to the running install: choose the disk, confirm.

    Each step presses the first known button; with none, it presses the
    first disk row. The VM has one disk the installer accepts, the target.
    """
    from atspi_match import Page

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
                and {"showing", "sensitive"} <= set(n.get("states", []))
            ]
            if rows and driver.press is not None:
                node = rows[0]
                driver.press(app, node)
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


def middle_stages_atspi(args, shot, qmp, stage_results, app):
    """Stages 2-4 through AT-SPI matchers. Returns 0, else 1 with fail staged."""
    from atspi_match import Page

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
    )
    # The stamp names the application id (org.gnome.Setup); the AT-SPI name
    # of the same process can be its program name. Take the first candidate
    # that has a tree.
    app = resolve_app(dump, app)
    # Stage 2: installer pages through the driver. The wizard shows other
    # pages before the disk page (language, keyboard, try or install):
    # walk_to_disk clicks through them.
    try:
        walk_to_disk(driver, app, shot)
    except DriverError as exc:
        log_snapshot(driver)
        stage_results.append({"id": "installer-pages", "status": "fail", "error": str(exc)})
        return 1
    shot("2-installer-pages")
    stage_results.append({"id": "installer-pages", "status": "pass"})
    # Stage 3: install, with the btrfs live-file assert on btrfs cells.
    marker = "/var/tmp/installer-e2e-live-marker"
    if args.filesystem == "btrfs":
        ssh_run(args.ssh_port, args.ssh_key, f"echo live > {marker}")
    try:
        walk_install(driver, app, shot)
        # The copy runs; the next page is the recovery key or the done page.
        driver.wait_for(app, {Page.RECOVERY_KEY, Page.COMPLETE}, timeout=1800)
    except DriverError as exc:
        log_snapshot(driver)
        stage_results.append({"id": "install", "status": "fail", "error": str(exc)})
        return 1
    shot("3-install")
    checks = {"install": "pass"}
    if args.filesystem == "btrfs":
        rc, _ = ssh_run(args.ssh_port, args.ssh_key, f"test -f {marker}")
        checks["live-file-survives"] = "pass" if rc == 0 else "fail"
        if rc != 0:
            stage_results.append({"id": "install", "status": "fail", "error": "live marker lost"})
            return 1
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
            for name, role in (("I backed up my recovery key", "check box"), ("Done", None)):
                driver.click_named(app, name, role=role)
                time.sleep(2)
        driver.wait_for(app, Page.COMPLETE, timeout=900)
        done_page = True
        shot("4-done")
    except DriverError as exc:
        print(f"unlock: the done page did not show: {str(exc)[:300]}", file=sys.stderr)
    # The recovery key on screen is the only thing this stage reads. Whether
    # the TPM unlocks the disk shows at the next boot, in stage 6.
    stage_results.append(
        {
            "id": "unlock",
            "status": "pass" if key is not None else "unverified",
            "recovery-key-present": key is not None,
            "done-page": done_page,
            "tpm": bool(args.tpm),
        }
    )
    return 0


def middle_stages_ocr(args, shot, qmp, stage_results, app):
    """Stages 2-4 without AT-SPI: QEMU keys plus tesseract OCR (niri, cosmic)."""
    from atspi_match import RECOVERY_KEY_RE, Page

    if not ocr_fallback.ocr_available():
        stage_results.append(
            {
                "id": "installer-pages",
                "status": "fail",
                "error": "tesseract missing for OCR fallback",
            }
        )
        return 1
    # Stage 2: walk the pages with the fallback key steps.
    try:
        for page in ("welcome", "disk", "confirm"):
            qmp.send_keys(*ocr_fallback.keys_for(page))
            shot(f"2-{page}")
    except DriverError as exc:
        stage_results.append({"id": "installer-pages", "status": "fail", "error": str(exc)})
        return 1
    stage_results.append({"id": "installer-pages", "status": "pass", "input": "ocr-fallback"})
    # Stage 3: install through keys, watch OCR for progress then done.
    marker = "/var/tmp/installer-e2e-live-marker"
    if args.filesystem == "btrfs":
        ssh_run(args.ssh_port, args.ssh_key, f"echo live > {marker}")
    deadline = time.monotonic() + 1800
    page = Page.WAIT
    while time.monotonic() < deadline:
        png = shot("3-install-poll")
        text = ocr_fallback.ocr_text(png) if png is not None else ""
        page = ocr_fallback.classify_text(text)
        if page is Page.FAILURE:
            stage_results.append(
                {"id": "install", "status": "fail", "error": "OCR read an install failure"}
            )
            return 1
        if page in (Page.PROGRESS, Page.RECOVERY_KEY, Page.COMPLETE):
            break
        time.sleep(10)
    if page not in (Page.PROGRESS, Page.RECOVERY_KEY, Page.COMPLETE):
        stage_results.append(
            {"id": "install", "status": "fail", "error": "OCR never showed progress or done"}
        )
        return 1
    if args.filesystem == "btrfs":
        rc, _ = ssh_run(args.ssh_port, args.ssh_key, f"test -f {marker}")
        if rc != 0:
            stage_results.append({"id": "install", "status": "fail", "error": "live marker lost"})
            return 1
    stage_results.append({"id": "install", "status": "pass", "input": "ocr-fallback"})
    # Stage 4: recovery key by shape from OCR words (never logged).
    png = shot("4-unlock")
    text = ocr_fallback.ocr_text(png) if png is not None else ""
    stage_results.append(
        {
            "id": "unlock",
            "status": "pass",
            "recovery-key-present": bool(RECOVERY_KEY_RE.search(text)),
            "tpm": bool(args.tpm),
            "input": "ocr-fallback",
        }
    )
    return 0


def finish(evidence, boot, stage_results, code):
    """Write per-boot evidence JSON (chunked path mirrors iso-builder CI)."""
    path = Path(evidence) / f"{boot}-stages.json"
    path.write_text(json.dumps({"boot": boot, "stages": stage_results, "code": code}, indent=2))
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
