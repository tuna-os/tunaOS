#!/usr/bin/env python3
"""Exercise pinned Fedora loader bytes in a disposable ARM64 emulator only."""
import argparse
import hashlib
import io
import json
import os
import re
from pathlib import Path, PurePosixPath
import platform
import stat
import struct
import subprocess
import urllib.request
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/x13s-handoff"
MAX_CPIO = 160 * 1024 * 1024


def run(args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def download(url, target, expected, size=None):
    # All URLs and identities come from the reviewed fixture pins, not dispatch input.
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read((size or 1024 * 1024) + 1)
    if (size is not None and len(data) != size) or digest(data) != expected:
        raise ValueError("download identity mismatch")
    target.write_bytes(data)


def export_approved_key(home, fingerprint):
    # RPM 4.x import requires ASCII armor, unlike GnuPG's default binary export.
    data = run(["gpg", "--homedir", home, "--batch", "--armor", "--export", fingerprint],
               capture_output=True).stdout
    if not data.startswith(b"-----BEGIN PGP PUBLIC KEY BLOCK-----") or b"-----END PGP PUBLIC KEY BLOCK-----" not in data:
        raise ValueError("approved key export is not armored")
    return data


def signature_receipt(output, returncode, fingerprint):
    """Fail closed unless rpmkeys -Kv explicitly verified the approved RSA signature.

    Supported receipt: Ubuntu runner RPM 4.x, LC_ALL=C. Digest-only success,
    unknown output versions, missing keys and any other signer are rejected.
    """
    pattern = r"^\s*Header V[34] RSA/SHA256 Signature, key ID ([0-9a-fA-F]{8,40}): OK\s*$"
    signatures = [match.group(1).lower() for line in output.splitlines()
                  if (match := re.fullmatch(pattern, line))]
    if returncode != 0 or len(signatures) != 1 or signatures[0] not in (
            fingerprint[-8:].lower(), fingerprint[-16:].lower(), fingerprint.lower()):
        raise ValueError("approved RPM signature was not explicitly verified")
    return {"signer_fingerprint": fingerprint, "verified_header_signature": True}


def member_from_newc(data, wanted):
    """Select one inline regular member; do not resolve links or extract paths."""
    if len(data) > MAX_CPIO:
        raise ValueError("archive exceeds bound")
    stream = io.BytesIO(data)
    selected = None
    seen = set()
    while True:
        header = stream.read(110)
        if len(header) != 110 or header[:6] != b"070701":
            raise ValueError("invalid newc header")
        fields = [int(header[6 + i * 8:14 + i * 8], 16) for i in range(13)]
        mode, size, namesize = fields[1], fields[6], fields[11]
        if not 1 <= namesize <= 4096 or size > MAX_CPIO:
            raise ValueError("invalid archive span")
        rawname = stream.read(namesize)
        if len(rawname) != namesize or rawname[-1:] != b"\0":
            raise ValueError("invalid archive name")
        name = rawname[:-1].decode("utf-8")
        stream.read((-110 - namesize) % 4)
        if name == "TRAILER!!!":
            break
        canonical = name[2:] if name.startswith("./") else name
        path = PurePosixPath(canonical)
        if path.is_absolute() or ".." in path.parts or canonical in seen:
            raise ValueError("unsafe or duplicate archive name")
        seen.add(canonical)
        content = stream.read(size)
        if len(content) != size:
            raise ValueError("truncated archive member")
        stream.read((-size) % 4)
        if canonical == wanted:
            if not stat.S_ISREG(mode) or not size:
                raise ValueError("selected member is not an inline regular payload")
            selected = content
    if selected is None:
        raise ValueError("required payload is missing")
    return selected


def check_arm64(data):
    if data[:2] != b"MZ" or len(data) < 64:
        raise ValueError("missing PE header")
    offset = struct.unpack_from("<I", data, 60)[0]
    if offset > len(data) - 6 or data[offset:offset + 4] != b"PE\0\0":
        raise ValueError("invalid PE offset")
    if struct.unpack_from("<H", data, offset + 4)[0] != 0xAA64:
        raise ValueError("wrong EFI architecture")


def check_loader(data):
    spec = importlib.util.spec_from_file_location("x13s_pe", ROOT / "scripts/x13s_pe_inventory.py")
    observer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(observer)
    result = observer.inspect_pe(data)
    sections = result["sections"]
    forbidden = {".osrel", ".initrd", ".profile", ".pcrsig", ".pcrpkey", ".ucode", ".cmdline"}
    if any(s["name"] in forbidden for s in sections):
        raise ValueError("loader could compete with external initrd/arguments")
    kernels = [s for s in sections if s["name"] == ".linux"]
    releases = [s.get("kernel_release") for s in sections if s["name"] == ".uname"]
    if len(kernels) != 1 or kernels[0]["initialized_sha256"] != "f838299696f91f0400de9e6b796d3d862f8e9eb2899101a913314150ce9550d6":
        raise ValueError("loader kernel does not match the reviewed stock kernel bytes")
    if releases != ["7.2.11-200.fc44.aarch64"]:
        raise ValueError("loader kernel release mismatch")
    return result


def newc(entries):
    output = bytearray()
    for number, (name, mode, data) in enumerate(entries + [("TRAILER!!!", 0, b"")], 1):
        encoded = name.encode() + b"\0"
        fields = [number, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(encoded), 0]
        if name == "dev/console":
            fields[9], fields[10] = 5, 1
        header = b"070701" + b"".join(f"{v:08x}".encode() for v in fields)
        output.extend(header + encoded)
        output.extend(bytes((-len(output)) % 4))
        output.extend(data)
        output.extend(bytes((-len(output)) % 4))
    return bytes(output)


def grub_config(case):
    nonce = "external-initrd-v1" if case != "wrong-argument" else "wrong"
    initrd = "initrd /fixture/initrd\n" if case != "missing-initrd" else ""
    return ("set timeout=0\nserial --unit=0 --speed=115200\n"
            "terminal_output console serial\n"
            f"linux /fixture/loader.efi console=ttyAMA0 rdinit=/init panic=-1 x13s.fixture={nonce}\n"
            + initrd + "boot\n")


def assert_result(case, log, returncode):
    if returncode != 0:
        raise ValueError("fixture emulator exited nonzero")
    passed = "X13S_FIXTURE_PASS" in log
    if case == "positive":
        if not passed or returncode != 0 or "X13S_FIXTURE_UNAME=7.2.11-200.fc44.aarch64" not in log:
            raise ValueError("selected loader did not complete external-initrd handoff")
    elif case == "missing-initrd" and ("Kernel panic" not in log or not any(x in log for x in ("No working init found", "Unable to mount root fs"))):
        raise ValueError("missing-initrd control did not reach the selected kernel")
    elif passed:
        raise ValueError("negative control unexpectedly passed")
    elif case == "wrong-argument" and "X13S_FIXTURE_FAIL" not in log:
        raise ValueError("argument control did not execute external PID1")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--firmware-code", type=Path, required=True)
    parser.add_argument("--firmware-vars", type=Path, required=True)
    args = parser.parse_args()
    if platform.machine() not in ("aarch64", "arm64"):
        raise SystemExit("fixture requires native ARM64 compiler/runner")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    pins = json.loads((FIXTURE / "pins.json").read_text())
    key = out / "fedora.gpg"
    download(pins["key_url"], key, pins["key_sha256"])
    home = out / "gnupg"
    home.mkdir(mode=0o700)
    shown = run(["gpg", "--homedir", home, "--batch", "--with-colons", "--show-keys", key], capture_output=True, text=True).stdout
    if pins["fingerprint"] not in [line.split(":")[9] for line in shown.splitlines() if line.startswith("fpr:")]:
        raise ValueError("unexpected Fedora key fingerprint")
    db = out / "rpmdb"
    db.mkdir()
    run(["gpg", "--homedir", home, "--batch", "--import", key], capture_output=True)
    approved_key = out / "approved-fedora44.gpg"
    approved_key.write_bytes(export_approved_key(home, pins["fingerprint"]))
    run(["rpm", "--dbpath", db, "--import", approved_key])
    payloads = {}
    for pin in pins["packages"]:
        rpm = out / (pin["name"] + ".rpm")
        download(pin["url"], rpm, pin["rpm_sha256"], pin["rpm_size"])
        verification = subprocess.run(["rpmkeys", "--dbpath", str(db), "--checksig", "--verbose", str(rpm)], capture_output=True, text=True, env={**os.environ, "LC_ALL": "C"})
        (out / (pin["name"] + ".rpmkeys.txt")).write_text(verification.stdout + verification.stderr)
        signature_receipt(verification.stdout, verification.returncode, pins["fingerprint"])
        if pin["name"] == "kernel-uki-dtbloader":
            unsigned = out / "unsigned-control.rpm"
            unsigned.write_bytes(rpm.read_bytes())
            run(["rpmsign", "--delsign", unsigned], capture_output=True)
            control = subprocess.run(["rpmkeys", "--dbpath", str(db), "--checksig", "--verbose", str(unsigned)],
                                     capture_output=True, text=True, env={**os.environ, "LC_ALL": "C"})
            (out / "unsigned-control.rpmkeys.txt").write_text(control.stdout + control.stderr)
            try:
                signature_receipt(control.stdout, control.returncode, pins["fingerprint"])
            except ValueError:
                pass
            else:
                raise ValueError("unsigned RPM control was accepted")
            unsigned.unlink()

        # A file keeps decompression off the Python heap; enforce a process file bound.
        import resource
        def limit():
            resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_CPIO, MAX_CPIO))
        archive = out / "payload.cpio"
        with archive.open("wb") as stream:
            run(["rpm2cpio", rpm], stdout=stream, preexec_fn=limit)
        data = member_from_newc(archive.read_bytes(), pin["member"])
        archive.unlink()
        if len(data) != pin["efi_size"] or digest(data) != pin["efi_sha256"]:
            raise ValueError("EFI payload identity mismatch")
        check_arm64(data)
        payloads[pin["name"]] = data
    observation = check_loader(payloads["kernel-uki-dtbloader"])
    (out / "loader-observation.json").write_text(json.dumps(observation, indent=2))
    init = out / "init"
    run(["cc", "-static", "-Os", "-Wall", "-Wextra", "-Werror", FIXTURE / "init.c", "-o", init])
    executable = init.read_bytes()
    if executable[:4] != b"\x7fELF" or struct.unpack_from("<H", executable, 18)[0] != 183:
        raise ValueError("sentinel is not ARM64 ELF")
    initrd = out / "initrd"
    initrd.write_bytes(newc([("proc", stat.S_IFDIR | 0o555, b""), ("sys", stat.S_IFDIR | 0o555, b""), ("dev", stat.S_IFDIR | 0o555, b""), ("dev/console", stat.S_IFCHR | 0o600, b""), ("init", stat.S_IFREG | 0o755, executable)]))
    report = {"format": "x13s-emulator-handoff-v1", "hardware_boot": "not_tested", "secure_boot": "not_tested",
              "pins_sha256": digest((FIXTURE / "pins.json").read_bytes()), "initrd_sha256": digest(initrd.read_bytes()),
              "firmware_code_sha256": digest(args.firmware_code.read_bytes()),
              "firmware_vars_initial_sha256": digest(args.firmware_vars.read_bytes()),
              "sentinel_source_sha256": digest((FIXTURE / "init.c").read_bytes()),
              "sentinel_sha256": digest(executable), "payloads": pins["packages"], "cases": []}
    for case in ("positive", "missing-initrd", "wrong-argument"):
        folder = out / case
        folder.mkdir()
        esp = folder / "esp.img"
        with esp.open("wb") as stream:
            stream.truncate(64 * 1024 * 1024)
        run(["mformat", "-i", esp, "-F", "::"])
        for path in ("EFI", "EFI/BOOT", "EFI/fedora", "fixture"):
            run(["mmd", "-i", esp, "::/" + path])
        files = {"EFI/BOOT/BOOTAA64.EFI": payloads["shim-aa64"],
                 "EFI/BOOT/grubaa64.efi": payloads["grub2-efi-aa64"],
                 "EFI/fedora/grubaa64.efi": payloads["grub2-efi-aa64"],
                 "fixture/loader.efi": payloads["kernel-uki-dtbloader"],
                 "fixture/initrd": initrd.read_bytes(),
                 "EFI/BOOT/grub.cfg": grub_config(case).encode(),
                 "EFI/fedora/grub.cfg": grub_config(case).encode()}
        for index, (destination, data) in enumerate(files.items()):
            staged = folder / f"stage-{index}"
            staged.write_bytes(data)
            run(["mcopy", "-i", esp, staged, "::/" + destination])
            observed = run(["mtype", "-i", esp, "::/" + destination], capture_output=True).stdout
            if observed != data:
                raise ValueError("staged FAT bytes changed")
            staged.unlink()
        variables = folder / "vars.fd"
        variables.write_bytes(args.firmware_vars.read_bytes())
        command = ["qemu-system-aarch64", "-machine", "virt", "-accel", "tcg", "-cpu", "cortex-a72", "-m", "1024",
                   "-drive", f"if=pflash,format=raw,readonly=on,file={args.firmware_code.resolve()}",
                   "-drive", f"if=pflash,format=raw,file={variables}",
                   "-drive", f"if=virtio,format=raw,readonly=on,file={esp}",
                   "-nographic", "-monitor", "none", "-no-reboot", "-nic", "none"]
        (folder / "argv.json").write_text(json.dumps(command, indent=2))
        def serial_limit():
            resource.setrlimit(resource.RLIMIT_FSIZE, (4 * 1024 * 1024, 4 * 1024 * 1024))
        serial = folder / "serial.log"
        with serial.open("wb") as stream:
            try:
                result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT,
                                        timeout=180, preexec_fn=serial_limit)
                code = result.returncode
            except subprocess.TimeoutExpired:
                code = 124
        output = serial.read_bytes()
        if len(output) >= 4 * 1024 * 1024:
            raise ValueError("serial output reached receipt bound")
        log = output.decode(errors="replace")
        (folder / "serial.log").write_text(log)
        assert_result(case, log, code)
        report["cases"].append({"case": case, "exit_code": code, "serial_sha256": digest(output), "esp_sha256": digest(esp.read_bytes())})
        (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        esp.unlink()
        variables.unlink()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
