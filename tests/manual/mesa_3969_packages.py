#!/usr/bin/env python3
"""Fixed Mesa pair authoring and immutable RPM identity checks for the held lab."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import urllib.request

from mesa_3969 import (
    INPUTS,
    LabError,
    authorize_local_build,
    check_local_build_root,
    cleanup_local_build_root,
    create_local_build_root,
    normalize_image_id,
    read_json,
    sanitize_text,
    sha256_file,
    validate_local_authority,
    validate_local_manifest,
    validate_manifest,
    validate_package_record,
    validate_producer,
    verify_transfer_files,
    write_json,
)

IDENTITY = ("name", "epoch", "version", "release", "arch", "source_rpm")
INVENTORY = (*IDENTITY, "header_sha256")
QUERY = "%{NAME}\t%{EPOCH}\t%{VERSION}\t%{RELEASE}\t%{ARCH}\t%{SOURCERPM}\t%{SHA256HEADER}\n"
POLICY = "/usr/lib/systemd/user-environment-generators/60-tunaos-software-gl"
LAB_IDENTITY = Path("/usr/local/libexec/mesa-3969/identity.json")
PATCH_NAME = "c9b298660774291478323c5ef148362d9b136c3b.patch"
LOADER_PATCH_NAME = "mesa-3969-device-swrast-loader.patch"
PATCHES = [
    (11, "0001-device-select-add-a-layer-setting-to-disable-device-.patch"),
    (12, "0002-zink-use-device-select-layer-settings-to-disable-dev.patch"),
    (13, "0001-gallivm-handle-u16-correct-on-const-loads.patch"),
    (14, "0001-Revert-dri-fix-__DRI_IMAGE_FORMAT-to-PIPE_FORMAT-map.patch"),
    (1001, "cd129dbf8af2d16b1243f2ce287ff69c6a5dc557.patch"),
]
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def run(args, *, cwd=None, env=None, output=None):
    """No shell, retries, or success-shaped replacement for command failures."""
    result = subprocess.run(
        [str(arg) for arg in args], cwd=cwd, env=env, check=False,
        stdout=output if output is not None else subprocess.PIPE,
        stderr=subprocess.STDOUT if output is not None else subprocess.PIPE, text=True,
    )
    if result.returncode:
        detail = ((result.stdout or "") + (result.stderr or ""))[-16384:]
        if not detail and output is not None and getattr(output, "name", None):
            # Streamed output was redirected to the build log; surface its tail
            # instead of an empty message so the failing step is visible.
            output.flush()
            with open(output.name, "rb") as stream:
                stream.seek(0, os.SEEK_END)
                stream.seek(max(0, stream.tell() - 4096))
                detail = "log tail: " + stream.read().decode("utf-8", "replace")
        raise LabError(f"command {args[0]} failed ({result.returncode}): {sanitize_text(detail)}")
    return result.stdout if output is None else ""


def _records(text):
    records = []
    for line in text.splitlines():
        values = line.split("\t")
        if len(values) != len(INVENTORY):
            raise LabError("malformed RPM query record")
        record = dict(zip(INVENTORY, values, strict=True))
        epoch = record["epoch"]
        if epoch == "(none)":
            epoch = "0"  # RPM's absent Epoch has numeric value zero; query every file.
        if not re.fullmatch(r"[0-9]+", epoch):
            raise LabError("invalid RPM epoch")
        record["epoch"] = int(epoch)
        for field in ("source_rpm", "header_sha256"):
            if record[field] in ("(none)", ""):
                record[field] = None
        if record["header_sha256"] is not None and not HEX64.fullmatch(record["header_sha256"]):
            raise LabError("invalid SHA256HEADER; immutable RPM identity unavailable")
        records.append(record)
    return validate_inventory(records)


def validate_inventory(records):
    if not isinstance(records, list) or not records:
        raise LabError("empty or invalid RPM inventory")
    seen = set()
    normalized = []
    for record in records:
        if not isinstance(record, dict) or set(record) != set(INVENTORY):
            raise LabError("unexpected inventory fields")
        if type(record["epoch"]) is not int or not 0 <= record["epoch"] <= 2**32 - 1:
            raise LabError("invalid inventory epoch")
        for field in ("name", "version", "release", "arch"):
            if field == "arch" and record["name"] == "gpg-pubkey" and record[field] == "(none)":
                continue
            if not isinstance(record[field], str) or not re.fullmatch(r"[A-Za-z0-9_+.%~^:-]+", record[field]):
                raise LabError(f"invalid inventory {field}")
        source = record["source_rpm"]
        if source is not None and (not isinstance(source, str) or not re.fullmatch(r"[A-Za-z0-9_+.~^-]+\.src\.rpm", source)):
            raise LabError("invalid inventory source RPM")
        header = record["header_sha256"]
        if header is not None and (not isinstance(header, str) or not HEX64.fullmatch(header)):
            raise LabError("invalid immutable header digest")
        identity = tuple(record[field] for field in IDENTITY)
        if identity in seen:
            raise LabError("duplicate inventory identity")
        seen.add(identity)
        normalized.append(dict(record))
    return sorted(normalized, key=lambda item: tuple(str(item[field]) for field in IDENTITY))


def _require_header_tag(rpm="rpm"):
    if "SHA256HEADER" not in run([rpm, "--querytags"]).splitlines():
        raise LabError("RPM lacks SHA256HEADER support (RPM 4.14 or newer required)")


def query_inventory(rpm="rpm"):
    _require_header_tag(rpm)
    return _records(run([rpm, "-qa", "--qf", QUERY]))


# rpm -V compares file size and digest with the installed header and nothing
# else: owners, modes, mtimes and capabilities legitimately differ on a bootc
# deployment, and a link target is not file content.
VERIFY_ONLY_CONTENT = ("--nodeps", "--noscripts", "--nomtime", "--nouser", "--nogroup",
                       "--nomode", "--nordev", "--nocaps", "--nolinkto")


def verify_installed_files(inventory, rpm="rpm"):
    """rpm -V lines for pinned-source files whose bytes differ from their header.

    Run 41051314549's candidate rpmdb held the patched headers while every
    crashing process ran libEGL_mesa code whose return addresses exist only in
    the unpatched layout: header identity is not installed-byte identity.
    """
    names = sorted({record["name"] for record in inventory if record["source_rpm"] == INPUTS["source_rpm"]})
    if not names:
        raise LabError("no installed package from the pinned source RPM to verify")
    result = subprocess.run([rpm, "-V", *VERIFY_ONLY_CONTENT, *names], check=False,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    mismatches = result.stdout.splitlines()
    # rpm -V exits with the count of failing packages; listed files are a
    # finding, any other shape (diagnostics, signal, silent failure) is not.
    if result.stderr.strip() or result.returncode < 0 or bool(result.returncode) != bool(mismatches):
        raise LabError(f"installed file verification failed ({result.returncode}): "
                       f"{sanitize_text((result.stdout + result.stderr)[-2048:])}")
    return mismatches


def query_package(path, relative_path, arm=None):
    _require_header_tag()
    records = _records(run(["rpm", "-qp", "--qf", QUERY, path]))
    if len(records) != 1:
        raise LabError("RPM file must contain exactly one header")
    record = records[0]
    if record["source_rpm"] != INPUTS["source_rpm"] or record["header_sha256"] is None:
        raise LabError("binary RPM has wrong source or missing immutable header")
    record.update(path=relative_path, sha256=sha256_file(path), bytes=Path(path).stat().st_size)
    return validate_package_record(record, arm=arm)


def _package_map(packages):
    result = {}
    for record in packages:
        record = validate_package_record(record)
        identity = tuple(record[field] for field in IDENTITY)
        if identity in result:
            raise LabError("duplicate output package identity")
        if record["arch"] not in ("x86_64", "noarch"):
            raise LabError("non-native output package")
        if record["source_rpm"] != INPUTS["source_rpm"] or not record["header_sha256"]:
            raise LabError("output set contains a foreign source or missing header identity")
        result[identity] = record
    if not result:
        raise LabError("empty Mesa output package set")
    return result


def select_closure(baseline, packages):
    """Select *all* installed packages from the pinned SOURCERPM, not name prefixes."""
    baseline = validate_inventory(baseline)
    outputs = _package_map(packages)
    names = {(record["name"], record["arch"]) for record in outputs.values()}
    selected = []
    for installed in baseline:
        source = installed["source_rpm"]
        from_other_mesa = isinstance(source, str) and re.match(r"mesa-[0-9]", source)
        if source != INPUTS["source_rpm"] and (
            (installed["name"], installed["arch"]) in names or from_other_mesa
        ):
            raise LabError("baseline Mesa source/version drift")
        if source != INPUTS["source_rpm"]:
            continue
        if installed["header_sha256"] is None:
            raise LabError("baseline Mesa has no immutable header identity")
        identity = tuple(installed[field] for field in IDENTITY)
        if identity not in outputs:
            raise LabError(f"missing exact installed Mesa output: {identity}")
        selected.append(outputs[identity])
    if not selected:
        raise LabError("baseline has no packages from the fixed Mesa SOURCERPM")
    return selected


def validate_pair(control, candidate, baseline):
    left, right = _package_map(control), _package_map(candidate)
    if set(left) != set(right):
        raise LabError("control/candidate complete output identities differ")
    return {"control": select_closure(baseline, control), "candidate": select_closure(baseline, candidate)}


def validate_installed(baseline, installed, selected):
    """Require selected signed headers and byte-identical unrelated inventory."""
    baseline = validate_inventory(baseline)
    installed = validate_inventory(installed)
    expected = {tuple(item[field] for field in IDENTITY): item for item in baseline}
    selected_map = _package_map(selected)
    if set(selected_map) != {
        tuple(item[field] for field in IDENTITY)
        for item in baseline if item["source_rpm"] == INPUTS["source_rpm"]
    }:
        raise LabError("installed transaction does not cover the exact source closure")
    for identity, record in selected_map.items():
        expected[identity] = {field: record[field] for field in INVENTORY}
    actual = {tuple(item[field] for field in IDENTITY): item for item in installed}
    if actual != expected:
        raise LabError("installed headers differ from selected arm or unrelated inventory changed")


def candidate_spec(original):
    """Add only the ordered candidate patches; retain the vendor build/check policy."""
    declarations = [
        (int(match[0] or "0"), match[1])
        for match in re.findall(r"^[ \t]*Patch([0-9]*):[ \t]*(\S+)[ \t]*$", original, re.MULTILINE)
    ]
    if declarations != PATCHES:
        raise LabError("vendor patch chain drift")
    if re.findall(r"^%autosetup[^\n]*$", original, re.MULTILINE) != ["%autosetup -n %{name}-%{ver} -p1"]:
        raise LabError("vendor autosetup drift")
    if re.findall(r"^%(global|define)[ \t]+ver[ \t]+([^\n]*)$", original, re.MULTILINE) != [("global", "25.2.7")]:
        raise LabError("vendor version drift")
    anchor = re.search(r"^Patch1001:[^\n]*\n", original, re.MULTILINE)
    if anchor is None:
        raise LabError("missing vendor Patch1001")
    return (original[:anchor.end()] + f"Patch1002: {PATCH_NAME}\n"
            + f"Patch1003: {LOADER_PATCH_NAME}\n" + original[anchor.end():])


def candidate_loader_patch():
    """The reviewed local supplement is part of the immutable input contract."""
    path = Path(__file__).with_name(LOADER_PATCH_NAME)
    if sha256_file(path, max_bytes=2 * 1024**2) != INPUTS["loader_patch_sha256"]:
        raise LabError("candidate loader patch digest mismatch")
    return path


def public_fingerprint(path):
    with tempfile.TemporaryDirectory(prefix="mesa-3969-public-") as directory:
        os.chmod(directory, 0o700)
        text = run(["gpg", "--homedir", directory, "--batch", "--with-colons", "--show-keys", path])
    primary = []
    pending = False
    for line in text.splitlines():
        fields = line.split(":")
        if fields[0] == "pub":
            if (
                len(fields) < 12 or fields[2:4] != ["3072", "1"]
                or not fields[5].isdigit() or not fields[6].isdigit()
                or not 0 < int(fields[6]) - int(fields[5]) <= 2 * 86400
                or "s" not in fields[11].lower()
            ):
                raise LabError("lab public key is not a short-lived RSA3072 signing key")
            pending = True
        elif fields[0] == "fpr" and pending:
            primary.append(fields[9])
            pending = False
    if len(primary) != 1 or not re.fullmatch(r"[A-F0-9]{40}", primary[0]):
        raise LabError("public key must have exactly one RSA signing identity")
    return primary[0]


def verify_signatures(directory, manifest):
    """Use a fresh RPMdb containing only this one run's public signing key."""
    directory = Path(directory)
    key = directory / "public-key.asc"
    fingerprint = public_fingerprint(key)
    if fingerprint != manifest["signer"]["fingerprint"]:
        raise LabError("signer fingerprint mismatch")
    with tempfile.TemporaryDirectory(prefix="mesa-3969-rpmdb-") as temporary:
        db = Path(temporary) / "rpmdb"
        db.mkdir(mode=0o700)
        run(["rpm", "--dbpath", db, "--initdb"])
        run(["rpmkeys", "--dbpath", db, "--import", key])
        keys = run(["rpm", "--dbpath", db, "-qa", "--qf", "%{NAME}\n"]).splitlines()
        if keys != ["gpg-pubkey"]:
            raise LabError("isolated RPMdb does not contain exactly one public key")
        for arm in ("control", "candidate"):
            for record in manifest["arms"][arm]["packages"]:
                path = directory / record["path"]
                text = run(["rpmkeys", "--dbpath", db, "--checksig", "--verbose", path])
                signatures = re.findall(r"(?im)^\s*.*signature, key ID ([0-9a-f]+): OK\s*$", text)
                if not signatures or any(not fingerprint.lower().endswith(key_id.lower()) or len(key_id) < 8 for key_id in signatures):
                    raise LabError("RPM has no verified signature from the isolated lab key")
                if re.search(r"(?i)NOT OK|NOKEY|NOTTRUSTED|BAD", text):
                    raise LabError("RPM signature or digest verification failed")


def verify_transfer(directory, expected_producer=None):
    directory = Path(directory)
    manifest = validate_manifest(read_json(directory / "manifest.json"), expected_producer)
    verify_transfer_files(directory, manifest, "manifest.json")
    return _verify_transfer_packages(directory, manifest)


def verify_local_transfer(directory, expected_local):
    directory = Path(directory)
    local = validate_local_authority(expected_local)
    manifest = validate_local_manifest(read_json(directory / "local-manifest.json"), local)
    verify_transfer_files(directory, manifest, "local-manifest.json")
    return _verify_transfer_packages(directory, manifest)


def _verify_transfer_packages(directory, manifest):
    if manifest["inputs"] != INPUTS:
        raise LabError("transfer fixed inputs changed")
    baseline = read_json(directory / "baseline-inventory.json")
    for arm in ("control", "candidate"):
        for record in manifest["arms"][arm]["packages"]:
            validate_package_record(record, arm=arm)
            path = directory / record["path"]
            if path.is_symlink() or not path.is_file():
                raise LabError("RPM is not a regular transfer file")
            if query_package(path, record["path"], arm) != record:
                raise LabError("transferred RPM bytes or immutable header changed")
    selected = validate_pair(manifest["arms"]["control"]["packages"], manifest["arms"]["candidate"]["packages"], baseline)
    verify_signatures(directory, manifest)
    return manifest, baseline, selected


CPIO_NEWC = b"070701"
MAX_PAYLOAD_BYTES = 8 * 1024**3


def _read_exact(stream, size):
    data = stream.read(size)
    if len(data) != size:
        raise LabError("truncated RPM payload archive")
    return data


def rpm_payload_digests(path, rpm2cpio="rpm2cpio"):
    """SHA-256 of every regular file in an RPM's payload, read from the archive.

    Header digests describe what the payload should be; these are the bytes it
    is. rpm2cpio emits newc; a hard-link set carries its data on one member.
    """
    process = subprocess.Popen([rpm2cpio, str(path)], stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    files, links, link_data = {}, {}, {}
    total = 0
    try:
        while True:
            header = _read_exact(process.stdout, 110)
            if header[:6] != CPIO_NEWC:
                raise LabError("RPM payload is not a newc cpio archive")
            try:
                fields = [int(header[6 + 8 * index:14 + 8 * index], 16) for index in range(13)]
            except ValueError as error:
                raise LabError("malformed RPM payload header") from error
            inode, mode, _, _, nlink, _, size, major, minor, _, _, namesize, _ = fields
            raw = _read_exact(process.stdout, namesize)
            _read_exact(process.stdout, -(110 + namesize) % 4)
            if not raw.endswith(b"\0"):
                raise LabError("malformed RPM payload member name")
            name = raw[:-1].decode("utf-8", "surrogateescape")
            if name == "TRAILER!!!":
                break
            total += size
            if total > MAX_PAYLOAD_BYTES:
                raise LabError("RPM payload exceeds bound")
            digest = hashlib.sha256()
            remaining = size
            while remaining:
                chunk = process.stdout.read(min(remaining, 1 << 20))
                if not chunk:
                    raise LabError("truncated RPM payload archive")
                digest.update(chunk)
                remaining -= len(chunk)
            _read_exact(process.stdout, -size % 4)
            if not stat.S_ISREG(mode):
                continue
            member = "/" + name.removeprefix("./").lstrip("/")
            if any(part in ("", ".", "..") for part in member[1:].split("/")) or member in files:
                raise LabError("unsafe or duplicate RPM payload path")
            files[member] = {"sha256": digest.hexdigest(), "size": size}
            if nlink > 1:
                links.setdefault((major, minor, inode), []).append(member)
                if size:
                    link_data[(major, minor, inode)] = files[member]
        while chunk := process.stdout.read(1 << 16):
            if chunk.strip(b"\0"):
                raise LabError("data after RPM payload trailer")
    finally:
        process.stdout.close()
        error = process.stderr.read(16384)
        process.stderr.close()
        returncode = process.wait()
    if returncode:
        raise LabError(f"rpm2cpio failed ({returncode}): {sanitize_text(error.decode('utf-8', 'replace'))}")
    for key, members in links.items():
        for member in members:
            files[member] = dict(link_data.get(key, files[member]))
    return files


def payload_digests(directory):
    """Per-arm payload digests of the selected (installed) packages, after full verification."""
    directory = Path(directory)
    _, _, selected = verify_transfer(directory)
    tables = {}
    for arm in ("control", "candidate"):
        table = {}
        for record in selected[arm]:
            for member, entry in rpm_payload_digests(directory / record["path"]).items():
                if member in table and table[member]["sha256"] != entry["sha256"]:
                    raise LabError(f"selected packages ship different bytes at {member}")
                table.setdefault(member, dict(entry, package=record["name"]))
        tables[arm] = table
    return validate_payload_digests(tables)


def validate_payload_digests(value):
    if not isinstance(value, dict) or set(value) != {"control", "candidate"}:
        raise LabError("payload digests must name exactly the two arms")
    for table in value.values():
        if not isinstance(table, dict) or not table:
            raise LabError("empty payload digest table")
        for member, entry in table.items():
            if (not isinstance(member, str) or not member.startswith("/") or not isinstance(entry, dict)
                    or set(entry) != {"sha256", "size", "package"}
                    or not isinstance(entry["sha256"], str) or not HEX64.fullmatch(entry["sha256"])
                    or type(entry["size"]) is not int or entry["size"] < 0
                    or not isinstance(entry["package"], str)):
                raise LabError("malformed payload digest entry")
    return value


def install_arm(directory, arm):
    if os.geteuid() != 0 or not Path("/run/.containerenv").is_file() or not LAB_IDENTITY.is_file():
        raise LabError("RPM replacement is restricted to an owned lab container")
    scope = validate_producer(read_json(LAB_IDENTITY))
    directory = Path(directory)
    manifest, baseline, selected = verify_transfer(directory, expected_producer=scope)
    before = query_inventory()
    if before != validate_inventory(baseline):
        raise LabError("installation does not start from the common baseline inventory")
    if sha256_file(POLICY) != manifest["baseline"]["software_policy_sha256"]:
        raise LabError("common software policy changed")
    paths = [directory / item["path"] for item in selected[arm]]
    run(["rpm", "-Uvh", "--replacepkgs", *paths])
    after = query_inventory()
    validate_installed(baseline, after, selected[arm])
    mismatches = verify_installed_files(after)
    if mismatches:
        raise LabError("replaced files differ from their installed headers: " + "; ".join(mismatches)[:2048])
    if sha256_file(POLICY) != manifest["baseline"]["software_policy_sha256"]:
        raise LabError("replacement transaction changed software policy")
    return {"arm": arm, "installed": after, "selected": selected[arm], "software_policy_sha256": sha256_file(POLICY)}


def _fetch_fixed(url, destination, expected, maximum):
    with urllib.request.urlopen(url, timeout=120) as response, destination.open("xb") as stream:
        total = 0
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > maximum:
                raise LabError("fixed source input exceeds download bound")
            stream.write(chunk)
    if sha256_file(destination, max_bytes=maximum) != expected:
        raise LabError("fixed source input SHA256 mismatch")


def _factory_arguments(repository, short_head):
    """Resolve only reviewed repository pins, never ambient image overrides."""
    arguments = {
        "BASE_IMAGE": INPUTS["baseline_parent"],
        "IMAGE_NAME": "albacore",
        "IMAGE_VENDOR": "tuna-os",
        "IMAGE_REGISTRY": "ghcr.io",
        "IMAGE_NAME_VARIANT": "albacore",
        "DESKTOP_FLAVOR": "tuna",
        "TUNAOS_IMAGE_FLAVOR": "tuna",
        "ENABLE_HWE": "0",
        "ENABLE_ASAHI": "0",
        "ENABLE_NVIDIA": "0",
        "ENABLE_SSHD": "0",
        "AKMODS_VERSION": "centos-10",
        "SHA_HEAD_SHORT": short_head,
    }
    versions = repository / "image-versions.yaml"
    for name, key in (
        ("common", "COMMON_IMAGE_REF"),
        ("brew", "BREW_IMAGE_REF"),
        ("utah-packages", "UTAH_PACKAGES_IMAGE_REF"),
        ("gnome50-el10-packages", "GNOME50_EL10_PACKAGES_IMAGE_REF"),
    ):
        image = run(["yq", "-r", f'.images[] | select(.name == "{name}") | .image', versions]).strip()
        digest = run(["yq", "-r", f'.images[] | select(.name == "{name}") | .digest', versions]).strip()
        if not re.fullmatch(r"[a-z0-9./_-]+", image):
            raise LabError("invalid checked-in factory image reference")
        arguments[key] = f"{image}@{normalize_image_id(digest)}"
    arguments["BOOTC_VERSION"] = run(["yq", "-r", ".downloads.bootc", versions]).strip()
    if not re.fullmatch(r"v?[0-9]+(?:\.[0-9]+)+", arguments["BOOTC_VERSION"]):
        raise LabError("missing pinned factory bootc version")
    # Match build-image-inner.sh's find/sort/sha256sum selection and output.
    paths = sorted(
        path.relative_to(repository).as_posix()
        for path in (repository / "build_scripts").rglob("*")
        if path.is_file() and not path.is_symlink() and (
            path.suffix == ".sh" or path.relative_to(repository).as_posix()
            in ("build_scripts/lib/identity.env", "build_scripts/lib/image-packages.tsv")
        )
    )
    entries = "".join(f"{sha256_file(repository / path)}  {path}\n" for path in paths)
    arguments["BUILD_SCRIPTS_HASH"] = hashlib.sha256(entries.encode()).hexdigest()[:16]
    arguments["AKMODS_BASE"] = run(
        ["bash", "-c", 'source scripts/_registry.sh; registry_ref akmods'], cwd=repository,
        env={key: value for key, value in os.environ.items() if not key.startswith("TUNA_")},
    ).strip()
    if not re.fullmatch(r"[a-z0-9./_-]+", arguments["AKMODS_BASE"]):
        raise LabError("invalid checked-in akmods registry")
    return arguments


class Build:
    """One native pipeline with mutually exclusive hosted or local provenance."""

    def __init__(self, root, producer=None, *, local=None):
        if (producer is None) == (local is None):
            raise LabError("exactly one hosted or local build identity is required")
        self.producer = validate_producer(producer) if producer is not None else None
        self.local = validate_local_authority(local) if local is not None else None
        identity = self.producer if self.producer is not None else self.local
        self.namespace = str(identity["run_id"]) if self.producer is not None else "local-" + identity["operation_id"]
        self.head = identity["head_sha"]
        self.provenance = {"producer": self.producer} if self.producer is not None else {"local": self.local}
        self.manifest_name = "manifest.json" if self.producer is not None else "local-manifest.json"
        self.root = Path(root)
        self.work = self.root / "work"
        self.transfer = self.root / "transfer"
        self.evidence_source = self.work / "evidence"
        self.repository = Path(__file__).resolve().parents[2]
        if self.local is not None and self.local["checkout"] != str(self.repository):
            raise LabError("local native build checkout differs from authorized repository")
        self.label = f"{self.namespace}-{self.head}"
        self.prefix = f"mesa-3969-{self.namespace}-{self.head[:8]}-build"
        self.images = []
        self.containers = []
        self.report = {
            "kind": "mesa3969-build-report" if self.producer is not None else "mesa3969-local-build-report",
            **self.provenance, "status": "failed", "phase": "prepare",
        }
        self.log = None
        self.auth = self.work / "auth.json"
        self.core = Path(__file__).with_name("mesa_3969.py")

    def command(self, args, *, capture=False, cwd=None, env=None):
        if self.log is not None and not self.log.closed:
            self.log.write("$ " + json.dumps([str(value) for value in args]) + "\n")
            self.log.flush()
        return run(args, cwd=cwd, env=env, output=None if capture else self.log)

    def image_id(self, image):
        data = json.loads(self.command(["podman", "image", "inspect", image], capture=True))
        if len(data) != 1 or data[0].get("Labels", {}).get("io.tunaos.mesa3969") != self.label:
            raise LabError("image is not uniquely owned by this admitted build")
        return normalize_image_id(data[0]["Id"])

    def reserve_tag(self, tag):
        result = subprocess.run(["podman", "image", "exists", tag], check=False)
        if result.returncode == 0:
            raise LabError("refusing to overwrite an existing image tag")
        if result.returncode != 1:
            raise LabError("container engine cannot establish image tag availability")
        self.images.append(tag)

    def image_build(self, suffix, context, containerfile, extra=()):
        tag = f"localhost/{self.prefix}-{suffix}:once"
        self.reserve_tag(tag)
        command = [
            "podman", "build", "--authfile", self.auth, "--no-cache", "--force-rm",
            "--platform", "linux/amd64", "--label", f"io.tunaos.mesa3969={self.label}",
            "--tag", tag, "--file", containerfile, *extra, context,
        ]
        self.command(command, cwd=self.repository)
        return tag, self.image_id(tag)

    def container(self, suffix, image, command, mounts=(), *, network=False, capture=False, keep=False, environment=()):
        name = f"{self.prefix}-{suffix}"
        self.containers.append(name)
        arguments = [
            "podman", "run", "--name", name, "--pull=never",
            "--label", f"io.tunaos.mesa3969={self.label}",
            "--network", "bridge" if network else "none",
        ]
        if not keep:
            arguments.append("--rm")
        for source, target, readonly in mounts:
            arguments.extend(["--mount", f"type=bind,src={source},dst={target}" + (",ro" if readonly else "")])
        for key, value in environment:
            arguments.extend(["--env", f"{key}={value}"])
        result = self.command([*arguments, image, *command], capture=capture)
        return result, name

    def cleanup_objects(self):
        errors = []
        for kind, names in (("container", self.containers), ("image", self.images)):
            for name in reversed(names):
                try:
                    result = subprocess.run(
                        ["podman", kind, "inspect", name], check=False,
                        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    )
                    if result.returncode:
                        exists = subprocess.run(["podman", kind, "exists", name], check=False)
                        if exists.returncode != 1:
                            errors.append(f"cannot establish {kind} ownership: {name}")
                        continue
                    values = json.loads(result.stdout)
                    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
                        raise LabError("inspection must identify exactly one owned object")
                    labels = values[0].get("Labels", {}) if kind == "image" else values[0].get("Config", {}).get("Labels", {})
                    if not isinstance(labels, dict) or labels.get("io.tunaos.mesa3969") != self.label:
                        errors.append(f"refusing cleanup of unowned {kind}: {name}")
                        continue
                    result = subprocess.run(
                        ["podman", kind, "rm", "--force", name], check=False,
                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                    )
                    if result.returncode:
                        errors.append(f"failed owned {kind} removal: {name}")
                except (OSError, ValueError, TypeError, AttributeError, LabError) as error:
                    errors.append(f"cannot safely clean {kind} {name}: {sanitize_text(str(error))}")
        return errors

    def execute(self):
        self.work.mkdir(mode=0o700, exist_ok=True)
        self.transfer.mkdir(mode=0o700)
        self.evidence_source.mkdir(mode=0o700)
        self.auth.write_text('{"auths":{}}\n')
        self.auth.chmod(0o600)
        if any(os.environ.get(key) for key in ("CONTAINER_HOST", "CONTAINER_CONNECTION", "DOCKER_HOST")):
            raise LabError("remote container engines are forbidden")
        self.log = (self.work / "build.raw.log").open("w")
        try:
            self.prepare_and_build()
            self.report["status"] = "sealed"
        except BaseException as error:
            self.report["status"] = "failed"
            self.report["error"] = sanitize_text(str(error))
            raise
        finally:
            cleanup_errors = self.cleanup_objects()
            if cleanup_errors:
                self.report["cleanup_errors"] = cleanup_errors
                self.report["status"] = "failed"
            self.log.close()
            raw = self.work / "build.raw.log"
            masks = []
            with raw.open("r", errors="replace") as stream:
                while line := stream.readline(1024 * 1024):
                    if line.startswith("::add-mask::"):
                        value = line[len("::add-mask::"):].rstrip("\r\n")
                        if len(value) > 4096 or len(masks) >= 1024:
                            raise LabError("private build log mask inventory exceeds evidence bound")
                        if value:
                            masks.append(value.replace("%0A", "\n").replace("%0D", "\r").replace("%25", "%"))
            with raw.open("rb") as stream:
                stream.seek(max(0, raw.stat().st_size - 1024 * 1024))
                tail = stream.read().decode("utf-8", errors="replace")
            (self.evidence_source / "build-log.txt").write_text(
                "Bounded final 1 MiB tail of private build log; not the complete log.\n"
                + sanitize_text(tail, secrets=masks)
            )
            write_json(self.evidence_source / "build-report.json", self.report)
            self.command([
                sys.executable, self.core, "pack-evidence", "--source", self.evidence_source,
                "--output", self.root / "evidence",
            ], capture=True)
            if cleanup_errors:
                raise LabError("; ".join(cleanup_errors))

    def prepare_and_build(self):
        source = self.work / INPUTS["source_rpm"]
        patch = self.work / PATCH_NAME
        loader_patch = candidate_loader_patch()
        self.report["phase"] = "fixed-inputs"
        _fetch_fixed(INPUTS["srpm_url"], source, INPUTS["srpm_sha256"], 128 * 1024**2)
        _fetch_fixed(INPUTS["patch_url"], patch, INPUTS["patch_sha256"], 2 * 1024**2)
        modules = self.work / "modules"
        modules.mkdir()
        for name in ("mesa_3969.py", "mesa_3969_packages.py", "mesa_3969_guest.py", "mesa-3969-probe.service"):
            shutil.copyfile(Path(__file__).with_name(name), modules / name)
        for name in ("repro-egldevice-swrast.c", "greeter-graphics-evidence.sh"):
            value = self.command(
                ["git", "show", f"{INPUTS['helper_commit']}:scripts/{name}"], capture=True, cwd=self.repository,
            )
            (modules / name).write_text(value)
        factory_context = self.work / "factory-context"
        factory_context.mkdir()
        archive = self.work / "reviewed-source.tar"
        self.command([
            "git", "archive", "--format=tar", "--output", archive, self.head,
        ], cwd=self.repository)
        self.command(["tar", "--extract", "--file", archive, "--directory", factory_context])
        self.command([
            sys.executable, factory_context / "scripts" / "config.py", "generate", "--root", factory_context,
        ])
        self.report["phase"] = "native-albacore-baseline"
        short_head = self.command(
            ["git", "rev-parse", "--short", self.head], capture=True, cwd=self.repository,
        ).strip()
        arguments = _factory_arguments(factory_context, short_head)
        self.report["factory"] = {
            "containerfile": "Containerfile.el10", "target": "tuna", "platform": "linux/amd64",
            "build_args": arguments, "engine": "single direct podman build; no factory retry wrapper",
            "source_references": [
                "Justfile:56-143 (positional parent interface; retry wrapper is not invoked)",
                "scripts/build-image-inner.sh:75-120,150-157,184-195 (build arguments/hash/flags)",
                "scripts/build-image-inner.sh:217-232 (excluded retry/global-prune wrapper)",
                "scripts/config.py:151-152; scripts/lib/tunaos_config.py:772-834 (native adapters)",
                "Containerfile.el10:40-58,282-295 (unchanged context/target)",
            ],
        }
        build_args = ["--target", "tuna", "--pull=always", "--security-opt", "label=disable", "--dns=8.8.8.8"]
        for key, value in arguments.items():
            build_args.extend(["--build-arg", f"{key}={value}"])
        _, raw_id = self.image_build("raw", factory_context, factory_context / "Containerfile.el10", build_args)
        self.report["raw_image_id"] = raw_id
        raw_policy, _ = self.container("raw-policy", raw_id, ["sha256sum", POLICY], capture=True)
        policy_digest = raw_policy.split()[0]
        original_policy = sha256_file(factory_context / "system_files" / POLICY.lstrip("/"))
        if policy_digest != original_policy:
            raise LabError("factory baseline changed the original software policy")
        self.report["phase"] = "freeze-native-dependency-root"
        _, dependency_container = self.container(
            "dependencies", raw_id,
            ["bash", "-euc", "dnf -y install rpm-build rpm-sign dnf-plugins-core gnupg2 gcc gcc-c++ glibc-devel python3; "
             "dnf config-manager --set-enabled crb; dnf -y builddep /inputs/mesa.src.rpm; dnf clean all"],
            [(source, "/inputs/mesa.src.rpm", True)], network=True, keep=True,
        )
        root_tag = f"localhost/{self.prefix}-root:once"
        self.reserve_tag(root_tag)
        self.command(["podman", "commit", "--change", f"LABEL io.tunaos.mesa3969={self.label}", dependency_container, root_tag])
        root_id = self.image_id(root_tag)
        self.report["buildroot_image_id"] = root_id
        inventory, _ = self.container(
            "root-inventory", root_id, ["python3", "/lab/mesa_3969_packages.py", "inventory"],
            [(modules, "/lab", True)], capture=True,
        )
        write_json(self.transfer / "buildroot-inventory.json", json.loads(inventory))
        macros, _ = self.container("root-macros", root_id, ["rpm", "--showrc"], capture=True)
        (self.transfer / "buildroot-macros.txt").write_text(macros)
        toolchain, _ = self.container(
            "root-toolchain", root_id,
            ["bash", "-euc", "uname -m; cc --version; c++ --version; ld --version; rpm --version; "
             "rpmbuild --version; gpg --version; python3 --version; clang --version; rustc --version; "
             "cargo --version; meson --version; ninja --version"], capture=True,
        )
        (self.transfer / "toolchain.txt").write_text(toolchain)
        self.container(
            "compile-probe", root_id,
            ["cc", "-O0", "-g", "-Wall", "-Wextra", "-Werror", "/stage/repro-egldevice-swrast.c",
             "-o", "/stage/repro-egldevice-swrast", "-ldl"], [(modules, "/stage", False)],
        )
        arms = {}
        for arm in ("control", "candidate"):
            self.report["phase"] = f"build-{arm}"
            topdir = self.work / arm
            topdir.mkdir()
            for child in ("BUILD", "BUILDROOT", "RPMS", "SOURCES", "SPECS", "SRPMS"):
                (topdir / child).mkdir()
            self.container(
                f"unpack-{arm}", root_id,
                ["rpm", "-i", "--define", "_topdir /build", "/inputs/mesa.src.rpm"],
                [(topdir, "/build", False), (source, "/inputs/mesa.src.rpm", True)],
            )
            specs = list((topdir / "SPECS").glob("*.spec"))
            if len(specs) != 1 or specs[0].name != "mesa.spec":
                raise LabError("fixed source RPM must provide exactly mesa.spec")
            original = specs[0].read_text()
            amended = candidate_spec(original)
            if arm == "candidate":
                specs[0].write_text(amended)
                shutil.copyfile(patch, topdir / "SOURCES" / PATCH_NAME)
                shutil.copyfile(loader_patch, topdir / "SOURCES" / LOADER_PATCH_NAME)
            self.container(
                f"rpmbuild-{arm}", root_id,
                ["rpmbuild", "-ba", "--define", "_topdir /build", "/build/SPECS/mesa.spec"],
                [(topdir, "/build", False)],
            )
            generated = list((topdir / "SRPMS").glob("*.src.rpm"))
            if len(generated) != 1 or generated[0].name != INPUTS["source_rpm"]:
                raise LabError("generated source RPM identity changed")
            destination = self.transfer / "rpms" / arm
            destination.mkdir(parents=True)
            binaries = sorted((topdir / "RPMS").rglob("*.rpm"))
            if not binaries:
                raise LabError("native build produced no binary packages")
            for binary in binaries:
                if (destination / binary.name).exists():
                    raise LabError("duplicate binary RPM basename")
                shutil.copyfile(binary, destination / binary.name)
            arms[arm] = {
                "buildroot_image_id": root_id,
                "generated_srpm_sha256": sha256_file(generated[0], max_bytes=128 * 1024**2),
                "packages": [],
            }
        self.report["phase"] = "temporary-signing"
        keydir = self.work / "gnupg"
        keydir.mkdir(mode=0o700)
        signing_environment = [("GNUPGHOME", "/key")]
        self.container(
            "generate-key", root_id,
            ["gpg", "--batch", "--pinentry-mode", "loopback", "--passphrase", "",
             "--quick-generate-key", f"Mesa 3969 {self.namespace} <mesa3969@invalid.example>",
             "rsa3072", "sign", "2d"], [(keydir, "/key", False)], environment=signing_environment,
        )
        public, _ = self.container(
            "export-key", root_id, ["gpg", "--batch", "--armor", "--export"],
            [(keydir, "/key", False)], capture=True, environment=signing_environment,
        )
        (self.transfer / "public-key.asc").write_text(public)
        fingerprint_text, _ = self.container(
            "fingerprint", root_id, ["gpg", "--batch", "--with-colons", "--list-keys"],
            [(keydir, "/key", False)], capture=True, environment=signing_environment,
        )
        fingerprints = [line.split(":")[9] for line in fingerprint_text.splitlines() if line.startswith("fpr:")]
        if len(fingerprints) != 1 or not re.fullmatch(r"[A-F0-9]{40}", fingerprints[0]):
            raise LabError("temporary signer did not produce one primary fingerprint")
        fingerprint = fingerprints[0]
        sign_script = (
            "from pathlib import Path; import subprocess; "
            "files=sorted(Path('/transfer/rpms').glob('*/*.rpm')); "
            f"subprocess.run(['rpmsign','--define','_gpg_name {fingerprint}',"
            "'--define','_gpg_path /key','--define','__gpg /usr/bin/gpg',"
            "'--define','_gpg_sign_cmd_extra_args --pinentry-mode loopback','--addsign',"
            "*map(str,files)],check=True)"
        )
        self.container(
            "sign-pair", root_id, ["python3", "-c", sign_script],
            [(keydir, "/key", False), (self.transfer, "/transfer", False)], environment=signing_environment,
        )
        self.container(
            "stop-key-agent", root_id, ["gpgconf", "--kill", "all"],
            [(keydir, "/key", False)], environment=signing_environment,
        )
        # Private material is gone before the lab image context is created.
        shutil.rmtree(keydir)
        for arm in ("control", "candidate"):
            for index, binary in enumerate(sorted((self.transfer / "rpms" / arm).glob("*.rpm"))):
                relative = f"rpms/{arm}/{binary.name}"
                record, _ = self.container(
                    f"query-{arm}-{index}", root_id,
                    ["python3", "/lab/mesa_3969_packages.py", "query-package",
                     "--file", f"/transfer/{relative}", "--path", relative, "--arm", arm],
                    [(modules, "/lab", True), (self.transfer, "/transfer", True)], capture=True,
                )
                arms[arm]["packages"].append(json.loads(record))
        self.report["phase"] = "common-instrumented-baseline"
        context = self.work / "lab-context"
        context.mkdir()
        for name in ("mesa_3969.py", "mesa_3969_packages.py", "mesa_3969_guest.py",
                     "mesa-3969-probe.service", "repro-egldevice-swrast", "greeter-graphics-evidence.sh"):
            shutil.copyfile(modules / name, context / name)
        shutil.copyfile(self.transfer / "public-key.asc", context / "public-key.asc")
        write_json(context / "identity.json", self.producer if self.producer is not None else self.local)
        (context / "software.conf").write_text(
            "[Service]\nEnvironment=LIBGL_ALWAYS_SOFTWARE=1\nEnvironment=COGL_DEBUG=winsys\n"
        )
        (context / "90-mesa-3969-logging.conf").write_text(
            "COGL_DEBUG=winsys\n"
        )
        containerfile = context / "Containerfile"
        containerfile.write_text(
            f"FROM {raw_id}\n"
            "RUN dnf -y install python3 gnupg2 && dnf clean all\n"
            "COPY mesa_3969.py mesa_3969_packages.py mesa_3969_guest.py repro-egldevice-swrast "
            "greeter-graphics-evidence.sh /usr/local/libexec/mesa-3969/\n"
            "COPY identity.json /usr/local/libexec/mesa-3969/identity.json\n"
            "COPY mesa-3969-probe.service /etc/systemd/system/mesa-3969-probe.service\n"
            "COPY software.conf /etc/systemd/system/gdm.service.d/90-mesa-3969.conf\n"
            "COPY 90-mesa-3969-logging.conf /etc/environment.d/90-mesa-3969-logging.conf\n"
            "COPY public-key.asc /etc/pki/rpm-gpg/RPM-GPG-KEY-mesa-3969\n"
            "RUN chmod 0755 /usr/local/libexec/mesa-3969/repro-egldevice-swrast "
            "/usr/local/libexec/mesa-3969/greeter-graphics-evidence.sh && "
            "rpm --import /etc/pki/rpm-gpg/RPM-GPG-KEY-mesa-3969 && "
            "systemctl enable mesa-3969-probe.service\n"
        )
        lab_tag, lab_id = self.image_build("labbase", context, containerfile, ["--pull=never"])
        baseline_text, _ = self.container(
            "baseline-inventory", lab_id,
            ["python3", "/usr/local/libexec/mesa-3969/mesa_3969_packages.py", "inventory"], capture=True,
        )
        baseline = validate_inventory(json.loads(baseline_text))
        write_json(self.transfer / "baseline-inventory.json", baseline)
        instrumented_policy, _ = self.container("lab-policy", lab_id, ["sha256sum", POLICY], capture=True)
        if instrumented_policy != raw_policy:
            raise LabError("instrumentation changed production software policy")
        selected = validate_pair(arms["control"]["packages"], arms["candidate"]["packages"], baseline)
        self.report["selected"] = selected
        self.report["arms"] = arms
        manifest = {
            "schema_version": 1,
            "kind": "mesa3969-inputs" if self.producer is not None else "mesa3969-local-inputs",
            **self.provenance, "inputs": INPUTS,
            "baseline": {
                "parent": INPUTS["baseline_parent"], "raw_image_id": raw_id, "image_id": lab_id,
                "image_tag": lab_tag, "inventory": "baseline-inventory.json", "software_policy_sha256": policy_digest,
            },
            "buildroot": {
                "image_id": root_id, "inventory": "buildroot-inventory.json",
                "macros": "buildroot-macros.txt", "toolchain": "toolchain.txt",
            },
            "signer": {"fingerprint": fingerprint, "public_key": "public-key.asc"},
            "probe": {
                "helper_commit": INPUTS["helper_commit"], "source_sha256": sha256_file(modules / "repro-egldevice-swrast.c"),
                "binary_sha256": sha256_file(modules / "repro-egldevice-swrast"),
            },
            "arms": arms, "files": [],
        }
        write_json(self.transfer / self.manifest_name, manifest)
        self.report["phase"] = "export-baseline"
        self.command(["podman", "save", "--format", "oci-archive", "--output", self.transfer / "baseline.oci.tar", lab_tag])
        self.report["baseline_image_id"] = lab_id
        self.report["phase"] = "seal-transfer"
        self.report["status"] = "prepared-for-sealing"
        write_json(self.transfer / "build-report.json", self.report)
        if self.local is None:
            seal = ["seal-transfer", "--directory", self.transfer]
            verify = ["verify-transfer", "--directory", "/transfer"]
            mounts = [(self.transfer, "/transfer", True)]
        else:
            owner = self.work / "local-owner.json"
            write_json(owner, self.local)
            check_local_build_root(self.root, self.local)
            seal = ["seal-local-transfer", "--directory", self.transfer, "--owner", owner]
            verify = ["verify-local-transfer", "--directory", "/transfer", "--owner", "/local-owner.json"]
            mounts = [(self.transfer, "/transfer", True), (owner, "/local-owner.json", True)]
        # Rootful build products must remain private but readable by upload-artifact.
        uid = self.root.stat().st_uid
        for path in [*self.transfer.rglob("*"), self.transfer]:
            path.chmod(0o700 if path.is_dir() else 0o600)
            if os.geteuid() == 0:
                os.chown(path, uid, -1, follow_symlinks=False)
        self.command([sys.executable, self.core, *seal], capture=True)
        # No transfer member is written after sealing; native checks read it only.
        self.report["phase"] = "native-verify-transfer"
        self.container(
            "verify-pair", lab_id,
            ["python3", "/usr/local/libexec/mesa-3969/mesa_3969_packages.py", *verify], mounts,
        )
        self.report["phase"] = "sealed"
        self.report["status"] = "sealed"


def build_pair(root, producer):
    core = Path(__file__).with_name("mesa_3969.py")
    admitted = json.loads(run([sys.executable, core, "producer", "--job-name", "Build signed Mesa pair"]))
    if producer != admitted:
        raise LabError("producer metadata no longer matches live admission")
    actual_root = Path(run([sys.executable, core, "validate-root", "--role", "build"]).strip())
    if root != actual_root:
        raise LabError("build root does not match the admitted marker-bound root")
    def interrupted(signum, _frame):
        raise LabError(f"build interrupted by signal {signum}")
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, interrupted)
    Build(root, producer).execute()


LOCAL_DEADLINE_SECONDS = 9900


@contextlib.contextmanager
def local_deadline(seconds):
    """Bound a local build like the hosted 9900 s body timeout, still running cleanup."""
    def expired(_signum, _frame):
        raise LabError(f"local build exceeded its {seconds}s deadline")
    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def local_build(reviewed_head, scratch_parent, confirmation):
    """Authorize a local-only build; retain artifacts, never private working state."""
    repository = Path(__file__).resolve().parents[2]
    local = authorize_local_build(repository, reviewed_head, confirmation)
    if os.geteuid() != 0:
        raise LabError("local native build requires privileged rootful Podman")
    if any(os.environ.get(key) for key in ("CONTAINER_HOST", "CONTAINER_CONNECTION", "DOCKER_HOST")):
        raise LabError("remote container engines are forbidden")
    if run(["podman", "info", "--format", "{{.Host.Security.Rootless}}"]).strip() != "false":
        raise LabError("local native build requires a rootful local Podman engine")
    root = create_local_build_root(scratch_parent, local)
    receipt = {
        "schema_version": 1, "kind": "mesa3969-local-build-receipt", "local": local,
        "status": "failed", "root": str(root), "evidence_path": str(root / "evidence"),
    }
    failure = None
    cleanup_errors = []
    previous = {}

    def interrupted(signum, _frame):
        raise LabError(f"local build interrupted by signal {signum}")

    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(signum, interrupted)
        check_local_build_root(root, local)
        owner = root / "local-owner.json"
        write_json(owner, local)
        owner.chmod(0o600)
        os.chown(owner, local["owner_uid"], -1, follow_symlinks=False)
        with local_deadline(LOCAL_DEADLINE_SECONDS):
            Build(root, local=local).execute()
    except BaseException as error:
        failure = error
        receipt["error"] = sanitize_text(str(error))
    finally:
        try:
            cleanup_local_build_root(root, local, child="work")
        except BaseException as error:
            cleanup_errors.append(sanitize_text(str(error)))
        if cleanup_errors:
            receipt["cleanup_errors"] = cleanup_errors
        elif failure is None:
            receipt.update(
                status="verified-local-only", transfer_path=str(root / "transfer"),
                manifest_path=str(root / "transfer" / "local-manifest.json"),
            )
        try:
            check_local_build_root(root, local)
            destination = root / "local-build-receipt.json"
            write_json(destination, receipt)
            destination.chmod(0o600)
            os.chown(destination, local["owner_uid"], -1, follow_symlinks=False)
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
    if cleanup_errors:
        raise LabError("local private work cleanup failed: " + "; ".join(cleanup_errors)) from failure
    if failure is not None:
        raise failure
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inventory = commands.add_parser("inventory")
    inventory.add_argument("--output", type=Path)
    query = commands.add_parser("query-package")
    query.add_argument("--file", type=Path, required=True)
    query.add_argument("--path", required=True)
    query.add_argument("--arm", choices=("control", "candidate"), required=True)
    spec = commands.add_parser("candidate-spec")
    spec.add_argument("--input", type=Path, required=True)
    spec.add_argument("--output", type=Path, required=True)
    for name in ("verify-transfer", "verify-local-transfer", "install", "payload-digests"):
        command = commands.add_parser(name)
        command.add_argument("--directory", type=Path, required=True)
        if name == "verify-local-transfer":
            command.add_argument("--owner", type=Path, required=True)
        elif name == "install":
            command.add_argument("--arm", choices=("control", "candidate"), required=True)
    build = commands.add_parser("build")
    build.add_argument("--root", type=Path, required=True)
    build.add_argument("--producer", type=Path, required=True)
    local = commands.add_parser("local-build", help="build locally only; no CI, guest, install or publication authority")
    local.add_argument("--reviewed-head", required=True)
    local.add_argument("--scratch-parent", type=Path, required=True)
    local.add_argument("--confirmation", required=True)
    args = parser.parse_args()
    if args.command == "inventory":
        value = query_inventory()
        if args.output:
            write_json(args.output, value)
            return
    elif args.command == "query-package":
        value = query_package(args.file, args.path, args.arm)
    elif args.command == "candidate-spec":
        args.output.write_text(candidate_spec(args.input.read_text()))
        return
    elif args.command == "verify-transfer":
        manifest, _, selected = verify_transfer(args.directory)
        value = {"signer": manifest["signer"]["fingerprint"], "selected": selected}
    elif args.command == "payload-digests":
        value = payload_digests(args.directory)
    elif args.command == "verify-local-transfer":
        manifest, _, selected = verify_local_transfer(args.directory, read_json(args.owner))
        value = {
            "kind": "mesa3969-local-verification", "local": manifest["local"],
            "signer": manifest["signer"]["fingerprint"], "selected": selected,
        }
    elif args.command == "local-build":
        value = local_build(args.reviewed_head, args.scratch_parent, args.confirmation)
    elif args.command == "install":
        value = install_arm(args.directory, args.arm)
    else:
        build_pair(args.root, read_json(args.producer))
        return
    print(json.dumps(value, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (LabError, OSError, KeyError, TypeError) as error:
        print(f"Mesa #3969 refused: {sanitize_text(str(error))}", file=sys.stderr)
        sys.exit(1)
