#!/usr/bin/env python3
"""Verify actual Grouper/GNOME kernel, recipe and initramfs bytes for #3474.

Run from the exact generated source checkout, inside the inspected image (root
/), or against an owned unpacked image root. This is static artifact evidence:
it never boots, installs, updates or recovers an operating system.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import selectors
import signal
import struct
import time
from pathlib import Path
import re
import subprocess
import sys
import os
import stat
import tempfile
import resource

ROOT = Path(__file__).resolve().parents[1]
BACKEND = {"bootloader": "systemd", "composeFsBackend": "true", "filesystem": "ext4"}


class InvalidImage(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise InvalidImage(code)


def owned(root, relative):
    path = root / relative
    require(path.resolve().is_relative_to(root), "image-path-escapes-root")
    return path


def digest(path):
    require(path.is_file() and path.stat().st_size > 0, "missing-image-file")
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


def command(argv, code, *, env=None, timeout=120, limit=1024 * 1024):
    # Match the package harness's new-session/killpg convention. Drain both
    # pipes concurrently and refuse oversized output during collection.
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               stdin=subprocess.DEVNULL, env=env, start_new_session=True)
    captured = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            for name, pipe in (("stdout", process.stdout), ("stderr", process.stderr)):
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, name)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                require(remaining > 0, "inspection-timeout")
                for key, _events in selector.select(min(remaining, 0.1)):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    target = captured[key.data]
                    require(len(target) + len(chunk) <= limit, "inspection-output-limit")
                    target.extend(chunk)
            require(process.wait(timeout=max(0.001, deadline - time.monotonic())) == 0, code)
        return bytes(captured["stdout"])
    finally:
        # Descendants can keep pipes open after their parent exits; the shared
        # deadline and group kill cover that case as well as a live parent.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        process.stdout.close()
        process.stderr.close()


def kernel_identity(path, expected_release):
    with path.open("rb") as stream:
        header = stream.read(65536)
    require(header[0x1FE:0x200] == b"\x55\xaa" and header[0x202:0x206] == b"HdrS",
            "not-an-x86-linux-kernel")
    require(len(header) >= 0x238, "short-kernel-boot-header")
    protocol = struct.unpack_from("<H", header, 0x206)[0]
    require(protocol >= 0x20C and struct.unpack_from("<H", header, 0x236)[0] & 1,
            "kernel-binary-is-not-amd64")
    offset = 0x200 + struct.unpack_from("<H", header, 0x20E)[0]
    require(0x238 <= offset < len(header), "missing-kernel-release")
    release = header[offset:].split(b"\0", 1)[0].split(b" ", 1)[0]
    require(release == expected_release.encode("ascii"), "kernel-binary-release-mismatch")


def confine_probe_inputs(root):
    def subtree(relative):
        pending, seen = [owned(root, relative)], set()
        while pending:
            directory = pending.pop().resolve()
            if directory in seen or not directory.is_dir():
                continue
            seen.add(directory)
            for entry in directory.iterdir():
                confined = owned(root, str(entry.relative_to(root)))
                if confined.is_dir():
                    pending.append(confined)

    for relative in ("etc/plymouth", "usr/share/plymouth/themes", "usr/lib/ostree",
                     "usr/lib/bootupd", "usr/lib/efi", "usr/lib/systemd/boot/efi"):
        subtree(relative)
    usr = owned(root, "usr")
    for library in usr.glob("lib*"):
        library = owned(root, str(library.relative_to(root)))
        if not library.is_dir():
            continue
        subtree(str((library / "plymouth").relative_to(root)))
        for architecture in library.iterdir():
            architecture = owned(root, str(architecture.relative_to(root)))
            if architecture.is_dir():
                subtree(str((architecture / "plymouth").relative_to(root)))


def decoded_artifacts(initramfs, destination, version, drivers):
    from lib.apt_initramfs import unpack

    records = unpack(initramfs, destination)
    module_lists = [name for name in ("usr/lib/dracut/modules.txt", "lib/dracut/modules.txt")
                    if records.get(name) == stat.S_IFREG]
    require(len(module_lists) == 1, "missing-dracut-module-list")
    module_file = owned(destination, module_lists[0])
    require(module_file.stat().st_size <= 65536, "oversized-dracut-module-list")
    modules = module_file.read_text(encoding="utf-8").splitlines()
    observed = {}
    for driver in drivers:
        names = {driver + suffix for suffix in (".ko", ".ko.xz", ".ko.zst", ".ko.gz")}
        observed[driver] = any(
            kind == stat.S_IFREG and Path(member).name in names
            and (member.startswith(f"usr/lib/modules/{version}/kernel/")
                 or member.startswith(f"lib/modules/{version}/kernel/"))
            and owned(destination, member).is_file() and owned(destination, member).stat().st_size > 0
            for member, kind in records.items())
    return {"bootcModule": "bootc" in modules, "drivers": observed}

def verify(root):
    deadline = time.monotonic() + 120
    root = root.resolve(strict=True)
    modules = owned(root, "usr/lib/modules")
    kernels = [path for path in modules.iterdir() if path.is_dir() and (path / "vmlinuz").is_file()]
    require(len(kernels) == 1, "expected-one-staged-kernel")
    kernel = kernels[0]
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,127}", kernel.name), "invalid-kernel-version")
    kernel = owned(root, "usr/lib/modules/" + kernel.name)
    vmlinuz, config, initramfs = [owned(root, str((kernel / name).relative_to(root)))
                                for name in ("vmlinuz", "config", "initramfs.img")]
    hashes = {"vmlinuzSha256": digest(vmlinuz), "configSha256": digest(config),
              "initramfsSha256": digest(initramfs)}
    require(config.stat().st_size <= 4 * 1024**2, "oversized-kernel-config")
    symbols = {}
    for line in config.read_text(encoding="utf-8").splitlines():
        if line.startswith("CONFIG_") and "=" in line:
            name, value = line.split("=", 1)
            require(name not in symbols, "duplicate-kernel-symbol")
            symbols[name] = value
    for name in ("CONFIG_X86_64", "CONFIG_EROFS_FS_BACKED_BY_FILE", "CONFIG_FS_VERITY"):
        require(symbols.get(name) == "y", "kernel-lacks-" + name)
    drivers = {"CONFIG_EROFS_FS": "erofs", "CONFIG_OVERLAY_FS": "overlay", "CONFIG_EXT4_FS": "ext4"}
    for name in drivers:
        require(symbols.get(name) in {"y", "m"}, "kernel-lacks-" + name)
    kernel_identity(vmlinuz, kernel.name)
    efi = owned(root, "usr/lib/systemd/boot/efi/systemd-bootx64.efi")
    digest(efi)
    confine_probe_inputs(root)
    probe = ROOT / "live-iso/common/src/installer-recipe-backend.sh"
    raw = command(["bash", str(probe), str(root)], "recipe-probe-failed",
                  timeout=max(0.001, deadline - time.monotonic()))
    observed = dict(line.split("=", 1) for line in raw.decode("utf-8").splitlines())
    require(observed == BACKEND, "wrong-apt-install-layout")
    checker = ROOT / "build_scripts/checks/verify-plymouth-initramfs.sh"
    modular = [driver for symbol, driver in drivers.items() if symbols[symbol] == "m"]
    with tempfile.TemporaryDirectory(prefix="apt-initrd-proof-") as temporary:
        decoded = Path(temporary) / "tree"
        decoded.mkdir()
        raw = command([sys.executable, str(Path(__file__).resolve()), "--decode-initramfs",
                       str(initramfs), "--destination", str(decoded), "--kernel-version", kernel.name,
                       "--drivers", *modular], "initramfs-decoding-failed",
                      timeout=max(0.001, deadline - time.monotonic()))
        evidence = json.loads(raw)
        require(evidence.get("bootcModule") is True, "initramfs-lacks-bootc-module")
        for driver in modular:
            require(evidence.get("drivers", {}).get(driver) is True, "initramfs-lacks-" + driver)
        command(["bash", str(checker), "--tree", "grouper", str(decoded)], "initramfs-branding-failed",
                env={**os.environ, "PLYMOUTH_SYSROOT": str(root)},
                timeout=max(0.001, deadline - time.monotonic()))
    return {"schemaVersion": 1, "purpose": "apt-image-static-proof-only", "family": "apt",
            "variant": "grouper", "desktop": "gnome", "platform": "linux/amd64",
            "backend": {"bootloader": "systemd", "composeFsBackend": True, "filesystem": "ext4"},
            "kernel": {"version": kernel.name, **hashes},
            "branding": {"status": "passed", "checkerSha256": digest(checker)},
            "runtimeAcceptance": "not-run"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--root", type=Path)
    modes.add_argument("--decode-initramfs", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--destination", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--kernel-version", help=argparse.SUPPRESS)
    parser.add_argument("--drivers", nargs="*", choices=("erofs", "overlay", "ext4"), default=[],
                        help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.decode_initramfs is not None:
            require(args.destination is not None and args.kernel_version is not None,
                    "missing-internal-decoder-input")
            # Bound native decoder allocations before loading libarchive/zstd;
            # never raise an inherited limit. Parent supervises the wall clock.
            inherited = resource.getrlimit(resource.RLIMIT_AS)
            cap = min([2 * 1024**3] + [value for value in inherited if value != resource.RLIM_INFINITY])
            resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
            require(args.decode_initramfs.stat().st_size <= 1024**3, "oversized-initramfs-input")
            result = decoded_artifacts(args.decode_initramfs, args.destination, args.kernel_version, args.drivers)
        else:
            result = verify(args.root)
        print(json.dumps(result, sort_keys=True))
    except InvalidImage as exc:
        print("ERROR: APT image proof: " + str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError, subprocess.SubprocessError):
        print("ERROR: APT image proof: unreadable-artifact-or-missing-tool", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
