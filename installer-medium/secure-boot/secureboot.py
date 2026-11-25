#!/usr/bin/env python3
"""Secure Boot policy for the installer medium (tunaOS#4955).

Two modes, chosen per cell and always passed explicitly:

  distro-chain  shim -> distro-signed loader -> distro-signed kernel, Type #1
                entries. No tunaOS key, no enrolment, no UKI we built.
  tunaos-key    shim -> tunaOS-signed systemd-boot -> tunaOS-signed UKI or
                kernel. MokManager plus the public certificate on the ESP, and
                the systemd-boot key bundle under /loader/keys/auto/.

Nothing here signs anything and nothing here takes a private key: signatures
come from CI (ci-sign.sh). Every check that decides trust runs `sbverify
--cert` against a certificate, never a name match.

Why `auto`: systemd-boot enrols by itself only from the directory named
`auto` (systemd src/boot/boot.c:3366, `strcaseeq16(dirent->FileName,
u"auto")`). Any other name is a manual menu entry only.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import shutil
import struct
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
CERTS = HERE / "certs"
MODES = ("distro-chain", "tunaos-key")
ENROLL = ("off", "manual", "if-safe", "force")
# shim's file names per EFI architecture: removable-media name, shim,
# MokManager (shim.h:151) and the default loader (Make.defaults:31).
ARCH = {
    "x64": ("BOOTX64.EFI", "shimx64.efi", "mmx64.efi", "grubx64.efi"),
    "aa64": ("BOOTAA64.EFI", "shimaa64.efi", "mmaa64.efi", "grubaa64.efi"),
}
VENDOR_DIR = "EFI/tunaos"
CERT_NAME = "tunaos-secure-boot.cer"
KEYS_DIR = "loader/keys/auto"
VARIABLES = ("PK", "KEK", "db")
X509_GUID = uuid.UUID("a5c059a1-94e4-4aa7-87b5-ab155c2bf072")
# shim's vendor certificate section. A PE header holds 8 name bytes, so a
# build with no COFF string table shows the short form.
VENDOR_SECTIONS = (".vendor_cert", ".vendor_")


class SecureBootError(Exception):
    """A Secure Boot policy check failed."""


# --- certificates ---------------------------------------------------------


def pem_to_der(pem: str) -> bytes:
    body = [line for line in pem.strip().splitlines() if not line.startswith("-----")]
    return base64.b64decode("".join(body))


def der_to_pem(der: bytes) -> str:
    b64 = base64.b64encode(der).decode()
    lines = [b64[i : i + 64] for i in range(0, len(b64), 64)]
    return "-----BEGIN CERTIFICATE-----\n" + "\n".join(lines) + "\n-----END CERTIFICATE-----\n"


def _tomllib():
    spec = importlib.util.spec_from_file_location(
        "tunaos_config_for_sb", HERE.parents[1] / "scripts/lib/tunaos_config.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.tomllib


def load_manifest(certs_dir: Path = CERTS) -> dict:
    return _tomllib().loads((certs_dir / "manifest.toml").read_text())


def microsoft_certs(certs_dir: Path = CERTS) -> list[dict]:
    """The Microsoft certificates, each checked against its pinned sha256."""
    out = []
    for row in load_manifest(certs_dir)["microsoft"]:
        path = certs_dir / row["file"]
        if not path.is_file():
            raise SecureBootError(f"Microsoft certificate missing: {row['file']}")
        der = pem_to_der(path.read_text())
        if hashlib.sha256(der).hexdigest() != row["sha256"]:
            raise SecureBootError(f"{row['file']}: sha256 differs from manifest.toml")
        out.append({**row, "der": der})
    for variable in ("KEK", "db"):
        if not any(row["variable"] == variable for row in out):
            raise SecureBootError(f"manifest.toml lists no Microsoft {variable} certificate")
    return out


# --- EFI signature lists ---------------------------------------------------


def esl(entries: list[tuple[str, bytes]]) -> bytes:
    """One EFI_SIGNATURE_LIST per (owner GUID, DER certificate), as sbsiglist."""
    out = b""
    for owner, der in entries:
        size = 16 + len(der)
        out += X509_GUID.bytes_le + struct.pack("<III", 28 + size, 0, size)
        out += uuid.UUID(owner).bytes_le + der
    return out


def esl_certs(blob: bytes) -> list[bytes]:
    """The X.509 certificates in a chain of EFI_SIGNATURE_LISTs."""
    certs, pos = [], 0
    while pos + 28 <= len(blob):
        kind = uuid.UUID(bytes_le=blob[pos : pos + 16])
        total, header, size = struct.unpack_from("<III", blob, pos + 16)
        if total < 28 or size < 16 or pos + total > len(blob):
            raise SecureBootError("malformed EFI signature list")
        body = pos + 28 + header
        while body + size <= pos + total:
            if kind == X509_GUID:
                certs.append(blob[body + 16 : body + size])
            body += size
        pos += total
    return certs


def key_bundle_esl(cert_der: bytes, certs_dir: Path = CERTS) -> dict[str, bytes]:
    """PK, KEK and db signature lists, from public certificates only.

    PK holds the tunaOS certificate alone. KEK and db hold it plus every
    Microsoft certificate in the manifest: without those, option ROMs and a
    dual-boot Windows stop after enrolment (man loader.conf, "soft-brick").
    """
    owners = load_manifest(certs_dir)["owners"]
    own = (owners["tunaos"], cert_der)
    lists = {"PK": [own], "KEK": [own], "db": [own]}
    for row in microsoft_certs(certs_dir):
        lists[row["variable"]].append((owners["microsoft"], row["der"]))
    return {name: esl(entries) for name, entries in lists.items()}


def auth_payload(blob: bytes) -> tuple[bool, bytes]:
    """(is signed, signature list) of an EFI_VARIABLE_AUTHENTICATION_2 file.

    Layout: EFI_TIME (16 bytes), then WIN_CERTIFICATE_UEFI_GUID whose first
    field is its length. A length of 24 covers only the header and the type
    GUID: no signature (systemd src/boot/secure-boot.c:151-162).
    """
    if len(blob) < 40:
        raise SecureBootError("authenticated variable file is too short")
    (length,) = struct.unpack_from("<I", blob, 16)
    if length < 24 or 16 + length > len(blob):
        raise SecureBootError("malformed authentication descriptor")
    return length > 24, blob[16 + length :]


# --- PE files ----------------------------------------------------------------


def pe_sections(path: Path) -> dict[str, tuple[int, int]]:
    """Section name -> (file offset, size). Raises when PATH is not a PE file."""
    data = path.read_bytes()
    if data[:2] != b"MZ" or len(data) < 0x40:
        raise SecureBootError(f"{path}: not a PE file")
    (pe,) = struct.unpack_from("<I", data, 0x3C)
    if data[pe : pe + 4] != b"PE\0\0":
        raise SecureBootError(f"{path}: not a PE file")
    count, optional = (
        struct.unpack_from("<H", data, pe + 6)[0],
        struct.unpack_from("<H", data, pe + 20)[0],
    )
    table = pe + 24 + optional
    # A name longer than 8 bytes is "/N": offset N in the COFF string table,
    # which follows the symbol table (18 bytes per symbol).
    symbols, symbol_count = struct.unpack_from("<II", data, pe + 12)
    strings = symbols + 18 * symbol_count
    out = {}
    for i in range(count):
        row = table + 40 * i
        name = data[row : row + 8].rstrip(b"\0").decode("ascii", "replace")
        if name.startswith("/") and name[1:].isdigit() and symbols:
            start = strings + int(name[1:])
            name = data[start : data.index(b"\0", start)].decode("ascii", "replace")
        vsize, _, rsize, offset = struct.unpack_from("<IIII", data, row + 8)
        out[name] = (offset, min(vsize, rsize) if vsize else rsize)
    return out


def is_pe(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(2) == b"MZ"


def is_uki(path: Path) -> bool:
    """A unified kernel image carries the kernel in a `.linux` section."""
    return ".linux" in pe_sections(path)


def is_shim(path: Path) -> bool:
    return any(name in pe_sections(path) for name in VENDOR_SECTIONS)


def shim_vendor_certs(shim: Path) -> list[bytes]:
    """The certificates shim trusts by itself (its `.vendor_cert` section).

    The section is covered by shim's own signature, so a Microsoft-signed
    shim binds this list. Header: four uint32 (authorized size, deauthorized
    size, authorized offset, deauthorized offset), shim.c:30-36.
    """
    sections = pe_sections(shim)
    name = next((name for name in VENDOR_SECTIONS if name in sections), None)
    if name is None:
        raise SecureBootError(f"{shim}: no .vendor_cert section; not a shim")
    offset, size = sections[name]
    data = shim.read_bytes()[offset : offset + size]
    auth_size, _, auth_offset, _ = struct.unpack_from("<IIII", data, 0)
    blob = data[auth_offset : auth_offset + auth_size]
    if not blob:
        return []
    if blob[:1] == b"\x30":
        return [blob]
    return esl_certs(blob)


def signed_by(path: Path, certs: list[bytes]) -> bool:
    """True when `sbverify --cert` accepts PATH for one of CERTS (DER)."""
    if not shutil.which("sbverify"):
        raise SecureBootError("sbverify not found; install sbsigntool")
    with tempfile.TemporaryDirectory() as tmp:
        for index, der in enumerate(certs):
            pem = Path(tmp) / f"{index}.pem"
            pem.write_text(der_to_pem(der))
            done = subprocess.run(
                ["sbverify", "--cert", str(pem), str(path)],
                capture_output=True,
                check=False,
            )
            if done.returncode == 0:
                return True
    return False


def microsoft_uefi_cas(certs_dir: Path = CERTS) -> list[bytes]:
    """The Microsoft CAs that sign third-party loaders such as shim."""
    return [row["der"] for row in microsoft_certs(certs_dir) if "UEFI CA" in row["subject_cn"]]


# --- boot entries --------------------------------------------------------------


def entry_fields(text: str) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {}
    for line in text.splitlines():
        key, _, value = line.strip().partition(" ")
        if key and not key.startswith("#"):
            fields.setdefault(key, []).append(value.strip())
    return fields


def type1_entry(title: str, linux: str, initrds: list[str], options: str, version: str = "") -> str:
    """A Type #1 Boot Loader Specification entry. UKI keys never appear."""
    if linux.lower().endswith(".efi"):
        raise SecureBootError(f"Type #1 entry needs a kernel, not an EFI image: {linux}")
    lines = [f"title {title}"]
    if version:
        lines.append(f"version {version}")
    lines.append(f"linux {linux}")
    lines += [f"initrd {initrd}" for initrd in initrds]
    lines.append(f"options {options}")
    return "\n".join(lines) + "\n"


def _resolve(root: Path, ref: str) -> Path:
    path = (root / ref.lstrip("/")).resolve()
    if root.resolve() not in path.parents:
        raise SecureBootError(f"entry path leaves its root: {ref}")
    return path


def boot_binaries(root: Path) -> tuple[list[Path], list[str]]:
    """Every boot binary under ROOT, and the problems found on the way.

    Binaries: each PE file under EFI/, plus each `linux` or `efi` target of
    an entry in loader/entries/.
    """
    found: dict[Path, None] = {}
    problems = []
    efi = root / "EFI"
    if efi.is_dir():
        for path in sorted(efi.rglob("*")):
            if path.is_file() and is_pe(path):
                found[path.resolve()] = None
    entries = root / "loader/entries"
    if entries.is_dir():
        for conf in sorted(entries.glob("*.conf")):
            fields = entry_fields(conf.read_text())
            for key in ("linux", "efi", "uki"):
                for ref in fields.get(key, []):
                    target = _resolve(root, ref)
                    if not target.is_file():
                        problems.append(f"{conf.name}: {key} target missing: {ref}")
                    else:
                        found[target] = None
    return list(found), problems


# --- distro-chain --------------------------------------------------------------


def check_distro_chain(
    roots: list[Path], arch: str = "x64", certs_dir: Path = CERTS, pin_sha256: tuple[str, ...] = ()
) -> list[str]:
    """Problems that stop a distro-chain medium. Empty means the chain holds.

    ROOTS: the ESP first, then any other tree with entries (GRUB cells keep
    kernels under /boot). The trust root is the Microsoft-signed shim on the
    ESP: the loader and every kernel must verify against a certificate that
    shim carries.
    """
    boot_name, _, _, loader_name = ARCH[arch]
    esp = roots[0]
    problems = []
    shim = esp / "EFI/BOOT" / boot_name
    if not shim.is_file():
        return [f"shim missing: EFI/BOOT/{boot_name}"]
    try:
        vendor = shim_vendor_certs(shim)
    except SecureBootError as error:
        return [str(error)]
    if not signed_by(shim, microsoft_uefi_cas(certs_dir)):
        problems.append(f"EFI/BOOT/{boot_name}: no Microsoft UEFI CA signature")
    if not vendor:
        problems.append(f"EFI/BOOT/{boot_name}: shim carries no vendor certificate")
    digests = {hashlib.sha256(der).hexdigest() for der in vendor}
    if pin_sha256 and not digests & set(pin_sha256):
        problems.append("shim vendor certificate is not the pinned distro certificate")
    # openSUSE builds shim with the loader name grub.efi (sdbootutil copies
    # systemd-boot there); every other shim measured uses grub<arch>.efi.
    if not any(list(esp.glob(f"EFI/*/{name}")) for name in (loader_name, "grub.efi")):
        problems.append(f"no {loader_name} next to shim: shim starts that name only")
    if (esp / "loader/keys").exists():
        problems.append("loader/keys present: distro-chain enrols no key")
    for cert in list(esp.glob("*.cer")) + list(esp.glob("EFI/*/*.cer")):
        problems.append(f"{cert.relative_to(esp)}: distro-chain ships no certificate to enrol")
    for root in roots:
        binaries, missing = boot_binaries(root)
        problems += missing
        for path in binaries:
            name = str(path.relative_to(root.resolve()))
            if signed_by(path, vendor):
                continue
            if signed_by(path, microsoft_uefi_cas(certs_dir)) and is_shim(path):
                continue
            kind = "UKI" if is_uki(path) else "binary"
            problems.append(f"{name}: {kind} is not signed by the distro (shim vendor certificate)")
    return problems


# --- tunaos-key ----------------------------------------------------------------


def loader_conf(text: str, enroll: str) -> str:
    """loader.conf with one `secure-boot-enroll` line."""
    if enroll not in ENROLL:
        raise SecureBootError(f"secure-boot-enroll must be one of {ENROLL}")
    lines = [line for line in text.splitlines() if not line.startswith("secure-boot-enroll")]
    return "\n".join([*lines, f"secure-boot-enroll {enroll}"]) + "\n"


def tunaos_key_plan(arch: str = "x64") -> list[tuple[str, str]]:
    """(source role, ESP path) for every file the tunaos-key mode stages."""
    boot_name, shim_name, mm_name, loader_name = ARCH[arch]
    plan = []
    for directory, first in (("EFI/BOOT", boot_name), (VENDOR_DIR, shim_name)):
        plan += [
            ("shim", f"{directory}/{first}"),
            ("mokmanager", f"{directory}/{mm_name}"),
            ("loader", f"{directory}/{loader_name}"),
        ]
    # ESP root: MokManager's file picker opens there (MokManager.c:2076), so
    # the certificate is the first thing the user sees.
    plan += [("cert", CERT_NAME), ("cert", f"{VENDOR_DIR}/{CERT_NAME}")]
    plan += [(f"{name}.auth", f"{KEYS_DIR}/{name}.auth") for name in VARIABLES]
    return plan


def check_tunaos_key_inputs(
    sources: dict[str, Path], cert_der: bytes, certs_dir: Path = CERTS
) -> list[str]:
    """Problems with the files a tunaos-key medium is about to stage."""
    problems = []
    for role, path in sources.items():
        if not path.is_file():
            problems.append(f"{role}: missing {path}")
    if problems:
        return problems
    shim = sources["shim"]
    if not signed_by(shim, microsoft_uefi_cas(certs_dir)):
        problems.append(f"shim: {shim.name} has no Microsoft UEFI CA signature")
    try:
        vendor = shim_vendor_certs(shim)
    except SecureBootError as error:
        vendor = []
        problems.append(str(error))
    if vendor and not signed_by(sources["mokmanager"], vendor):
        problems.append("mokmanager: not signed by the certificate of this shim")
    if not signed_by(sources["loader"], [cert_der]):
        problems.append("loader: systemd-boot is not signed by the tunaOS certificate")
    if sources["cert"].read_bytes() != cert_der:
        problems.append("cert: the DER file differs from the tunaOS certificate")
    expected = key_bundle_esl(cert_der, certs_dir)
    for name in VARIABLES:
        try:
            signed, payload = auth_payload(sources[f"{name}.auth"].read_bytes())
        except SecureBootError as error:
            problems.append(f"{name}.auth: {error}")
            continue
        if not signed:
            problems.append(f"{name}.auth: no signature; CI must sign it (ci-sign.sh auth)")
        if payload != expected[name]:
            problems.append(
                f"{name}.auth: payload differs from the public key bundle (Microsoft certificates?)"
            )
    return problems


def check_tunaos_key_esp(esp: Path, cert_der: bytes) -> list[str]:
    """Problems with the boot binaries already on a tunaos-key ESP."""
    binaries, problems = boot_binaries(esp)
    names = {name.lower() for row in ARCH.values() for name in row[:3]}
    for path in binaries:
        if path.name.lower() in names:
            continue
        if not signed_by(path, [cert_der]):
            kind = "UKI" if is_uki(path) else "binary"
            problems.append(
                f"{path.relative_to(esp.resolve())}: {kind} is not signed by the tunaOS certificate"
            )
    return problems


def stage_tunaos_key(
    esp: Path,
    sources: dict[str, Path],
    cert_der: bytes,
    arch: str = "x64",
    enroll: str = "if-safe",
    dry_run: bool = False,
    certs_dir: Path = CERTS,
    log=print,
) -> None:
    """Verify, then copy the tunaos-key files onto the ESP."""
    problems = check_tunaos_key_inputs(sources, cert_der, certs_dir)
    problems += check_tunaos_key_esp(esp, cert_der)
    if problems:
        raise SecureBootError("\n".join(problems))
    for role, target in tunaos_key_plan(arch):
        log(f"secure-boot: copy {sources[role]} -> {target}")
        if not dry_run:
            (esp / target).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(sources[role], esp / target)
    conf = esp / "loader/loader.conf"
    log(f"secure-boot: loader/loader.conf secure-boot-enroll {enroll}")
    if not dry_run:
        conf.parent.mkdir(parents=True, exist_ok=True)
        conf.write_text(loader_conf(conf.read_text() if conf.is_file() else "", enroll))


# --- command line ----------------------------------------------------------------


def _cert_der(path: Path) -> bytes:
    data = path.read_bytes()
    return pem_to_der(data.decode()) if data.lstrip().startswith(b"-----BEGIN") else data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--certs-dir", type=Path, default=CERTS, help="public certificates and manifest.toml"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    cmd = sub.add_parser("plan", help="print what a mode puts on the ESP; needs no input files")
    cmd.add_argument("mode", choices=MODES)
    cmd.add_argument("--arch", choices=sorted(ARCH), default="x64")

    cmd = sub.add_parser("build-esl", help="write PK.esl, KEK.esl, db.esl from public certificates")
    cmd.add_argument("--cert", type=Path)
    cmd.add_argument("--out", type=Path, required=True)

    cmd = sub.add_parser("check", help="distro-chain: verify every boot binary against shim")
    cmd.add_argument("--esp", type=Path, required=True)
    cmd.add_argument("--boot", type=Path, action="append", default=[])
    cmd.add_argument("--arch", choices=sorted(ARCH), default="x64")
    cmd.add_argument("--pin-sha256", action="append", default=[])

    cmd = sub.add_parser("entry", help="distro-chain: write a Type #1 entry for a verified kernel")
    cmd.add_argument("--esp", type=Path, required=True)
    cmd.add_argument("--root", type=Path, help="tree that holds the kernel (default: the ESP)")
    cmd.add_argument("--arch", choices=sorted(ARCH), default="x64")
    cmd.add_argument("--name", required=True)
    cmd.add_argument("--title", required=True)
    cmd.add_argument("--linux", required=True)
    cmd.add_argument("--initrd", action="append", default=[])
    cmd.add_argument("--options", required=True)
    cmd.add_argument("--dry-run", action="store_true")

    cmd = sub.add_parser(
        "stage", help="tunaos-key: verify and stage shim, MokManager, cert, key bundle"
    )
    cmd.add_argument("--esp", type=Path, required=True)
    cmd.add_argument("--shim-dir", type=Path, required=True)
    cmd.add_argument("--loader", type=Path, required=True)
    cmd.add_argument("--auth-dir", type=Path, required=True)
    cmd.add_argument("--cert", type=Path)
    cmd.add_argument("--arch", choices=sorted(ARCH), default="x64")
    cmd.add_argument("--enroll", choices=ENROLL, default="if-safe")
    cmd.add_argument("--allow-force", action="store_true")
    cmd.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)
    certs = args.certs_dir
    if getattr(args, "cert", "") is None:
        args.cert = certs / "tunaos-sb.cer"
    try:
        if args.command == "plan":
            if args.mode == "distro-chain":
                print("secure-boot: distro-chain stages nothing; it verifies the distro files")
                print("secure-boot: no certificate, no loader/keys, Type #1 entries only")
            else:
                for role, target in tunaos_key_plan(args.arch):
                    print(f"secure-boot: copy <{role}> -> {target}")
                print("secure-boot: loader/loader.conf secure-boot-enroll if-safe")
        elif args.command == "build-esl":
            args.out.mkdir(parents=True, exist_ok=True)
            for name, blob in key_bundle_esl(_cert_der(args.cert), certs).items():
                (args.out / f"{name}.esl").write_bytes(blob)
                print(
                    f"secure-boot: wrote {args.out / (name + '.esl')} ({len(esl_certs(blob))} certificates)"
                )
        elif args.command == "check":
            problems = check_distro_chain(
                [args.esp, *args.boot], args.arch, certs, tuple(args.pin_sha256)
            )
            if problems:
                raise SecureBootError("\n".join(problems))
            print("secure-boot: distro chain holds")
        elif args.command == "entry":
            root = args.root or args.esp
            shim = args.esp / "EFI/BOOT" / ARCH[args.arch][0]
            kernel = _resolve(root, args.linux)
            if not kernel.is_file() or not signed_by(kernel, shim_vendor_certs(shim)):
                raise SecureBootError(
                    f"{args.linux}: kernel is not signed by the distro (shim vendor certificate)"
                )
            if is_uki(kernel):
                raise SecureBootError(f"{args.linux}: distro-chain takes no UKI")
            text = type1_entry(args.title, args.linux, args.initrd, args.options)
            target = root / "loader/entries" / f"{args.name}.conf"
            print(f"secure-boot: write {target}")
            if not args.dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text)
        elif args.command == "stage":
            if args.enroll == "force" and not args.allow_force:
                raise SecureBootError(
                    "secure-boot-enroll force needs --allow-force (see SECURE-BOOT.md)"
                )
            _, shim_name, mm_name, _ = ARCH[args.arch]
            sources = {
                "shim": args.shim_dir / shim_name,
                "mokmanager": args.shim_dir / mm_name,
                "loader": args.loader,
                "cert": args.cert,
                **{f"{name}.auth": args.auth_dir / f"{name}.auth" for name in VARIABLES},
            }
            cert_der = _cert_der(args.cert)
            if not args.cert.read_bytes() == cert_der:
                raise SecureBootError("--cert must be the DER file: MokManager reads DER only")
            stage_tunaos_key(
                args.esp, sources, cert_der, args.arch, args.enroll, args.dry_run, certs
            )
    except SecureBootError as error:
        for line in str(error).splitlines():
            print(f"secure-boot: REFUSED: {line}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
