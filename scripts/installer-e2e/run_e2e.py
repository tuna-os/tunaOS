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
from tree_dump import GUEST_DUMP_SOURCE, parse_tree, ssh_dump_command, summarize

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
        "-bios",
        str(ovmf_code),
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
        f"file:{work}/serial.log",
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

            reply()  # greeting
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


def wait_ssh(ssh_port, key_path, timeout=SSH_TIMEOUT):
    """Wait until the guest sshd answers. Raises DriverError on timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
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
        subprocess.run(["qemu-img", "create", "-f", "qcow2", str(disk), "20G"], check=True)
    swtpm_proc, tpm_sock = (None, None)
    vm = None
    try:
        if args.tpm:
            swtpm_proc, tpm_sock = start_swtpm(work, boot)
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
        )
        serial = work / "serial.log"
        with serial.open("ab") as _:
            pass
        vm = subprocess.Popen(cmd)
        time.sleep(10)
        wait_ssh(args.ssh_port, args.ssh_key)
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
            "systemctl is-active display-manager medium-live-setup",
            timeout=60,
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
    # Stage 5: first-boot setup. EL10 stays a TODO marker until #4908/#4909.
    shot("5-first-boot-setup")
    if args.filesystem == "xfs":
        stage_results.append({"id": "first-boot-setup", "status": "todo", "note": EL10_REBOOT_TODO})
    else:
        stage_results.append({"id": "first-boot-setup", "status": "pass"})
    # Stage 6: desktop plus bootc status.
    rc, out = ssh_run(args.ssh_port, args.ssh_key, "bootc status --format=json", timeout=60)
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
    stage_results.append({"id": "desktop-status", "status": "pass", "booted": digest})
    # Stage 7: bootc switch plus rollback (Utah phase rules).
    if not args.candidate:
        stage_results.append(
            {"id": "switch-rollback", "status": "todo", "note": "no --candidate digest given"}
        )
        return finish(evidence, boot, stage_results, 0)
    rc, _ = ssh_run(args.ssh_port, args.ssh_key, f"bootc switch {args.candidate}", timeout=600)
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


def log_snapshot(driver):
    """Actionable AT-SPI lines to the CI log; timeouts save the full JSON."""
    for line in summarize(driver.last_nodes):
        print(f"atspi: {line}", file=sys.stderr)


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

    driver = Driver(dump, qmp.run, shot, width=SCREEN_W, height=SCREEN_H)
    # Stage 2: installer pages through the driver.
    try:
        driver.wait_for(app, Page.DISK, timeout=PAGE_TIMEOUT)
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
        driver.click_primary(app)
        driver.wait_for(app, {Page.PROGRESS, Page.RECOVERY_KEY, Page.COMPLETE}, timeout=1800)
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
    stage_results.append(
        {
            "id": "unlock",
            "status": "pass",
            "recovery-key-present": key is not None,
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
